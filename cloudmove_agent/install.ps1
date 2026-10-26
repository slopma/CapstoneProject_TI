# ==============================================================================
# CloudMove Agent — Script de Instalación Oficial para Windows (PowerShell)
# ==============================================================================
param (
    [Parameter(Mandatory=$true)]
    [string]$Token,
    [Parameter(Mandatory=$false)]
    [string]$Server = "http://localhost:8000"
)

Write-Host "==> Comprobando privilegios de Administrador..." -ForegroundColor Cyan
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "ERROR: Este script debe ejecutarse en una consola de PowerShell con privilegios de Administrador."
    exit 1
}

$installDir = "C:\Program Files\CloudMove"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
New-Item -ItemType Directory -Force -Path "$installDir\logs" | Out-Null

$hostname = [System.Net.Dns]::GetHostName()
$ip = "127.0.0.1"
try {
    $ip = (Test-Connection -ComputerName $hostname -Count 1).IPV4Address.IPAddressToString
} catch {}

$machineGuid = (Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Cryptography").MachineGuid

$enrollBody = @{
    enrollment_token = $Token
    hostname = $hostname
    ip_address = $ip
    os_family = "windows"
    os_name = (Get-CimInstance Win32_OperatingSystem).Caption
    os_version = (Get-CimInstance Win32_OperatingSystem).Version
    architecture = (Get-CimInstance Win32_OperatingSystem).OSArchitecture
    machine_id = $machineGuid
    version = "2.1.0"
} | ConvertTo-Json

Write-Host "==> Registrando e inscribiendo agente en $Server..." -ForegroundColor Cyan
try {
    $resp = Invoke-RestMethod -Uri "$Server/api/v1/agents/enroll" -Method Post -ContentType "application/json" -Body $enrollBody
    $agentId = $resp.agent_id
    $apiKey = $resp.agent_api_key

    $confContent = @"
[agent]
server_url = $Server
agent_id = $agentId
api_key = $apiKey
heartbeat_interval = 20
"@
    Set-Content -Path "$installDir\agent.conf" -Value $confContent
    Write-Host "==> [OK] Agente CloudMove ($agentId) registrado correctamente en $Server" -ForegroundColor Green
    Write-Host "==> Configuración guardada en $installDir\agent.conf" -ForegroundColor Green
    Write-Host "==> Para ejecutar el agente en primer plano: python -m cloudmove_agent.agent_daemon" -ForegroundColor Yellow
} catch {
    Write-Error "ERROR en el enrolamiento del agente: $_"
    exit 1
}
