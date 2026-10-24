# Publica la consola en la red interna (VLAN).
#
# Hace tres cosas:
#   1. Abre el puerto 8010 en el firewall solo para rangos privados.
#   2. Reinicia el servicio para que escuche en todas las interfaces.
#   3. Verifica que responda por la IP de la red.
#
# Ejecutar como administrador:
#   powershell -ExecutionPolicy Bypass -File scripts\publicar_lan.ps1

param(
    [int]$Port = 8010,
    [switch]$SoloFirewall,
    [switch]$SoloReinicio
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Host "Este script necesita una consola de PowerShell como administrador." -ForegroundColor Red
    Write-Host "Cerrá esta ventana, abrí PowerShell con 'Ejecutar como administrador' y volvé a correrlo."
    exit 1
}

$ip = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1)
if (-not $ip) {
    Write-Host "No se encontró una IP de red para este servidor." -ForegroundColor Red
    exit 1
}

$subred = "$($ip.IPAddress)/$($ip.PrefixLength)"
Write-Host "Servidor: $subred en $($ip.InterfaceAlias)"

if (-not $SoloReinicio) {
    $regla = Get-NetFirewallRule -DisplayName "ROHO consola $Port" -ErrorAction SilentlyContinue
    if ($regla) {
        Write-Host "Actualizando regla de firewall existente…"
        Set-NetFirewallRule -DisplayName "ROHO consola $Port" -Enabled True -Action Allow
        Set-NetFirewallAddressFilter -AssociatedNetFirewallRule $regla `
            -RemoteAddress 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
    } else {
        Write-Host "Creando regla de firewall (solo rangos privados)…"
        New-NetFirewallRule -DisplayName "ROHO consola $Port" `
            -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow `
            -RemoteAddress 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 | Out-Null
    }
    Write-Host "Firewall: puerto $Port abierto para rangos privados." -ForegroundColor Green
}

if (-not $SoloFirewall) {
    $servicio = Get-Service -Name "RohoBot" -ErrorAction SilentlyContinue
    if (-not $servicio) {
        Write-Host "No existe el servicio RohoBot. Instalalo con scripts\install_service.ps1" -ForegroundColor Red
        exit 1
    }
    Write-Host "Reiniciando RohoBot…"
    Restart-Service -Name "RohoBot"
    Start-Sleep -Seconds 12
}

Write-Host "Verificando…"
$okLocal = $false
$okLan = $false
try {
    $local = Invoke-WebRequest "http://127.0.0.1:$Port/health" -TimeoutSec 10 -UseBasicParsing
    $okLocal = $local.StatusCode -eq 200
} catch { }

try {
    $lan = Invoke-WebRequest "http://$($ip.IPAddress):$Port/health" -TimeoutSec 10 -UseBasicParsing
    $okLan = $lan.StatusCode -eq 200
} catch { }

Write-Host ""
Write-Host "Local   http://127.0.0.1:$Port  -> $(if ($okLocal) { 'OK' } else { 'sin respuesta' })" -ForegroundColor $(if ($okLocal) { 'Green' } else { 'Red' })
Write-Host "Red     http://$($ip.IPAddress):$Port  -> $(if ($okLan) { 'OK' } else { 'sin respuesta' })" -ForegroundColor $(if ($okLan) { 'Green' } else { 'Red' })
Write-Host ""
Write-Host "Consola para el equipo:  http://$($ip.IPAddress):$Port/console/"
Write-Host ""
Write-Host "Pendiente del DNS interno: registro A  roho-chatbot.gruporoda.com -> $($ip.IPAddress)"
Write-Host "Recomendado: reservar esa IP por DHCP (reserva por MAC) para que no cambie."
