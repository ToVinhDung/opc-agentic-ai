const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const appState = {
  bootstrap: null,
  result: null,
  preset: "live",
  running: false,
  qualityFilter: "ALL",
  reconciliationFilter: "ALL",
  controlTab: "data-quality",
};

const PARTNER_LOGOS = Object.freeze({
  vietinbank: { src: "/static/assets/partners/vietinbank.svg", alt: "Logo VietinBank" },
  coopbank: { src: "/static/assets/partners/coopbank.png", alt: "Logo Co-opBank" },
  partnerx: { src: "/static/assets/partners/partnerx.svg", alt: "Logo giả lập PartnerX" },
});

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const formatVnd = (value, compact = true) => {
  const number = Number(value || 0);
  if (compact) {
    if (Math.abs(number) >= 1_000_000_000) return `${(number / 1_000_000_000).toFixed(2)} tỷ`;
    if (Math.abs(number) >= 1_000_000) return `${Math.round(number / 1_000_000).toLocaleString("vi-VN")} triệu`;
  }
  return `${Math.round(number).toLocaleString("vi-VN")} VND`;
};

const formatPercent = (value, digits = 1) => `${(Number(value || 0) * 100).toFixed(digits)}%`;

const compactAuditId = (value) => {
  const fullId = String(value || "");
  const match = fullId.match(/^((?:TRACE|APR)-\d{8}-\d{6})-([0-9A-F]{32})$/i);
  return match ? `${match[1]}-${match[2].slice(0, 8)}…` : fullId;
};

const firstFinite = (...values) => {
  for (const value of values) {
    const number = Number(value);
    if (value !== null && value !== "" && Number.isFinite(number)) return number;
  }
  return null;
};

const contractLabel = (contract) => contract?.display_name
  || `${contract?.contract_id || "—"}- ${contract?.customer_name || contract?.customer_id || contract?.description || "Chưa có tên khách hàng"}`;

function fundingSnapshot(finance = {}) {
  const need = firstFinite(finance.immediate_liquidity_need) || 0;
  const capacity = firstFinite(
    finance.eligible_funding_capacity,
    finance.potential_funding_capacity,
    finance.funding_capacity,
    finance.working_capital_request,
  );
  const explicitCoverage = firstFinite(finance.funding_coverage_ratio, finance.funding_coverage);
  const coverage = explicitCoverage ?? (need > 0 && capacity !== null ? capacity / need : null);
  const shortfall = firstFinite(finance.funding_shortfall)
    ?? (capacity !== null ? Math.max(0, need - capacity) : null);
  return { need, capacity, coverage, shortfall };
}

function normaliseQuality(result = {}) {
  const supplied = result.data_quality || result.finance?.data_quality || {};
  const issues = [...(Array.isArray(supplied.issues) ? supplied.issues : [])];
  if (!issues.length && Array.isArray(result.finance?.missing_fields)) {
    result.finance.missing_fields.forEach((item) => {
      if (!item || typeof item !== "object") return;
      const source = item.source || "UNMAPPED";
      issues.push({
        level: item.level || "BLOCKING",
        sheet: item.sheet || String(source).split("[")[0] || "UNMAPPED",
        label: item.label || item.field || "Dữ liệu bắt buộc",
        source,
        impact: item.impact || "Không thể hoàn tất phân tích hợp đồng.",
        request: item.request || "Bổ sung vào TeamPack rồi upload lại.",
        expected_type: item.expected_type || "Theo cấu trúc TeamPack",
        issue_type: item.issue_type || "FIELD_MISSING",
        required_fields: item.required_fields || [],
      });
    });
  }
  const count = (level) => issues.filter((item) => String(item.level || "").toUpperCase() === level).length;
  const affectedSheets = [...new Set(issues.map((item) => item.sheet).filter(Boolean))];
  return {
    ...supplied,
    issues,
    blocking_count: firstFinite(supplied.blocking_count) ?? count("BLOCKING"),
    warning_count: firstFinite(supplied.warning_count) ?? count("WARNING"),
    optional_count: firstFinite(supplied.optional_count) ?? count("OPTIONAL"),
    total_issue_count: firstFinite(supplied.total_issue_count) ?? issues.length,
    affected_sheets: supplied.affected_sheets || affectedSheets,
    affected_sheet_count: firstFinite(supplied.affected_sheet_count) ?? affectedSheets.length,
  };
}

function reconciliationSource(result = {}) {
  const source = result?.risk?.transaction_reconciliation || result?.transaction_reconciliation || {};
  return source && typeof source === "object" && !Array.isArray(source) ? source : {};
}

const normaliseRecordId = (value) => String(value || "").toUpperCase().replace(/[^A-Z0-9]/g, "");

const truthyFlag = (value) => value === true || value === 1 || ["TRUE", "YES", "Y", "1"].includes(String(value || "").toUpperCase());

function maskSensitive(value, visibleTail = 3) {
  const text = String(value ?? "").trim();
  if (!text) return "—";
  if (/[•*]{2,}/.test(text) || /MASKED|REDACTED/i.test(text)) return text;
  const compact = text.replace(/\s+/g, " ");
  return `••••${compact.slice(-Math.min(visibleTail, compact.length))}`;
}

function sanitizeReconciliationPayload(value, key = "") {
  if (value === null || value === undefined) return value;
  const sensitive = /(counterparty|account|beneficiary|iban)/i.test(key);
  if (sensitive) {
    if (Array.isArray(value)) return value.map((item) => sanitizeReconciliationPayload(item, key));
    if (typeof value === "object") return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => [childKey, sanitizeReconciliationPayload(childValue, key)]));
    return maskSensitive(value, /account|iban/i.test(key) ? 4 : 3);
  }
  if (Array.isArray(value)) return value.map((item) => sanitizeReconciliationPayload(item));
  if (typeof value === "object") return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => [childKey, sanitizeReconciliationPayload(childValue, childKey)]));
  return value;
}

