$ErrorActionPreference = "Stop"

$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$demoPort = 8766
$url = "http://127.0.0.1:$demoPort"
$statusUrl = "$url/api/status"
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

function Get-DemoPython {
    if (Test-Path -LiteralPath $bundledPython) { return $bundledPython }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    throw "Khong tim thay Python 3.10+."
}

function Assert-UltimatePortAvailable {
    $client = [System.Net.Sockets.TcpClient]::new()
    $occupied = $false
    try { $client.Connect("127.0.0.1", $demoPort); $occupied = $true } catch { } finally { $client.Dispose() }
    if (-not $occupied) { return }

    $status = $null
    try { $status = Invoke-RestMethod -Uri $statusUrl -TimeoutSec 2 } catch { }
    if ($status -and $status.app_id -eq "team-tsd-opc-agentic-ai-ultimate") {
        throw "Ultimate dang chay tai $url. Hay dung STOP_ULTIMATE_SERVER.bat truoc khi khoi dong lai."
    }
    throw "Cong $demoPort dang duoc ung dung khac su dung. Ultimate khong mo trinh duyet de tranh hien nham giao dien."
}

Assert-UltimatePortAvailable

Write-Host ""
Write-Host "OPC AGENTIC AI ULTIMATE - OPENAI LIVE" -ForegroundColor Cyan
Write-Host "Ultimate dung cong rieng $demoPort; ban cu van dung cong 8765." -ForegroundColor DarkGray
Write-Host "API key duoc nhap an va chi ton tai trong tien trinh demo." -ForegroundColor DarkGray
Write-Host ""

$secureKey = Read-Host "Nhap OpenAI API key" -AsSecureString
$plainKey = [System.Net.NetworkCredential]::new("", $secureKey).Password
if ([string]::IsNullOrWhiteSpace($plainKey)) { throw "API key rong." }
$env:OPENAI_API_KEY = $plainKey.Trim()
$plainKey = $null
$secureKey = $null
if (-not $env:OPENAI_MODEL) { $env:OPENAI_MODEL = "gpt-5.6-luna" }

try {
    Write-Host "Dang kiem tra API key..." -ForegroundColor Yellow
    try {
        $headers = @{ Authorization = "Bearer $env:OPENAI_API_KEY" }
        Invoke-RestMethod -Uri "https://api.openai.com/v1/models" -Headers $headers -TimeoutSec 20 | Out-Null
        Write-Host "API key da duoc OpenAI chap nhan." -ForegroundColor Green
    }
    catch {
        $statusCode = $null
        if ($_.Exception.Response) { $statusCode = [int]$_.Exception.Response.StatusCode }
        if ($statusCode -in 401, 403) {
            throw "OpenAI tu choi API key (HTTP $statusCode). Hay rotate/tao key moi va thu lai."
        }
        Write-Warning "Khong preflight duoc /v1/models. Demo van khoi dong de hien thi loi chi tiet theo fail-safe."
    }

    $python = Get-DemoPython
    $pythonArgs = @("app.py", "--host", "127.0.0.1", "--port", "$demoPort")
    if ([System.IO.Path]::GetFileName($python) -ieq "py.exe") {
        $pythonArgs = @("-3", "app.py", "--host", "127.0.0.1", "--port", "$demoPort")
    }

    Set-Location -LiteralPath $appRoot
    & $python -c "import openpyxl" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Dang cai dependency toi thieu..." -ForegroundColor Yellow
        & $python -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw "Khong cai duoc openpyxl." }
    }

    Write-Host ""
    Write-Host "OPENAI LIVE DANG KHOI DONG" -ForegroundColor Green
    Write-Host "Dashboard rieng: $url" -ForegroundColor Cyan
    Write-Host "Giu cua so nay mo. Nhan Ctrl+C hoac dong cua so de dung server." -ForegroundColor Yellow
    Write-Host "Neu server con chay, dung STOP_ULTIMATE_SERVER.bat." -ForegroundColor Yellow
    Write-Host ""

    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile",
        "-WindowStyle", "Hidden",
        "-Command", "Start-Sleep -Seconds 2; Start-Process '$url'"
    ) -WindowStyle Hidden | Out-Null

    # Chạy foreground để server không sống ẩn sau khi đóng launcher.
    & $python @pythonArgs
    if ($LASTEXITCODE -ne 0) { throw "Server Ultimate dung voi ma loi $LASTEXITCODE." }
}
finally {
    Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
}
