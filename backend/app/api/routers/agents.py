"""
CloudMove Agent Management API Router (`/api/v1/agents`).

Addresses Section 3 (CloudMove Agent: Instalable y Funcional) and Section 8 (API & Integrations):
- Enrollment tokens with TTL, max uses, and revocation.
- Cryptographically authenticated enrollment and Bearer API Key issuance.
- Replay-protected heartbeats with system health metrics (CPU %, RAM %, disk %, uptime).
- Agent capability whitelist and dispatching of authorized migration tasks.
- Outbound polling of tasks and execution result recording.
- Inventory ingestion, CMIR normalization, and asset reconciliation.
- Dynamic delivery of Linux (`install.sh`) and Windows (`install.ps1`) installer scripts.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.persistence.transactional_db import get_transactional_db
from app.cmir.normalizer import normalize_inventory
from app.cmir.builder import build_cmir_hierarchy
from app.cmir.models import CMIR, CMIRNode, CMIREvidence
from app.dependencies.resolver import resolve_dependencies


router = APIRouter(prefix="/api/v1/agents", tags=["CloudMove Agent Management"])

DEFAULT_OPERATOR = os.getenv("CLOUDMOVE_OPERATOR_USER", "operator")


# ==============================================================================
# Pydantic Request / Response Schemas
# ==============================================================================

class CreateEnrollmentTokenRequest(BaseModel):
    ttl_seconds: int = Field(86400, ge=60, le=2592000, description="Token lifetime in seconds (1 min to 30 days)")
    max_uses: int = Field(1, ge=1, le=1000, description="Maximum number of times this token can be used")
    org_id: str = Field("default", description="Organization or tenant identifier")
    created_by: str = Field(DEFAULT_OPERATOR, description="Operator creating the enrollment token")


class EnrollAgentRequest(BaseModel):
    enrollment_token: str = Field(..., description="Single-use or bounded enrollment token")
    hostname: str = Field(..., description="Target server hostname")
    ip_address: Optional[str] = Field("127.0.0.1", description="Primary IP address")
    os_family: Optional[str] = Field("linux", description="Operating system family: linux | windows")
    os_name: Optional[str] = Field("Linux", description="Operating system distribution name")
    os_version: Optional[str] = Field("unknown", description="Operating system version")
    architecture: Optional[str] = Field("x86_64", description="Hardware architecture")
    machine_id: Optional[str] = Field(None, description="Stable host identifier (/etc/machine-id or DMI UUID)")
    version: Optional[str] = Field("2.1.0", description="Agent software release version")
    capabilities: Optional[List[str]] = Field(None, description="Requested agent capabilities")
    health_metrics: Optional[Dict[str, Any]] = Field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class AgentHeartbeatRequest(BaseModel):
    health_metrics: Dict[str, Any] = Field(..., description="CPU %, RAM %, disk %, uptime, load average")
    nonce: Optional[str] = Field(None, description="Replay protection nonce")
    timestamp: Optional[str] = Field(None, description="ISO 8601 UTC timestamp of request generation")


class DispatchTaskRequest(BaseModel):
    action: str = Field(
        ...,
        description="Authorized action: collect_inventory | inspect_disk | check_mgn_prerequisites | check_gcp_migrate_prerequisites | install_mgn_agent | quiesce_database | unquiesce_database",
    )
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict)
    timeout_seconds: int = Field(300, ge=10, le=3600)
    operator_id: str = Field("operator@cloudmove.local")


class TaskResultRequest(BaseModel):
    status: str = Field(..., description="COMPLETED | FAILED")
    result: Optional[Dict[str, Any]] = Field(default_factory=dict)
    error: Optional[str] = Field(None)


class RevokeAgentRequest(BaseModel):
    reason: str = Field("Desmantelamiento o desautorización de host", description="Audit reason for revocation")
    operator_id: str = Field(DEFAULT_OPERATOR)


# ==============================================================================
# Authentication Helper
# ==============================================================================

def _verify_agent_auth(agent_id: str, authorization: Optional[str]) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Falta la cabecera de autenticación 'Authorization: Bearer <agent_api_key>'.",
        )
    api_key = authorization.replace("Bearer ", "", 1).strip()
    db = get_transactional_db()
    agent = db.authenticate_agent(agent_id, api_key)
    if not agent:
        raise HTTPException(
            status_code=403,
            detail=f"Credenciales de agente no válidas o agente '{agent_id}' revocado.",
        )
    return agent


# ==============================================================================
# Endpoints
# ==============================================================================

@router.post("/enrollment-tokens")
def create_enrollment_token(req: CreateEnrollmentTokenRequest, request: Request):
    """
    Generate an authorized, time-limited token for enrolling a new CloudMove agent.
    Tokens are hashed on storage and can be restricted to a single use.
    """
    db = get_transactional_db()
    token_record = db.create_enrollment_token(
        created_by=req.created_by,
        ttl_seconds=req.ttl_seconds,
        max_uses=req.max_uses,
        org_id=req.org_id,
    )
    server_url = os.getenv("CLOUDMOVE_API_URL") or str(request.base_url).rstrip("/")
    return {
        "status": "created",
        "token_id": token_record["token_id"],
        "enrollment_token": token_record["enrollment_token"],
        "token_prefix": token_record["token_prefix"],
        "expires_at": token_record["expires_at"],
        "max_uses": token_record["max_uses"],
        "install_command_linux": (
            f"curl -sSL {server_url}/api/v1/agents/install.sh | sudo bash -s -- "
            f"--token {token_record['enrollment_token']} --server {server_url}"
        ),
        "install_command_windows": (
            f"Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('{server_url}/api/v1/agents/install.ps1')) "
            f"-Server '{server_url}' -Token '{token_record['enrollment_token']}'"
        ),
    }


@router.get("/enrollment-tokens")
def list_enrollment_tokens():
    """List all created enrollment tokens with expiration and usage status."""
    db = get_transactional_db()
    return {"tokens": db.list_enrollment_tokens()}


@router.post("/enroll")
def enroll_agent(req: EnrollAgentRequest):
    """
    Authenticate with an enrollment token, bind the machine's hardware identity,
    and issue a unique Agent API Key (Bearer Token) for ongoing operations.
    """
    db = get_transactional_db()
    token_record = db.verify_and_consume_enrollment_token(req.enrollment_token)
    if not token_record:
        raise HTTPException(
            status_code=401,
            detail="Token de inscripción inválido, expirado o revocado.",
        )

    enrolled = db.enroll_agent({
        "hostname": req.hostname,
        "ip_address": req.ip_address,
        "os_family": req.os_family,
        "os_name": req.os_name,
        "os_version": req.os_version,
        "architecture": req.architecture,
        "machine_id": req.machine_id,
        "version": req.version,
        "capabilities": req.capabilities,
        "health_metrics": req.health_metrics,
        "metadata": req.metadata,
    })

    return {
        "status": enrolled.get("status", "ONLINE"),
        "agent_id": enrolled["agent_id"],
        "agent_api_key": enrolled["agent_api_key"],
        "hostname": enrolled["hostname"],
        "capabilities": enrolled["capabilities"],
        "enrolled_at": enrolled["enrolled_at"],
        "server_version": "2.1.0",
        "heartbeat_interval_seconds": 20,
    }


# ==============================================================================
# Installer Script Delivery (Linux bash & Windows PowerShell)
# (Defined before /{agent_id} to ensure correct path precedence)
# ==============================================================================

@router.get("/install.sh")
def download_linux_installer(request: Request):
    """Deliver a self-contained, reproducible bash installer script for systemd-managed Linux."""
    host_url = f"{request.url.scheme}://{request.url.netloc}"
    script = f"""#!/usr/bin/env bash
