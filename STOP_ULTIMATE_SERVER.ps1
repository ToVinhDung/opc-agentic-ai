$ErrorActionPreference = "Stop"

$demoPort = 8766
$url = "http://127.0.0.1:$demoPort"
$appId = "team-tsd-opc-agentic-ai-ultimate"

$status = $null
try { $status = Invoke-RestMethod -Uri "$url/api/status" -TimeoutSec 2 } catch { }
if (-not $status) {
    Write-Host "Khong co Ultimate server nao dang chay tren $url." -ForegroundColor DarkGray
    exit 0
}
if ($status.app_id -ne $appId) {
    throw "Dia chi $url thuoc ung dung khac. Script tu choi gui lenh dung de bao ve project khac."
}

$result = Invoke-RestMethod -Uri "$url/api/shutdown" -Method Post -Headers @{ "X-OPC-App-ID" = $appId } -ContentType "application/json" -Body "{}" -TimeoutSec 3
if ($result.status -ne "stopping") { throw "Server khong xac nhan lenh dung." }

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 200
    try { Invoke-RestMethod -Uri "$url/api/status" -TimeoutSec 1 | Out-Null } catch {
        Write-Host "Da dung dung Ultimate server tren $url." -ForegroundColor Green
        exit 0
    }
}
throw "Ultimate da nhan lenh dung nhung cong $demoPort chua giai phong. Hay dong cua so launcher."
