"""
Shared agent catalog, version helpers, and live discovery payload builder.

Decouples shared agent version checks and live-discovery payload assembly
from FastAPI routers so routers never import other routers.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

from fastapi import Request

from app.core.security import is_control_plane_agent

LATEST_AGENT_VERSION = "2.2.0"


def is_version_gte(ver: Optional[str], target: str = LATEST_AGENT_VERSION) -> bool:
    """Return True when semantic version `ver` is greater than or equal to `target`."""
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


def extract_server_url(request: Request) -> str:
    """Resolve external CloudMove base URL from env override or reverse-proxy headers."""
    env_url = os.getenv("CLOUDMOVE_API_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip()
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
        or ""
    ).split(",")[0].strip()
    return f"{proto}://{host}".rstrip("/")


def build_live_agent_discovery_payload(
    server_url: Optional[str] = None,
    agent_id: Optional[str] = None,
    db_factory: Optional[Callable[[], Any]] = None,
    db: Any = None,
) -> Dict[str, Any]:
    """Build live discovery payload from enrolled non-control-plane agent telemetry."""
    base_url = (server_url or os.getenv("CLOUDMOVE_API_URL", "") or "http://localhost:8000").rstrip("/")
    resolved_db = db if db is not None else (db_factory() if db_factory is not None else None)
    if resolved_db is None:
        raise ValueError("build_live_agent_discovery_payload requires either `db` or `db_factory`.")
    all_agents = resolved_db.list_agents(include_revoked=False)
    remote_agents = [a for a in all_agents if not is_control_plane_agent(a)]

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

    online_list = [a for a in remote_agents if a.get("status") == "ONLINE"]
    chosen_agent = None
    if agent_id:
        chosen_agent = next((a for a in remote_agents if a.get("agent_id") == agent_id), None)
    if not chosen_agent:
        chosen_agent = online_list[0] if online_list else remote_agents[0]

    target_id = chosen_agent["agent_id"]
    assets = [
        a for a in resolved_db.list_assets()
        if a.get("payload", {}).get("agent_id") == target_id or a.get("id") == f"asset-{target_id}"
    ]
    payload = assets[0].get("payload", {}) if assets else {}

    filesystem_tree = payload.get("filesystem_tree") or []
    total_user_files_bytes = sum(node.get("size_bytes", 0) for node in filesystem_tree)
    total_user_files_gib = round(total_user_files_bytes / (1024 ** 3), 3)

    chosen_version = chosen_agent.get("version") or "2.1.0"
    upgrade_cmd = f"curl -sSL {base_url}/api/v1/agents/install.sh | sudo bash -s -- --upgrade"

    return {
        "agent_connected": True,
        "agents": remote_agents,
        "active_agent": {
            **chosen_agent,
            "supports_file_staging": is_version_gte(chosen_version, LATEST_AGENT_VERSION),
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
