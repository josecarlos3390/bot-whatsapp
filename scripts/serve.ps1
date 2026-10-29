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
    [string]$BindHost = "",
    [switch]$NoTunnel,
    [switch]$NoCatalogSync
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$cloudflared = Join-Path $root ".tools\cloudflared.exe"
$logDir = Join-Path $root ".tools"
$tunnelLog = Join-Path $logDir "cloudflared.log"
$tunnelErrLog = Join-Path $logDir "cloudflared.err.log"
$urlFile = Join-Path $logDir "tunnel-url.txt"
$fuzzStamp = Join-Path $logDir "fuzz.stamp"
$fuzzMesStamp = Join-Path $logDir "fuzz-mes.stamp"
$faltantesStamp = Join-Path $logDir "faltantes.stamp"
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
$webhookLog = Join-Path $logDir "webhook.log"
$backupStamp = Join-Path $logDir "last-backup.txt"
$backupLog = Join-Path $logDir "backup.log"

function Test-SapCredentials {
    if (-not (Test-Path $envFile)) { return $false }
    $text = [System.IO.File]::ReadAllText($envFile)
    return [bool]($text -match "(?m)^SAP_USER=\S+")
}

function Get-EnvValue([string]$Name) {
    if (-not (Test-Path $envFile)) { return "" }
    $text = [System.IO.File]::ReadAllText($envFile)
    $match = [regex]::Match($text, "(?m)^$Name=(\S+)")
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return ""
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

function Log {
    param([string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Write-Host "[serve] $Message"
    try {
        Add-Content -Path (Join-Path $logDir "supervisor.log") -Value $line -Encoding UTF8
    } catch { }
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

function Start-WebhookWatch {
    # Mantiene el webhook de Meta apuntando al túnel vigente: si la URL cambia
    # y nadie lo actualiza, el bot deja de recibir mensajes sin avisar.
    if ($NoTunnel) { return $null }
    Start-Process -FilePath $python `
        -ArgumentList @(
            "-m", "scripts.refresh_tunnel",
            "--log", $tunnelErrLog,
            "--env", $envFile,
            "--watch",
            "--interval", "120"
        ) `
        -WorkingDirectory $root `
        -RedirectStandardOutput $webhookLog `
        -RedirectStandardError (Join-Path $logDir "webhook.err.log") `
        -WindowStyle Hidden -PassThru
}

function Fuzz-Due {
    # Fuzzing nocturno: una corrida por día si está habilitado.
    if ($env:FUZZ_NIGHTLY -eq "false") { return $false }
    if (-not (Test-Path $fuzzStamp)) { return $true }
    $last = (Get-Item $fuzzStamp).LastWriteTime
    return ((Get-Date) - $last).TotalHours -ge 20
}

function Start-Fuzz {
    Write-Host "[serve] fuzzing nocturno"
    Write-TextNoBom -Path $fuzzStamp -Text (Get-Date -Format o)
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "scripts.nightly_fuzz", "--modo", "regresion") `
        -WorkingDirectory $root `
        -WindowStyle Hidden
}

function FuzzMensual-Due {
    # Exploración: casos aleatorios una vez al mes para descubrir problemas
    # nuevos (los escenarios fijos solo detectan regresiones).
    if ($env:FUZZ_MONTHLY -eq "false") { return $false }
    if (-not (Test-Path $fuzzMesStamp)) { return $true }
    $last = (Get-Item $fuzzMesStamp).LastWriteTime
    return ((Get-Date) - $last).TotalDays -ge 28
}

function Start-FuzzMensual {
    Write-Host "[serve] fuzzing exploratorio mensual"
    Write-TextNoBom -Path $fuzzMesStamp -Text (Get-Date -Format o)
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "scripts.nightly_fuzz", "--modo", "exploracion") `
        -WorkingDirectory $root `
        -WindowStyle Hidden
}

function Faltantes-Due {
    if (-not (Test-Path $faltantesStamp)) { return $true }
    $last = (Get-Item $faltantesStamp).LastWriteTime
    # Los lunes, y como mucho una vez cada 20 horas.
    return (((Get-Date).DayOfWeek -eq 'Monday') -and
        (((Get-Date) - $last).TotalHours -ge 20))
}

function Start-Faltantes {
    Write-Host "[serve] informe semanal de faltantes"
    $fecha = Get-Date -Format 'yyyyMMdd'
    $csv = Join-Path $root "logs\faltantes-$fecha.csv"
    Write-TextNoBom -Path $faltantesStamp -Text (Get-Date -Format o)
    Start-Process -FilePath $python `
        -ArgumentList @(
            "-m", "scripts.informe_faltantes",
            "--dias", "7",
            "--csv", $csv
        ) `
        -WorkingDirectory $root `
        -RedirectStandardOutput (Join-Path $logDir "faltantes.out.log") `
        -RedirectStandardError (Join-Path $logDir "faltantes.err.log") `
        -WindowStyle Hidden | Out-Null
}

function Backup-Due {
    if (-not (Test-Path $backupStamp)) { return $true }
    $last = (Get-Item $backupStamp).LastWriteTime
    return ((Get-Date) - $last).TotalHours -ge 20
}

function Start-Backup {
    Write-Host "[serve] copia de seguridad diaria"
    Write-TextNoBom -Path $backupStamp -Text (Get-Date -Format o)
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "scripts.backup_db") `
        -WorkingDirectory $root `
        -RedirectStandardOutput $backupLog `
        -RedirectStandardError (Join-Path $logDir "backup.err.log") `
        -WindowStyle Hidden | Out-Null
}

function Start-Bot {
    # Por defecto escucha solo en local (el túnel publica el webhook). Para la
    # consola en la red interna se configura APP_HOST=0.0.0.0 en .env.
    $listen = $BindHost
    if (-not $listen) { $listen = Get-EnvValue "APP_HOST" }
    if (-not $listen) { $listen = "127.0.0.1" }
    # Cuidado: no usar "*" suelto en ArgumentList; PowerShell lo expande a los
    # archivos del directorio y uvicorn recibe argumentos inválidos.
    # El túnel y el proxy local corren en 127.0.0.1, que es el valor por defecto.
    Start-Process -FilePath $python `
        -ArgumentList @(
            "-m", "uvicorn", "app.main:app",
            "--host", $listen, "--port", $Port,
            "--proxy-headers"
        ) `
        -WorkingDirectory $root `
        -RedirectStandardOutput $botOut `
        -RedirectStandardError $botErr `
        -WindowStyle Hidden `
        -PassThru
}

function Start-Tunnel {
    # cloudflared escribe en stderr; con -WindowStyle Hidden y sin redirección
    # Start-Process se queda colgado y el túnel nunca arranca.
    Start-Process -FilePath $cloudflared `
        -ArgumentList @("tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate") `
        -WorkingDirectory $root `
        -RedirectStandardOutput $tunnelLog `
        -RedirectStandardError $tunnelErrLog `
        -WindowStyle Hidden `
        -PassThru
}

function Read-SharedText {
    # cloudflared mantiene el archivo abierto: hay que leerlo compartiendo.
    param([string]$Path)
    if (-not (Test-Path $Path)) { return "" }
    try {
        $stream = [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite
        )
        $reader = New-Object System.IO.StreamReader($stream)
        try { return $reader.ReadToEnd() } finally { $reader.Close(); $stream.Close() }
    } catch {
        return ""
    }
}

function Read-TunnelUrl {
    $parts = @()
    foreach ($path in @($tunnelErrLog, $tunnelLog)) {
        $parts += Read-SharedText -Path $path
    }
    $matches = [regex]::Matches(($parts -join "`n"), "https://[a-z0-9-]+\.trycloudflare\.com")
    if ($matches.Count -eq 0) { return $null }
    return $matches[$matches.Count - 1].Value
}

function Sync-TunnelUrl {
    param([string]$CurrentUrl)

    $url = Read-TunnelUrl
    if (-not $url) { return $null }
    Write-TextNoBom -Path $urlFile -Text $url

    if ($url -eq $CurrentUrl) { return $null }

    if (Test-Path $envFile) {
        $text = [System.IO.File]::ReadAllText($envFile)
        $text = $text -replace "(?m)^PUBLIC_BASE_URL=.*$", "PUBLIC_BASE_URL=$url"
        Write-TextNoBom -Path $envFile -Text $text
    }
    return $url
}

Log "iniciando (puerto $Port, modo $(Get-CatalogMode))"
$bot = Start-Bot
Log "API arrancada (PID $($bot.Id))"
$tunnel = $null
if (-not $NoTunnel) {
    if (-not (Test-Path $cloudflared)) {
        throw "Falta $cloudflared. Ver docs/despliegue.md (instalación de cloudflared)."
    }
    $tunnel = Start-Tunnel
    Log "túnel arrancado (PID $($tunnel.Id))"
}

$currentUrl = (Select-String -Path $envFile -Pattern "^PUBLIC_BASE_URL=(.*)$" -ErrorAction SilentlyContinue).Matches[0].Groups[1].Value

Start-Sleep -Seconds 15

if (Sync-Due) { Start-CatalogSync }
if (Backup-Due) { Start-Backup }
$webhook = Start-WebhookWatch
Log "vigilante de webhook arrancado (PID $($webhook.Id))"

while ($true) {
    Start-Sleep -Seconds 5

    try {
        if (Sync-Due) { Start-CatalogSync }
        if (Backup-Due) { Start-Backup }
        if (Fuzz-Due) { Start-Fuzz }
        if (FuzzMensual-Due) { Start-FuzzMensual }
        if (Faltantes-Due) { Start-Faltantes }

        if ($webhook -and $webhook.HasExited) {
            Log "el vigilante del webhook se detuvo; reiniciando"
            Start-Sleep -Seconds 3
            $webhook = Start-WebhookWatch
        }

        if ($bot.HasExited) {
            Log "la API se detuvo; reiniciando"
            Start-Sleep -Seconds 3
            $bot = Start-Bot
        }

        if ($tunnel -and $tunnel.HasExited) {
            Log "el túnel se detuvo; reiniciando"
            Start-Sleep -Seconds 3
            $tunnel = Start-Tunnel
            Start-Sleep -Seconds 10
        }

        if ($tunnel) {
            $url = Sync-TunnelUrl -CurrentUrl $currentUrl
            if ($url) {
                $currentUrl = $url
                Log "URL nueva: $url; reiniciando la API"
                if (-not $bot.HasExited) { $bot | Stop-Process -Force }
                Start-Sleep -Seconds 2
                $bot = Start-Bot
            }
        }
    } catch {
        # Un error en una vuelta no debe dejar el servidor sin supervisor.
        Log "ERROR en el supervisor: $($_.Exception.Message)"
        Start-Sleep -Seconds 5
    }
}
