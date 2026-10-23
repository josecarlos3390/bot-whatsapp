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
- escribe la URL vigente en .tools/tunnel-url.txt,
- sincroniza el catálogo al arrancar y cada 24 h según SAP_MODE: VTEX usa
  scripts/sync_vtex y SAP usa scripts/sync_catalog (este último necesita
  SAP_USER en .env). Usar -NoCatalogSync para desactivarlo.

Requiere cloudflared en .tools\cloudflared.exe (ver docs/despliegue.md).
Para que sobreviva al cierre de sesión hace falta un servicio de Windows
(NSSM, como administrador); esta tarea corre al iniciar sesión.
#>
param(
    [int]$Port = 8010,
    [switch]$NoTunnel,
    [switch]$NoCatalogSync
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

$syncLog = Join-Path $logDir "sync.log"
$syncStamp = Join-Path $logDir "last-sync.txt"

function Test-SapCredentials {
    if (-not (Test-Path $envFile)) { return $false }
    $text = [System.IO.File]::ReadAllText($envFile)
    return [bool]($text -match "(?m)^SAP_USER=\S+")
}

function Get-CatalogMode {
    if (-not (Test-Path $envFile)) { return "mock" }
    $text = [System.IO.File]::ReadAllText($envFile)
    $match = [regex]::Match($text, "(?m)^SAP_MODE=(\S+)")
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return "mock"
}

function Sync-Due {
    if ($NoCatalogSync) { return $false }
    # VTEX se sincroniza por el integrador: no necesita credenciales SAP.
    if ((Get-CatalogMode) -ne "vtex" -and -not (Test-SapCredentials)) {
        return $false
    }
    if (-not (Test-Path $syncStamp)) { return $true }
    $last = (Get-Item $syncStamp).LastWriteTime
    return ((Get-Date) - $last).TotalHours -ge 24
}

function Start-CatalogSync {
    if ((Get-CatalogMode) -eq "vtex") {
        $source = "VTEX"
        # Catálogo y luego promociones locales (calculadas del propio catálogo).
        $command = (
            "& '$python' -m scripts.sync_vtex --deactivate-missing; " +
            "& '$python' -m scripts.sync_vtex_promotions"
        )
        $file = "powershell.exe"
        $arguments = @("-NoProfile", "-Command", $command)
    } else {
        $source = "SAP"
        $file = $python
        $arguments = @("-m", "scripts.sync_catalog", "--deactivate-missing")
    }
    Write-Host "[serve] sincronizando catálogo desde $source"
    Write-TextNoBom -Path $syncStamp -Text (Get-Date -Format o)
    Start-Process -FilePath $file `
        -ArgumentList $arguments `
        -WorkingDirectory $root `
        -RedirectStandardOutput $syncLog `
        -RedirectStandardError (Join-Path $logDir "sync.err.log") `
        -WindowStyle Hidden | Out-Null
}

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

if (Sync-Due) { Start-CatalogSync }

while ($true) {
    Start-Sleep -Seconds 5

    if (Sync-Due) { Start-CatalogSync }

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
