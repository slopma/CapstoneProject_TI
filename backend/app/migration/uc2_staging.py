"""
Case 2 (`vm_image`) persistent user-file staging manager (`uc2_staging.py`).

Handles safe, chunked staging of real user-selected folders and files (such as
`/home/<user>/Descargas`) uploaded either by the enrolled CloudMove agent or
directly from the operator browser session, overcoming AWS EC2's 16 KB UserData
limit while keeping transfers bounded, verifiable by SHA-256, and protected by
constant-time per-stage tokens.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import tarfile
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.text_utils import utc_now_iso as _utc_now
from app.persistence.transactional_db import get_transactional_db


DEFAULT_MAX_STAGE_BYTES = 15 * 1024 * 1024 * 1024  # 15 GiB safety limit per stage archive
MIN_FREE_DISK_BYTES = 4 * 1024 * 1024 * 1024  # Keep at least 4 GiB free on CloudMove host
STAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,80}$")

_STAGE_LOCK = threading.RLock()


def _ensure_staging_base() -> Path:
    base = get_staging_base_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_dynamic_stage_budget_mb() -> int:
    """Compute safe staging budget (in MiB) based on available host storage."""
    try:
        free_b = shutil.disk_usage(_ensure_staging_base()).free
        usable_mb = max(512, int((free_b - MIN_FREE_DISK_BYTES) // (1024 * 1024)))
        return min(14 * 1024, usable_mb)
    except Exception:
        return 4096


def prune_old_stages(keep_latest: int = 3, protected_stage_id: Optional[str] = None) -> None:
    """Remove stale staging directories when creating new uploads to prevent disk bloat."""
    try:
        base = _ensure_staging_base()
        entries = [d for d in base.iterdir() if d.is_dir()]
        entries.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        for idx, d in enumerate(entries):
            if idx < keep_latest or (protected_stage_id and d.name == protected_stage_id):
                continue
            meta = _read_meta(d.name)
            if meta and meta.get("status") == "UPLOADING":
                continue
            shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


def get_staging_base_dir() -> Path:
    """Resolve persistent staging directory alongside transactional DB storage."""
    app_data = Path("/app/data")
    if app_data.is_dir() and os.access(app_data, os.W_OK):
        base = app_data / "uc2_staged"
    else:
        db = get_transactional_db()
        base = Path(db.db_path).resolve().parent / "uc2_staged"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _validate_stage_id(stage_id: str) -> str:
    clean = str(stage_id or "").strip()
    if not STAGE_ID_RE.match(clean):
        raise ValueError("Identificador stage_id inválido.")
    return clean


def _safe_rel_path(raw_path: str) -> Optional[str]:
    """Normalize and validate relative POSIX path without traversal components."""
    clean = str(raw_path or "").replace("\\", "/").lstrip("/")
    if not clean or "\x00" in clean or clean.startswith("/"):
        return None
    parts = [p for p in clean.split("/") if p and p != "."]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _stage_dir(stage_id: str) -> Path:
    clean_id = _validate_stage_id(stage_id)
    d = get_staging_base_dir() / clean_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(stage_id: str) -> Path:
    return _stage_dir(stage_id) / "meta.json"


def _read_meta(stage_id: str) -> Optional[Dict[str, Any]]:
    mp = _meta_path(stage_id)
    if not mp.is_file():
        return None
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_meta(stage_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    meta["updated_at"] = _utc_now()
    _meta_path(stage_id).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return meta


def create_or_get_stage(
    stage_id: Optional[str] = None,
    selected_paths: Optional[List[str]] = None,
    agent_id: Optional[str] = None,
    migration_id: Optional[str] = None,
    source_type: str = "agent",
    sync_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Initialize or update metadata for a Case 2 file staging session."""
    clean_id = (
        _validate_stage_id(stage_id)
        if stage_id
        else f"uc2stg-{secrets.token_hex(8)}"
    )
    norm_paths = [
        str(p).strip() for p in (selected_paths or []) if str(p).strip()
    ][:100]

    with _STAGE_LOCK:
        prune_old_stages(keep_latest=3, protected_stage_id=clean_id)
        existing = _read_meta(clean_id)
        if existing:
            if norm_paths:
                existing["selected_paths"] = norm_paths
            if agent_id:
                existing["agent_id"] = agent_id
            if migration_id:
                existing["migration_id"] = migration_id
            if sync_token:
                existing["sync_token"] = sync_token
            return _write_meta(clean_id, existing)

        now = _utc_now()
        meta: Dict[str, Any] = {
            "stage_id": clean_id,
            "agent_id": agent_id,
            "migration_id": migration_id,
            "source_type": source_type,
            "status": "PENDING",
            "selected_paths": norm_paths,
            "download_token": secrets.token_urlsafe(24),
            "sync_token": sync_token or secrets.token_urlsafe(18),
            "files": [],
            "skipped_files": [],
            "files_count": 0,
            "total_uncompressed_bytes": 0,
            "bundle_size_bytes": 0,
            "bundle_sha256": None,
            "created_at": now,
            "updated_at": now,
        }
        return _write_meta(clean_id, meta)


