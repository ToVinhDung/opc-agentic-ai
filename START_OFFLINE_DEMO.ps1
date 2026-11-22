$ErrorActionPreference = "Stop"

$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$demoPort = 8766
$url = "http://127.0.0.1:$demoPort"
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

$client = [System.Net.Sockets.TcpClient]::new()
$occupied = $false
try { $client.Connect("127.0.0.1", $demoPort); $occupied = $true } catch { } finally { $client.Dispose() }
if ($occupied) {
    throw "Cong $demoPort dang duoc su dung. Ultimate khong mo browser de tranh hien nham giao dien. Dung STOP_ULTIMATE_SERVER.bat neu Ultimate dang chay."
}

if (Test-Path -LiteralPath $bundledPython) {
    $python = $bundledPython
    $pythonArgs = @("app.py", "--host", "127.0.0.1", "--port", "$demoPort")
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = (Get-Command py).Source
    $pythonArgs = @("-3", "app.py", "--host", "127.0.0.1", "--port", "$demoPort")
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = (Get-Command python).Source
    $pythonArgs = @("app.py", "--host", "127.0.0.1", "--port", "$demoPort")
}
else {
    throw "Khong tim thay Python 3.10+."
}

Set-Location -LiteralPath $appRoot
$env:PYTHONUTF8 = "1"
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue

& $python -c "import openpyxl" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Khong cai duoc openpyxl." }
}

Write-Host "Ultimate OFFLINE dang chay rieng tai $url" -ForegroundColor Cyan
Write-Host "Giu cua so nay mo; Ctrl+C de dung server." -ForegroundColor Yellow
Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-Command", "Start-Sleep -Seconds 2; Start-Process '$url'"
) -WindowStyle Hidden | Out-Null

& $python @pythonArgs
if ($LASTEXITCODE -ne 0) { throw "Server Ultimate dung voi ma loi $LASTEXITCODE." }