# ==============================================================================
# CloudMove Agent — Script de Instalación Oficial para Linux (systemd)
# Compatible con Debian, Ubuntu, RHEL, Rocky, AlmaLinux y derivados.
# ==============================================================================
set -euo pipefail

SERVER_URL="{host_url}"
ENROLLMENT_TOKEN=""
INSTALL_DIR="/opt/cloudmove-agent"
SERVICE_NAME="cloudmove-agent"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token)
      ENROLLMENT_TOKEN="$2"
      shift 2
      ;;
    --server)
      SERVER_URL="$2"
      shift 2
      ;;
    *)
      echo "Opción desconocida: $1"
      echo "Uso: $0 --token <ENROLLMENT_TOKEN> [--server <URL>]"
      exit 1
      ;;
  esac
done

if [[ -z "$ENROLLMENT_TOKEN" ]]; then
  echo "ERROR: Debe proporcionar un token de inscripción válido con --token <TOKEN>"
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Este script debe ejecutarse como root o con sudo para configurar systemd."
  exit 1
fi

echo "==> Comprobando dependencias (Python 3.8+ y curl)..."
command -v python3 >/dev/null 2>&1 || {{ echo "ERROR: python3 no está instalado."; exit 1; }}
command -v curl >/dev/null 2>&1 || {{ echo "ERROR: curl no está instalado."; exit 1; }}

echo "==> Creando directorio de instalación en $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
mkdir -p /etc/cloudmove
mkdir -p /var/log/cloudmove

echo "==> Registrando e inscribiendo el agente en $SERVER_URL..."
HOSTNAME=$(hostname -f 2>/dev/null || hostname)
MACHINE_ID=""
if [[ -f /etc/machine-id ]]; then
  MACHINE_ID=$(cat /etc/machine-id | tr -d ' \\n')
