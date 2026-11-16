"""
Use Case 2 (`vm_image`) VM Image, Live Host OS Capture, Staging & Telemetry Endpoints.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import List, Optional
import urllib.request

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse

from app.api.routers.migration_helpers import (
    fetch_json_endpoint,
    fetch_uc2_ec2_file,
    infer_public_api_url,
    probe_tcp_port,
    resolve_facade_probe_fn,
    sanitize_probe_host,
    validate_target_provider,
)
from app.api.routers.migration_schemas import (
    ImageInspectRequest,
    RemediateBlockerRequest,
    Uc2BrowserBatchRequest,
    Uc2DispatchAgentStageRequest,
    Uc2StageCommitRequest,
    Uc2StageInitRequest,
)
from app.core.agents_catalog import LATEST_AGENT_VERSION, is_version_gte
from app.core.security import is_control_plane_agent, open_url_no_redirects
from app.migration.image_migrator import (
    build_vm_image_cmir,
    evaluate_vm_image_compatibility,
    inspect_vm_image,
    probe_live_storage_devices,
)
from app.migration.orchestrator import migration_orchestrator
from app.persistence.transactional_db import get_transactional_db

router = APIRouter()


@router.post("/use-case-2/inspect")
def inspect_use_case_2_vm_image(
    http_request: Request,
    request: Optional[ImageInspectRequest] = None,
):
    """Inspect a VM disk image or live OS capture and compute compatibility & CMIR."""
    req = request or ImageInspectRequest()
    target = validate_target_provider(req.target_provider)
    try:
        manifest = inspect_vm_image(
            image_path=req.image_path,
            manifest_override=req.manifest_override,
            require_authentic_binary=req.require_authentic_binary,
            capture_live_host=req.capture_live_host,
            target_provider=target,
            output_format=req.output_format or "QCOW2",
            agent_id=req.agent_id,
        )
        sel_paths = (req.manifest_override or {}).get("selected_user_paths") or manifest.get("selected_user_paths") or []
        stage_status = None
        if req.capture_live_host and sel_paths:
            try:
                from app.migration.uc2_staging import ensure_uc2_selected_paths_staged

                stage_status = ensure_uc2_selected_paths_staged(
                    selected_paths=sel_paths,
                    agent_id=req.agent_id or (manifest.get("live_capture_details") or {}).get("captured_via", "").replace("agent:", "") or None,
                    stage_id=(req.manifest_override or {}).get("stage_id"),
                    public_api_url=infer_public_api_url(http_request),
                )
                if stage_status.get("stage"):
                    manifest["stage_id"] = stage_status["stage"]["stage_id"]
                    manifest["staged_files_count"] = stage_status["stage"].get("files_count", 0)
            except Exception:
                stage_status = None

        source_type = str(manifest.get("source_type") or req.source_type or "standalone_offline_disk_image")
        compat = evaluate_vm_image_compatibility(
            manifest,
            target_provider=target,
            require_live_memory_state=req.require_live_memory_state,
            require_authentic_binary=req.require_authentic_binary,
            source_type=source_type,
            prefer_continuous_replication=req.prefer_continuous_replication,
        )
        cmir_obj = build_vm_image_cmir(
            manifest,
            target_provider=target,
            user_decisions=req.user_decisions,
        )
        return {
            "use_case": "vm_image",
            "target_provider": target,
            "manifest": manifest,
            "transformation_catalog": manifest.get("transformation_catalog"),
            "compatibility": compat,
            "cmir": cmir_obj.model_dump(),
            "stage_status": stage_status,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{migration_id}/remediate-blocker")
def remediate_migration_job_blocker(
    migration_id: str,
    request: Optional[RemediateBlockerRequest] = None,
):
    """Remediate a compatibility blocker on a migration job and advance to PLAN_READY."""
    req = request or RemediateBlockerRequest()
    try:
        return migration_orchestrator.remediate_compatibility_blocker(
            migration_id=migration_id,
            action=req.action,
            operator_id=req.operator_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/use-case-2/devices")
def get_live_storage_devices(agent_id: Optional[str] = Query(None)):
    """Query live block devices and partitions from host or enrolled agent."""
    return probe_live_storage_devices(agent_id=agent_id)


@router.post("/use-case-2/probe-devices")
def trigger_probe_devices(agent_id: Optional[str] = Query(None)):
    """Trigger an on-demand probe of host storage devices."""
    return probe_live_storage_devices(agent_id=agent_id)


@router.post("/use-case-2/capture-live")
def capture_live_host_use_case_2(
    http_request: Request,
    request: Optional[ImageInspectRequest] = None,
):
    """Capture live host operating system and prepare disk image for cloud provisioning."""
    req = request or ImageInspectRequest()
    req.capture_live_host = True
    req.source_type = "live_server"
    return inspect_use_case_2_vm_image(http_request=http_request, request=req)


@router.post("/use-case-2/migrate")
def orchestrate_use_case_2_migration(request: Optional[ImageInspectRequest] = None):
    """Create and plan a 13-stage OS/VM Image migration job in the orchestrator."""
    req = request or ImageInspectRequest()
    target = validate_target_provider(req.target_provider)
    try:
        source_type = "live_server" if req.capture_live_host else req.source_type
        name_prefix = "Live Host OS Migration" if req.capture_live_host else "VM Image Migration"
        return migration_orchestrator.create_migration(
            name=f"{name_prefix} -> {target.upper()}",
            use_case="vm_image",
            target_provider=target,
            source_config={
                "image_path": req.image_path,
                "manifest_override": req.manifest_override,
                "require_live_memory_state": req.require_live_memory_state,
                "require_authentic_binary": req.require_authentic_binary,
                "source_type": source_type,
                "prefer_continuous_replication": req.prefer_continuous_replication,
                "capture_live_host": req.capture_live_host,
                "output_format": req.output_format,
                "agent_id": req.agent_id,
                "user_decisions": req.user_decisions,
            },
            auto_assess_and_plan=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/probe-uc2-validation")
def probe_uc2_validation(ip: str = Query(..., description="Public IP of deployed Case 2 EC2 instance")):
    """Probe /health and /files on the deployed UC2 EC2 telemetry server side."""
    clean_ip = sanitize_probe_host(ip)
    tcp_fn = resolve_facade_probe_fn("_probe_tcp_port", probe_tcp_port)
    ssh_ok = tcp_fn(clean_ip, 22, timeout=2.0)
    health_res = fetch_json_endpoint(f"http://{clean_ip}:3000/health", timeout=3.5)
    if not health_res["ok"]:
        health_res = fetch_json_endpoint(f"http://{clean_ip}:8000/health", timeout=3.0)
    files_res = fetch_json_endpoint(f"http://{clean_ip}:3000/files", timeout=3.5)

    hdata = health_res.get("data") or {}
    fdata = files_res.get("data") or {}
    live_files = fdata.get("files") or hdata.get("uploaded_files") or []
    manifest_files = ((hdata.get("captured_os_manifest") or {}).get("uploaded_os_files") or [])
    expected_count = len(manifest_files) if manifest_files else len(live_files)
    synced_count = len(live_files)
    ebs_mirrored_count = sum(1 for f in live_files if f.get("ebs_mirrored"))
    ebs_mounted = bool(hdata.get("ebs_mounted") or ebs_mirrored_count > 0)

    all_ok = bool(
        health_res["ok"]
        and files_res["ok"]
        and synced_count > 0
        and (expected_count == 0 or synced_count >= expected_count)
    )

    return {
        "ip": clean_ip,
        "ssh_open": ssh_ok,
        "all_ok": all_ok,
        "checks": {
            "health": {
                "ok": health_res["ok"],
                "http_status": health_res["http_status"],
                "latency_ms": health_res["latency_ms"],
                "url": f"http://{clean_ip}:3000/health",
                "error": health_res["error"],
            },
            "files": {
                "ok": files_res["ok"],
                "http_status": files_res["http_status"],
                "latency_ms": files_res["latency_ms"],
                "url": f"http://{clean_ip}:3000/files",
                "synced_count": synced_count,
                "expected_count": expected_count,
                "ebs_mirrored_count": ebs_mirrored_count,
                "error": files_res["error"],
            },
            "ebs": {
                "mounted": ebs_mounted,
                "mount_dir": fdata.get("ebs_mount_dir") or hdata.get("ebs_mount_dir") or "/mnt/cloudmove_ebs/rootfs",
                "rootfs_dir": fdata.get("rootfs_dir") or hdata.get("rootfs_dir") or "/opt/cloudmove/os_capture/rootfs",
            },
        },
        "telemetry": hdata,
        "files_payload": fdata,
    }


@router.get("/probe-uc2-file")
def probe_uc2_file(
    ip: str = Query(..., description="Public IP of deployed Case 2 EC2 instance"),
    path: str = Query(..., description="Relative file path inside /opt/cloudmove/os_capture/rootfs/"),
):
    """Fetch captured file text content safely from the deployed EC2 telemetry server."""
    clean_rel, raw = fetch_uc2_ec2_file(ip=ip, path=path, endpoint="/files/view", timeout_sec=6.0)
    return {
        "ok": True,
        "path": clean_rel,
        "origin_path": f"/{clean_rel}",
        "rootfs_path": f"/opt/cloudmove/os_capture/rootfs/{clean_rel}",
        "ebs_path": f"/mnt/cloudmove_ebs/rootfs/{clean_rel}",
        "size_bytes": len(raw),
        "content": raw.decode("utf-8", errors="replace"),
    }


@router.get("/probe-uc2-file-raw")
def probe_uc2_file_raw(
    ip: str = Query(..., description="Public IP of deployed Case 2 EC2 instance"),
    path: str = Query(..., description="Relative file path inside /opt/cloudmove/os_capture/rootfs/"),
):
    """Serve raw UTF-8 view of a migrated Case 2 file over HTTPS."""
    _, raw = fetch_uc2_ec2_file(ip=ip, path=path, endpoint="/files/view", timeout_sec=8.0)
    return PlainTextResponse(content=raw.decode("utf-8", errors="replace"))


@router.get("/probe-uc2-bundle")
def probe_uc2_bundle(ip: str = Query(..., description="Public IP of deployed Case 2 EC2 instance")):
    """Download os_real_files_bundle.tar.gz directly from the deployed EC2 instance."""
    clean_ip = sanitize_probe_host(ip)
    target_url = f"http://{clean_ip}:3000/bundle.tar.gz"
    try:
        req = urllib.request.Request(target_url, headers={"User-Agent": "CloudMove-UC2-Bundle/1.0"})
        with open_url_no_redirects(req, timeout=10.0) as resp:
            return Response(
                content=resp.read(),
                media_type="application/gzip",
                headers={"Content-Disposition": 'attachment; filename="os_real_files_bundle.tar.gz"'},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo descargar bundle.tar.gz desde {clean_ip}: {exc}")


@router.get("/probe-uc2-file-download")
def probe_uc2_file_download(
    ip: str = Query(..., description="Public IP of deployed Case 2 EC2 instance"),
    path: str = Query(..., description="Relative file path inside /opt/cloudmove/os_capture/rootfs/"),
):
    """Proxy binary or large file download safely from the deployed Case 2 EC2 instance."""
    clean_rel, raw = fetch_uc2_ec2_file(ip=ip, path=path, endpoint="/files/download", timeout_sec=15.0)
    fname = Path(clean_rel).name or "migrated-file"
    return Response(
        content=raw,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/uc2-stage/init")
def init_uc2_stage_session(req: Uc2StageInitRequest):
    """Initialize a Case 2 persistent file staging session."""
    from app.migration.uc2_staging import create_or_get_stage, get_stage_metadata

    try:
        meta = create_or_get_stage(
            stage_id=req.stage_id,
            selected_paths=req.selected_paths,
            agent_id=req.agent_id,
            migration_id=req.migration_id,
            source_type="browser_upload",
        )
        return get_stage_metadata(meta["stage_id"], include_secrets=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/uc2-stage/{stage_id}/upload-files")
def upload_uc2_stage_files_batch(stage_id: str, req: Uc2BrowserBatchRequest):
    """Receive real files from browser folder picker in bounded JSON/base64 batches."""
    from app.migration.uc2_staging import save_browser_uploaded_batch

    rel_list: List[str] = []
    contents: List[bytes] = []
    for item in req.files:
        try:
            raw = base64.b64decode(item.content_b64.encode("ascii"), validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Contenido base64 inválido para '{item.rel_path}'.")
        rel_list.append(item.rel_path)
        contents.append(raw)

    try:
        return save_browser_uploaded_batch(
            stage_id=stage_id,
            rel_paths=rel_list,
            contents=contents,
            selected_paths=req.selected_paths,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/uc2-stage/{stage_id}/commit")
def commit_uc2_browser_stage(
    stage_id: str,
    http_request: Request,
    req: Optional[Uc2StageCommitRequest] = None,
):
    """Build bundle.tar.gz from uploaded files, bind to job, and optionally push to live EC2."""
    from app.migration.uc2_staging import (
        build_stage_download_url,
        finalize_browser_stage,
        get_stage_metadata,
        push_stage_to_ec2,
    )

    body = req or Uc2StageCommitRequest()
    try:
        meta = finalize_browser_stage(
            stage_id=stage_id,
            selected_paths=body.selected_paths,
            migration_id=body.migration_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    api_url = infer_public_api_url(http_request)
    if body.migration_id:
        try:
            migration_orchestrator.refresh_uc2_stage_binding(
                body.migration_id,
                stage_meta=meta,
                public_api_url=api_url,
            )
        except Exception:
            pass

    ec2_sync = None
    if body.ec2_ip:
        clean_ip = sanitize_probe_host(body.ec2_ip)
        dl_url = build_stage_download_url(api_url, meta)
        ec2_sync = push_stage_to_ec2(clean_ip, dl_url, sync_token=meta.get("sync_token"))

    clean = get_stage_metadata(stage_id, include_secrets=False) or {}
    clean["ec2_sync"] = ec2_sync
    return clean


@router.get("/uc2-stage/status")
def get_uc2_stage_status(
    http_request: Request,
    stage_id: Optional[str] = Query(None),
    migration_id: Optional[str] = Query(None),
    paths: Optional[str] = Query(None, description="JSON array or comma-separated selected paths"),
):
    """Check staging readiness + connected remote agent capabilities."""
    from app.migration.uc2_staging import find_ready_stage, get_stage_metadata

    selected_paths: List[str] = []
    if paths:
        try:
            parsed = json.loads(paths)
            selected_paths = [str(p) for p in parsed] if isinstance(parsed, list) else []
        except Exception:
            selected_paths = [p.strip() for p in paths.split(",") if p.strip()]

    db = get_transactional_db()
    remote_agents = [a for a in db.list_agents(include_revoked=False) if not is_control_plane_agent(a)]
    online = next((a for a in remote_agents if a.get("status") == "ONLINE"), remote_agents[0] if remote_agents else None)
    ag_ver = str((online or {}).get("version") or "2.1.0")
    supports_staging = bool(online and is_version_gte(ag_ver, LATEST_AGENT_VERSION))

    stage = None
    if stage_id:
        stage = get_stage_metadata(stage_id, include_secrets=False)
    if not stage or stage.get("status") != "READY":
        ready = find_ready_stage(
            stage_id=stage_id,
            migration_id=migration_id,
            agent_id=(online or {}).get("agent_id"),
            selected_paths=selected_paths,
            include_secrets=False,
        )
        if ready:
            stage = ready

    api_url = infer_public_api_url(http_request)
    return {
        "agent_connected": bool(online and online.get("status") == "ONLINE"),
        "agent_id": (online or {}).get("agent_id"),
        "agent_hostname": (online or {}).get("hostname"),
        "agent_version": ag_ver,
        "latest_agent_version": LATEST_AGENT_VERSION,
        "supports_file_staging": supports_staging,
        "upgrade_command_linux": f"curl -sSL {api_url}/api/v1/agents/install.sh | sudo bash -s -- --upgrade",
        "stage": stage,
        "ready": bool(stage and stage.get("status") == "READY"),
    }


@router.post("/uc2-stage/dispatch-agent")
def dispatch_uc2_agent_stage(req: Uc2DispatchAgentStageRequest, http_request: Request):
    """Request enrolled remote agent to pack and upload selected folders/files to staging."""
    from app.migration.uc2_staging import ensure_uc2_selected_paths_staged

    if not req.selected_paths:
        raise HTTPException(status_code=400, detail="Debes seleccionar al menos una carpeta o archivo.")

    res = ensure_uc2_selected_paths_staged(
        selected_paths=req.selected_paths,
        agent_id=req.agent_id,
        migration_id=req.migration_id,
        public_api_url=infer_public_api_url(http_request),
    )
    if res.get("status") == "no_online_agent":
        raise HTTPException(status_code=404, detail="No hay ningún agente remoto ONLINE conectado.")
    if res.get("upgrade_required"):
        res["message"] = (
            f"El agente instalado usa v{res.get('agent_version', '2.1.0')}. "
            f"Actualízalo a v{res.get('latest_agent_version', '2.2.0')} con el comando sugerido o sube la carpeta directamente desde tu navegador."
        )
    return res


@router.get("/uc2-stage/{stage_id}/bundle.tar.gz")
def download_uc2_staged_bundle(stage_id: str, token: str = Query(...)):
    """Stream staged Case 2 archive to EC2 instances authenticating with per-stage token."""
    from app.migration.uc2_staging import verify_stage_download_token

    verified = verify_stage_download_token(stage_id, token)
    if not verified:
        raise HTTPException(status_code=403, detail="Token de descarga inválido o paquete no disponible.")
    bundle_path, _ = verified
    return FileResponse(path=str(bundle_path), media_type="application/gzip", filename=f"{stage_id}.tar.gz")
