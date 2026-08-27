# Windows 状态检查脚本
# 用法：powershell -ExecutionPolicy Bypass -File check.ps1

$ErrorActionPreference = "Continue"
$ProjectDir = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Resolve-Path $MyInvocation.MyCommand.Path)))

Write-Host "== 进程状态 =="
$FlaskPidFile = Join-Path $ProjectDir "logs\flask.pid"
if (Test-Path -LiteralPath $FlaskPidFile) {
    $Pid = Get-Content -LiteralPath $FlaskPidFile -Raw
    $Proc = Get-Process -Id $Pid -ErrorAction SilentlyContinue
    if ($Proc) { Write-Host ("Flask backend : RUNNING (pid {0})" -f $Pid) }
    else        { Write-Host "Flask backend : NOT RUNNING" }
} else { Write-Host "Flask backend : NOT RUNNING (no pid file)" }

try {
    $P = Get-Process -Name "nginx" -ErrorAction Stop
    Write-Host ("Nginx         : RUNNING ({0} process(es))" -f $P.Count)
} catch {
    Write-Host "Nginx         : NOT RUNNING"
}

Write-Host ""
Write-Host "== HTTP 检查 =="
$Ports = @(8080)
foreach ($Port in $Ports) {
    try {
        $R = Invoke-WebRequest -Uri "http://localhost:$Port/" -UseBasicParsing -TimeoutSec 5
        Write-Host ("首页 http://localhost:{0} -> HTTP {1}" -f $Port, $R.StatusCode)
    } catch {
        Write-Host ("首页 http://localhost:{0} -> 不可访问 ({1})" -f $Port, $_.Exception.Message)
    }
}

try {
    $L = Invoke-WebRequest -Uri "http://localhost:8080/api/local" -UseBasicParsing -TimeoutSec 5
    $Body = $L.Content | ConvertFrom-Json
    Write-Host ("api/local 本机访问判定 -> {0}" -f $Body.local)
} catch {
    Write-Host "api/local 本机访问判定 -> 不可访问"
}