elif [[ -f /var/lib/dbus/machine-id ]]; then
  MACHINE_ID=$(cat /var/lib/dbus/machine-id | tr -d ' \\n')
fi

ENROLL_PAYLOAD=$(python3 -c "
import json, socket, platform, os
data = {{
    'enrollment_token': '$ENROLLMENT_TOKEN',
    'hostname': '$HOSTNAME',
    'ip_address': socket.gethostbyname(socket.gethostname()) if hasattr(socket, 'gethostbyname') else '127.0.0.1',
    'os_family': 'linux',
    'os_name': platform.system(),
    'os_version': platform.version(),
    'architecture': platform.machine(),
    'machine_id': '$MACHINE_ID' or None,
    'version': '2.1.0'
}}
print(json.dumps(data))
")

ENROLL_RESP=$(curl -sS -X POST "$SERVER_URL/api/v1/agents/enroll" \\
  -H "Content-Type: application/json" \\
  -d "$ENROLL_PAYLOAD")

AGENT_ID=$(python3 -c "import json, sys; d=json.loads(sys.argv[1]); print(d.get('agent_id',''))" "$ENROLL_RESP")
API_KEY=$(python3 -c "import json, sys; d=json.loads(sys.argv[1]); print(d.get('agent_api_key',''))" "$ENROLL_RESP")

if [[ -z "$AGENT_ID" || -z "$API_KEY" ]]; then
  echo "ERROR al inscribir el agente. Respuesta del servidor:"
  echo "$ENROLL_RESP"
  exit 1
fi

echo "==> Guardando configuración segura en /etc/cloudmove/agent.conf (chmod 600)..."
cat <<CONF > /etc/cloudmove/agent.conf
[agent]
server_url = $SERVER_URL
agent_id = $AGENT_ID
api_key = $API_KEY
heartbeat_interval = 20
CONF
chmod 600 /etc/cloudmove/agent.conf

echo "==> Configurando servicio systemd ($SERVICE_NAME)..."
cat <<SERVICE > /etc/systemd/system/$SERVICE_NAME.service
[Unit]
Description=CloudMove Discovery & Migration Agent
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 -m cloudmove_agent.agent_daemon
WorkingDirectory=$INSTALL_DIR
Restart=always
RestartSec=10
StandardOutput=append:/var/log/cloudmove/agent.log
StandardError=append:/var/log/cloudmove/agent.log
NoNewPrivileges=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl restart $SERVICE_NAME

echo "==> [OK] Agente CloudMove ($AGENT_ID) instalado y activo correctamente."
systemctl status $SERVICE_NAME --no-pager || true
"""
    return Response(content=script, media_type="text/x-shellscript")


@router.get("/install.ps1")
def download_windows_installer(request: Request):
    """Deliver a PowerShell installer script for Windows systems."""
    host_url = f"{request.url.scheme}://{request.url.netloc}"
    script = f"""# ==============================================================================
# CloudMove Agent — Script de Instalación Oficial para Windows (PowerShell)
# ==============================================================================
param (
    [Parameter(Mandatory=$true)]
    [string]$Token,
    [Parameter(Mandatory=$false)]
    [string]$Server = "{host_url}"
)

Write-Host "==> Comprobando entorno de Windows..." -ForegroundColor Cyan
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{
    Write-Error "ERROR: Este script debe ejecutarse como Administrador."
    exit 1
}}

Write-Host "==> Plataforma Windows detectada. Verificando conectividad hacia $Server..." -ForegroundColor Cyan
$installDir = "C:\\Program Files\\CloudMove"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
New-Item -ItemType Directory -Force -Path "$installDir\\logs" | Out-Null

