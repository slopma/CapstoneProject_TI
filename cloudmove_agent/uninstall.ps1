# ==============================================================================
# CloudMove Agent — Script de Desinstalación Limpia para Windows (PowerShell)
# ==============================================================================
Write-Host "==> Desinstalando CloudMove Agent en Windows..." -ForegroundColor Cyan

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "ERROR: Debe ejecutar PowerShell como Administrador para desinstalar el agente."
    exit 1
}

$installDir = "C:\Program Files\CloudMove"
if (Test-Path $installDir) {
    Remove-Item -Recurse -Force $installDir
    Write-Host "==> [OK] Archivos y configuraciones de CloudMove eliminados de $installDir" -ForegroundColor Green
} else {
    Write-Host "==> No se encontró instalación en $installDir" -ForegroundColor Yellow
}