def save_stage_chunk(
    stage_id: str,
    chunk_index: int,
    total_chunks: int,
    raw_bytes: bytes,
    selected_paths: Optional[List[str]] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist one binary chunk of a `.tar.gz` bundle during streaming upload."""
    if chunk_index < 0 or total_chunks < 1 or chunk_index >= total_chunks:
        raise ValueError("Índice de fragmento (chunk) fuera de rango.")
    if len(raw_bytes) > 64 * 1024 * 1024:
        raise ValueError("El fragmento supera el tamaño máximo de 64 MiB.")

    with _STAGE_LOCK:
        meta = create_or_get_stage(
            stage_id=stage_id,
            selected_paths=selected_paths,
            agent_id=agent_id,
        )
        chunks_dir = _stage_dir(stage_id) / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        part_file = chunks_dir / f"part_{chunk_index:06d}.bin"
        part_file.write_bytes(raw_bytes)
        meta["status"] = "UPLOADING"
        meta["expected_chunks"] = total_chunks
        meta["received_chunks"] = len(list(chunks_dir.glob("part_*.bin")))
        return _write_meta(stage_id, meta)


def _inspect_and_validate_tarball(bundle_path: Path) -> Tuple[List[Dict[str, Any]], int]:
    """Validate tar members against path traversal and collect safe file listing."""
    files: List[Dict[str, Any]] = []
    total_uncompressed = 0
    with tarfile.open(bundle_path, "r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            safe_rel = _safe_rel_path(member.name)
            if not safe_rel:
                raise ValueError(f"Entrada tar insegura rechazada: {member.name}")
            total_uncompressed += int(member.size or 0)
            if total_uncompressed > DEFAULT_MAX_STAGE_BYTES:
                raise ValueError("El archivo empaquetado excede la cuota máxima de staging.")
            files.append({
                "path": safe_rel,
                "origin_path": f"/{safe_rel}",
                "size_bytes": int(member.size or 0),
                "is_dir": False,
            })
    return files, total_uncompressed


def commit_stage_archive(
    stage_id: str,
    total_chunks: int,
    selected_paths: Optional[List[str]] = None,
    agent_id: Optional[str] = None,
    migration_id: Optional[str] = None,
    expected_sha256: Optional[str] = None,
    skipped_files: Optional[List[Dict[str, Any]]] = None,
    source_type: str = "agent",
) -> Dict[str, Any]:
    """Assemble uploaded tar.gz chunks into final validated bundle & READY metadata."""
    with _STAGE_LOCK:
        meta = create_or_get_stage(
            stage_id=stage_id,
            selected_paths=selected_paths,
            agent_id=agent_id,
            migration_id=migration_id,
            source_type=source_type,
        )
        sdir = _stage_dir(stage_id)
        chunks_dir = sdir / "chunks"
        bundle_path = sdir / "bundle.tar.gz"
        tmp_bundle = sdir / "bundle.tar.gz.tmp"

        hasher = hashlib.sha256()
        total_written = 0
        with tmp_bundle.open("wb") as out_f:
            for idx in range(total_chunks):
                part = chunks_dir / f"part_{idx:06d}.bin"
                if not part.is_file():
                    raise ValueError(f"Falta el fragmento #{idx} del paquete '{stage_id}'.")
                data = part.read_bytes()
                total_written += len(data)
                if total_written > DEFAULT_MAX_STAGE_BYTES:
                    raise ValueError("El paquete comprimido excede la cuota máxima de staging.")
                hasher.update(data)
                out_f.write(data)

        actual_sha = hasher.hexdigest()
        if expected_sha256 and actual_sha.lower() != expected_sha256.lower().strip():
            tmp_bundle.unlink(missing_ok=True)
            raise ValueError("Checksum SHA-256 del bundle cargado no coincide con el origen.")

        files_list, uncompressed_total = _inspect_and_validate_tarball(tmp_bundle)
        tmp_bundle.replace(bundle_path)
        shutil.rmtree(chunks_dir, ignore_errors=True)

        meta["status"] = "READY"
        meta["files"] = files_list[:2500]
        meta["files_count"] = len(files_list)
        meta["skipped_files"] = (skipped_files or [])[:500]
        meta["total_uncompressed_bytes"] = uncompressed_total
        meta["bundle_size_bytes"] = total_written
        meta["bundle_sha256"] = actual_sha
        return _write_meta(stage_id, meta)


def save_browser_uploaded_batch(
    stage_id: str,
    rel_paths: List[str],
    contents: List[bytes],
    selected_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Store a batch of real files uploaded directly from the browser folder picker."""
    if len(rel_paths) != len(contents):
        raise ValueError("La cantidad de rutas y archivos no coincide.")

    with _STAGE_LOCK:
        meta = create_or_get_stage(
            stage_id=stage_id,
            selected_paths=selected_paths,
            source_type="browser_upload",
        )
        root_dir = _stage_dir(stage_id) / "staged_root"
        root_dir.mkdir(parents=True, exist_ok=True)
        root_resolved = root_dir.resolve()

        saved_count = 0
        for raw_rel, blob in zip(rel_paths, contents):
            safe_rel = _safe_rel_path(raw_rel)
            if not safe_rel:
                continue
            dest = (root_dir / safe_rel).resolve()
            if not str(dest).startswith(str(root_resolved) + "/") and dest != root_resolved:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)
            saved_count += 1

        meta["status"] = "UPLOADING"
        meta["saved_files_count"] = int(meta.get("saved_files_count") or 0) + saved_count
        return _write_meta(stage_id, meta)