$hostname = [System.Net.Dns]::GetHostName()
$ip = (Test-Connection -ComputerName $hostname -Count 1).IPV4Address.IPAddressToString
$machineGuid = (Get-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Cryptography").MachineGuid

$enrollBody = @{{
    enrollment_token = $Token
    hostname = $hostname
    ip_address = $ip
    os_family = "windows"
    os_name = (Get-CimInstance Win32_OperatingSystem).Caption
    os_version = (Get-CimInstance Win32_OperatingSystem).Version
    architecture = (Get-CimInstance Win32_OperatingSystem).OSArchitecture
    machine_id = $machineGuid
    version = "2.1.0"
}} | ConvertTo-Json

try {{
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
    Set-Content -Path "$installDir\\agent.conf" -Value $confContent
    Write-Host "==> [OK] Agente CloudMove ($agentId) registrado correctamente en $Server" -ForegroundColor Green
    Write-Host "==> Configuración guardada en $installDir\\agent.conf" -ForegroundColor Green
}} catch {{
    Write-Error "ERROR en el enrolamiento del agente: $_"
    exit 1
}}
"""
    return Response(content=script, media_type="text/plain")


@router.post("/{agent_id}/heartbeat")
def record_heartbeat(
    agent_id: str,
    req: AgentHeartbeatRequest,
    authorization: Optional[str] = Header(None),
    x_agent_nonce: Optional[str] = Header(None),
    x_agent_timestamp: Optional[str] = Header(None),
):
    """
    Receive outbound heartbeat from an enrolled host, updating CPU/RAM metrics
    and returning the number of pending tasks awaiting execution.
    """
    _verify_agent_auth(agent_id, authorization)
    db = get_transactional_db()
    try:
        hb_res = db.record_agent_heartbeat(
            agent_id=agent_id,
            health_metrics=req.health_metrics,
            nonce=req.nonce or x_agent_nonce,
            timestamp=req.timestamp or x_agent_timestamp,
        )
        return hb_res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_agents(include_revoked: bool = Query(True)):
    """List all registered agents, their OS, health, capabilities, and online/offline status."""
    db = get_transactional_db()
    agents = db.list_agents(include_revoked=include_revoked)
    return {
        "total": len(agents),
        "online_count": sum(1 for a in agents if a["status"] == "ONLINE"),
        "agents": agents,
    }


@router.get("/{agent_id}")
def get_agent(agent_id: str):
    """Retrieve full details of an enrolled agent."""
    db = get_transactional_db()
    agent = db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agente '{agent_id}' no encontrado.")
    return agent


@router.post("/{agent_id}/revoke")
def revoke_agent(agent_id: str, req: RevokeAgentRequest):
    """Revoke an agent's credentials and permanently block further operations."""
    db = get_transactional_db()
    try:
        return db.revoke_agent(agent_id, reason=req.reason, revoked_by=req.operator_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{agent_id}/dispatch-task")
def dispatch_task(agent_id: str, req: DispatchTaskRequest):
    """
    Dispatch a bounded, authorized migration operation to the agent.
    Arbitrary shell execution is strictly rejected by policy.
    """
    db = get_transactional_db()
    try:
        return db.create_agent_task(
            agent_id=agent_id,
            action=req.action,
            parameters=req.parameters,
            timeout_seconds=req.timeout_seconds,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{agent_id}/tasks")
def poll_tasks(agent_id: str, authorization: Optional[str] = Header(None)):
    """Outbound task polling endpoint used by the agent."""
    _verify_agent_auth(agent_id, authorization)
    db = get_transactional_db()
    tasks = db.get_pending_tasks_for_agent(agent_id)
    return {"tasks": tasks}


@router.post("/{agent_id}/tasks/{task_id}/result")
def submit_task_result(
    agent_id: str,
    task_id: str,
    req: TaskResultRequest,
    authorization: Optional[str] = Header(None),
):
    """Agent submits task execution outcome."""
    _verify_agent_auth(agent_id, authorization)
    db = get_transactional_db()
    try:
        return db.complete_agent_task(
            task_id=task_id,
            agent_id=agent_id,
            status=req.status,
            result=req.result,
            error=req.error,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{agent_id}/inventory")
def ingest_agent_inventory(
    agent_id: str,
    payload: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    """
    Ingest a complete system inventory scan performed by the agent.
    Normalizes to CMIR v2.1 and reconciles host assets in transactional persistence.
    """
    agent = _verify_agent_auth(agent_id, authorization)
    db = get_transactional_db()
    now = datetime.now(timezone.utc).isoformat()

    # Reconcile asset in persistence
    hostname = payload.get("hostname") or agent["hostname"]
    canonical_key = f"host:{agent.get('machine_id') or hostname}"
    asset_id = f"asset-{agent_id}"

    db.upsert_asset(
        asset_id=asset_id,
        canonical_key=canonical_key,
        hostname=hostname,
        asset_type="physical_host",
        environment_id="on-premise-datacenter",
        site_id="site-agent-discovered",
        lifecycle_state="DISCOVERED",
        payload={
            "agent_id": agent_id,
            "os_name": agent.get("os_name"),
            "os_version": agent.get("os_version"),
            "architecture": agent.get("architecture"),
            "ip_address": agent.get("ip_address"),
            "cpu": payload.get("cpu", {}),
            "memory": payload.get("memory", {}),
            "disks": payload.get("disks", []),
            "processes": payload.get("processes", []),
            "listening_ports": payload.get("listening_ports", []),
            "services": payload.get("services", []),
            "databases": payload.get("databases", []) or payload.get("detected_databases", []),
            "detected_databases": payload.get("detected_databases", []),
            "discovered_at": now,
        },
    )

    return {
        "status": "ingested",
        "agent_id": agent_id,
        "asset_id": asset_id,
        "canonical_key": canonical_key,
        "hostname": hostname,
        "ingested_at": now,
    }