function normaliseReconciliation(result = {}) {
  const source = reconciliationSource(result);
  const records = Array.isArray(source.records)
    ? source.records
    : Array.isArray(source.transactions) ? source.transactions
      : Array.isArray(source.items) ? source.items : [];
  const enterpriseAnomalies = Array.isArray(source.enterprise_anomalies) ? source.enterprise_anomalies : [];
  const reverseWarnings = Array.isArray(source.reverse_paid_warnings) ? source.reverse_paid_warnings : [];
  const selectedContractId = source.scope?.contract_id || result?.contract?.contract_id || $("#contractSelect")?.value || "—";
  const itemId = (item, fallback = "") => item?.txn_id || item?.transaction_id || item?.record_id || item?.invoice_id || fallback;
  const anomalyIds = new Set(enterpriseAnomalies.map((item) => normaliseRecordId(itemId(item))).filter(Boolean));
  const reverseWarningIds = new Set(reverseWarnings.map((item) => normaliseRecordId(itemId(item))).filter(Boolean));
  const baseIds = new Set(records.map((item) => normaliseRecordId(itemId(item))).filter(Boolean));
  const augmented = records.map((item) => ({ raw: item, kind: "TRANSACTION" }));
  enterpriseAnomalies.forEach((item, index) => {
    const id = normaliseRecordId(itemId(item));
    if (!id || !baseIds.has(id)) augmented.push({ raw: item, kind: "ANOMALY", fallbackId: `ANOMALY-${index + 1}` });
  });
  reverseWarnings.forEach((item, index) => {
    const id = normaliseRecordId(itemId(item));
    if (!id || !baseIds.has(id)) augmented.push({ raw: item, kind: "REVIEW", fallbackId: `REVIEW-${index + 1}` });
  });

  const rows = augmented.map(({ raw, kind, fallbackId }, index) => {
    const transactionId = String(itemId(raw, fallbackId || `TXN-${index + 1}`));
    const normalisedId = normaliseRecordId(transactionId);
    const matchStatus = String(raw.match_status || raw.status || raw.outcome || "UNKNOWN").toUpperCase();
    const matchLevel = String(raw.match_level || raw.match_type || "NONE").toUpperCase();
    const hasIncludedFlag = Object.prototype.hasOwnProperty.call(raw, "included_in_selected_contract");
    const included = hasIncludedFlag
      ? truthyFlag(raw.included_in_selected_contract)
      : truthyFlag(raw.in_selected_contract);
    const excluded = (hasIncludedFlag && !included) || /EXCLUDED|UNMATCHED|OUTSIDE|NOT_LINKED|BROKEN|AMBIGUOUS/.test(matchStatus);
    const anomaly = kind === "ANOMALY" || anomalyIds.has(normalisedId) || truthyFlag(raw.is_anomaly) || truthyFlag(raw.is_enterprise_anomaly) || /ANOMAL/.test(matchStatus);
    const review = kind === "REVIEW" || reverseWarningIds.has(normalisedId) || truthyFlag(raw.requires_review) || excluded || anomaly || /REVIEW|WARNING/.test(matchStatus);
    const explicitScope = String(raw.scope?.type || raw.scope || "").toUpperCase();
    const scopes = new Set();
    const backendScopes = Array.isArray(raw.scopes) ? raw.scopes.map((scope) => String(scope).toUpperCase()) : [];
    [...backendScopes, explicitScope].forEach((scope) => {
      if (scope.includes("BOTH")) {
        scopes.add("CASE");
        scopes.add("ENTERPRISE");
      }
      if (scope.includes("CASE")) scopes.add("CASE");
      if (scope.includes("ENTERPRISE")) scopes.add("ENTERPRISE");
      if (scope.includes("REVIEW")) scopes.add("REVIEW");
    });
    // Backward-compatible fallback is still driven only by backend flags and
    // statuses; no transaction identifier receives special treatment.
    if (!scopes.size) scopes.add(included ? "CASE" : "ENTERPRISE");
    if (included) scopes.add("CASE");
    if (anomaly) scopes.add("ENTERPRISE");
    if (review) scopes.add("REVIEW");
    const status = anomaly ? "ANOMALY" : excluded ? "EXCLUDED" : matchStatus;
    const statusClass = anomaly ? "anomaly" : excluded || kind === "REVIEW" ? "excluded" : /MATCHED|INCLUDED|PASS/.test(matchStatus) ? "matched" : "neutral";
    const invoiceId = raw.invoice_id || raw.lineage?.invoice_id || "—";
    const orderId = raw.order_id || raw.lineage?.order_id || "—";
    const contractId = raw.contract_id || raw.lineage?.contract_id || "—";
    const matchPath = matchLevel === "NONE" && invoiceId === "—"
      ? "NONE · Không có invoice match"
      : `${matchLevel} · ${invoiceId} → ${orderId} → ${contractId}`;
    return {
      transactionId,
      transactionDate: raw.txn_date || raw.transaction_date || raw.date || "—",
      direction: String(raw.direction || "").toUpperCase(),
      amount: firstFinite(raw.amount, raw.txn_amount, raw.value),
      counterparty: maskSensitive(raw.counterparty_masked || raw.masked_counterparty || raw.counterparty_token || raw.counterparty_id || raw.counterparty, 3),
      account: maskSensitive(raw.account_masked || raw.masked_account || raw.account_id || raw.account_number, 4),
      scopes: [...scopes],
      status,
      statusClass,
      matchPath,
      reason: raw.reason || raw.detail || raw.explanation || raw.message || raw.title || "Không có diễn giải bổ sung.",
      included,
      excluded,
      anomaly,
      review,
    };
  });

  const kpis = source.kpis || source.summary || {};
  const total = firstFinite(kpis.incoming_txn_count, kpis.total_records, kpis.total) ?? records.length;
  const included = firstFinite(kpis.selected_contract_matched_txn_count, kpis.included_incoming_count, kpis.included_count)
    ?? rows.filter((row) => row.included && !row.excluded).length;
  const excluded = firstFinite(kpis.excluded_incoming_count, kpis.unmatched_incoming_count, kpis.excluded_count)
    ?? rows.filter((row) => row.excluded).length;
  const anomalies = firstFinite(kpis.enterprise_anomaly_count, kpis.anomaly_count)
    ?? rows.filter((row) => row.anomaly).length;
  const route = Array.isArray(source.route) && source.route.length
    ? source.route
    : ["08_BANK_TXN", "07_INVOICES", "06_ORDERS", "04_CONTRACTS"];
  return { source, rows, selectedContractId, total, included, excluded, anomalies, route };
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { element.className = "toast"; }, 3200);
}

