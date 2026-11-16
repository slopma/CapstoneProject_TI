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
import io
import json
import os
from pathlib import Path
import tarfile
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
LATEST_AGENT_VERSION = "2.2.0"


def _is_version_gte(ver: Optional[str], target: str = LATEST_AGENT_VERSION) -> bool:
    try:
        cur_p = [int(x) for x in str(ver or "0").split(".")[:3]]
        tgt_p = [int(x) for x in target.split(".")[:3]]
        while len(cur_p) < 3:
            cur_p.append(0)
        while len(tgt_p) < 3:
            tgt_p.append(0)
        return tuple(cur_p) >= tuple(tgt_p)
    except Exception:
        return False


def _get_server_url(request: Request) -> str:
    env_url = os.getenv("CLOUDMOVE_API_URL")
    if env_url:
        return env_url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    if "digitalcafeluna.store" in (host or ""):
        proto = "https"
    return f"{proto}://{host}".rstrip("/")


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


class StageCommitRequest(BaseModel):
    stage_id: str
    total_chunks: int = Field(..., ge=1, le=50000)
    selected_paths: List[str] = Field(default_factory=list)
    migration_id: Optional[str] = None
    expected_sha256: Optional[str] = None
    skipped_files: List[Dict[str, Any]] = Field(default_factory=list)


