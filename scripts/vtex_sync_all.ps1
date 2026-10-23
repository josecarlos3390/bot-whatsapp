# Sincronizacion periodica del bot contra VTEX.
# Ejecutar con:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\vtex_sync_all.ps1
#
# Programar en el Programador de tareas de Windows (admin):
#   schtasks /Create /SC DAILY /TN "Chatbot VTEX Sync" ^
#     /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\ProyectosPython\chatbot-whatsapp\scripts\vtex_sync_all.ps1" ^
#     /ST 03:00 /RU SYSTEM /RL HIGHEST

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$log = Join-Path $logDir ("vtex_sync_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

function Run-Step {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    Write-Host "== $Name ==" -ForegroundColor Cyan
    & $python @Arguments 2>&1 |
        Tee-Object -FilePath $log -Append |
        Out-Null
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Write-Host "$Name fallo con codigo $code" -ForegroundColor Yellow
    }
    return $code
}

$failed = 0
$steps = @()

# Catalogo, imagenes, precio de lista y PriceValidUntil.
$code = Run-Step "Catalogo VTEX" @("-m", "scripts.sync_vtex")
$failed += $code
$steps += [pscustomobject]@{ name = "Catalogo VTEX"; exit_code = $code }

# Promociones locales con vigencia.
$code = Run-Step "Promociones VTEX" @("-m", "scripts.sync_vtex_promotions")
$failed += $code
$steps += [pscustomobject]@{ name = "Promociones VTEX"; exit_code = $code }

# Mas vendidos desde OMS.
$code = Run-Step "Ventas VTEX" @("-m", "scripts.sync_vtex_sales_stats")
$failed += $code
$steps += [pscustomobject]@{ name = "Ventas VTEX"; exit_code = $code }

# Clientes ya vinculados por RUT/email y sus compras.
$code = Run-Step "Clientes/compras VTEX" @(
    "-m", "scripts.sync_vtex_customers", "--from-contacts"
)
$failed += $code
$steps += [pscustomobject]@{ name = "Clientes/compras VTEX"; exit_code = $code }

$status = [ordered]@{
    last_run  = (Get-Date).ToString("o")
    exit_code = $failed
    log       = $log
    steps     = $steps
}
$statusPath = Join-Path $logDir "vtex_sync_status.json"
$status | ConvertTo-Json -Depth 4 | Set-Content -Path $statusPath -Encoding UTF8

Write-Host "Log: $log" -ForegroundColor Cyan
if ($failed -ne 0) {
    exit 1
}
exit 0