async function api(path, payload = null) {
  const options = payload === null
    ? { headers: { Accept: "application/json" } }
    : { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(payload) };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
  if (!response.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
  return data;
}

async function bootstrap() {
  try {
    const data = await api("/api/bootstrap");
    appState.bootstrap = data;
    renderBootstrap(data);
    const autorun = new URLSearchParams(window.location.search).get("autorun");
    if (["main", "live"].includes(autorun)) {
      setTimeout(runWorkflow, 250);
    }
  } catch (error) {
    $("#dataBadge").className = "status-pill status-error";
    $("#dataBadge").innerHTML = '<span class="dot"></span> Không đọc được dữ liệu';
    toast(error.message, true);
  }
}

function renderBootstrap(data, preferredContractId = null) {
  const missingValues = data.data.missing_contract_values || [];
  const contracts = Array.isArray(data.contracts) ? data.contracts : [];
  $("#dataBadge").className = `status-pill ${missingValues.length ? "status-warning" : "status-ok"}`;
  $("#dataBadge").innerHTML = `<span class="dot"></span> ${missingValues.length ? "TeamPack · thiếu contract value" : `TeamPack · ${contracts.length} contracts`}`;
  $("#sheetCount").textContent = `${data.data.sheet_count} sheets`;
  $("#fileName").textContent = data.data.file_name;
  $("#workbookStatus").textContent = data.data.file_name;
  $("#missingDataCount").textContent = String(missingValues.length);
  $("#controlBlocking").textContent = "—";
  $("#controlWarning").textContent = "—";
  $("#openDataQuality").disabled = true;
  $("#openDataQuality").textContent = "Chi tiết";
  $("#cashflowDataStatus").textContent = "CHỜ PHÂN TÍCH";
  $("#fundingMappingStatus").textContent = "WAITING";
  $("#fundingMappingStatus").style.color = "";
  $("#cashflowMethod").textContent = "Chạy luồng phân tích để lập dòng tiền hợp đồng";
  $("#sourceHash").textContent = data.data.sha256_short;
  $("#schemaStatus").textContent = data.data.required_sheets_ok ? (missingValues.length ? "SCHEMA PASS · VALUE MISSING" : "PASS") : "FAIL";
  $("#schemaStatus").style.color = data.data.required_sheets_ok ? (missingValues.length ? "#d97706" : "#14946f") : "#dc3545";

  const openaiBadge = $("#openaiBadge");
  if (data.openai.configured) {
    openaiBadge.className = "status-pill status-ok openai-status";
    openaiBadge.innerHTML = `<img src="/static/assets/openai-blossom.svg" alt="OpenAI"> OpenAI · ${escapeHtml(data.openai.model)}`;
  } else {
    openaiBadge.className = "status-pill status-warning openai-status";
    openaiBadge.innerHTML = '<img src="/static/assets/openai-blossom.svg" alt="OpenAI"> OpenAI · cần API key';
  }
  $("#modelName").textContent = data.openai.model;

  const select = $("#contractSelect");
  const selectedId = contracts.some((contract) => contract.contract_id === preferredContractId)
    ? preferredContractId
    : contracts.some((contract) => contract.contract_id === "CON-004") ? "CON-004" : contracts[0]?.contract_id;
  select.innerHTML = contracts.map((contract) => (
    `<option value="${escapeHtml(contract.contract_id)}" ${contract.contract_id === selectedId ? "selected" : ""}>` +
    `${escapeHtml(contractLabel(contract))}</option>`
  )).join("");
  select.disabled = !contracts.length;
  $("#runButton").disabled = !contracts.length;
  resetRunView("Hãy chạy workflow cho hợp đồng đang chọn.");
  updateContractMeta();
}

function updateContractMeta(resetResult = false) {
  if (!appState.bootstrap) return;
  const selected = appState.bootstrap.contracts.find((item) => item.contract_id === $("#contractSelect").value);
  if (resetResult) resetRunView("Đã đổi hợp đồng · chạy workflow để tạo kết quả riêng cho hợp đồng này.");
  $("#contractDisplay").textContent = selected ? contractLabel(selected) : "—";
  $("#contractMeta").innerHTML = selected
    ? `<strong>${selected.contract_value ? formatVnd(selected.contract_value) : "MISSING"}</strong> · ${escapeHtml(selected.status || "Chưa có trạng thái")}<br>${escapeHtml(selected.description || "Chưa có mô tả hợp đồng")}`
    : "";
  $("#kpiContract").textContent = selected?.contract_value ? formatVnd(selected.contract_value) : "—";
  $("#kpiContractNote").textContent = selected ? "04_CONTRACTS · chờ đối soát 06_ORDERS" : "Không có hợp đồng để phân tích";
}

function resetReconciliationView() {
  appState.reconciliationFilter = "ALL";
  $("#openReconciliation").disabled = true;
  $("#openReconciliation").textContent = "Chi tiết đối soát";
  $("#downloadReconciliation").disabled = true;
  $("#reconciliationContract").textContent = "—";
  $("#reconciliationTotal").textContent = "0";
  $("#reconciliationIncluded").textContent = "0";
  $("#reconciliationExcluded").textContent = "0";
  $("#reconciliationAnomalies").textContent = "0";
  $("#reconciliationTruth").textContent = "Rule engine là nguồn sự thật";
  $("#reconciliationRoute").innerHTML = '<span>08_BANK_TXN</span><i>→</i><span>07_INVOICES</span><i>→</i><span>06_ORDERS</span><i>→</i><span>04_CONTRACTS</span><small>Đối soát theo khóa liên kết · không suy đoán giao dịch ngoài phạm vi</small>';
  $("#reconciliationRows").innerHTML = '<tr><td colspan="6" class="reconciliation-empty">Chạy Agent Workflow để đối soát giao dịch.</td></tr>';
  $$("#reconciliationFilters button").forEach((button) => button.classList.toggle("active", button.dataset.scope === "ALL"));
  if ($("#reconciliationDialog").open) $("#reconciliationDialog").close();
}

function resetRunView(message = "Hãy chạy workflow để tạo kết quả.") {
  appState.result = null;
  ["#contractSigned", "#agingEvidence", "#capacityPlan", "#txnReviewed"].forEach((selector) => {
    $(selector).checked = false;
  });
  $("#missingDataCount").textContent = "—";
  $("#schemaStatus").textContent = "SCHEMA PASS · RUN DATA GATE";
  $("#schemaStatus").style.color = "#1d56ca";
  $("#traceId").textContent = "CHƯA CHẠY";
  $("#workflowState").textContent = "READY";
  ["finance", "risk", "decision"].forEach((agent) => setAgentState(agent, "", "WAITING"));
  $("#financeAgentSummary").textContent = "Đọc workbook, chuẩn hóa dữ liệu và tạo Financial Snapshot riêng theo hợp đồng.";
  $("#riskAgentSummary").textContent = "Áp rule, phát hiện dữ liệu thiếu và kích hoạt approval gate.";
  $("#decisionAgentSummary").textContent = "Chỉ xếp hạng vốn khi mapping của hợp đồng đã đầy đủ.";
  $("#kpiMargin").textContent = "—";
  $("#kpiMarginNote").textContent = "Chờ phân tích";
  $("#kpiGap").textContent = "—";
  $("#kpiGapNote").textContent = "Chờ funding coverage";
  $("#kpiRisk").textContent = "—";
  $("#kpiRiskNote").textContent = "CASE / ENTERPRISE";
  $("#cashflowDataStatus").textContent = "CHỜ PHÂN TÍCH";
  $("#cashflowDataStatus").style.color = "";
  $("#fundingMappingStatus").textContent = "WAITING";
  $("#fundingMappingStatus").style.color = "";
  $("#cashflowMethod").textContent = "Chạy luồng phân tích để lập dòng tiền hợp đồng";
  $("#cashflowChart").className = "chart-empty";
  $("#cashflowChart").textContent = message;
  $("#riskSummary").textContent = "Chưa chạy";
  $("#riskList").className = "empty-list";
  $("#riskList").textContent = "Các cảnh báo sẽ xuất hiện tại đây.";
  resetReconciliationView();
  $("#partnerStatus").textContent = "WAITING";
  $("#partnerRows").innerHTML = '<tr><td colspan="5" class="table-empty">Chưa có kết quả xếp hạng.</td></tr>';
  $("#decisionCard").className = "decision-card empty";
  $("#decisionType").textContent = "WAITING FOR WORKFLOW";
  $("#decisionConfidence").textContent = "—";
  $("#heroTitle").textContent = message;
  $("#heroSubtitle").textContent = "Mỗi kết quả chỉ áp dụng cho hợp đồng và TeamPack ghi trên Trace.";
  $("#decisionReasons").innerHTML = "<li>Hệ thống chưa tạo Decision Card cho lựa chọn hiện tại.</li>";
  $("#humanCondition").textContent = "Điểm xác nhận của Founder sẽ xuất hiện tại đây.";
  $("#controlStatus").textContent = "NOT RUN";
  $("#controlMessage").textContent = "Data Gate sẽ chỉ rõ sheet và trường còn thiếu; Founder sửa workbook rồi upload lại.";
  $("#controlBlocking").textContent = "—";
  $("#controlWarning").textContent = "—";
  $("#controlMissing").textContent = "—";
  $("#controlOpenAI").textContent = "—";
  $("#dataQualityCard").className = "control-card neutral";
  $("#openDataQuality").disabled = true;
  $("#openDataQuality").textContent = "Chi tiết";
  $("#logRows").innerHTML = "";
  $("#evidenceButton").disabled = true;
  renderOpenAIEvidence({});
  setControlTab("data-quality");
  $("#exportButton").disabled = true;
  $("#approvalConfirm").disabled = true;
  $("#approvalConfirm").checked = false;
  $("#founderName").disabled = true;
  $("#approveButton").disabled = true;
  $("#rejectButton").disabled = true;
  $("#approvalInstruction").textContent = "Tôi đã đọc điều kiện bảo vệ và hiểu đây là tiền kiểm mô phỏng.";
  $("#gateStatus").className = "gate-status pending";
  $("#gateStatus").innerHTML = "<span>●</span> NOT READY";
}

function currentPayload() {
  return {
    contract_id: $("#contractSelect").value,
    preset: appState.preset,
    use_openai: $("#useOpenAI").checked,
    evidence: {
      contract_signed: $("#contractSigned").checked,
      receivable_aging: $("#agingEvidence").checked,
      capacity_plan: $("#capacityPlan").checked,
      suspicious_txn_reviewed: $("#txnReviewed").checked,
    },
    scenario: {
      cost_increase_pct: 0,
      payment_delay_days: 0,
      deadline_change_days: 0,
      scope_change_pct: 0,
      collateral_change_pp: 0,
    },
  };
}

function setAgentState(agent, state, text) {
  const node = $(`.agent-node[data-agent="${agent}"]`);
  node.classList.remove("running", "done", "blocked");
  if (state) node.classList.add(state);
  node.querySelector(".agent-status").textContent = text;
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function animateWorkflow(promise) {
  $("#workflowState").textContent = "RUNNING";
  setAgentState("finance", "running", "READING XLSX");
  setAgentState("risk", "", "WAITING");
  setAgentState("decision", "", "WAITING");
  await wait(350);
  setAgentState("finance", "done", "SNAPSHOT READY");
  setAgentState("risk", "running", "APPLYING RULES");
  await wait(360);
  setAgentState("risk", "done", "RISK REPORT READY");
  setAgentState("decision", "running", "RANKING OPTIONS");
  const result = await promise;
  await wait(280);
  const decisionType = String(result.decision?.decision_type || "").toUpperCase();
  const blocked = decisionType === "NEED MORE DATA";
  const needsReview = decisionType === "NEED REVIEW";
  if (blocked) {
    setAgentState("finance", "blocked", "NEED MORE DATA");
    setAgentState("risk", "blocked", "BLOCKED BY DATA");
    setAgentState("decision", "blocked", "WAITING FOR DATA");
  } else if (needsReview) {
    setAgentState("decision", "blocked", "FOUNDER REVIEW");
  } else {
    setAgentState("decision", "done", "DECISION READY");
  }
  $("#workflowState").textContent = blocked ? "BLOCKED SAFELY" : needsReview ? "REVIEW REQUIRED" : "COMPLETE";
  return result;
}

async function runWorkflow() {
  if (appState.running) return;
  appState.running = true;
  const button = $("#runButton");
  button.disabled = true;
  button.innerHTML = '<span class="run-icon">◌</span><span>Agents đang phối hợp...</span>';
  try {
    const promise = api("/api/analyze", currentPayload());
    const result = await animateWorkflow(promise);
    appState.result = result;
    renderResult(result);
    toast(result.openai.status === "validated" ? "Workflow hoàn tất · OpenAI output đã qua guardrails" : "Workflow hoàn tất · Decision Card đã được kiểm soát");
  } catch (error) {
    setAgentState("finance", "blocked", "ERROR");
    $("#workflowState").textContent = "FAILED SAFELY";
    const control = $("#dataQualityCard");
    control.className = "control-card error";
    $("#controlStatus").textContent = "REQUEST ERROR";
    $("#controlMessage").textContent = error.message;
    $("#controlOpenAI").textContent = "not completed";
    toast(error.message, true);
  } finally {
    appState.running = false;
    button.disabled = false;
    button.innerHTML = '<span class="run-icon">▶</span><span>Chạy lại Agent Workflow</span>';
  }
}

function renderResult(result) {
  const finance = result.finance || {};
  const risk = result.risk || { case_risk_level: "Unknown", enterprise_risk_level: "Unknown", alerts: [] };
  const partner = result.partner || { status: "NEED MORE DATA", options: [] };
  const missing = Array.isArray(finance.missing_data) ? finance.missing_data : [];
  const missingFields = Array.isArray(finance.missing_fields) ? finance.missing_fields : [];
  const quality = normaliseQuality(result);
  const funding = fundingSnapshot(finance);
  const financeBlocked = finance.cashflow_status === "BLOCKED_BY_DATA" || result.decision?.decision_type === "NEED MORE DATA";
  const marginBlocked = missingFields.some((item) => ["order_revenue", "estimated_cost"].includes(item.field));
  const mappingIssue = quality.issues.some((item) => (
    String(item.level || "").toUpperCase() === "BLOCKING"
    && (String(item.sheet || "").includes("10_CREDIT_PROFILE") || String(item.issue_type || "").includes("MAPPING"))
  ));
  const explicitMappingStatus = finance.credit_mapping_status || finance.funding_mapping_status || partner.mapping_status;
  const fundingMappingStatus = explicitMappingStatus
    || (mappingIssue || funding.capacity === null ? "NEED MORE DATA" : "PRECHECK FOUND");
  const fundingMappingBlocked = mappingIssue || funding.capacity === null
    || /(NEED|MISSING|UNMAPPED|BLOCK)/i.test(String(fundingMappingStatus));
  $("#dataBadge").className = `status-pill ${quality.blocking_count ? "status-warning" : "status-ok"}`;
  $("#dataBadge").innerHTML = `<span class="dot"></span> ${quality.blocking_count ? `TeamPack · ${quality.blocking_count} blocking` : quality.warning_count ? `TeamPack · passed · ${quality.warning_count} warning` : "TeamPack · data gate passed"}`;
  $("#schemaStatus").textContent = quality.blocking_count ? "SCHEMA PASS · DATA GATE BLOCK" : "PASS · DATA GATE READY";
  $("#schemaStatus").style.color = quality.blocking_count ? "#d97706" : "#14946f";
  $("#traceId").textContent = compactAuditId(result.trace_id);
  $("#heroTitle").textContent = result.decision.headline;
  $("#heroSubtitle").textContent = `Đọc ${result.source?.sheets_used?.length || 0} sheet · ${result.workflow?.length || 0} sự kiện · deterministic ${result.performance?.deterministic_total_ms ?? "—"} ms`;
  $("#kpiContract").textContent = Number(finance.contract_value) > 0 ? formatVnd(finance.contract_value) : "MISSING";
  $("#kpiContractNote").textContent = `Order coverage ${formatPercent(finance.order_coverage_ratio)} · 04_CONTRACTS/06_ORDERS`;
  $("#kpiMargin").textContent = marginBlocked ? "NEED DATA" : `${formatPercent(finance.gross_margin)} / ${formatPercent(finance.target_gross_margin)}`;
  const marginDeltaPp = (Number(finance.gross_margin || 0) - Number(finance.target_gross_margin || 0)) * 100;
  $("#kpiMarginNote").textContent = marginBlocked
    ? "Không tính biên khi thiếu revenue/cost bắt buộc"
    : Math.abs(marginDeltaPp) < 0.05 ? "Bằng mục tiêu"
      : marginDeltaPp > 0 ? `Cao hơn mục tiêu ${marginDeltaPp.toFixed(1)} điểm %`
        : `Thấp hơn mục tiêu ${Math.abs(marginDeltaPp).toFixed(1)} điểm %`;
  $("#kpiGap").textContent = financeBlocked ? "NEED DATA" : formatVnd(finance.immediate_liquidity_need);
  $("#kpiGapNote").textContent = financeBlocked
    ? "Dòng tiền/nguồn vốn bị khóa đến khi bổ sung đủ liên kết dữ liệu"
    : funding.coverage === null
      ? "Chưa xác định funding coverage cho hợp đồng"
      : `Funding coverage ${formatPercent(funding.coverage)} · capacity ${formatVnd(funding.capacity || 0)}${funding.shortfall ? ` · thiếu ${formatVnd(funding.shortfall)}` : ""}`;
  $("#kpiRisk").textContent = `CASE ${String(risk.case_risk_level || "UNKNOWN").toUpperCase()}`;
  $("#kpiRisk").style.color = risk.case_risk_level === "Critical" ? "#dc3545" : risk.case_risk_level === "High" ? "#d97706" : "#14946f";
  $("#kpiRiskNote").textContent = `Enterprise ${risk.enterprise_risk_level || "Unknown"} · không quy chụp vào hồ sơ`;
  $("#missingDataCount").textContent = String(quality.blocking_count || 0);
  $("#fundingMappingStatus").textContent = String(fundingMappingStatus).replaceAll("_", " ");
  $("#fundingMappingStatus").style.color = fundingMappingBlocked ? "#b66a05" : "#159873";
  const cashflowBlocked = ["BLOCKED_BY_DATA", "NEED_MORE_DATA"].includes(String(finance.cashflow_status || "").toUpperCase());
  $("#cashflowDataStatus").textContent = cashflowBlocked ? "TẠM KHÓA DO THIẾU DỮ LIỆU" : "ĐÃ LIÊN KẾT HỢP ĐỒNG";
  $("#cashflowDataStatus").style.color = cashflowBlocked ? "#b66a05" : "#159873";
  $("#decisionConfidence").textContent = result.decision.confidence
    ? `Confidence ${formatPercent(result.decision.confidence, 0)}`
    : "Controlled output";
  $("#financeAgentSummary").textContent = financeBlocked
    ? `${finance.linked_order_count || 0} orders · ${finance.linked_invoice_count || 0} invoices · ${quality.blocking_count} blocking / ${quality.warning_count} warning; Financial Snapshot bị khóa an toàn.`
    : `${finance.linked_order_count || 0} orders · ${finance.linked_invoice_count || 0} invoices · margin ${formatPercent(finance.gross_margin)} · funding coverage ${funding.coverage === null ? "chưa xác định" : formatPercent(funding.coverage)}.`;
  $("#riskAgentSummary").textContent = `${risk.case_risk_level || "Unknown"} case risk · ${(risk.alerts || []).length} alerts · enterprise ${risk.enterprise_risk_level || "Unknown"}.`;
  $("#decisionAgentSummary").textContent = `${result.decision.decision_type} · ${(partner.options || []).length} partner options · ${result.openai?.status || "not requested"}.`;
  $("#cashflowMethod").textContent = `${result.contract.contract_id} · Đơn hàng (06) + Hóa đơn (07) · triệu VND`;
  renderChart(finance.contract_cashflow, finance);
  renderRisks(risk);
  renderReconciliation(result, appState.reconciliationFilter);
  renderPartners(partner);
  renderDecision(result);
  renderControlStatus(result);
  renderOpenAIEvidence(result.openai);
  renderLogs(result.workflow);
  $("#evidenceButton").disabled = false;
  $("#exportButton").disabled = false;

}

function renderControlStatus(result) {
  const quality = normaliseQuality(result);
  const openai = result.openai || {};
  const extraction = openai.extraction || {};
  const challenger = openai.challenger || {};
  const guardrailCount = (Array.isArray(extraction.validation) ? extraction.validation.length : 0)
    + (Array.isArray(challenger.validation) ? challenger.validation.length : 0);
  const card = $("#dataQualityCard");
  $("#controlBlocking").textContent = String(quality.blocking_count || 0);
  $("#controlWarning").textContent = String(quality.warning_count || 0);
  $("#controlMissing").textContent = String(quality.total_issue_count || 0);
  $("#controlOpenAI").textContent = openai.status || "not requested";
  $("#openDataQuality").disabled = false;
  $("#openDataQuality").textContent = `Chi tiết (${quality.total_issue_count || 0})`;
  renderDataQuality(quality, appState.qualityFilter);

  if (quality.blocking_count) {
    card.className = "control-card warning";
    $("#controlStatus").textContent = "DATA BLOCK";
    $("#controlMessage").textContent = `${quality.blocking_count} lỗi chặn và ${quality.warning_count || 0} cảnh báo trên ${quality.affected_sheet_count || 0} sheet/nhóm dữ liệu. Nhấn Chi tiết để Founder xem đầy đủ.`;
    return;
  }
  if (openai.status === "blocked_by_data") {
    card.className = "control-card warning";
    $("#controlStatus").textContent = "DATA GATE";
    $("#controlMessage").textContent = "OpenAI không được gọi khi dữ liệu hoặc mapping theo hợp đồng còn thiếu. Founder sửa TeamPack và upload lại để kiểm tra.";
    return;
  }
  if (/(safe_fallback|blocked_by_validation|challenger_fallback)/.test(String(openai.status || ""))) {
    card.className = "control-card error";
    $("#controlStatus").textContent = String(openai.status).includes("fallback") ? "API FALLBACK" : "VALIDATION BLOCK";
    $("#controlMessage").textContent = extraction.error || challenger.error || openai.error || "OpenAI output không vượt qua guardrail; Decision Card giữ kết quả deterministic.";
    return;
  }
  if (openai.status === "validated") {
    card.className = "control-card good";
    $("#controlStatus").textContent = quality.warning_count ? "VALIDATED · WARN" : "VALIDATED";
    $("#controlMessage").textContent = `Data gate passed${quality.warning_count ? ` với ${quality.warning_count} cảnh báo` : ""}; Extraction và Challenger vượt qua ${guardrailCount} kiểm tra guardrail.`;
    return;
  }
  if (openai.status === "extraction_validated_data_blocked") {
    card.className = "control-card warning";
    $("#controlStatus").textContent = "EXTRACTION VALIDATED";
    $("#controlMessage").textContent = "Structured Evidence đã hợp lệ; Decision Challenger dừng đúng thiết kế vì Data Quality Gate đang chặn.";
    return;
  }
  card.className = "control-card neutral";
  $("#controlStatus").textContent = "RULE ENGINE";
  $("#controlMessage").textContent = "Lượt chạy dùng rule engine; trạng thái OpenAI được công bố rõ và không giả lập cuộc gọi API.";
}

function renderDataQuality(quality, level = "ALL") {
  const issues = (quality.issues || []).filter((item) => level === "ALL" || String(item.level || "").toUpperCase() === level);
  $("#qualityContract").textContent = appState.result?.contract?.contract_id || $("#contractSelect").value || "—";
  $("#qualityBlocking").textContent = String(quality.blocking_count || 0);
  $("#qualityWarning").textContent = String(quality.warning_count || 0);
  $("#qualityOptional").textContent = String(quality.optional_count || 0);
  $("#qualitySheets").textContent = String(quality.affected_sheet_count || 0);
  $("#qualityTruth").textContent = quality.truth_source ? "Rule engine là nguồn sự thật · OpenAI chỉ diễn giải" : "Rule engine là nguồn sự thật";
  $$("#qualityFilters button").forEach((button) => button.classList.toggle("active", button.dataset.level === level));

  if (!issues.length) {
    $("#qualityGroups").innerHTML = `<div class="quality-empty">${level === "ALL" ? "Không phát hiện vấn đề dữ liệu trong phạm vi kiểm tra." : `Không có mục ${escapeHtml(level.toLowerCase())}.`}</div>`;
    return;
  }

  const grouped = new Map();
  issues.forEach((issue) => {
    const sheet = issue.sheet || String(issue.source || "UNMAPPED").split("[")[0] || "UNMAPPED";
    if (!grouped.has(sheet)) grouped.set(sheet, []);
    grouped.get(sheet).push(issue);
  });
  let openedBlocking = false;
  $("#qualityGroups").innerHTML = [...grouped.entries()].map(([sheet, sheetIssues]) => {
    const dominant = sheetIssues.some((item) => String(item.level || "").toUpperCase() === "BLOCKING")
      ? "BLOCKING"
      : sheetIssues.some((item) => String(item.level || "").toUpperCase() === "WARNING") ? "WARNING" : "OPTIONAL";
    const shouldOpen = dominant === "BLOCKING" && !openedBlocking;
    if (shouldOpen) openedBlocking = true;
    const rows = sheetIssues.map((issue) => {
      const issueLevel = String(issue.level || "BLOCKING").toUpperCase();
      const required = (issue.required_fields || []).length
        ? `<span>Trường cần có: ${escapeHtml(issue.required_fields.join(", "))}</span>`
        : "";
      return `<div class="quality-issue"><span class="issue-level ${escapeHtml(issueLevel.toLowerCase())}">${escapeHtml(issueLevel)}</span><div class="issue-copy"><strong>${escapeHtml(issue.label || issue.field || "Dữ liệu bắt buộc")}</strong><code class="issue-source">${escapeHtml(issue.source || sheet)}</code><p>${escapeHtml(issue.impact || "Không thể hoàn tất phân tích hợp đồng.")} ${escapeHtml(issue.request || "Bổ sung vào TeamPack rồi upload lại.")}</p><div class="issue-requirement"><span>Yêu cầu: ${escapeHtml(issue.expected_type || "Theo cấu trúc TeamPack")}</span><span>${escapeHtml(issue.issue_type || "FIELD_MISSING")}</span>${required}</div></div></div>`;
    }).join("");
    return `<details class="quality-sheet" ${shouldOpen ? "open" : ""}><summary><span class="quality-sheet-name">${escapeHtml(sheet)}</span><span class="quality-sheet-count">${sheetIssues.length} mục</span><span class="quality-level-chip ${escapeHtml(dominant.toLowerCase())}">${escapeHtml(dominant)}</span></summary><div class="quality-issue-list">${rows}</div></details>`;
  }).join("");
}

function renderChart(rows, finance = {}) {
  if (["BLOCKED_BY_DATA", "NEED_MORE_DATA"].includes(String(finance.cashflow_status || "").toUpperCase())) {
    $("#cashflowChart").className = "chart-blocked";
    $("#cashflowChart").innerHTML = `<div><strong>CẦN BỔ SUNG DỮ LIỆU</strong><span>${escapeHtml(finance.cashflow_block_reason || "Không đủ dữ liệu để xác nhận phân tích dòng tiền.")}</span></div>`;
    return;
  }
  if (!rows?.length) {
    $("#cashflowChart").className = "chart-empty";
    $("#cashflowChart").textContent = "Chưa có dữ liệu dòng tiền.";
    return;
  }
  const width = 700;
  const height = 210;
  const pad = { left: 52, right: 18, top: 16, bottom: 30 };
  const values = rows.flatMap((row) => [row.cumulative_cashflow, 0]).map((v) => v / 1_000_000);
  let min = Math.min(...values, 0);
  let max = Math.max(...values, 0);
  const span = Math.max(100, max - min);
  min -= span * .12;
  max += span * .12;
  const x = (index) => pad.left + index * ((width - pad.left - pad.right) / Math.max(1, rows.length - 1));
  const y = (value) => pad.top + (max - value / 1_000_000) * ((height - pad.top - pad.bottom) / (max - min));
  const path = (field) => rows.map((row, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(row[field]).toFixed(1)}`).join(" ");
  const zeroY = y(0);
  const plotBottom = height - pad.bottom;
  const deficitAreaPath = [
    `M${x(0).toFixed(1)},${zeroY.toFixed(1)}`,
    ...rows.map((row, index) => `L${x(index).toFixed(1)},${y(row.cumulative_cashflow).toFixed(1)}`),
    `L${x(rows.length - 1).toFixed(1)},${zeroY.toFixed(1)}`,
    "Z",
  ].join(" ");
  const ticks = 4;
  const grid = Array.from({ length: ticks + 1 }, (_, index) => {
    const tickValue = min + (max - min) * index / ticks;
    const py = pad.top + (ticks - index) * (height - pad.top - pad.bottom) / ticks;
    return `<line class="chart-grid" x1="${pad.left}" x2="${width - pad.right}" y1="${py}" y2="${py}"/><text class="chart-label" x="${pad.left - 8}" y="${py + 3}" text-anchor="end">${Math.round(tickValue)}</text>`;
  }).join("");
  const labels = rows.map((row, index) => `<text class="chart-label chart-month-label" x="${x(index)}" y="${height - 8}" text-anchor="middle">${escapeHtml(row.month.slice(5))}</text>`).join("");
  const points = rows.map((row, index) => `<circle class="cashflow-point" cx="${x(index)}" cy="${y(row.cumulative_cashflow)}" r="4"><title>${escapeHtml(row.month)} · tích lũy ${Math.round(row.cumulative_cashflow / 1_000_000)} triệu · thu ${Math.round(row.cash_in / 1_000_000)} triệu · chi ${Math.round(row.cash_out / 1_000_000)} triệu</title></circle>`).join("");
  $("#cashflowChart").className = "chart-wrap";
  $("#cashflowChart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Biểu đồ dòng tiền tích lũy theo hợp đồng"><defs><clipPath id="cashflow-deficit-clip"><rect x="${pad.left}" y="${zeroY.toFixed(1)}" width="${width - pad.left - pad.right}" height="${Math.max(0, plotBottom - zeroY).toFixed(1)}"/></clipPath></defs>${grid}<path class="cashflow-deficit-area" d="${deficitAreaPath}" clip-path="url(#cashflow-deficit-clip)"/><line class="cashflow-break-even-line" x1="${pad.left}" x2="${width - pad.right}" y1="${zeroY.toFixed(1)}" y2="${zeroY.toFixed(1)}"/><text class="chart-break-even-label" x="${width - pad.right}" y="${(zeroY - 5).toFixed(1)}" text-anchor="end">0</text><path class="cashflow-series-line" d="${path("cumulative_cashflow")}"/>${points}${labels}</svg>`;
}

function renderRisks(risk) {
  const alerts = Array.isArray(risk?.alerts) ? risk.alerts : [];
  $("#riskSummary").textContent = `${alerts.length} alerts · human review ${risk?.human_review_required ? "required" : "not required"}`;
  const container = $("#riskList");
  container.className = alerts.length ? "risk-list" : "empty-list";
  container.innerHTML = alerts.length
    ? alerts.map((alert) => `<div class="risk-item ${escapeHtml(String(alert.severity || "medium").toLowerCase())}"><span class="severity-bar"></span><div><strong><span class="scope-tag">${escapeHtml(alert.scope || "CASE")}</span>${escapeHtml(alert.title || "Risk control")}</strong><p>${escapeHtml(alert.detail || "")} ${escapeHtml(alert.required_action || "")}</p></div><span class="risk-tag">${escapeHtml(alert.rule_id || "RULE")}</span></div>`).join("")
    : "Không có cảnh báo đủ dữ liệu để hiển thị.";
}

function renderReconciliation(result, filter = "ALL") {
  const reconciliation = normaliseReconciliation(result);
  $("#reconciliationContract").textContent = reconciliation.selectedContractId;
  $("#reconciliationTotal").textContent = String(reconciliation.total);
  $("#reconciliationIncluded").textContent = String(reconciliation.included);
  $("#reconciliationExcluded").textContent = String(reconciliation.excluded);
  $("#reconciliationAnomalies").textContent = String(reconciliation.anomalies);
  const reconciliationStatus = reconciliation.source.selected_contract_status || reconciliation.source.status;
  $("#reconciliationTruth").textContent = reconciliationStatus
    ? `${String(reconciliationStatus).replaceAll("_", " ")} · Rule engine là nguồn sự thật`
    : "Rule engine là nguồn sự thật · không dùng raw counterparty/account";
  $("#reconciliationRoute").innerHTML = `${reconciliation.route.map((step, index) => `${index ? "<i>→</i>" : ""}<span>${escapeHtml(step)}</span>`).join("")}<small>Đối soát theo khóa liên kết · không suy đoán giao dịch ngoài phạm vi</small>`;
  $$("#reconciliationFilters button").forEach((button) => button.classList.toggle("active", button.dataset.scope === filter));

  const rows = reconciliation.rows.filter((row) => filter === "ALL" || row.scopes.includes(filter));
  if (!rows.length) {
    $("#reconciliationRows").innerHTML = `<tr><td colspan="6" class="reconciliation-empty">${filter === "ALL" ? "Không có bản ghi đối soát trong kết quả này." : `Không có bản ghi thuộc ${escapeHtml(filter)}.`}</td></tr>`;
  } else {
    $("#reconciliationRows").innerHTML = rows.map((row) => {
      const privacyLine = [];
      if (row.counterparty !== "—") privacyLine.push(`Đối tác ${row.counterparty}`);
      if (row.account !== "—") privacyLine.push(`TK ${row.account}`);
      const context = [row.transactionDate, row.direction, ...privacyLine].filter((item) => item && item !== "—").join(" · ");
      const scopes = row.scopes.map((scope) => `<span class="reconciliation-scope ${escapeHtml(scope.toLowerCase())}">${escapeHtml(scope)}</span>`).join("");
      const amount = row.amount === null ? "—" : formatVnd(row.amount);
      return `<tr class="reconciliation-record ${escapeHtml(row.statusClass)}"><td data-label="Giao dịch"><strong>${escapeHtml(row.transactionId)}</strong><small>${escapeHtml(context)}</small></td><td data-label="Phạm vi"><div class="reconciliation-scopes">${scopes}</div></td><td data-label="Kết quả đối soát"><code>${escapeHtml(row.matchPath)}</code></td><td data-label="Số tiền" class="reconciliation-amount">${escapeHtml(amount)}</td><td data-label="Trạng thái"><span class="reconciliation-status ${escapeHtml(row.statusClass)}">${escapeHtml(row.status)}</span></td><td data-label="Giải thích"><p>${escapeHtml(row.reason)}</p></td></tr>`;
    }).join("");
  }
  $("#openReconciliation").disabled = false;
  $("#openReconciliation").textContent = `Chi tiết đối soát (${reconciliation.total})`;
  $("#downloadReconciliation").disabled = false;
}

function renderPartners(partner) {
  const status = String(partner?.status || "NEED MORE DATA").replaceAll("_", " ");
  const options = Array.isArray(partner?.options) ? partner.options : [];
  $("#partnerStatus").textContent = status;
  if (status === "NEED MORE DATA" || !options.length) {
    const reason = partner?.missing_data_message || partner?.reason || "Thiếu mapping tín dụng/tài trợ riêng cho hợp đồng. Founder bổ sung TeamPack rồi upload lại.";
    $("#partnerRows").innerHTML = `<tr><td colspan="5" class="table-empty">${escapeHtml(reason)}</td></tr>`;
    return;
  }
  $("#partnerRows").innerHTML = options.map((option) => {
    const logo = PARTNER_LOGOS[option.logo_key] || PARTNER_LOGOS.partnerx;
    const presentationLabel = option.presentation_label || "PHƯƠNG ÁN MÔ PHỎNG";
    return `<tr class="${option.rank === 1 ? "rank-one" : ""}"><td>${option.rank}</td><td><div class="partner-identity"><span class="partner-logo-shell"><img src="${logo.src}" alt="${escapeHtml(logo.alt)}"></span><div class="partner-copy"><strong>${escapeHtml(option.provider)}</strong><span class="simulation-badge">${escapeHtml(presentationLabel)}</span><span class="subtle">${escapeHtml(option.product)}</span></div></div></td><td>${formatVnd(option.liquidity_amount)}</td><td><span class="fit-score">${option.fit_score}</span></td><td>${escapeHtml(option.status)}</td></tr>`;
  }).join("");
}

function renderDecision(result) {
  const decision = result.decision;
  const decisionType = String(decision.decision_type || "").toUpperCase();
  const card = $("#decisionCard");
  card.className = "decision-card";
  if (decisionType === "NEED MORE DATA") card.classList.add("need-data");
  if (decisionType === "NEED REVIEW") card.classList.add("need-review");
  if (decisionType === "REJECT") card.classList.add("reject");
  $("#decisionType").textContent = `${decision.decision_type}${decision.openai_enhanced ? " · OPENAI VALIDATED" : " · RULE ENGINE"}`;
  $("#heroTitle").textContent = decision.headline;
  $("#decisionReasons").innerHTML = (decision.three_reasons || []).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("") || "<li>Không có diễn giải an toàn để hiển thị.</li>";
  $("#humanCondition").textContent = decision.human_confirmation_point || "Founder cần xem lại nguồn dữ liệu trước hành động tiếp theo.";
  const canRecordDecision = Boolean(decision.approval_required);
  const canApprove = Boolean(decision.approval_allowed ?? decision.approval_required);
  $("#approvalConfirm").disabled = !canRecordDecision;
  $("#approvalConfirm").checked = false;
  $("#founderName").disabled = !canRecordDecision;
  $("#founderName").value = "Founder Demo";
  $("#approveButton").disabled = !canApprove;
  $("#rejectButton").disabled = !canRecordDecision;
  const gate = $("#gateStatus");
  gate.className = `gate-status ${decisionType === "NEED REVIEW" ? "review" : "pending"}`;
  if (decisionType === "NEED MORE DATA") {
    gate.innerHTML = "<span>●</span> BLOCKED BY DATA";
    $("#approvalInstruction").textContent = "Founder sửa đúng trường trong TeamPack và upload lại; prototype không nhận dữ liệu nhập trực tiếp.";
  } else if (decisionType === "NEED REVIEW") {
    gate.innerHTML = "<span>●</span> FOUNDER REVIEW REQUIRED · APPROVE LOCKED";
    $("#approvalInstruction").textContent = "Tôi đã kiểm tra funding coverage, phần thiếu hụt và điều kiện bảo vệ trước khi đưa ra quyết định của Founder.";
  } else {
    gate.innerHTML = canApprove ? "<span>●</span> PENDING FOUNDER" : "<span>●</span> RULE REJECT · APPROVE LOCKED";
    $("#approvalInstruction").textContent = "Tôi đã đọc điều kiện bảo vệ và hiểu đây là tiền kiểm mô phỏng.";
  }
}

const EXTRACTION_FIELD_LABELS = Object.freeze({
  performance_bond_required: {
    label: "Yêu cầu bảo lãnh thực hiện",
    description: "Tín hiệu nghĩa vụ performance bond được nêu trực tiếp trong văn bản.",
  },
  deployment_scope_provinces: {
    label: "Phạm vi triển khai",
    description: "Số tỉnh/thành được trích xuất trực tiếp từ mô tả hợp đồng.",
  },
  collection_timing_signal: {
    label: "Tín hiệu thời điểm thu tiền",
    description: "Mốc thu tiền được nêu rõ trong điều khoản hoặc ghi chú giao hàng.",
  },
});

function openAIStateClass(status) {
  const value = String(status || "").toLowerCase();
  if (value === "validated" || value === "supported") return "valid";
  if (/(blocked|fallback|error|failed)/.test(value)) return "blocked";
  if (/(not_stated|ambiguous|disabled|not_requested|not run)/.test(value)) return "neutral";
  return "review";
}

function formatEvidenceValue(value) {
  if (value === null || value === undefined || value === "") return "Không được nêu";
  if (value === true) return "Có";
  if (value === false) return "Không";
  return String(value).replaceAll("_", " ");
}

function renderGuardrailChecks(checks) {
  const rows = Array.isArray(checks) ? checks : [];
  if (!rows.length) return '<div class="openai-empty compact">Chưa có validation event.</div>';
  return rows.map((check) => {
    const passed = Boolean(check?.passed);
    return `<div class="guardrail-check ${passed ? "pass" : "fail"}"><b>${passed ? "✓" : "!"}</b><div><strong>${escapeHtml(check?.check || "validation")}</strong><p>${escapeHtml(check?.note || "Không có diễn giải bổ sung.")}</p></div><span>${passed ? "PASS" : "BLOCK"}</span></div>`;
  }).join("");
}

function setControlTab(tabName = "data-quality") {
  const requested = ["data-quality", "openai-extraction", "openai-guardrails"].includes(tabName)
    ? tabName
    : "data-quality";
  appState.controlTab = requested;
  $$("#controlTabs [data-control-tab]").forEach((button) => {
    const active = button.dataset.controlTab === requested;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  $$('[data-control-panel]').forEach((panel) => {
    const active = panel.dataset.controlPanel === requested;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
}

function openControlDialog(tabName = "data-quality") {
  if (!appState.result) return;
  setControlTab(tabName);
  const dialog = $("#dataQualityDialog");
  if (!dialog.open) dialog.showModal();
}

function renderOpenAIEvidence(openai = {}) {
  const extraction = openai.extraction || {};
  const challenger = openai.challenger || {};
  const model = extraction.model || challenger.model || openai.model || appState.bootstrap?.openai?.model || "—";
  const extractionStatus = extraction.status || "not run";
  const challengerStatus = challenger.status || "not run";
  const overallStatus = openai.status || "not run";
  $("#extractionModel").textContent = model;
  $("#extractionStatus").textContent = String(extractionStatus).replaceAll("_", " ").toUpperCase();
  $("#extractionResponseId").textContent = extraction.response_id || "—";
  $("#guardrailExtractionStatus").textContent = String(extractionStatus).replaceAll("_", " ").toUpperCase();
  $("#guardrailChallengerStatus").textContent = String(challengerStatus).replaceAll("_", " ").toUpperCase();
  $("#guardrailOverallStatus").textContent = String(overallStatus).replaceAll("_", " ").toUpperCase();
  [
    ["#extractionStatus", extractionStatus],
    ["#guardrailExtractionStatus", extractionStatus],
    ["#guardrailChallengerStatus", challengerStatus],
    ["#guardrailOverallStatus", overallStatus],
  ].forEach(([selector, status]) => {
    const element = $(selector);
    element.className = `openai-inline-status ${openAIStateClass(status)}`;
  });

  const overallBadge = $("#extractionOverallBadge");
  overallBadge.className = `openai-state ${openAIStateClass(extractionStatus)}`;
  overallBadge.textContent = String(extractionStatus).replaceAll("_", " ").toUpperCase();

  const validatedFields = extraction.validated_evidence && typeof extraction.validated_evidence === "object"
    ? extraction.validated_evidence
    : {};
  const rawFields = extraction.output?.fields && typeof extraction.output.fields === "object"
    ? extraction.output.fields
    : {};
  $("#extractionFields").innerHTML = Object.entries(EXTRACTION_FIELD_LABELS).map(([fieldName, meta]) => {
    const validated = Object.prototype.hasOwnProperty.call(validatedFields, fieldName);
    const field = validatedFields[fieldName] || rawFields[fieldName] || null;
    const status = field?.status || "NOT RETURNED";
    const confidence = Number(field?.confidence);
    const confidenceLabel = Number.isFinite(confidence) ? formatPercent(confidence, 0) : "—";
    const citations = Array.isArray(field?.evidence) ? field.evidence : [];
    const evidenceHtml = citations.length
      ? citations.map((citation) => {
        const source = citation?.source || citation?.source_id || "Không có nguồn";
        return `<div class="evidence-citation"><code>${escapeHtml(source)}</code><blockquote>“${escapeHtml(citation?.quote || "Không có quote") }”</blockquote></div>`;
      }).join("")
      : '<div class="evidence-citation empty"><span>Không có evidence quote cho trường này.</span></div>';
    return `<article class="extraction-field-card ${validated ? "validated" : "unvalidated"}"><div class="extraction-field-head"><div><span>${escapeHtml(fieldName)}</span><h3>${escapeHtml(meta.label)}</h3></div><span class="field-validation ${validated ? "valid" : "neutral"}">${validated ? "SERVER VALIDATED" : "CHƯA VALIDATE"}</span></div><p>${escapeHtml(meta.description)}</p><div class="extraction-field-facts"><div><span>Value</span><strong>${escapeHtml(formatEvidenceValue(field?.value))}</strong></div><div><span>Status</span><strong class="openai-inline-status ${openAIStateClass(status)}">${escapeHtml(String(status).replaceAll("_", " "))}</strong></div><div><span>Confidence</span><strong>${escapeHtml(confidenceLabel)}</strong></div></div><div class="evidence-citations"><span>Evidence source + exact quote</span>${evidenceHtml}</div></article>`;
  }).join("");

  $("#extractionValidationChecks").innerHTML = renderGuardrailChecks(extraction.validation);
  $("#challengerValidationChecks").innerHTML = renderGuardrailChecks(challenger.validation || openai.validation);
  $("#extractionMaskedInput").textContent = JSON.stringify(extraction.input_masked || {}, null, 2);
  $("#challengerMaskedInput").textContent = JSON.stringify(openai.input_masked || {}, null, 2);
}

function renderLogs(logs) {
  $("#logRows").innerHTML = logs.map((row) => `<tr><td>${escapeHtml((row.timestamp || "").split("T")[1] || row.timestamp)}</td><td>${escapeHtml(row.agent_or_component)}</td><td>${escapeHtml(row.event_type)}</td><td>${escapeHtml(row.response_status)}</td></tr>`).join("");
}

async function submitApproval(action) {
  if (!appState.result) return;
  try {
    const record = await api("/api/approve", {
      trace_id: appState.result.trace_id,
      founder_name: $("#founderName").value,
      action,
      confirmed: $("#approvalConfirm").checked,
    });
    const gate = $("#gateStatus");
    gate.className = `gate-status ${record.status.startsWith("APPROVED") ? "approved" : "rejected"}`;
    gate.innerHTML = `<span>●</span> ${escapeHtml(record.status)}`;
    $("#approveButton").disabled = true;
    $("#rejectButton").disabled = true;
    toast(`${compactAuditId(record.approval_id)} · ${record.status}`);
  } catch (error) {
    toast(error.message, true);
  }
}

async function uploadTeamPack(file) {
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) {
    toast("File vượt quá giới hạn 5 MB.", true);
    return;
  }
  $("#dataBadge").className = "status-pill status-loading";
  $("#dataBadge").innerHTML = '<span class="dot"></span> Đang kiểm tra workbook';
  const selectedBeforeUpload = $("#contractSelect").value;
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    const data = await api("/api/upload", { filename: file.name, data_base64: String(dataUrl).split(",")[1] });
    appState.bootstrap = data;
    appState.result = null;
    renderBootstrap(data, selectedBeforeUpload);
    toast(`Đã đọc ${data.data.sheet_count} sheets và ${data.contracts.length} hợp đồng từ ${file.name}`);
  } catch (error) {
    $("#dataBadge").className = "status-pill status-error";
    $("#dataBadge").innerHTML = '<span class="dot"></span> Upload lỗi · nguồn cũ được giữ';
    toast(`${error.message} TeamPack đang hoạt động không bị thay đổi.`, true);
  } finally {
    // Cho phép Founder chọn lại chính file vừa sửa, kể cả khi tên file không đổi.
    $("#teamPackInput").value = "";
  }
}

function exportDecisionCard() {
  if (!appState.result) return;
  const result = appState.result;
  const payload = {
    schema_version: "OPC_DECISION_CARD_V2",
    trace_id: result.trace_id,
    generated_at: result.generated_at,
    source: result.source,
    scenario: result.scenario,
    scenario_fingerprint: result.openai.input_masked?.scenario_fingerprint,
    finance: {
      contract_value: result.finance.contract_value,
      order_coverage_ratio: result.finance.order_coverage_ratio,
      gross_margin: result.finance.gross_margin,
      target_gross_margin: result.finance.target_gross_margin,
      peak_funding_gap: result.finance.peak_funding_gap,
      guarantee_cash_impact: result.finance.guarantee_cash_impact,
      immediate_liquidity_need: result.finance.immediate_liquidity_need,
      liquidity_headroom: result.finance.liquidity_headroom,
      cashflow_status: result.finance.cashflow_status,
      contract_cashflow: result.finance.contract_cashflow,
      linked_order_count: result.finance.linked_order_count,
      linked_invoice_count: result.finance.linked_invoice_count,
      eligible_funding_capacity: result.finance.eligible_funding_capacity ?? result.finance.potential_funding_capacity ?? result.finance.working_capital_request,
      funding_coverage_ratio: fundingSnapshot(result.finance).coverage,
      funding_shortfall: fundingSnapshot(result.finance).shortfall,
      credit_mapping_status: result.finance.credit_mapping_status ?? result.finance.funding_mapping_status,
    },
    data_quality: {
      ...result.data_quality,
      missing_data: result.finance.missing_data,
      missing_fields: result.finance.missing_fields,
      cashflow_block_reason: result.finance.cashflow_block_reason,
    },
    risk: {
      case_risk_level: result.risk.case_risk_level,
      enterprise_risk_level: result.risk.enterprise_risk_level,
      triggered_rules: result.risk.alerts.map((item) => item.rule_id),
      transaction_reconciliation: sanitizeReconciliationPayload(reconciliationSource(result)),
    },
    partner_precheck: result.partner.recommended,
    decision: result.decision,
    openai_evidence: {
      status: result.openai.status,
      model: result.openai.model,
      extraction: {
        status: result.openai.extraction?.status,
        response_id: result.openai.extraction?.response_id,
        input_masked: result.openai.extraction?.input_masked,
        validated_evidence: result.openai.extraction?.validated_evidence,
        validation: result.openai.extraction?.validation,
      },
      challenger: {
        status: result.openai.challenger?.status,
        response_id: result.openai.challenger?.response_id,
        input_masked: result.openai.input_masked,
        output: result.openai.challenger?.output,
        validation: result.openai.challenger?.validation,
      },
    },
    external_submission_executed: false,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `Decision_Card_${result.trace_id}.json`;
  link.click();
  URL.revokeObjectURL(url);
  toast("Đã xuất Decision Card có trace và scenario fingerprint.");
}

function downloadReconciliation() {
  if (!appState.result) return;
  const result = appState.result;
  const reconciliation = normaliseReconciliation(result);
  const payload = {
    schema_version: "OPC_TRANSACTION_RECONCILIATION_V1",
    trace_id: result.trace_id,
    generated_at: result.generated_at,
    contract_id: reconciliation.selectedContractId,
    transaction_reconciliation: sanitizeReconciliationPayload(reconciliation.source),
    privacy: "counterparty/account masked in browser export",
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `Transaction_Reconciliation_${reconciliation.selectedContractId}_${result.trace_id}.json`;
  link.click();
  URL.revokeObjectURL(url);
  toast("Đã tải JSON đối soát; counterparty và account đã được che.");
}

function downloadDataRequest() {
  if (!appState.result) return;
  const quality = normaliseQuality(appState.result);
  const payload = {
    schema_version: "OPC_FOUNDER_DATA_REQUEST_V1",
    trace_id: appState.result.trace_id,
    generated_at: appState.result.generated_at,
    contract_id: appState.result.contract.contract_id,
    source: appState.result.source,
    summary: {
      status: quality.status,
      blocking_count: quality.blocking_count || 0,
      warning_count: quality.warning_count || 0,
      optional_count: quality.optional_count || 0,
      affected_sheets: quality.affected_sheets || [],
    },
    issues: quality.issues || [],
    instruction: "Bổ sung dữ liệu trong TeamPack gốc, upload lại workbook và chạy Kiểm tra lại. Rule engine là nguồn sự thật; OpenAI không được thay đổi danh sách này.",
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `Founder_Data_Request_${appState.result.contract.contract_id}_${appState.result.trace_id}.json`;
  link.click();
  URL.revokeObjectURL(url);
  toast("Đã tải danh sách dữ liệu cần bổ sung theo từng sheet.");
}

function bindEvents() {
  $("#contractSelect").addEventListener("change", () => updateContractMeta(true));
  $("#runButton").addEventListener("click", runWorkflow);
  $("#exportButton").addEventListener("click", exportDecisionCard);
  $("#teamPackInput").addEventListener("change", (event) => uploadTeamPack(event.target.files[0]));
  $("#approveButton").addEventListener("click", () => submitApproval("APPROVE"));
  $("#rejectButton").addEventListener("click", () => submitApproval("REJECT"));
  $("#evidenceButton").addEventListener("click", () => openControlDialog("openai-guardrails"));
  $("#openDataQuality").addEventListener("click", () => openControlDialog("data-quality"));
  $("#closeDataQuality").addEventListener("click", () => $("#dataQualityDialog").close());
  $$("#controlTabs [data-control-tab]").forEach((button) => button.addEventListener("click", () => setControlTab(button.dataset.controlTab)));
  $("#openReconciliation").addEventListener("click", () => {
    if (!appState.result) return;
    renderReconciliation(appState.result, appState.reconciliationFilter);
    $("#reconciliationDialog").showModal();
  });
  $("#closeReconciliation").addEventListener("click", () => $("#reconciliationDialog").close());
  $("#downloadReconciliation").addEventListener("click", downloadReconciliation);
  $("#downloadDataRequest").addEventListener("click", downloadDataRequest);
  $("#uploadCorrectedPack").addEventListener("click", () => {
    $("#dataQualityDialog").close();
    $("#teamPackInput").click();
  });
  $("#recheckData").addEventListener("click", () => {
    $("#dataQualityDialog").close();
    runWorkflow();
  });
  $$("#qualityFilters button").forEach((button) => button.addEventListener("click", () => {
    appState.qualityFilter = button.dataset.level;
    const quality = appState.result ? normaliseQuality(appState.result) : null;
    if (quality) renderDataQuality(quality, appState.qualityFilter);
  }));
  $$("#reconciliationFilters button").forEach((button) => button.addEventListener("click", () => {
    appState.reconciliationFilter = button.dataset.scope;
    if (appState.result) renderReconciliation(appState.result, appState.reconciliationFilter);
  }));
  $("#toggleLog").addEventListener("click", () => {
    const body = $("#logBody");
    body.classList.toggle("collapsed");
    $("#toggleLog").textContent = body.classList.contains("collapsed") ? "Mở log" : "Thu gọn";
  });
}

function updateClock() {
  const now = new Date();
  const date = new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" }).format(now);
  const time = new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(now);
  $("#clock").textContent = `${date} · ${time}`;
}

bindEvents();
updateClock();
setInterval(updateClock, 1000);
bootstrap();
