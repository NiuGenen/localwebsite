# Windows 停止脚本：Flask 后端 + Nginx
# 用法：powershell -ExecutionPolicy Bypass -File stop.ps1
# 可选：-NginxExe nginx（与 start.ps1 保持一致）

param(
    [string]$NginxExe = "nginx"
)

$ErrorActionPreference = "Continue"

# 项目根目录 = 本脚本的上级目录
$ProjectDir = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Resolve-Path $MyInvocation.MyCommand.Path)))
$LogDir     = Join-Path $ProjectDir "logs"
$NginxConf  = Join-Path $ProjectDir "nginx.windows.conf"

$NginxCmd = Get-Command $NginxExe -ErrorAction SilentlyContinue
if ($NginxCmd) {
    Write-Host "Stopping nginx..."
    Start-Process -FilePath $NginxCmd.Source `
        -ArgumentList "-p `"$ProjectDir\`" -c `"$NginxConf`" -s quit" `
        -WindowStyle Hidden -Wait -ErrorAction SilentlyContinue
} else {
    Write-Host "nginx 命令不可用，尝试通过 pid 文件停止..."
    $NginxPidFile = Join-Path $LogDir "nginx.pid"
    if (Test-Path -LiteralPath $NginxPidFile) {
        $Pid = Get-Content -LiteralPath $NginxPidFile -Raw
        Stop-Process -Id $Pid -ErrorAction SilentlyContinue
    }
}

# 停止 Flask
Write-Host "Stopping Flask backend..."
$FlaskPidFile = Join-Path $LogDir "flask.pid"
if (Test-Path -LiteralPath $FlaskPidFile) {
    $Pid = Get-Content -LiteralPath $FlaskPidFile -Raw
    Stop-Process -Id $Pid -ErrorAction SilentlyContinue
}

Remove-Item -LiteralPath (Join-Path $LogDir "flask.pid") -ErrorAction SilentlyContinue
Write-Host "Done. Services stopped."
