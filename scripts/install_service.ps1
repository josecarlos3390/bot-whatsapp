#Requires -RunAsAdministrator
<#
Instala el bot como servicio de Windows con NSSM.

Uso (en PowerShell COMO ADMINISTRADOR):
    powershell -ExecutionPolicy Bypass -File C:\ProyectosPython\chatbot-whatsapp\scripts\install_service.ps1

Qué hace:
1. Detiene el supervisor que corre en la sesión del usuario (para no duplicar).
2. Instala/reconfigura el servicio RohoBot con NSSM.
3. Lo arranca y verifica que la API responda.
4. Quita el acceso directo de inicio de sesión (ya no hace falta).

Opciones:
    -ServiceName  (por defecto RohoBot)
    -KeepStartup  (no borrar el acceso directo de inicio)
#>
param(
    [string]$ServiceName = "RohoBot",
    [switch]$KeepStartup
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$serve = Join-Path $root "scripts\serve.ps1"
$python = Join-Path $root ".venv\Scripts\python.exe"
$nssm = "C:\Windows\system32\nssm.exe"
$logDir = Join-Path $root ".tools"
$startup = [Environment]::GetFolderPath("Startup")
$shortcut = Join-Path $startup "ROHO Bot.lnk"

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Ejecutá este script en una consola de PowerShell COMO ADMINISTRADOR."
}
if (-not (Test-Path $nssm)) { throw "No encuentro nssm.exe en $nssm" }
if (-not (Test-Path $serve)) { throw "No encuentro $serve" }
if (-not (Test-Path $python)) { throw "No encuentro el python del venv: $python" }
New-Item -ItemType Directory -Force $logDir | Out-Null

Step "Deteniendo el supervisor de la sesión (si está corriendo)"
$ownPid = $PID
Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "powershell.exe" -and
        $_.ProcessId -ne $ownPid -and
        $_.CommandLine -like "*scripts\serve.ps1*"
    } |
    ForEach-Object {
        Write-Host "  supervisor PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "python.exe" -and (
            $_.CommandLine -like "*port 8010*" -or
            $_.CommandLine -like "*refresh_tunnel*"
        )
    } |
    ForEach-Object {
        Write-Host "  proceso PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "  túnel PID $($_.Id)"
    Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 5

Step "Instalando el servicio $ServiceName"
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "  ya existe: se reconfigura"
    & $nssm stop $ServiceName | Out-Null
    Start-Sleep -Seconds 3
} else {
    & $nssm install $ServiceName "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
        "-NoProfile" "-ExecutionPolicy" "Bypass" "-File" $serve
    if ($LASTEXITCODE -ne 0) { throw "nssm install falló (código $LASTEXITCODE)" }
}

& $nssm set $ServiceName AppDirectory $root | Out-Null
& $nssm set $ServiceName DisplayName "ROHO Bot WhatsApp" | Out-Null
& $nssm set $ServiceName Description "Bot WhatsApp + consola + tunel Cloudflare (supervisor)" | Out-Null
& $nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $nssm set $ServiceName AppStdout (Join-Path $logDir "service.out.log") | Out-Null
& $nssm set $ServiceName AppStderr (Join-Path $logDir "service.err.log") | Out-Null
& $nssm set $ServiceName AppRotateFiles 1 | Out-Null
& $nssm set $ServiceName AppRotateOnline 1 | Out-Null
& $nssm set $ServiceName AppRotateBytes 10485760 | Out-Null
& $nssm set $ServiceName AppStopMethodConsole 20000 | Out-Null
& $nssm set $ServiceName AppRestartDelay 5000 | Out-Null

Step "Arrancando el servicio"
& $nssm start $ServiceName | Out-Null
Start-Sleep -Seconds 20

# NSSM imprime el estado con espacios ("S E R V I C E _ R U N N I N G").
$status = (& $nssm status $ServiceName) -replace "\s", ""
Write-Host "  estado: $status"
$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($status -ne "SERVICE_RUNNING" -and $service.Status -ne "Running") {
    throw "El servicio no arrancó. Revisá $logDir\service.err.log y $logDir\supervisor.log"
}

Step "Verificando la API"
$ok = $false
for ($i = 0; $i -lt 12; $i++) {
    try {
        $health = Invoke-WebRequest "http://127.0.0.1:8010/health" -TimeoutSec 15 -UseBasicParsing
        if ($health.StatusCode -eq 200) { $ok = $true; break }
    } catch {
        Start-Sleep -Seconds 5
    }
}
if (-not $ok) {
    throw "La API no responde en 8010. Revisá $logDir\bot.err.log"
}
Write-Host "  API: $($health.Content)"

if (-not $KeepStartup -and (Test-Path $shortcut)) {
    Step "Quitando el acceso directo de inicio (el servicio ya lo reemplaza)"
    Remove-Item $shortcut -Force
    Write-Host "  borrado: $shortcut"
}

Step "Listo"
Write-Host "Comandos útiles:"
Write-Host "  nssm status $ServiceName"
Write-Host "  nssm restart $ServiceName"
Write-Host "  nssm stop $ServiceName"
Write-Host "  nssm remove $ServiceName confirm   (desinstalar)"
Write-Host "Logs: $logDir\supervisor.log, service.out.log, bot.err.log"
