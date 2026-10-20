<#
Arranca la API del bot y el túnel de Cloudflare con autoreinicio.

Uso:
    powershell -ExecutionPolicy Bypass -File scripts\serve.ps1
    powershell -ExecutionPolicy Bypass -File scripts\serve.ps1 -Port 8010
    powershell -ExecutionPolicy Bypass -File scripts\serve.ps1 -NoTunnel

Qué hace:
- levanta uvicorn en el puerto indicado (por defecto 8010),
- levanta un quick tunnel de cloudflared hacia ese puerto,
- reinicia cualquiera de los dos si se cae,
- cuando el túnel estrena URL, actualiza PUBLIC_BASE_URL en .env y reinicia
  la API para que los links de pago usen la URL nueva,
- escribe la URL vigente en .tools/tunnel-url.txt.

Requiere cloudflared en .tools\cloudflared.exe (ver docs/despliegue.md).
Para que sobreviva al cierre de sesión hace falta un servicio de Windows
(NSSM, como administrador); esta tarea corre al iniciar sesión.
#>
param(
    [int]$Port = 8010,
    [switch]$NoTunnel
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$cloudflared = Join-Path $root ".tools\cloudflared.exe"
$logDir = Join-Path $root ".tools"
$tunnelLog = Join-Path $logDir "cloudflared.log"
$urlFile = Join-Path $logDir "tunnel-url.txt"
$botOut = Join-Path $logDir "bot.out.log"
$botErr = Join-Path $logDir "bot.err.log"
$envFile = Join-Path $root ".env"

New-Item -ItemType Directory -Force $logDir | Out-Null

# PowerShell 5.1 escribe BOM con -Encoding UTF8 y puede romper .env; escribimos
# siempre UTF-8 sin BOM.
function Write-TextNoBom {
    param([string]$Path, [string]$Text)
    [System.IO.File]::WriteAllText(
        $Path, $Text, (New-Object System.Text.UTF8Encoding($false))
    )
}

if (-not $env:SAP_PAAS_URL) { $env:SAP_PAAS_URL = "http://127.0.0.1:5050" }

function Start-Bot {
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $Port) `
        -WorkingDirectory $root `
        -RedirectStandardOutput $botOut `
        -RedirectStandardError $botErr `
        -WindowStyle Hidden `
        -PassThru
}

function Start-Tunnel {
    Start-Process -FilePath $cloudflared `
        -ArgumentList @("tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate", "--logfile", $tunnelLog, "--loglevel", "info") `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -PassThru
}

function Sync-TunnelUrl {
    param([string]$CurrentUrl)

    $match = Select-String -Path $tunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -AllMatches -ErrorAction SilentlyContinue
    if (-not $match) { return $null }
    $url = $match.Matches[-1].Value
    Write-TextNoBom -Path $urlFile -Text $url

    if ($url -eq $CurrentUrl) { return $null }

    if (Test-Path $envFile) {
        $text = [System.IO.File]::ReadAllText($envFile)
        $text = $text -replace "(?m)^PUBLIC_BASE_URL=.*$", "PUBLIC_BASE_URL=$url"
        Write-TextNoBom -Path $envFile -Text $text
    }
    return $url
}

$bot = Start-Bot
$tunnel = $null
if (-not $NoTunnel) {
    if (-not (Test-Path $cloudflared)) {
        throw "Falta $cloudflared. Ver docs/despliegue.md (instalación de cloudflared)."
    }
    $tunnel = Start-Tunnel
}

$currentUrl = (Select-String -Path $envFile -Pattern "^PUBLIC_BASE_URL=(.*)$" -ErrorAction SilentlyContinue).Matches[0].Groups[1].Value

Start-Sleep -Seconds 15

while ($true) {
    Start-Sleep -Seconds 5

    if ($bot.HasExited) {
        Write-Host "[serve] la API se detuvo; reiniciando"
        Start-Sleep -Seconds 3
        $bot = Start-Bot
    }

    if ($tunnel -and $tunnel.HasExited) {
        Write-Host "[serve] el túnel se detuvo; reiniciando"
        Start-Sleep -Seconds 3
        $tunnel = Start-Tunnel
        Start-Sleep -Seconds 10
    }

    if ($tunnel) {
        $url = Sync-TunnelUrl -CurrentUrl $currentUrl
        if ($url) {
            $currentUrl = $url
            Write-Host "[serve] URL nueva: $url; reiniciando la API"
            if (-not $bot.HasExited) { $bot | Stop-Process -Force }
            Start-Sleep -Seconds 2
            $bot = Start-Bot
        }
    }
}
