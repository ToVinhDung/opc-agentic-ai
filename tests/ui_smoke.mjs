import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";


const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputDir = path.resolve(root, "..", "..", "tmp", "ui_qa");
await fs.mkdir(outputDir, { recursive: true });
const fixtureDir = await fs.mkdtemp(path.join(os.tmpdir(), "opc-founder-upload-"));
const canonicalTeamPack = path.join(root, "data", "MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx");
const externalMissingTeamPack = path.join(fixtureDir, "Founder_CON004_missing.xlsx");
const externalCorrectedTeamPack = path.join(fixtureDir, "Founder_CON004_corrected.xlsx");

await new Promise((resolve, reject) => {
  const fixture = spawn("python3", [
    path.join(root, "tests", "workbook_fixtures.py"),
    "--source", canonicalTeamPack,
    "--output", externalMissingTeamPack,
  ], { cwd: root, stdio: "inherit" });
  fixture.on("error", reject);
  fixture.on("exit", (code) => code === 0 ? resolve() : reject(new Error(`Fixture builder exited ${code}`)));
});
await fs.copyFile(canonicalTeamPack, externalCorrectedTeamPack);

const server = spawn("python3", ["app.py", "--host", "127.0.0.1", "--port", "8766"], {
  cwd: root,
  stdio: "ignore",
});
let browser;

async function waitForServer() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch("http://127.0.0.1:8766/api/health");
      if (response.ok) return;
    } catch {
      // Server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("Local prototype server did not become ready.");
}

