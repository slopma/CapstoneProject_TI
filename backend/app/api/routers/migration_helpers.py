"""
Shared helpers for `/api/v1/migration` routers: provider validation, sanitization,
SSRF-safe HTTP/TCP probing, Terraform post-apply synchronization, and UC2 proxies.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
from typing import Any, Callable, Dict, Optional
import urllib.error
import urllib.parse
import urllib.request

from fastapi import HTTPException, Request

from app.core.agents_catalog import extract_server_url
from app.core.security import SSRFBlockedError, open_url_no_redirects, validate_public_target_host
from app.migration.orchestrator import SUPPORTED_TARGET_PROVIDERS, migration_orchestrator


def validate_target_provider(provider: Optional[str]) -> str:
    clean = str(provider or "aws").lower().strip()
    if clean not in SUPPORTED_TARGET_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Proveedor destino '{provider}' no admitido. "
                "El único proveedor destino admitido en CloudMove es 'aws' (Amazon Web Services)."
            ),
        )
    return clean


def sanitize_job_for_export(job_data: Any) -> Any:
    """Recursively redact sensitive credential keys prior to bundle/report export."""
    if isinstance(job_data, dict):
        sanitized = {}
        for k, v in job_data.items():
            k_lower = str(k).lower()
            if any(term in k_lower for term in ("token", "password", "secret", "private_key", "credential", "api_key", "auth")):
                sanitized[k] = "[REDACTED]" if (v and isinstance(v, str)) else v
            else:
                sanitized[k] = sanitize_job_for_export(v)
        return sanitized
    if isinstance(job_data, list):
        return [sanitize_job_for_export(item) for item in job_data]
    return job_data


def infer_public_api_url(request: Optional[Request] = None) -> str:
    env_url = os.getenv("CLOUDMOVE_API_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    if not request:
        return "http://localhost:8000"
    return extract_server_url(request)


def sanitize_probe_host(ip: str) -> str:
    """Validate target host/IP for external EC2 probe preventing DNS rebinding & IMDS SSRF."""
    try:
        return validate_public_target_host(ip, allow_private=False)
    except SSRFBlockedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def probe_tcp_port(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def probe_http_endpoint(url: str, timeout: float = 2.5) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "CloudMove-HealthCheck/1.0"},
        )
        with open_url_no_redirects(req, timeout=timeout) as resp:
            return {"online": True, "status": resp.status, "message": "OK"}
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            return {"online": False, "status": exc.code, "message": "Redirección HTTP bloqueada por política anti-SSRF"}
        return {"online": True, "status": exc.code, "message": f"HTTP {exc.code}"}
    except (urllib.error.URLError, socket.timeout, ConnectionRefusedError, OSError) as exc:
        return {"online": False, "status": None, "message": str(exc)}


def resolve_facade_probe_fn(attr_name: str, default_fn: Callable[..., Any]) -> Callable[..., Any]:
    """Allow monkeypatching via `app.api.routers.migration` facade without circular imports."""
    facade_mod = sys.modules.get("app.api.routers.migration")
    candidate = getattr(facade_mod, attr_name, None) if facade_mod else None
    return candidate if callable(candidate) else default_fn


def fetch_json_endpoint(url: str, timeout: float = 3.5) -> Dict[str, Any]:
    """Fetch JSON from an EC2 validation endpoint with latency timing & anti-redirect guard."""
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "CloudMove-UC2-Validator/1.0"},
        )
        with open_url_no_redirects(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed_ms = round((time.monotonic() - t0) * 1000.0, 1)
            return {
                "ok": 200 <= resp.status < 300,
                "http_status": resp.status,
                "latency_ms": elapsed_ms,
                "data": json.loads(raw),
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "http_status": exc.code,
            "latency_ms": round((time.monotonic() - t0) * 1000.0, 1),
            "data": None,
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "http_status": None,
            "latency_ms": round((time.monotonic() - t0) * 1000.0, 1),
            "data": None,
            "error": str(exc),
        }


def resolve_probe_targets(
    migration_id: Optional[str],
    frontend_port: Optional[int],
    backend_port: Optional[int],
    health_path: Optional[str],
) -> tuple[int, int, str]:
    """Resolve target frontend/backend ports and health endpoint for an EC2 live probe."""
    fe_port = frontend_port
    be_port = backend_port
    clean_hp = (health_path or "").strip()

    if migration_id:
        try:
            job = migration_orchestrator.get_migration(migration_id)
            if job.get("use_case") == "vm_image":
                return fe_port or 3000, be_port or 8000, clean_hp or "/health"
            src_env = job.get("source_environment") or {}
            endpoints = src_env.get("service_endpoints") or {}
            if not endpoints and (src_env.get("components") or src_env.get("exposed_ports")):
                from app.migration.app_migrator import _infer_service_endpoints

                endpoints = _infer_service_endpoints(
                    src_env.get("components") or [],
                    src_env.get("exposed_ports") or [],
                    src_env.get("health_endpoints") or ["/health"],
                )
            if fe_port is None and endpoints.get("frontend_port"):
                fe_port = int(endpoints["frontend_port"])
            if be_port is None and endpoints.get("backend_port"):
                be_port = int(endpoints["backend_port"])
            if not clean_hp and endpoints.get("health_endpoint"):
                clean_hp = str(endpoints["health_endpoint"])
        except Exception:
            pass

    if not clean_hp or not re.match(r"^/[A-Za-z0-9/_-]*$", clean_hp):
        clean_hp = "/health"
    return int(fe_port or 3000), int(be_port or 8000), clean_hp


def fetch_uc2_ec2_file(
    ip: str,
    path: str,
    endpoint: str,
    timeout_sec: float = 8.0,
) -> tuple[str, bytes]:
    """Fetch a migrated Case 2 file safely from the EC2 inspection service (`3000`)."""
    clean_ip = sanitize_probe_host(ip)
    clean_rel = str(path or "").lstrip("/")
    if not clean_rel or ".." in clean_rel.split("/"):
        raise HTTPException(status_code=400, detail="Ruta de archivo inválida")
    target_url = f"http://{clean_ip}:3000{endpoint}?path={urllib.parse.quote(clean_rel)}"
    try:
        req = urllib.request.Request(target_url, headers={"User-Agent": "CloudMove-UC2-Proxy/1.0"})
        with open_url_no_redirects(req, timeout=timeout_sec) as resp:
            return clean_rel, resp.read()
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail=f"Archivo no accesible en EC2: HTTP {exc.code}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar archivo desde {clean_ip}: {exc}")


def sync_job_after_terraform(migration_id: str, tf_result: Dict[str, Any]) -> None:
    """Synchronize orchestrator state machine when a live Terraform apply succeeds."""
    if not tf_result.get("success"):
        return
    action = str(tf_result.get("action") or "").lower()
    if action not in ("apply", "continue", "full_deploy"):
        return
    try:
        job = migration_orchestrator.get_migration(migration_id)
        prereqs = job.get("prerequisites") or {}
        prereqs["live_credentials_verified"] = True
        job["prerequisites"] = prereqs
        migration_orchestrator._save_job(job, actor_id="cloudmove-terraform-runner@cloudmove.local")

        if job.get("state") == "PLAN_READY":
            migration_orchestrator.approve_migration(
                migration_id,
                approved_by="cloudmove-terraform-runner@cloudmove.local",
                notes="Aprobado automáticamente tras ejecución exitosa de Terraform Apply en la nube.",
            )

        for _ in range(5):
            curr_job = migration_orchestrator.get_migration(migration_id)
            if curr_job.get("state") in ("APPROVED", "PREPARING", "TESTING", "READY_FOR_CUTOVER"):
                migration_orchestrator.advance_execution(
                    migration_id=migration_id,
                    dry_run=False,
                    operator_id="cloudmove-terraform-runner@cloudmove.local",
                )
            else:
                break

        latest_job = migration_orchestrator.get_migration(migration_id)
        if latest_job.get("use_case") == "vm_image":
            src_env = latest_job.get("source_environment") or {}
            src_cfg = latest_job.get("source_config") or {}
            sel_paths = src_env.get("selected_user_paths") or src_cfg.get("selected_user_paths") or []
            ec2_ip = (
                ((tf_result.get("outputs") or {}).get("instance_public_ip") or {}).get("value")
                or ((tf_result.get("primary_instance") or {}).get("public_ip"))
            )
            sync_tok = str(src_env.get("uc2_sync_token") or "").strip()
            if ec2_ip and sel_paths:
                from app.migration.uc2_staging import (
                    build_stage_download_url,
                    dispatch_push_to_ec2,
                    find_ready_stage,
                    push_stage_to_ec2,
                )

                ready_stg = find_ready_stage(
                    stage_id=src_env.get("stage_id"),
                    migration_id=migration_id,
                    agent_id=src_cfg.get("agent_id"),
                    selected_paths=sel_paths,
                    include_secrets=True,
                )
                if ready_stg:
                    dl_url = build_stage_download_url(infer_public_api_url(None), ready_stg)
                    push_stage_to_ec2(ec2_ip, dl_url, sync_token=sync_tok or ready_stg.get("sync_token"))
                elif sync_tok:
                    dispatch_push_to_ec2(
                        ec2_host=ec2_ip,
                        selected_paths=sel_paths,
                        sync_token=sync_tok,
                        agent_id=src_cfg.get("agent_id"),
                        migration_id=migration_id,
                    )
    except Exception:
        pass