def finalize_browser_stage(
    stage_id: str,
    selected_paths: Optional[List[str]] = None,
    migration_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compress all browser-uploaded files under `staged_root` into `bundle.tar.gz`."""
    with _STAGE_LOCK:
        meta = create_or_get_stage(
            stage_id=stage_id,
            selected_paths=selected_paths,
            migration_id=migration_id,
            source_type="browser_upload",
        )
        sdir = _stage_dir(stage_id)
        root_dir = sdir / "staged_root"
        bundle_path = sdir / "bundle.tar.gz"
        tmp_bundle = sdir / "bundle.tar.gz.tmp"

        files_meta: List[Dict[str, Any]] = []
        uncompressed_total = 0

        if root_dir.is_dir():
            all_files = sorted(p for p in root_dir.rglob("*") if p.is_file())
        else:
            all_files = []

        # Build concise manifest inside tar documenting uploaded paths
        with tarfile.open(tmp_bundle, "w:gz") as tf:
            for fpath in all_files:
                rel = fpath.relative_to(root_dir).as_posix()
                sz = fpath.stat().st_size
                if uncompressed_total + sz > DEFAULT_MAX_STAGE_BYTES:
                    break
                uncompressed_total += sz
                tf.add(fpath, arcname=rel)
                files_meta.append({
                    "path": rel,
                    "origin_path": f"/{rel}",
                    "size_bytes": sz,
                    "is_dir": False,
                })

            inv_payload = json.dumps(
                {
                    "selected_paths": meta.get("selected_paths") or [],
                    "files_count": len(files_meta),
                    "total_bytes": uncompressed_total,
                    "staged_at": _utc_now(),
                    "files": [f["path"] for f in files_meta[:500]],
                },
                indent=2,
                ensure_ascii=False,
            ).encode("utf-8")
            ti = tarfile.TarInfo("var/log/cloudmove_selected_paths_inventory.json")
            ti.size = len(inv_payload)
            tf.addfile(ti, io.BytesIO(inv_payload))

        bundle_bytes = tmp_bundle.stat().st_size
        bundle_sha = hashlib.sha256(tmp_bundle.read_bytes()).hexdigest()
        tmp_bundle.replace(bundle_path)
        shutil.rmtree(root_dir, ignore_errors=True)

        meta["status"] = "READY"
        meta["files"] = files_meta[:2500]
        meta["files_count"] = len(files_meta)
        meta["total_uncompressed_bytes"] = uncompressed_total
        meta["bundle_size_bytes"] = bundle_bytes
        meta["bundle_sha256"] = bundle_sha
        return _write_meta(stage_id, meta)


def link_stage_to_migration(stage_id: str, migration_id: str) -> Optional[Dict[str, Any]]:
    """Associate a staged bundle with a migration job."""
    with _STAGE_LOCK:
        meta = _read_meta(stage_id)
        if not meta:
            return None
        meta["migration_id"] = migration_id
        return _write_meta(stage_id, meta)


def get_stage_metadata(stage_id: str, include_secrets: bool = False) -> Optional[Dict[str, Any]]:
    """Return stage metadata, redacting tokens unless explicitly requested server-side."""
    meta = _read_meta(stage_id)
    if not meta:
        return None
    if include_secrets:
        return meta
    clean = dict(meta)
    clean.pop("download_token", None)
    clean.pop("sync_token", None)
    return clean


def _paths_cover(stage_paths: Iterable[str], requested_paths: Iterable[str]) -> bool:
    s_norm = [str(p).strip().rstrip("/") for p in stage_paths if str(p).strip()]
    r_norm = [str(p).strip().rstrip("/") for p in requested_paths if str(p).strip()]
    if not s_norm or not r_norm:
        return False
    return all(
        any(st == req or req.startswith(f"{st}/") for st in s_norm)
        for req in r_norm
    )


def find_ready_stage(
    stage_id: Optional[str] = None,
    migration_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    selected_paths: Optional[List[str]] = None,
    include_secrets: bool = False,
) -> Optional[Dict[str, Any]]:
    """Locate the newest READY staged bundle matching stage_id, migration_id, or selected_paths."""
    base = _ensure_staging_base()
    if stage_id:
        meta = _read_meta(stage_id)
        if meta and meta.get("status") == "READY" and (_stage_dir(stage_id) / "bundle.tar.gz").is_file():
            if not selected_paths or _paths_cover(meta.get("selected_paths") or [], selected_paths):
                return meta if include_secrets else get_stage_metadata(stage_id, include_secrets=False)

    candidates: List[Dict[str, Any]] = []
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        meta = _read_meta(entry.name)
        if not meta or meta.get("status") != "READY":
            continue
        if not (entry / "bundle.tar.gz").is_file():
            continue
        candidates.append(meta)

    candidates.sort(key=lambda m: m.get("updated_at") or "", reverse=True)

    chosen: Optional[Dict[str, Any]] = None
    if migration_id:
        chosen = next(
            (
                m for m in candidates
                if m.get("migration_id") == migration_id
                and (not selected_paths or _paths_cover(m.get("selected_paths") or [], selected_paths))
            ),
            None,
        )
    if not chosen and selected_paths:
        chosen = next(
            (
                m for m in candidates
                if _paths_cover(m.get("selected_paths") or [], selected_paths)
                and (not agent_id or not m.get("agent_id") or m.get("agent_id") == agent_id)
            ),
            None,
        )
    if not chosen:
        return None
    return chosen if include_secrets else get_stage_metadata(chosen["stage_id"], include_secrets=False)


def verify_stage_download_token(stage_id: str, token: str) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """Validate download token in constant time and return `(bundle_path, meta)`."""
    meta = _read_meta(stage_id)
    if not meta or meta.get("status") != "READY":
        return None
    expected = str(meta.get("download_token") or "")
    if not expected or not token or not hmac.compare_digest(expected, str(token)):
        return None
    bundle_path = _stage_dir(stage_id) / "bundle.tar.gz"
    if not bundle_path.is_file():
        return None
    return bundle_path, meta


def build_stage_download_url(public_api_url: str, stage_meta: Dict[str, Any]) -> str:
    """Construct the HTTPS pull URL embedded in EC2 user_data or sync requests."""
    base = str(public_api_url or "").rstrip("/")
    sid = stage_meta["stage_id"]
    tok = stage_meta["download_token"]
    return f"{base}/api/v1/migration/uc2-stage/{sid}/bundle.tar.gz?token={tok}"


def push_stage_to_ec2(
    ec2_host: str,
    download_url: str,
    sync_token: Optional[str] = None,
    timeout: float = 12.0,
) -> Dict[str, Any]:
    """Trigger an already-running Case 2 EC2 instance to pull and extract a staged bundle."""
    payload = json.dumps({"bundle_url": download_url}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "CloudMove-UC2-Sync/1.0",
    }
    if sync_token:
        headers["X-CloudMove-Sync-Token"] = sync_token

    last_err = ""
    for port in (3000, 8000):
        url = f"http://{ec2_host}:{port}/sync-stage"
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return {
                    "ok": 200 <= resp.status < 300,
                    "http_status": resp.status,
                    "response": json.loads(raw) if raw.startswith("{") else {"raw": raw},
                }
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
        except Exception as exc:
            last_err = str(exc)

    return {
        "ok": False,
        "error": last_err or "El endpoint /sync-stage aún no está habilitado en la instancia EC2 actual (requiere re-apply).",
    }


def _find_active_remote_agent(preferred_agent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return ONLINE remote host agent (excluding CloudMove server itself)."""
    from app.core.security import is_control_plane_agent

    db = get_transactional_db()
    remote = [
        a for a in db.list_agents(include_revoked=False)
        if a.get("status") == "ONLINE"
        and not is_control_plane_agent(a)
    ]
    if not remote:
        return None
    if preferred_agent_id:
        match = next((a for a in remote if a.get("agent_id") == preferred_agent_id), None)
        if match:
            return match
    return remote[0]


def ensure_uc2_selected_paths_staged(
    selected_paths: Optional[List[str]],
    agent_id: Optional[str] = None,
    migration_id: Optional[str] = None,
    stage_id: Optional[str] = None,
    public_api_url: str = "",
) -> Dict[str, Any]:
    """
    Ensure user-selected folders/files are staged cleanly whenever Case 2 inspect or plan runs.
    Dispatches an automatic agent staging task if not yet staged and agent supports v2.2.0+.
    """
    clean_paths = [str(p).strip() for p in (selected_paths or []) if str(p).strip()]
    if not clean_paths:
        return {"status": "no_paths"}

    agent = _find_active_remote_agent(agent_id)
    eff_agent_id = (agent or {}).get("agent_id") or agent_id

    ready = find_ready_stage(
        stage_id=stage_id,
        migration_id=migration_id,
        agent_id=eff_agent_id,
        selected_paths=clean_paths,
        include_secrets=False,
    )
    if ready:
        if migration_id and ready.get("migration_id") != migration_id:
            link_stage_to_migration(ready["stage_id"], migration_id)
        return {
            "status": "READY",
            "ready": True,
            "stage": ready,
            "agent_id": eff_agent_id,
        }

    if not agent:
        return {"status": "no_online_agent", "ready": False}

    from app.core.agents_catalog import LATEST_AGENT_VERSION, is_version_gte

    ver = str(agent.get("version") or "2.1.0")
    upgrade_cmd = (
        f"curl -sSL {public_api_url.rstrip('/')}/api/v1/agents/install.sh | sudo bash -s -- --upgrade"
        if public_api_url
        else "curl -sSL http://localhost:8000/api/v1/agents/install.sh | sudo bash -s -- --upgrade"
    )
    if not is_version_gte(ver, LATEST_AGENT_VERSION):
        return {
            "status": "upgrade_required",
            "ready": False,
            "upgrade_required": True,
            "agent_id": agent["agent_id"],
            "agent_version": ver,
            "latest_agent_version": LATEST_AGENT_VERSION,
            "upgrade_command_linux": upgrade_cmd,
        }

    # Avoid spamming duplicate PENDING/DISPATCHED staging tasks for the same paths
    db = get_transactional_db()
    with db.transaction(write=False) as conn:
        pending = conn.execute(
            """
            SELECT task_id, parameters_json FROM agent_tasks
            WHERE agent_id = ? AND action = 'stage_selected_paths' AND status IN ('PENDING', 'DISPATCHED')
            """,
            (agent["agent_id"],),
        ).fetchall()
    for row in pending:
        try:
            p = json.loads(row["parameters_json"] or "{}")
            if _paths_cover(p.get("selected_paths") or [], clean_paths):
                return {
                    "status": "PENDING",
                    "ready": False,
                    "dispatched": True,
                    "task_id": row["task_id"],
                    "stage": get_stage_metadata(p.get("stage_id", ""), include_secrets=False),
                    "agent_id": agent["agent_id"],
                }
        except Exception:
            pass

    meta = create_or_get_stage(
        selected_paths=clean_paths,
        agent_id=agent["agent_id"],
        migration_id=migration_id,
        source_type="agent",
    )
    budget_mb = get_dynamic_stage_budget_mb()
    task = db.create_agent_task(
        agent_id=agent["agent_id"],
        action="stage_selected_paths",
        parameters={
            "stage_id": meta["stage_id"],
            "selected_paths": clean_paths,
            "migration_id": migration_id,
            "max_total_mb": budget_mb,
            "per_file_max_mb": 512,
        },
        timeout_seconds=1800,
    )
    return {
        "status": "PENDING",
        "ready": False,
        "dispatched": True,
        "task_id": task["task_id"],
        "stage": get_stage_metadata(meta["stage_id"], include_secrets=False),
        "agent_id": agent["agent_id"],
    }


def dispatch_push_to_ec2(
    ec2_host: str,
    selected_paths: List[str],
    sync_token: str,
    agent_id: Optional[str] = None,
    migration_id: Optional[str] = None,
    max_total_mb: int = 24000,
) -> Optional[Dict[str, Any]]:
    """
    Dispatch direct host-to-EC2 transfer task to v2.2.0+ agent when full folder size exceeds
    CloudMove server staging budget or wasn't yet extracted onto the newly provisioned EC2.
    """
    clean_paths = [str(p).strip() for p in (selected_paths or []) if str(p).strip()]
    if not clean_paths or not ec2_host or not sync_token:
        return None
    agent = _find_active_remote_agent(agent_id)
    if not agent:
        return None
    from app.core.agents_catalog import LATEST_AGENT_VERSION, is_version_gte

    if not is_version_gte(str(agent.get("version") or "2.1.0"), LATEST_AGENT_VERSION):
        return None

    db = get_transactional_db()
    return db.create_agent_task(
        agent_id=agent["agent_id"],
        action="push_selected_paths_to_ec2",
        parameters={
            "stage_id": f"ec2push-{secrets.token_hex(6)}",
            "selected_paths": clean_paths,
            "target_url": f"http://{ec2_host}:3000",
            "sync_token": sync_token,
            "migration_id": migration_id,
            "max_total_mb": max_total_mb,
            "per_file_max_mb": 1024,
        },
        timeout_seconds=3600,
    )