try {
  await waitForServer();
  try {
    browser = await chromium.launch({ headless: true });
  } catch (firstError) {
    browser = await chromium.launch({ headless: true, channel: "msedge" });
  }

  const page = await browser.newPage({ viewport: { width: 1366, height: 768 }, deviceScaleFactor: 1 });
  await page.goto("http://127.0.0.1:8766", { waitUntil: "networkidle" });
  await page.waitForFunction(() => document.querySelector("#sheetCount")?.textContent?.includes("26"));
  const horizontalOverflowAtLoad = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (horizontalOverflowAtLoad > 1) throw new Error(`Horizontal overflow at load: ${horizontalOverflowAtLoad}px`);
  const contractSelectLabel = await page.locator("#contractSelect option:checked").textContent();
  const contractInputLabel = await page.locator("#contractDisplay").textContent();
  const contractSourceHintPresent = await page.locator("#contractCount").count();
  const founderControlHeading = await page.locator(".input-controls summary").innerText();
  const evidenceAtLoad = await page.locator("#contractSigned, #agingEvidence, #capacityPlan, #txnReviewed").evaluateAll((inputs) => inputs.map((input) => input.checked));
  await page.check("#contractSigned");
  await page.check("#agingEvidence");
  await page.check("#capacityPlan");
  await page.selectOption("#contractSelect", "CON-005");
  const evidenceAfterContractChange = await page.locator("#contractSigned, #agingEvidence, #capacityPlan, #txnReviewed").evaluateAll((inputs) => inputs.map((input) => input.checked));
  await page.selectOption("#contractSelect", "CON-004");
  const stressPresetPresent = await page.locator('[data-preset="stress"]').count();
  const reconciliationDisabledAtLoad = await page.locator("#openReconciliation").isDisabled();
  const reconciliationHiddenAtLoad = await page.locator("#openReconciliation").isHidden();

  await page.setInputFiles("#teamPackInput", externalMissingTeamPack);
  await page.waitForFunction(() => document.querySelector("#fileName")?.textContent?.includes("Founder_CON004_missing"));
  const evidenceAfterUpload = await page.locator("#contractSigned, #agingEvidence, #capacityPlan, #txnReviewed").evaluateAll((inputs) => inputs.map((input) => input.checked));
  await page.check("#contractSigned");
  await page.check("#agingEvidence");
  await page.check("#capacityPlan");
  await page.click("#runButton");
  await page.waitForFunction(() => document.querySelector("#decisionType")?.textContent?.includes("NEED MORE DATA"), null, { timeout: 15000 });
  await page.click("#openDataQuality");
  await page.waitForFunction(() => document.querySelector("#qualityBlocking")?.textContent === "1");
  const controlTabs = await page.locator("#controlTabs [data-control-tab]").allTextContents();
  const dataQualityDefault = await page.locator("#tabDataQuality").getAttribute("aria-selected");
  const qualityRows = await page.locator(".quality-issue").count();
  const qualitySheets = await page.locator(".quality-sheet").count();
  const qualityActionsVisible = await page.locator(".quality-actions button:visible").count();
  const uploadActionLabel = await page.locator("#uploadCorrectedPack").textContent();
  const actionBox = await page.locator(".quality-actions").boundingBox();
  const dialogBox = await page.locator("#dataQualityDialog").boundingBox();
  const actionsInsideDialog = Boolean(actionBox && dialogBox && actionBox.y + actionBox.height <= dialogBox.y + dialogBox.height + 1);
  await page.click("#tabOpenAIExtraction");
  const extractionFieldCards = await page.locator(".extraction-field-card").count();
  const extractionPanelVisible = await page.locator("#panelOpenAIExtraction").isVisible();
  await page.click("#tabOpenAIGuardrails");
  const guardrailColumns = await page.locator(".guardrail-columns > section").count();
  const maskedJsonPanels = await page.locator(".masked-json-grid pre").count();
  await page.click("#tabDataQuality");
  if (stressPresetPresent !== 0 || qualityActionsVisible !== 3 || !actionsInsideDialog || controlTabs.join(",") !== "Data Quality,OpenAI Extraction,OpenAI Guardrails" || dataQualityDefault !== "true" || extractionFieldCards !== 3 || !extractionPanelVisible || guardrailColumns !== 2 || maskedJsonPanels !== 2) {
    throw new Error("Semifinal UI scope or unified Data/OpenAI control dialog is invalid.");
  }
  await page.screenshot({ path: path.join(outputDir, "data_quality_details.png"), fullPage: true });
  await page.click("#closeDataQuality");
  await page.screenshot({ path: path.join(outputDir, "dashboard_missing.png"), fullPage: true });

  await page.setInputFiles("#teamPackInput", externalCorrectedTeamPack);
  await page.waitForFunction(() => document.querySelector("#fileName")?.textContent?.includes("Founder_CON004_corrected"));
  const evidenceAfterContextChange = await page.locator("#contractSigned, #agingEvidence, #capacityPlan, #txnReviewed").evaluateAll((inputs) => inputs.map((input) => input.checked));
  await page.check("#contractSigned");
  await page.check("#agingEvidence");
  await page.check("#capacityPlan");
  await page.click("#runButton");
  await page.waitForFunction(() => document.querySelector("#decisionType")?.textContent?.includes("REJECT"), null, { timeout: 15000 });
  await page.waitForFunction(() => [...document.querySelectorAll(".partner-logo-shell img")].length >= 1 && [...document.querySelectorAll(".partner-logo-shell img")].every((img) => img.complete && img.naturalWidth > 0));
  const evidenceAfterRun = await page.locator("#contractSigned, #agingEvidence, #capacityPlan, #txnReviewed").evaluateAll((inputs) => inputs.map((input) => input.checked));
  const cashflowTitle = await page.locator(".cashflow-compact h3").textContent();
  const cashflowSubtitle = await page.locator("#cashflowMethod").textContent();
  const cashflowLegend = await page.locator(".cashflow-compact .legend span").allTextContents();
  const cashflowTooltip = await page.locator("#cashflowChart title").first().textContent();
  const cashflowStatus = await page.locator("#cashflowDataStatus").textContent();
  const cashflowDeficitArea = await page.locator("#cashflowChart .cashflow-deficit-area").count();
  const cashflowBreakEvenLine = await page.locator("#cashflowChart .cashflow-break-even-line").count();
  const cashflowBreakEvenLabel = await page.locator("#cashflowChart .chart-break-even-label").textContent();
  const cashflowMonthLabels = await page.locator("#cashflowChart .chart-month-label").allTextContents();
  const cashflowVisibleText = await page.locator(".cashflow-compact").textContent();
  const reconciliationEnabledAfterRun = await page.locator("#openReconciliation").isEnabled();
  const reconciliationHiddenAfterRun = await page.locator("#openReconciliation").isHidden();
  const reconciliationDialogClosedByDefault = !(await page.locator("#reconciliationDialog").evaluate((dialog) => dialog.open));
  await page.locator("#openReconciliation").evaluate((button) => {
    button.hidden = false;
    button.removeAttribute("aria-hidden");
  });
  await page.click("#openReconciliation");
  await page.waitForFunction(() => Number(document.querySelector("#reconciliationTotal")?.textContent || 0) > 0);
  const reconciliationRows = await page.locator(".reconciliation-record").count();
  const reconciliationFilters = await page.locator("#reconciliationFilters button").allTextContents();
  const reconciliationRoute = await page.locator("#reconciliationRoute span").allTextContents();
  const backendExcludedRows = await page.locator(".reconciliation-record.excluded").count();
  const backendStatusClassesValid = await page.locator(".reconciliation-record").evaluateAll((rows) => rows.every((row) => {
    const status = row.querySelector(".reconciliation-status")?.textContent?.trim();
    return status !== "EXCLUDED" || row.classList.contains("excluded");
  }));
  const anomalyRows = await page.locator(".reconciliation-record.anomaly").count();
  const privacyMasked = await page.locator(".reconciliation-record small").evaluateAll((nodes) => nodes.every((node) => !node.textContent.includes("Đối tác") || node.textContent.includes("••••")));
  if (!reconciliationDisabledAtLoad || !reconciliationEnabledAfterRun || reconciliationRows < 1 || reconciliationFilters.join(",") !== "ALL,CASE,ENTERPRISE,REVIEW" || reconciliationRoute.join(",") !== "08_BANK_TXN,07_INVOICES,06_ORDERS,04_CONTRACTS" || backendExcludedRows < 1 || !backendStatusClassesValid || anomalyRows < 1 || !privacyMasked) {
    throw new Error("Transaction reconciliation UI, scope filters, status colors, or privacy masking is invalid.");
  }
  await page.screenshot({ path: path.join(outputDir, "transaction_reconciliation.png"), fullPage: true });
  await page.click("#closeReconciliation");
  await page.locator("#openReconciliation").evaluate((button) => {
    button.hidden = true;
    button.setAttribute("aria-hidden", "true");
  });
  await page.click("#evidenceButton");
  const guardrailsOpenedFromArrow = await page.locator("#tabOpenAIGuardrails").getAttribute("aria-selected");
  const openAIOverallStatus = await page.locator("#guardrailOverallStatus").textContent();
  await page.click("#closeDataQuality");
  const checkboxBox = await page.locator("#approvalConfirm").boundingBox();
  const confirmationBox = await page.locator(".approval-check span").boundingBox();
  const confirmationAligned = Boolean(checkboxBox && confirmationBox && Math.abs((checkboxBox.y + checkboxBox.height / 2) - (confirmationBox.y + confirmationBox.height / 2)) <= 2);
  const horizontalOverflowAfterRun = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  const allUnchecked = (values) => values.length === 4 && values.every((value) => value === false);
  const expectedManualEvidence = evidenceAfterRun.join(",") === "true,true,true,false";
  const cashflowVietnamese = cashflowTitle?.trim() === "Dòng tiền hợp đồng"
    && cashflowSubtitle?.trim() === "CON-004 · Đơn hàng (06) + Hóa đơn (07) · triệu VND"
    && cashflowLegend.map((item) => item.trim()).join(",") === "Dòng tiền tích lũy,Vùng thiếu hụt vốn,Điểm hòa vốn"
    && /tích lũy .* triệu · thu .* triệu · chi .* triệu/.test(cashflowTooltip || "")
    && cashflowStatus?.trim() === "ĐÃ LIÊN KẾT HỢP ĐỒNG"
    && cashflowDeficitArea === 1
    && cashflowBreakEvenLine === 1
    && cashflowBreakEvenLabel?.trim() === "0"
    && cashflowMonthLabels.includes("06")
    && cashflowMonthLabels.includes("11")
    && !/(Số dư tiền cuối tháng|SỐ DƯ TIỀN CUỐI THÁNG|Trục X|Trục Y)/.test(cashflowVisibleText || "");
  if (contractSelectLabel?.trim() !== "CON-004- Liên hiệp HTX Xanh" || contractInputLabel?.trim() !== "CON-004- Liên hiệp HTX Xanh" || contractSourceHintPresent !== 0 || !founderControlHeading.includes("Xác nhận hồ sơ") || !allUnchecked(evidenceAtLoad) || !allUnchecked(evidenceAfterContractChange) || !allUnchecked(evidenceAfterUpload) || !allUnchecked(evidenceAfterContextChange) || !expectedManualEvidence || !cashflowVietnamese || !reconciliationHiddenAtLoad || !reconciliationHiddenAfterRun || !reconciliationDialogClosedByDefault || uploadActionLabel?.trim() !== "Upload TeamPack" || !confirmationAligned || horizontalOverflowAfterRun > 1 || guardrailsOpenedFromArrow !== "true" || !openAIOverallStatus?.trim()) {
    throw new Error("Contract label, upload action, or Founder confirmation alignment is invalid.");
  }
  await page.screenshot({ path: path.join(outputDir, "dashboard_main.png"), fullPage: true });

  const result = {
    title: await page.title(),
    horizontalOverflowAtLoad,
    horizontalOverflowAfterRun,
    contractSelectLabel,
    contractInputLabel,
    contractSourceHintPresent,
    founderControlHeading,
    evidenceAtLoad,
    evidenceAfterContractChange,
    evidenceAfterUpload,
    evidenceAfterContextChange,
    evidenceAfterRun,
    cashflowTitle,
    cashflowSubtitle,
    cashflowLegend,
    cashflowTooltip,
    cashflowStatus,
    cashflowDeficitArea,
    cashflowBreakEvenLine,
    cashflowBreakEvenLabel,
    cashflowMonthLabels,
    sheets: await page.textContent("#sheetCount"),
    decision: await page.textContent("#decisionType"),
    gate: await page.textContent("#gateStatus"),
    stressPresetPresent,
    reconciliationDisabledAtLoad,
    reconciliationHiddenAtLoad,
    reconciliationEnabledAfterRun,
    reconciliationHiddenAfterRun,
    reconciliationDialogClosedByDefault,
    reconciliationRows,
    reconciliationFilters,
    reconciliationRoute,
    anomalyRows,
    privacyMasked,
    partnerLogos: await page.locator(".partner-logo-shell img").count(),
    agentIcons: await page.locator(".agent-icon svg").count(),
    openaiMarks: await page.locator('img[src="/static/assets/openai-blossom.svg"]').count(),
    qualityRows,
    qualitySheets,
    controlTabs,
    dataQualityDefault,
    extractionFieldCards,
    extractionPanelVisible,
    guardrailColumns,
    maskedJsonPanels,
    guardrailsOpenedFromArrow,
    openAIOverallStatus,
    qualityActionsVisible,
    actionsInsideDialog,
    uploadActionLabel,
    confirmationAligned,
    simulationLabels: await page.locator(".simulation-badge").allTextContents(),
  };
  process.stdout.write(JSON.stringify(result) + "\n");
} finally {
  await browser?.close();
  server.kill("SIGTERM");
  await fs.rm(fixtureDir, { recursive: true, force: true });
}
