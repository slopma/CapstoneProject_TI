"""
CloudMove Migration Router Facade (`/api/v1/migration`).

Composes focused bounded-context routers (`migration_jobs`, `migration_uc1`,
`migration_uc2`, `migration_cloud`) while preserving stable facade symbols.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import migration_cloud, migration_jobs, migration_uc1, migration_uc2
from app.api.routers.migration_helpers import (
    fetch_json_endpoint as _fetch_json_endpoint,
    fetch_uc2_ec2_file as _fetch_uc2_ec2_file,
    infer_public_api_url as _infer_public_api_url,
    probe_http_endpoint as _probe_http_endpoint,
    probe_tcp_port as _probe_tcp_port,
    resolve_probe_targets as _resolve_probe_targets,
    sanitize_job_for_export as _sanitize_job_for_export,
    sanitize_probe_host as _sanitize_probe_host,
    sync_job_after_terraform as _sync_job_after_terraform,
    validate_target_provider as _validate_target_provider,
)
from app.migration.orchestrator import migration_orchestrator

router = APIRouter(prefix="/api/v1/migration", tags=["Migration Engine & Orchestrator"])
router.include_router(migration_jobs.router)
router.include_router(migration_uc1.router)
router.include_router(migration_uc2.router)
router.include_router(migration_cloud.router)

__all__ = [
    "router",
    "migration_orchestrator",
    "_validate_target_provider",
    "_sanitize_job_for_export",
    "_infer_public_api_url",
    "_sanitize_probe_host",
    "_probe_tcp_port",
    "_probe_http_endpoint",
    "_fetch_json_endpoint",
    "_resolve_probe_targets",
    "_fetch_uc2_ec2_file",
    "_sync_job_after_terraform",
]