class DispatchTaskRequest(BaseModel):
    action: str = Field(
        ...,
        description="Authorized action: collect_inventory | inspect_disk | check_mgn_prerequisites | check_gcp_migrate_prerequisites | install_mgn_agent | quiesce_database | unquiesce_database | stage_selected_paths | self_update",
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
    server_url = _get_server_url(request)
    raw_token = token_record["enrollment_token"]
    linux_cmd = (
        f"curl -sSL {server_url}/api/v1/agents/install.sh | sudo bash -s -- "
        f"--token {raw_token} --server {server_url}"
    )
    windows_cmd = (
        f"Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('{server_url}/api/v1/agents/install.ps1')) "
        f"-Server '{server_url}' -Token '{raw_token}'"
    )
    return {
        "status": "created",
        "token_id": token_record["token_id"],
        "token": raw_token,
        "enrollment_token": raw_token,
        "token_prefix": token_record["token_prefix"],
        "expires_at": token_record["expires_at"],
        "max_uses": token_record["max_uses"],
        "install_command_linux": linux_cmd,
        "install_command_windows": windows_cmd,
        "install_commands": {
            "linux": linux_cmd,
            "linux_macos": linux_cmd,
            "windows_powershell": windows_cmd,
        },
    }


@router.get("/enrollment-tokens")
def list_enrollment_tokens():
    """List all created enrollment tokens with expiration and usage status."""
    db = get_transactional_db()
    return {"tokens": db.list_enrollment_tokens()}


@router.post("/enroll")
def enroll_agent(req: EnrollAgentRequest, request: Request):
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

    eff_ip = req.ip_address or ""
    if not eff_ip or eff_ip.startswith("127."):
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip", "").strip()
        client_ip = request.client.host if request.client else ""
        eff_ip = fwd or real_ip or client_ip or "10.0.0.1"

    eff_host = (req.hostname or "").strip()
    if not eff_host or eff_host.lower() in ("localhost", "localhost.localdomain"):
        eff_host = f"remote-node-{(req.machine_id or 'host')[:8]}"

    enrolled = db.enroll_agent({
        "hostname": eff_host,
        "ip_address": eff_ip,
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
        "server_version": LATEST_AGENT_VERSION,
        "heartbeat_interval_seconds": 20,
    }


# ==============================================================================
# Installer Script Delivery (Linux bash & Windows PowerShell)
# (Defined before /{agent_id} to ensure correct path precedence)
# ==============================================================================

@router.get("/bundle.tar.gz")
def download_agent_bundle():
    """Deliver the cloudmove_agent Python package as a tar.gz bundle for agents."""
    candidates = [
        Path("/app/cloudmove_agent"),
        Path(__file__).resolve().parents[4] / "cloudmove_agent",
        Path(__file__).resolve().parents[3] / "cloudmove_agent",
        Path(__file__).resolve().parents[2] / "cloudmove_agent",
        Path("/opt/cloudmove/cloudmove_agent"),
    ]
    agent_dir = None
    for cand in candidates:
        if cand.is_dir():
            agent_dir = cand
            break

    if not agent_dir:
        raise HTTPException(status_code=404, detail="Paquete cloudmove_agent no encontrado en el servidor.")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in agent_dir.glob("*.py"):
            tar.add(f, arcname=f.name)
        for f in agent_dir.glob("*.service"):
            tar.add(f, arcname=f.name)
        for f in agent_dir.glob("*.sh"):
            tar.add(f, arcname=f.name)

    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="application/gzip")


@router.get("/install.sh")
def download_linux_installer(request: Request, token: Optional[str] = Query(None)):
    """Deliver a self-contained, reproducible bash installer script for systemd-managed Linux."""
    host_url = _get_server_url(request)
    default_token = (token or "").strip()
    script = f"""#!/usr/bin/env bash
# ==============================================================================
# CloudMove Agent — Script de Instalación Oficial para Linux (systemd)
# Compatible con Debian, Ubuntu, RHEL, Rocky, AlmaLinux y derivados.
# ==============================================================================
set -euo pipefail

SERVER_URL="{host_url}"
ENROLLMENT_TOKEN="{default_token}"
INSTALL_DIR="/opt/cloudmove-agent"
SERVICE_NAME="cloudmove-agent"
UPGRADE_ONLY="false"

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
    --upgrade)
      UPGRADE_ONLY="true"
      shift 1
      ;;
    *)
      echo "Opción desconocida: $1"
      echo "Uso: $0 (--token <ENROLLMENT_TOKEN> | --upgrade) [--server <URL>]"
      exit 1
      ;;
  esac
done

if [[ "$UPGRADE_ONLY" != "true" && -z "$ENROLLMENT_TOKEN" ]]; then
  echo "ERROR: Debe proporcionar --token <TOKEN> o usar --upgrade para actualizar el agente existente."
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Este script debe ejecutarse como root o con sudo para configurar systemd."
  exit 1
fi

echo "==> Comprobando dependencias (Python 3.8+, curl y tar)..."
command -v python3 >/dev/null 2>&1 || {{ echo "ERROR: python3 no está instalado."; exit 1; }}
command -v curl >/dev/null 2>&1 || {{ echo "ERROR: curl no está instalado."; exit 1; }}
command -v tar >/dev/null 2>&1 || {{ echo "ERROR: tar no está instalado."; exit 1; }}

echo "==> Creando directorio de instalación en $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
mkdir -p /etc/cloudmove
mkdir -p /var/log/cloudmove

echo "==> Descargando archivos actualizados del paquete cloudmove_agent (v{LATEST_AGENT_VERSION})..."
mkdir -p "$INSTALL_DIR/cloudmove_agent"
curl -sSL "$SERVER_URL/api/v1/agents/bundle.tar.gz" | tar -xz -C "$INSTALL_DIR/cloudmove_agent"

if [[ "$UPGRADE_ONLY" == "true" ]]; then
  if [[ ! -f /etc/cloudmove/agent.conf ]]; then
    echo "ERROR: No se encontró /etc/cloudmove/agent.conf para actualizar. Ejecuta con --token <TOKEN>."
    exit 1
  fi
  echo "==> Modo actualización (--upgrade): conservando identidad y API Key de /etc/cloudmove/agent.conf..."
  systemctl daemon-reload || true
  systemctl restart $SERVICE_NAME
  PYTHONPATH="$INSTALL_DIR" /usr/bin/python3 -c "from cloudmove_agent.agent_daemon import CloudMoveAgentDaemon; d=CloudMoveAgentDaemon(); d.send_heartbeat(); d._task_collect_inventory()" >/dev/null 2>&1 || true
  echo "==> [OK] Agente CloudMove actualizado a v{LATEST_AGENT_VERSION} y reiniciado."
  systemctl status $SERVICE_NAME --no-pager || true
  exit 0
fi

echo "==> Registrando e inscribiendo el agente en $SERVER_URL..."
HOST_NAME=$(cat /etc/hostname 2>/dev/null | tr -d ' \\n' || hostname -s 2>/dev/null || hostname)
if [[ -z "$HOST_NAME" || "$HOST_NAME" == "localhost" ]]; then
  HOST_NAME=$(hostname)
fi
MACHINE_ID=""
if [[ -f /etc/machine-id ]]; then
  MACHINE_ID=$(cat /etc/machine-id | tr -d ' \\n')
elif [[ -f /var/lib/dbus/machine-id ]]; then
  MACHINE_ID=$(cat /var/lib/dbus/machine-id | tr -d ' \\n')
fi

ENROLL_PAYLOAD=$(python3 -c "
import json, socket, platform, os
def get_primary_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '10.0.0.1'
real_host = '$HOST_NAME'.strip() or platform.node() or socket.gethostname()
data = {{
    'enrollment_token': '$ENROLLMENT_TOKEN',
    'hostname': real_host,
    'ip_address': get_primary_ip(),
    'os_family': 'linux',
    'os_name': platform.system(),
    'os_version': platform.version(),
    'architecture': platform.machine(),
    'machine_id': '$MACHINE_ID' or None,
    'version': '{LATEST_AGENT_VERSION}'
}}
print(json.dumps(data))
")

ENROLL_RESP=$(curl -sSL -X POST "$SERVER_URL/api/v1/agents/enroll" \\
  -H "Content-Type: application/json" \\
  -d "$ENROLL_PAYLOAD")

AGENT_ID=$(python3 -c "import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get('agent_id',''))
except Exception:
    pass
" "$ENROLL_RESP" 2>/dev/null || true)

API_KEY=$(python3 -c "import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get('agent_api_key',''))
except Exception:
    pass
" "$ENROLL_RESP" 2>/dev/null || true)

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
Environment=PYTHONPATH=$INSTALL_DIR
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

echo "==> Sincronizando inventario inicial (carpetas, archivos, puertos y procesos) con CloudMove..."
PYTHONPATH="$INSTALL_DIR" /usr/bin/python3 -c "from cloudmove_agent.agent_daemon import CloudMoveAgentDaemon; CloudMoveAgentDaemon()._task_collect_inventory()" >/dev/null 2>&1 || true

echo "==> [OK] Agente CloudMove ($AGENT_ID) instalado, sincronizado y activo correctamente."
systemctl status $SERVICE_NAME --no-pager || true
"""
    return Response(content=script, media_type="text/x-shellscript")


@router.get("/install.ps1")
def download_windows_installer(request: Request):
    """Deliver a PowerShell installer script for Windows systems."""
    host_url = _get_server_url(request)
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
        # Auto-request inventory if asset is missing filesystem_tree
        try:
            assets = [
                a for a in db.list_assets()
                if a.get("payload", {}).get("agent_id") == agent_id or a.get("id") == f"asset-{agent_id}"
            ]
            has_fs_tree = bool(assets and assets[0].get("payload", {}).get("filesystem_tree"))
            if not has_fs_tree and hb_res.get("pending_tasks_count", 0) == 0:
                db.create_agent_task(agent_id=agent_id, action="collect_inventory", parameters={}, timeout_seconds=120)
                hb_res["pending_tasks_count"] = 1
        except Exception:
            pass
        return hb_res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/live-discovery")
def get_live_agent_discovery(
    request: Request,
    agent_id: Optional[str] = Query(None),
):
    """
    Return the complete live discovery inventory reported by the enrolled remote agent(s),
    including folders & files (filesystem_tree), listening ports, running processes,
    systemd services, disks/partitions, CPU/RAM, and AWS EBS storage quota limits.
    """
    db = get_transactional_db()
    all_agents = db.list_agents(include_revoked=False)
    remote_agents = [
        a for a in all_agents
        if (a.get("hostname") or "").lower() not in ("cloudmove-server", "localhost")
        and a.get("ip_address") != "100.50.88.231"
    ]
    if not remote_agents:
        return {
            "agent_connected": False,
            "agents": [],
            "active_agent": None,
            "inventory": None,
            "aws_storage_quota": {
                "free_tier_gib": 30.0,
                "max_single_volume_gib": 100.0,
                "academy_account_max_gib": 150.0,
                "base_os_overhead_gib": 2.5,
            },
        }

    # Pick requested agent or first ONLINE agent (or most recently enrolled)
    online_list = [a for a in remote_agents if a.get("status") == "ONLINE"]
    chosen_agent = None
    if agent_id:
        chosen_agent = next((a for a in remote_agents if a.get("agent_id") == agent_id), None)
    if not chosen_agent:
        chosen_agent = online_list[0] if online_list else remote_agents[0]

    target_id = chosen_agent["agent_id"]
    assets = [
        a for a in db.list_assets()
        if a.get("payload", {}).get("agent_id") == target_id or a.get("id") == f"asset-{target_id}"
    ]
    payload = assets[0].get("payload", {}) if assets else {}

    filesystem_tree = payload.get("filesystem_tree") or []
    total_user_files_bytes = sum(node.get("size_bytes", 0) for node in filesystem_tree)
    total_user_files_gib = round(total_user_files_bytes / (1024 ** 3), 3)

    chosen_version = chosen_agent.get("version") or "2.1.0"
    server_url = _get_server_url(request)
    upgrade_cmd = f"curl -sSL {server_url}/api/v1/agents/install.sh | sudo bash -s -- --upgrade"

    return {
        "agent_connected": True,
        "agents": remote_agents,
        "active_agent": {
            **chosen_agent,
            "supports_file_staging": _is_version_gte(chosen_version, LATEST_AGENT_VERSION),
            "latest_agent_version": LATEST_AGENT_VERSION,
            "upgrade_command_linux": upgrade_cmd,
        },
        "inventory": {
            "agent_id": target_id,
            "hostname": payload.get("hostname") or chosen_agent.get("hostname"),
            "ip_address": payload.get("ip_address") or chosen_agent.get("ip_address"),
            "os_name": payload.get("os_name") or chosen_agent.get("os_name"),
            "os_version": payload.get("os_version") or chosen_agent.get("os_version"),
            "os_release": payload.get("os_release") or "",
            "architecture": payload.get("architecture") or chosen_agent.get("architecture"),
            "discovered_at": payload.get("discovered_at") or chosen_agent.get("last_heartbeat_at"),
            "cpu": payload.get("cpu") or {},
            "memory": payload.get("memory") or {},
            "disks": payload.get("disks") or [],
            "network_interfaces": payload.get("network_interfaces") or [],
            "listening_ports": payload.get("listening_ports") or [],
            "processes": payload.get("processes") or [],
            "services": payload.get("services") or [],
            "runtimes": payload.get("runtimes") or [],
            "databases": payload.get("databases") or [],
            "filesystem_tree": filesystem_tree,
            "filesystem_summary": {
                "roots_count": len(filesystem_tree),
                "total_size_bytes": total_user_files_bytes,
                "total_size_mb": round(total_user_files_bytes / (1024 * 1024), 2),
                "total_size_gib": total_user_files_gib,
            },
        },
        "aws_storage_quota": {
            "free_tier_gib": 30.0,
            "max_single_volume_gib": 100.0,
            "academy_account_max_gib": 150.0,
            "base_os_overhead_gib": 2.5,
        },
    }


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
            "hostname": hostname,
            "os_name": agent.get("os_name"),
            "os_version": agent.get("os_version"),
            "os_release": payload.get("os_release"),
            "architecture": agent.get("architecture"),
            "ip_address": agent.get("ip_address"),
            "cpu": payload.get("cpu", {}),
            "memory": payload.get("memory", {}),
            "disks": payload.get("disks", []),
            "network_interfaces": payload.get("network_interfaces", []),
            "processes": payload.get("processes", []),
            "listening_ports": payload.get("listening_ports", []),
            "services": payload.get("services", []),
            "runtimes": payload.get("runtimes", []),
            "databases": payload.get("databases", []) or payload.get("detected_databases", []),
            "detected_databases": payload.get("detected_databases", []),
            "filesystem_tree": payload.get("filesystem_tree", []),
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


@router.post("/{agent_id}/stage-chunk")
async def upload_agent_stage_chunk(
    agent_id: str,
    request: Request,
    stage_id: str = Query(...),
    chunk_index: int = Query(..., ge=0),
    total_chunks: int = Query(..., ge=1),
    authorization: Optional[str] = Header(None),
):
    """Receive an authenticated binary chunk of user-selected Case 2 files from an agent."""
    _verify_agent_auth(agent_id, authorization)
    raw = await request.body()
    from app.migration.uc2_staging import save_stage_chunk

    try:
        return save_stage_chunk(
            stage_id=stage_id,
            chunk_index=chunk_index,
            total_chunks=total_chunks,
            raw_bytes=raw,
            agent_id=agent_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{agent_id}/stage-commit")
def commit_agent_stage_archive(
    agent_id: str,
    req: StageCommitRequest,
    authorization: Optional[str] = Header(None),
):
    """Assemble and validate uploaded Case 2 file chunks into persistent staging."""
    _verify_agent_auth(agent_id, authorization)
    from app.migration.uc2_staging import commit_stage_archive

    try:
        meta = commit_stage_archive(
            stage_id=req.stage_id,
            total_chunks=req.total_chunks,
            selected_paths=req.selected_paths,
            agent_id=agent_id,
            migration_id=req.migration_id,
            expected_sha256=req.expected_sha256,
            skipped_files=req.skipped_files,
            source_type="agent",
        )
        if req.migration_id:
            try:
                from app.migration.orchestrator import migration_orchestrator

                migration_orchestrator.refresh_uc2_stage_binding(req.migration_id, stage_meta=meta)
            except Exception:
                pass
        return {
            "status": "READY",
            "stage_id": meta["stage_id"],
            "files_count": meta.get("files_count", 0),
            "bundle_size_bytes": meta.get("bundle_size_bytes", 0),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
