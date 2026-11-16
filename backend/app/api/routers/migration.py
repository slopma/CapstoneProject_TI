import base64
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import time
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.cmir.normalizer import normalize_inventory
from app.graph.builder import build_graph
from app.dependencies.resolver import resolve_dependencies
from app.dependencies.validator import validate_migration_subgraph
from app.adapters.aws_adapter import AWSAdapter
from app.adapters.gcp_adapter import GCPAdapter
from app.generators.terraform import (
    generate_aws_terraform_files,
    generate_gcp_terraform_files,
)
from app.config import INVENTORY_PATH, AWS_OUTPUT_PATH, GCP_OUTPUT_PATH
from app.migration.orchestrator import migration_orchestrator, SUPPORTED_TARGET_PROVIDERS
from app.migration.app_migrator import (
    inspect_application_source,
    build_application_cmir,
    evaluate_app_migration_viability,
)
from app.migration.image_migrator import (
    inspect_vm_image,
    evaluate_vm_image_compatibility,
    build_vm_image_cmir,
    probe_live_storage_devices,
)
from app.migration.replication_and_import import (
    MACHINE_MIGRATION_COMPATIBILITY_MATRIX,
    select_machine_migration_strategy,
)
from app.persistence.transactional_db import (
    get_transactional_db,
    ConcurrencyConflictError,
    StageLockedError,
)
from app.discovery.connectors import ConnectorError

router = APIRouter(prefix="/api/v1/migration", tags=["Migration Engine & Orchestrator"])


def _validate_target_provider(provider: Optional[str]) -> str:
    clean = str(provider or "aws").lower().strip()
    if clean not in SUPPORTED_TARGET_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Proveedor destino '{provider}' no admitido. "
                "Proveedores destino admitidos exclusivamente: 'aws' y 'gcp'. "
                "Azure queda fuera del alcance funcional de esta versión."
            ),
        )
    return clean


class SelectionRequest(BaseModel):
    resources: List[str] = Field(..., description="IDs of nodes selected for migration")
    target_provider: Optional[str] = Field("aws", description="Target cloud provider: aws | gcp")
    validated_shared_resources: Optional[List[str]] = Field(
        default=None,
        description="Shared dependency IDs explicitly validated for migration",
    )
    include_inferred: bool = Field(
        False,
        description="Whether to include unconfirmed inferred dependencies in migration scope",
    )


class CreateMigrationJobRequest(BaseModel):
    name: Optional[str] = Field(None, description="Human-readable name for the migration")
    use_case: str = Field(..., description="app_source | vm_image")
    target_provider: str = Field("aws", description="aws | gcp")
    target_config: Optional[Dict[str, Any]] = Field(default_factory=dict)
    source_config: Optional[Dict[str, Any]] = Field(default_factory=dict)
    auto_assess_and_plan: bool = Field(True)


class ApproveMigrationJobRequest(BaseModel):
    approved_by: str = Field("architect@cloudmove.local")
    notes: str = Field("Plan, dependencias y prerrequisitos aprobados.")
    validated_shared_resources: Optional[List[str]] = Field(default=None)
    expected_version: Optional[int] = Field(default=None, description="Optimistic concurrency version")


class AdvanceMigrationJobRequest(BaseModel):
    dry_run: bool = Field(True, description="Execute in safe dry-run simulation mode unless live credentials are active")
    simulate_failure: bool = Field(False, description="Simulate a stage error to test failure and retry recovery")
    simulate_startup_failure: bool = Field(False, description="Simulate an application startup failure during testing")
    simulate_health_failure: bool = Field(False, description="Simulate a health check failure blocking cutover")
    failure_reason: str = Field("Fallo simulado en etapa de aprovisionamiento/transferencia")
    operator_id: str = Field("operator@cloudmove.local", description="Operator executing this stage")
    idempotency_key: Optional[str] = Field(default=None, description="Idempotency key to prevent duplicate execution")
    expected_version: Optional[int] = Field(default=None, description="Optimistic concurrency version")


class RollbackOrCancelRequest(BaseModel):
    reason: str = Field("Solicitado por el operador durante validación")
    expected_version: Optional[int] = Field(default=None, description="Optimistic concurrency version")


class MarkIrreversibleRequest(BaseModel):
    operation_reason: str = Field(..., description="Reason why rollback is no longer viable")
    recovery_procedure: Optional[str] = Field(default=None, description="Alternative recovery procedure")


class RemediateBlockerRequest(BaseModel):
    action: str = Field("apply_quiesced_snapshot", description="apply_quiesced_snapshot | switch_continuous_replication")
    operator_id: str = Field("operator@cloudmove.local", description="Operator applying remediation")


class GitHubValidateRequest(BaseModel):
    github_url: str = Field(..., description="Real GitHub repository URL e.g. https://github.com/owner/repo")
    github_token: Optional[str] = Field(None, description="Optional GitHub Personal Access Token")


class AppInspectRequest(BaseModel):
    source_path: Optional[str] = Field(None, description="Local path to application repository or directory")
    inline_files: Optional[Dict[str, str]] = Field(None, description="Optional map of filename -> content")
    runtime_metadata: Optional[Dict[str, Any]] = Field(None)
    app_name: Optional[str] = Field(None)
    target_provider: str = Field("aws", description="aws | gcp")
    deployment_mode: str = Field("vm_rehost", description="vm_rehost | container")
    github_url: Optional[str] = Field(None, description="Real GitHub repository URL e.g. https://github.com/owner/repo")
    github_ref: Optional[str] = Field(None, description="Branch, tag, or commit SHA to pin and analyze")
    github_token: Optional[str] = Field(None, description="Optional GitHub token for private repos or rate limit extension")
    user_decisions: Optional[Dict[str, str]] = Field(None, description="User choices mapping discovered GitHub items to target cloud transformations")


class UpdateArchitectureDecisionsRequest(BaseModel):
    user_decisions: Dict[str, str] = Field(default_factory=dict, description="User choices mapping discovered GitHub items to target cloud resources")


class ImageInspectRequest(BaseModel):
    image_path: Optional[str] = Field(None, description="Path to VMDK, VHD, VHDX, QCOW2, RAW, OVA, OVF")
    manifest_override: Optional[Dict[str, Any]] = Field(None)
    target_provider: str = Field("aws", description="aws | gcp")
    require_live_memory_state: bool = Field(False)
    require_authentic_binary: bool = Field(False)
    source_type: str = Field("disk_image", description="disk_image | live_machine | live_server")
    prefer_continuous_replication: bool = Field(False)
    capture_live_host: bool = Field(False, description="Capture live host operating system where CloudMove/agent runs")
    output_format: str = Field("QCOW2", description="QCOW2 | RAW | VMDK")
    agent_id: Optional[str] = Field(None, description="Enrolled agent identifier if capturing remotely")
    user_decisions: Optional[Dict[str, str]] = Field(None, description="User choices for EBS volume sizing, compute mode, instance type, and SG ports")


def _load_cmir():
    if not INVENTORY_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Inventory file not found at {INVENTORY_PATH}")
    with open(INVENTORY_PATH, "r", encoding="utf-8") as file:
        inventory = json.load(file)
    return normalize_inventory(inventory)


@router.get("/providers")
def get_supported_providers():
    """Return supported target providers (exclusively AWS and GCP) and their capabilities."""
    aws = AWSAdapter()
    gcp = GCPAdapter()
    return {
        "supported_providers": ["aws", "gcp"],
        "excluded_providers": ["azure"],
        "providers": {
            "aws": {
                "config": aws.validate_target_config({}),
                "prerequisites": aws.check_permissions_and_prerequisites({}),
            },
            "gcp": {
                "config": gcp.validate_target_config({}),
                "prerequisites": gcp.check_permissions_and_prerequisites({}),
            },
        },
    }


@router.post("/dependencies")
def get_migration_dependencies(request: SelectionRequest):
    if not request.resources:
        raise HTTPException(status_code=400, detail="Debe seleccionar al menos un recurso o nivel jerárquico.")

    cmir = _load_cmir()
    graph = build_graph(cmir)

    dep_analysis = resolve_dependencies(
        graph,
        request.resources,
        validated_shared_resources=request.validated_shared_resources,
        include_inferred=request.include_inferred,
    )
    return dep_analysis


@router.post("/validate")
def validate_migration(request: SelectionRequest):
    if not request.resources:
        raise HTTPException(status_code=400, detail="Debe seleccionar al menos un recurso para validar.")

    target = _validate_target_provider(request.target_provider)
    cmir = _load_cmir()
    graph = build_graph(cmir)
    dep_analysis = resolve_dependencies(
        graph,
        request.resources,
        validated_shared_resources=request.validated_shared_resources,
        include_inferred=request.include_inferred,
    )

    selected_ids = dep_analysis["auto_migratable_resources"]
    selected_nodes = [res for res in cmir.resources if res.id in selected_ids]

    sub_cmir = cmir.model_copy(
        update={
            "resources": selected_nodes,
            "relationships": [
                rel for rel in cmir.relationships
                if rel.source in selected_ids and rel.target in selected_ids
            ],
        }
    )

    validation_result = validate_migration_subgraph(
        sub_cmir,
        dep_analysis,
        target_provider=target,
    )
    return validation_result


@router.post("/generate")
def generate_migration_iac(request: SelectionRequest):
    if not request.resources:
        raise HTTPException(status_code=400, detail="Debe seleccionar al menos un recurso para migrar.")

    target = _validate_target_provider(request.target_provider)
    cmir = _load_cmir()
    graph = build_graph(cmir)

    dep_analysis = resolve_dependencies(
        graph,
        request.resources,
        validated_shared_resources=request.validated_shared_resources,
        include_inferred=request.include_inferred,
    )
    # Use auto_migratable_resources so unvalidated shared dependencies are not auto-migrated without validation
    migratable_ids = dep_analysis["auto_migratable_resources"]

    selected_nodes = [res for res in cmir.resources if res.id in migratable_ids]
    sub_cmir = cmir.model_copy(
        update={
            "resources": selected_nodes,
            "relationships": [
                rel for rel in cmir.relationships
                if rel.source in migratable_ids and rel.target in migratable_ids
            ],
        }
    )

    validation = validate_migration_subgraph(sub_cmir, dep_analysis, target_provider=target)
    if not validation["can_generate"]:
        return {
            "error": {
                "code": "VALIDATION_FAILED",
                "message": "La validación previa a la migración falló.",
                "details": validation["errors"],
            }
        }

    if target == "aws":
        adapter = AWSAdapter()
        translated_resources = adapter.translate_cmir(sub_cmir)
        files_map = generate_aws_terraform_files(translated_resources)
        output_path = AWS_OUTPUT_PATH
        code = files_map["main.tf"]
    elif target == "gcp":
        adapter = GCPAdapter()
        translated_resources = adapter.translate_cmir(sub_cmir)
        files_map = generate_gcp_terraform_files(translated_resources)
        output_path = GCP_OUTPUT_PATH
        code = files_map["main.tf"]
    else:
        raise HTTPException(status_code=400, detail=f"Proveedor de destino '{target}' no soportado.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    for fname, fcontent in files_map.items():
        (output_path.parent / fname).write_text(fcontent, encoding="utf-8")

    return {
        "status": "generated",
        "execution_mode": "artifact_generation_only",
        "completed_in_real_cloud": False,
        "target": target,
        "selected_requested": request.resources,
        "dependency_summary": {
            "required_direct": dep_analysis["required_direct"],
            "required_transitive": dep_analysis["required_transitive"],
            "confirmed": dep_analysis["confirmed_dependencies"],
            "inferred": dep_analysis["inferred_dependencies"],
            "shared": dep_analysis["shared_dependencies"],
            "shared_policies": dep_analysis["shared_dependency_policies"],
            "optional": dep_analysis["optional_dependencies"],
            "total_migrated_nodes": len(selected_nodes),
        },
        "resources_generated": [res.id for res in selected_nodes],
        "output_path": str(output_path),
        "validation": validation,
        "files": files_map,
        "iac_code": code,
    }


# ==============================================================================
# Unified Migration Orchestrator Endpoints (State Machine & 3 Use Cases)
# ==============================================================================


@router.get("/jobs")
def list_migration_jobs(
    use_case: Optional[str] = Query(None, description="app_source | vm_image"),
    target_provider: Optional[str] = Query(None, description="aws | gcp"),
):
    """List orchestrated migration jobs across all 3 use cases."""
    if target_provider:
        _validate_target_provider(target_provider)
    jobs = migration_orchestrator.list_migrations(use_case=use_case, target_provider=target_provider)
    return {"count": len(jobs), "jobs": jobs}


@router.post("/jobs")
def create_migration_job(request: CreateMigrationJobRequest):
    """Create and optionally assess/plan a new migration job for Use Case 1, 2, or 3."""
    target = _validate_target_provider(request.target_provider)
    try:
        return migration_orchestrator.create_migration(
            name=request.name or "",
            use_case=request.use_case,
            target_provider=target,
            target_config=request.target_config,
            source_config=request.source_config,
            auto_assess_and_plan=request.auto_assess_and_plan,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectorError as exc:
        status = 404 if exc.code == "GITHUB_NOT_FOUND" else (400 if exc.code in ("GITHUB_REF_NOT_FOUND", "GITHUB_RATE_LIMIT") else 502)
        raise HTTPException(status_code=status, detail=exc.message) from exc


@router.get("/jobs/{migration_id}")
def get_migration_job(migration_id: str):
    """Retrieve full state, stages, CMIR, dependencies, compatibility, artifacts and events of a migration job."""
    try:
        return migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _sanitize_job_for_export(job_data: Any) -> Any:
    """
    Recursively redact any sensitive credentials (tokens, passwords, secrets, aws keys)
    from migration jobs before exporting them to JSON or ZIP bundles.
    """
    if isinstance(job_data, dict):
        sanitized = {}
        for k, v in job_data.items():
            k_lower = str(k).lower()
            if any(term in k_lower for term in ("token", "password", "secret", "private_key", "credential", "api_key", "auth")):
                if v and isinstance(v, str):
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = v
            else:
                sanitized[k] = _sanitize_job_for_export(v)
        return sanitized
    elif isinstance(job_data, list):
        return [_sanitize_job_for_export(item) for item in job_data]
    return job_data


@router.get("/jobs/{migration_id}/bundle.zip")
def download_migration_bundle(migration_id: str):
    """
    Download a complete, production-ready ZIP package containing all generated Terraform IaC,
    deployment runbooks, manifests, in-guest scripts, and a step-by-step DEPLOYMENT_INSTRUCTIONS.md guide.
    """
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    artifacts = job.get("generated_artifacts") or {}
    files = dict(artifacts.get("files") or {})

    # Ensure deployment guide is included in files
    guide_content = (
        job.get("deployment_guide")
        or artifacts.get("deployment_guide")
        or files.get("DEPLOYMENT_INSTRUCTIONS.md")
    )
    if not guide_content:
        from app.migration.deployment_guide_generator import generate_deployment_guide

        guide_content = generate_deployment_guide(
            use_case=job.get("use_case", "app_source"),
            target_provider=job.get("target_provider", "aws"),
            job_name=job.get("name", "migrated-workload"),
            migration_id=migration_id,
            source_environment=job.get("source_environment", {}) or {},
            artifacts_files=files,
            target_config=job.get("target_config", {}) or {},
        )
    files["DEPLOYMENT_INSTRUCTIONS.md"] = guide_content

    # Include sanitized job metadata report for audit without leaking secrets
    sanitized_report = _sanitize_job_for_export(job)
    files["migration_report.json"] = json.dumps(sanitized_report, indent=2, ensure_ascii=False)

    # For Case 2 (vm_image), also embed the system image snapshot archive if available on disk (< 50MB)
    if job.get("use_case") == "vm_image":
        src_env = job.get("source_environment") or {}
        live_details = src_env.get("live_capture_details") or {}
        from app.migration.deployment_guide_generator import _slug
        job_slug = _slug(job.get("name", "workload"))
        candidates = [
            live_details.get("system_image_snapshot_archive"),
            live_details.get("config_archive"),
            src_env.get("system_image_snapshot_archive"),
            f"generated/staging_images/live_capture_{job_slug}/system_image_snapshot_{job_slug}.tar.gz",
            f"generated/staging_images/{job_slug}/system_image_snapshot_{job_slug}.tar.gz",
        ]
        staging_root = Path("generated/staging_images")
        if staging_root.is_dir():
            for sub in staging_root.iterdir():
                if sub.is_dir():
                    for tfile in sub.glob("system_image_snapshot_*.tar.gz"):
                        candidates.append(str(tfile))
                    for tfile in sub.glob("*.tar.gz"):
                        candidates.append(str(tfile))
        for c in candidates:
            if c and Path(c).is_file():
                tar_p = Path(c)
                try:
                    if tar_p.stat().st_size < 50 * 1024 * 1024:
                        files[tar_p.name] = tar_p.read_bytes()
                        break
                except Exception:
                    pass

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in files.items():
            if isinstance(content, str):
                zf.writestr(fname, content.encode("utf-8"))
            elif isinstance(content, bytes):
                zf.writestr(fname, content)

    zip_bytes = buf.getvalue()
    use_case = job.get("use_case", "migration")
    provider = job.get("target_provider", "cloud")
    filename = f"cloudmove-{use_case}-{provider}-{migration_id}.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(zip_bytes)),
        },
    )


@router.get("/jobs/{migration_id}/deployment-guide")
def get_migration_deployment_guide(migration_id: str):
    """Get the step-by-step markdown deployment instructions for the target cloud."""
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    guide = (
        job.get("deployment_guide")
        or (job.get("generated_artifacts") or {}).get("deployment_guide")
        or (job.get("generated_artifacts") or {}).get("files", {}).get("DEPLOYMENT_INSTRUCTIONS.md")
    )
    if not guide:
        from app.migration.deployment_guide_generator import generate_deployment_guide

        guide = generate_deployment_guide(
            use_case=job.get("use_case", "app_source"),
            target_provider=job.get("target_provider", "aws"),
            job_name=job.get("name", "migrated-workload"),
            migration_id=migration_id,
            source_environment=job.get("source_environment", {}) or {},
            artifacts_files=(job.get("generated_artifacts") or {}).get("files", {}) or {},
            target_config=job.get("target_config", {}) or {},
        )
    return {
        "migration_id": migration_id,
        "use_case": job.get("use_case"),
        "target_provider": job.get("target_provider"),
        "deployment_guide_markdown": guide,
    }


@router.get("/jobs/{migration_id}/system-image")
def download_system_image_snapshot(migration_id: str):
    """
    Download the compressed system image snapshot archive (.tar.gz) containing
    captured OS configurations (/etc), user accounts, services, and in-guest restore scripts.
    """
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from app.migration.deployment_guide_generator import _slug
    src = job.get("source_environment") or {}
    live_details = src.get("live_capture_details") or {}
    job_slug = _slug(job.get("name", "workload"))

    candidates = [
        live_details.get("system_image_snapshot_archive"),
        live_details.get("config_archive"),
        src.get("system_image_snapshot_archive"),
        f"generated/staging_images/live_capture_{job_slug}/system_image_snapshot_{job_slug}.tar.gz",
        f"generated/staging_images/{job_slug}/system_image_snapshot_{job_slug}.tar.gz",
    ]

    found_path: Optional[Path] = None
    for c in candidates:
        if c and Path(c).is_file():
            found_path = Path(c)
            break

    if not found_path:
        staging_root = Path("generated/staging_images")
        if staging_root.is_dir():
            staging_dirs = [
                staging_root / f"live_capture_{job_slug}",
                staging_root / job_slug,
            ] + [d for d in staging_root.iterdir() if d.is_dir()]
            for s_dir in staging_dirs:
                if s_dir.is_dir():
                    for tar_file in list(s_dir.glob("system_image_snapshot_*.tar.gz")) + list(s_dir.glob("*.tar.gz")):
                        if tar_file.is_file():
                            found_path = tar_file
                            break
                if found_path:
                    break

    if not found_path or not found_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró copia del sistema operativo (.tar.gz) almacenada para la migración '{migration_id}'. Ejecute el descubrimiento con captura de host en vivo para generarla.",
        )

    return FileResponse(
        path=str(found_path),
        filename=found_path.name,
        media_type="application/gzip",
    )


@router.get("/jobs/{migration_id}/disk-image")
def download_disk_image_file(
    migration_id: str,
    format: Optional[str] = Query(None, description="Target hypervisor format: 'vdi' (VirtualBox), 'vmdk' (VMware), 'qcow2' (QEMU/KVM/Proxmox), 'raw'"),
):
    """
    Download the generated binary virtual disk image from staging, optionally
    converting it on-the-fly to the requested hypervisor format (.vdi, .vmdk, .qcow2).
    """
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    import shutil
    import subprocess
    from app.migration.deployment_guide_generator import _slug
    src = job.get("source_environment") or {}
    live_details = src.get("live_capture_details") or {}
    job_slug = _slug(job.get("name", "workload"))

    candidates = [
        live_details.get("generated_image_file"),
        src.get("source_file"),
        f"generated/staging_images/live_capture_{job_slug}/{job_slug}.qcow2",
        f"generated/staging_images/{job_slug}/{job_slug}.qcow2",
    ]

    found_path: Optional[Path] = None
    for c in candidates:
        if c and Path(c).is_file():
            p = Path(c)
            # Only stream files smaller than 1 GiB directly over HTTP
            if p.stat().st_size < 1024 * 1024 * 1024:
                found_path = p
                break

    if not found_path:
        staging_root = Path("generated/staging_images")
        if staging_root.is_dir():
            staging_dirs = [
                staging_root / f"live_capture_{job_slug}",
                staging_root / job_slug,
            ] + [d for d in staging_root.iterdir() if d.is_dir()]
            for s_dir in staging_dirs:
                if s_dir.is_dir():
                    for disk_ext in ("*.qcow2", "*.vmdk", "*.raw", "*.vhdx", "*.vdi"):
                        for disk_file in s_dir.glob(disk_ext):
                            if disk_file.is_file() and disk_file.stat().st_size < 1024 * 1024 * 1024:
                                found_path = disk_file
                                break
                        if found_path:
                            break
                if found_path:
                    break

    if not found_path:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró archivo de imagen de disco disponible para descargar en la migración '{migration_id}'. Use 'create_full_raw_disk_clone.sh' para streaming o clonado local.",
        )

    # Conversion to requested hypervisor format if specified
    req_fmt = str(format).lower().strip().lstrip(".") if format else None
    if req_fmt and req_fmt in ("vdi", "vmdk", "qcow2", "raw"):
        cur_fmt = found_path.suffix.lower().lstrip(".")
        if cur_fmt != req_fmt:
            target_converted = found_path.parent / f"{found_path.stem}.{req_fmt}"
            if target_converted.is_file():
                found_path = target_converted
            else:
                qemu_bin = shutil.which("qemu-img")
                if qemu_bin:
                    try:
                        res = subprocess.run(
                            [qemu_bin, "convert", "-f", cur_fmt, "-O", req_fmt, str(found_path), str(target_converted)],
                            capture_output=True,
                            timeout=60,
                        )
                        if res.returncode == 0 and target_converted.is_file():
                            found_path = target_converted
                    except Exception:
                        pass

    media_type = "application/octet-stream"
    suf = found_path.suffix.lower()
    if suf == ".qcow2":
        media_type = "application/x-qemu-disk"
    elif suf == ".vmdk":
        media_type = "application/x-vmdk"
    elif suf == ".vdi":
        media_type = "application/x-virtualbox-vdi"

    return FileResponse(
        path=str(found_path),
        filename=found_path.name,
        media_type=media_type,
    )


@router.get("/jobs/{migration_id}/hypervisor-script")
def download_hypervisor_script(
    migration_id: str,
    hypervisor: str = Query("virtualbox", description="Target hypervisor: 'virtualbox' or 'vmware'"),
):
    """
    Download automated launch and provisioning script for VirtualBox or VMware.
    """
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from app.migration.deployment_guide_generator import _slug
    src = job.get("source_environment") or {}
    job_slug = _slug(job.get("name", "workload"))
    boot_mode = str(src.get("boot_mode") or "uefi").lower()

    if hypervisor.lower() == "vmware":
        content = f"""#!/usr/bin/env bash
# ==============================================================================
# CloudMove — Lanzador Automatizado para VMware Workstation / Player
# VM: CloudMove-{job_slug}
# ==============================================================================
set -euo pipefail

VM_NAME="CloudMove-{job_slug}"
VMDK_IMAGE="{job_slug}.vmdk"
QCOW_IMAGE="{job_slug}.qcow2"
VMX_FILE="{job_slug}.vmx"

echo "=========================================================="
echo " CloudMove — Lanzador Automatizado para VMware"
echo "=========================================================="

# 1. Convertir QCOW2 a VMDK si es necesario
if [ ! -f "$VMDK_IMAGE" ] && [ -f "$QCOW_IMAGE" ]; then
    echo "[1/3] Convirtiendo $QCOW_IMAGE a formato nativo VMware ($VMDK_IMAGE)..."
    qemu-img convert -f qcow2 -O vmdk "$QCOW_IMAGE" "$VMDK_IMAGE"
fi

if [ ! -f "$VMDK_IMAGE" ]; then
    echo "Descargando disco VMDK desde CloudMove..."
    CLOUDMOVE_API_URL="${{CLOUDMOVE_API_URL:-http://localhost:8000}}"
    curl -fSL "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/disk-image?format=vmdk" -o "$VMDK_IMAGE" || true
fi

echo "[2/3] Generando archivo de configuración VMware ($VMX_FILE)..."
cat << 'EOF_VMX' > "$VMX_FILE"
.encoding = "UTF-8"
config.version = "8"
virtualHW.version = "19"
vmci0.present = "TRUE"
displayName = "CloudMove-{job_slug}"
guestOS = "debian11-64"
memsize = "4096"
numvcpus = "2"
firmware = "{boot_mode}"
sata0.present = "TRUE"
sata0:0.present = "TRUE"
sata0:0.fileName = "{job_slug}.vmdk"
sata0:0.deviceType = "disk"
ethernet0.present = "TRUE"
ethernet0.connectionType = "nat"
ethernet0.virtualDev = "e1000e"
ethernet0.wakeOnPcktRcv = "FALSE"
ethernet0.addressType = "generated"
pciBridge0.present = "TRUE"
EOF_VMX

echo "[3/3] Configuración VMware creada exitosamente en $VMX_FILE."
echo "Para abrir la máquina virtual en VMware:"
echo "  vmplayer \"$(realpath "$VMX_FILE")\" &"
echo "  o abra '$VMX_FILE' desde VMware Workstation / Fusion."
"""
        filename = f"launch_vmware_{job_slug}.sh"
    else:
        content = f"""#!/usr/bin/env bash
# ==============================================================================
# CloudMove — Lanzador Automatizado para VirtualBox
# VM: CloudMove-{job_slug}
# ==============================================================================
set -euo pipefail

VM_NAME="CloudMove-{job_slug}"
VDI_IMAGE="{job_slug}.vdi"
QCOW_IMAGE="{job_slug}.qcow2"
MEMORY_MB=4096
CPUS=2

echo "=========================================================="
echo " CloudMove — Lanzador Automatizado para VirtualBox"
echo " Máquina Virtual: $VM_NAME"
echo "=========================================================="

if ! command -v VBoxManage >/dev/null 2>&1; then
    echo "ERROR: VBoxManage no está instalado o no se encuentra en el PATH."
    echo "Instale VirtualBox mediante: sudo apt-get install virtualbox"
    exit 1
fi

# 1. Convertir QCOW2 a VDI si es necesario o descargar
if [ ! -f "$VDI_IMAGE" ] && [ -f "$QCOW_IMAGE" ]; then
    echo "[1/4] Convirtiendo $QCOW_IMAGE a formato nativo VirtualBox ($VDI_IMAGE)..."
    qemu-img convert -f qcow2 -O vdi "$QCOW_IMAGE" "$VDI_IMAGE"
fi

if [ ! -f "$VDI_IMAGE" ]; then
    echo "Descargando disco VDI desde CloudMove..."
    CLOUDMOVE_API_URL="${{CLOUDMOVE_API_URL:-http://localhost:8000}}"
    curl -fSL "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/disk-image?format=vdi" -o "$VDI_IMAGE" || true
fi

if [ ! -f "$VDI_IMAGE" ]; then
    echo "ERROR: No se encontró '$VDI_IMAGE'."
    exit 1
fi

# 2. Desregistrar VM previa si existe
if VBoxManage showvminfo "$VM_NAME" >/dev/null 2>&1; then
    echo "Desregistrando instancia anterior de $VM_NAME..."
    VBoxManage controlvm "$VM_NAME" poweroff 2>/dev/null || true
    VBoxManage unregistervm "$VM_NAME" --delete 2>/dev/null || true
fi

echo "[2/4] Creando máquina virtual en VirtualBox..."
VBoxManage createvm --name "$VM_NAME" --ostype "Debian_64" --register

echo "[3/4] Configurando CPU ($CPUS), RAM (${{MEMORY_MB}}MB), Firmware ({boot_mode}) y red..."
VBoxManage modifyvm "$VM_NAME" \\
    --memory "$MEMORY_MB" \\
    --cpus "$CPUS" \\
    --firmware "{boot_mode}" \\
    --nic1 nat \\
    --audio none \\
    --vram 128 \\
    --graphicscontroller vmsvga \\
    --boot1 disk

echo "[4/4] Creando controlador SATA y adjuntando disco virtual VDI..."
VBoxManage storagectl "$VM_NAME" --name "SATA Controller" --add sata --controller IntelAhci --portcount 2
VBoxManage storageattach "$VM_NAME" --storagectl "SATA Controller" \\
    --port 0 --device 0 --type hdd --medium "$(realpath "$VDI_IMAGE")"

echo "=========================================================="
echo " Máquina virtual '$VM_NAME' lista en VirtualBox."
echo " Para iniciar la máquina virtual:"
echo "   VBoxManage startvm \"$VM_NAME\" --type gui"
echo "=========================================================="

read -p "¿Deseas iniciar la máquina virtual ahora en VirtualBox? (s/N): " -r CONFIRM || true
if [[ "${{CONFIRM:-n}}" =~ ^[sSyY]$ ]]; then
    VBoxManage startvm "$VM_NAME" --type gui
fi
"""
        filename = f"launch_virtualbox_{job_slug}.sh"

    return PlainTextResponse(
        content=content,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/jobs/{migration_id}/assess")
def assess_migration_job(migration_id: str):
    """Run discovery and compatibility assessment (DRAFT -> DISCOVERING -> ASSESSED)."""
    try:
        return migration_orchestrator.run_discovery_and_assessment(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectorError as exc:
        status = 404 if exc.code == "GITHUB_NOT_FOUND" else (400 if exc.code in ("GITHUB_REF_NOT_FOUND", "GITHUB_RATE_LIMIT") else 502)
        raise HTTPException(status_code=status, detail=exc.message) from exc


@router.get("/persistence/status")
def get_transactional_persistence_status():
    """Return ACID transactional SQLite/PostgreSQL database status, schema migrations, and row counts."""
    return get_transactional_db().get_schema_status()


@router.get("/compatibility-matrix")
def get_machine_migration_compatibility_matrix(
    target_provider: str = Query("aws", description="aws | gcp"),
    source_type: str = Query("standalone_offline_disk_image", description="standalone_offline_disk_image | live_server | hypervisor_vm"),
    disk_format: str = Query("VMDK"),
    os_family: str = Query("linux"),
    firmware_type: str = Query("UEFI"),
    total_size_gb: float = Query(60.0),
    prefer_continuous_replication: bool = Query(False),
):
    """Return the official AWS MGN / VM Import and GCP Migrate to VMs / Image Import compatibility matrix and strategy selection."""
    target = _validate_target_provider(target_provider)
    selection = select_machine_migration_strategy(
        manifest={
            "format": disk_format,
            "boot_mode": firmware_type,
            "os": {"family": os_family, "architecture": "x86_64"},
            "total_provisioned_gib": total_size_gb,
        },
        target_provider=target,
        source_type=source_type,
        prefer_continuous_replication=prefer_continuous_replication,
    )
    return {
        "matrix": MACHINE_MIGRATION_COMPATIBILITY_MATRIX,
        "recommended_selection": selection,
    }


@router.post("/jobs/{migration_id}/plan")
def plan_migration_job(migration_id: str, expected_version: Optional[int] = Query(None)):
    """Generate migration plan and validate Terraform/deployment artifacts (ASSESSED -> PLAN_READY)."""
    try:
        return migration_orchestrator.generate_plan_and_artifacts(
            migration_id, expected_version=expected_version
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConcurrencyConflictError, StageLockedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{migration_id}/approve")
def approve_migration_job(migration_id: str, request: Optional[ApproveMigrationJobRequest] = None):
    """Approve migration plan and shared dependency policies (PLAN_READY -> APPROVED)."""
    req = request or ApproveMigrationJobRequest()
    try:
        return migration_orchestrator.approve_migration(
            migration_id,
            approved_by=req.approved_by,
            notes=req.notes,
            validated_shared_resources=req.validated_shared_resources,
            expected_version=req.expected_version,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConcurrencyConflictError, StageLockedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{migration_id}/advance")
def advance_migration_job(migration_id: str, request: Optional[AdvanceMigrationJobRequest] = None):
    """Advance migration execution stage (APPROVED -> PREPARING -> TESTING -> READY_FOR_CUTOVER -> COMPLETED)."""
    req = request or AdvanceMigrationJobRequest()
    try:
        return migration_orchestrator.advance_execution(
            migration_id,
            dry_run=req.dry_run,
            simulate_failure=req.simulate_failure,
            simulate_startup_failure=req.simulate_startup_failure,
            simulate_health_failure=req.simulate_health_failure,
            failure_reason=req.failure_reason,
            operator_id=req.operator_id,
            idempotency_key=req.idempotency_key,
            expected_version=req.expected_version,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConcurrencyConflictError, StageLockedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{migration_id}/retry")
def retry_migration_job(migration_id: str, expected_version: Optional[int] = Query(None)):
    """Retry a FAILED stage from its last recovery checkpoint."""
    try:
        return migration_orchestrator.retry_failed_stage(
            migration_id, expected_version=expected_version
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConcurrencyConflictError, StageLockedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{migration_id}/mark-irreversible")
def mark_migration_job_irreversible(migration_id: str, request: MarkIrreversibleRequest):
    """Mark a migration operation as irreversible so automatic rollback is blocked and manual recovery steps are required."""
    try:
        return migration_orchestrator.mark_irreversible_operation(
            migration_id,
            operation_reason=request.operation_reason,
            recovery_procedure=request.recovery_procedure,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{migration_id}/rollback")
def rollback_migration_job(migration_id: str, request: Optional[RollbackOrCancelRequest] = None):
    """Execute rollback procedure and transition to ROLLED_BACK."""
    req = request or RollbackOrCancelRequest()
    try:
        return migration_orchestrator.rollback_migration(
            migration_id, reason=req.reason, expected_version=req.expected_version
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConcurrencyConflictError, StageLockedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{migration_id}/cancel")
def cancel_migration_job(migration_id: str, request: Optional[RollbackOrCancelRequest] = None):
    """Cancel an active or planned migration."""
    req = request or RollbackOrCancelRequest(reason="Cancelado por el usuario")
    try:
        return migration_orchestrator.cancel_migration(
            migration_id, reason=req.reason, expected_version=req.expected_version
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConcurrencyConflictError, StageLockedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/jobs/{migration_id}")
def delete_migration_job(migration_id: str):
    """Permanently delete a specific migration job and its associated artifacts."""
    deleted = migration_orchestrator.delete_migration(migration_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Trabajo de migración '{migration_id}' no encontrado.")
    return {"status": "DELETED", "migration_id": migration_id}


@router.delete("/jobs")
def clear_all_migration_jobs():
    """Permanently clear all migration jobs, plans, stages, and artifacts."""
    count = migration_orchestrator.clear_all_migrations()
    return {"status": "CLEARED", "deleted_count": count}


# ==============================================================================
# Direct Use Case 1 & Use Case 2 Inspection & Guided Migration Endpoints
# ==============================================================================


@router.post("/github/validate")
def validate_github_repository(request: GitHubValidateRequest):
    """
    Validate a real GitHub repository URL, query metadata via GitHub REST API,
    and return available branches, tags, default branch, and visibility.
    """
    from app.discovery.github_connector import GitHubConnector
    try:
        gh = GitHubConnector(token=request.github_token)
        repo_info = gh.validate_repository(request.github_url, token=request.github_token)
        refs = gh.list_branches_and_tags(request.github_url, token=request.github_token)
        default_branch = repo_info.get("default_branch", "main")
        tree_info = None
        try:
            tree_info = gh.get_repository_tree(request.github_url, ref=default_branch, token=request.github_token)
        except Exception:
            tree_info = None

        return {
            "status": "valid",
            "repository": repo_info,
            "branches": refs.get("branches", []),
            "tags": refs.get("tags", []),
            "default_branch": default_branch,
            "tree": tree_info,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/use-case-1/inspect")
def inspect_use_case_1_application(request: Optional[AppInspectRequest] = None):
    """
    Use Case 1: Inspect an application repository (GitHub or local directory) or inline manifests,
    pin exact commit revision, detect runtime/ports/env keys (redacting secret values),
    classify dependencies into confirmed vs inferred vs unknown, and evaluate AWS/GCP viability.
    """
    req = request or AppInspectRequest()
    target = _validate_target_provider(req.target_provider)
    try:
        app_disc = inspect_application_source(
            source_path=req.source_path,
            inline_files=req.inline_files,
            runtime_metadata=req.runtime_metadata,
            app_name_override=req.app_name,
            github_url=req.github_url,
            github_ref=req.github_ref,
            github_token=req.github_token,
        )
        cmir_obj = build_application_cmir(
            app_disc,
            target_provider=target,
            deployment_mode=req.deployment_mode,
            user_decisions=req.user_decisions,
        )
        viability = evaluate_app_migration_viability(app_disc, cmir_obj, target_provider=target, deployment_mode=req.deployment_mode)
        return {
            "use_case": "app_source",
            "target_provider": target,
            "application": app_disc,
            "transformation_catalog": app_disc.get("transformation_catalog"),
            "cmir": cmir_obj.model_dump(),
            "viability": viability,
        }
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectorError as exc:
        status = 404 if exc.code == "GITHUB_NOT_FOUND" else (400 if exc.code in ("GITHUB_REF_NOT_FOUND", "GITHUB_RATE_LIMIT") else 502)
        raise HTTPException(status_code=status, detail=exc.message) from exc


@router.post("/jobs/{migration_id}/decisions")
def update_job_architecture_decisions(migration_id: str, request: UpdateArchitectureDecisionsRequest):
    """
    Update user transformation choices for discovered GitHub components/services on an existing migration job
    and regenerate the CMIR + Terraform HCL bundle in real time.
    """
    try:
        return migration_orchestrator.update_architecture_decisions(
            migration_id=migration_id,
            user_decisions=request.user_decisions,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/use-case-1/migrate")
def orchestrate_use_case_1_migration(request: Optional[AppInspectRequest] = None):
    """Create and plan a full 12-stage guided application migration job in the orchestrator."""
    req = request or AppInspectRequest()
    target = _validate_target_provider(req.target_provider)
    try:
        app_name = req.app_name or (
            req.github_url.rstrip("/").split("/")[-1]
            if req.github_url
            else (Path(req.source_path).name if req.source_path else "app")
        )
        return migration_orchestrator.create_migration(
            name=f"App Migration: {app_name} -> {target.upper()}",
            use_case="app_source",
            target_provider=target,
            source_config={
                "source_path": req.source_path,
                "inline_files": req.inline_files,
                "runtime_metadata": req.runtime_metadata,
                "app_name": app_name,
                "deployment_mode": req.deployment_mode,
                "github_url": req.github_url,
                "github_ref": req.github_ref,
                "github_token": "[REDACTED]" if req.github_token else None,
                "user_decisions": req.user_decisions,
            },
            auto_assess_and_plan=True,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectorError as exc:
        status = 404 if exc.code == "GITHUB_NOT_FOUND" else (400 if exc.code in ("GITHUB_REF_NOT_FOUND", "GITHUB_RATE_LIMIT") else 502)
        raise HTTPException(status_code=status, detail=exc.message) from exc


@router.post("/use-case-2/inspect")
def inspect_use_case_2_vm_image(request: Optional[ImageInspectRequest] = None):
    """
    Use Case 2: Inspect a VM/disk image (`VMDK`, `VHD`, `VHDX`, `QCOW2`, `RAW`, `OVA`, `OVF`)
    or capture the live operating system where CloudMove/agent runs.
    Verifies authentic binary disk headers, partitions, SHA-256 integrity, and driver compatibility for AWS/GCP.
    """
    req = request or ImageInspectRequest()
    target = _validate_target_provider(req.target_provider)
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
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{migration_id}/remediate-blocker")
def remediate_migration_job_blocker(
    migration_id: str,
    request: Optional[RemediateBlockerRequest] = None,
):
    """
    Remediate a compatibility blocker on a migration job (such as volatile RAM state requirement).
    Applies an application-quiesced snapshot or continuous block replication, clears blockers,
    and advances the job cleanly to PLAN_READY.
    """
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
    """
    Query real-time live block devices, filesystems, and partitions from the host
    where CloudMove (or an enrolled agent) is running, without preloaded data.
    """
    return probe_live_storage_devices(agent_id=agent_id)


@router.post("/use-case-2/probe-devices")
def trigger_probe_devices(agent_id: Optional[str] = Query(None)):
    """
    Trigger an on-demand probe of host storage devices (disks, partitions, filesystems).
    """
    return probe_live_storage_devices(agent_id=agent_id)


@router.post("/use-case-2/capture-live")
def capture_live_host_use_case_2(request: Optional[ImageInspectRequest] = None):
    """
    Use Case 2: Capture the live host operating system (system files, /etc, fstab, packages,
    services, kernel) and generate an authentic VM disk image (QCOW2/RAW) for cloud provisioning.
    """
    req = request or ImageInspectRequest()
    req.capture_live_host = True
    req.source_type = "live_server"
    return inspect_use_case_2_vm_image(req)


@router.post("/use-case-2/migrate")
def orchestrate_use_case_2_migration(request: Optional[ImageInspectRequest] = None):
    """Create and plan a full 13-stage OS/VM Image migration job in the orchestrator."""
    req = request or ImageInspectRequest()
    target = _validate_target_provider(req.target_provider)
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


class ValidateExternalCredentialRequest(BaseModel):
    service_type: str = "supabase"
    credentials: Dict[str, str] = Field(default_factory=dict)


class VerifyCloudCredentialsRequest(BaseModel):
    provider: str = "aws"
    credentials: Optional[Dict[str, str]] = None


class DeployLiveJobRequest(BaseModel):
    dry_run: bool = False
    credentials: Optional[Dict[str, str]] = None
    secrets: Optional[Dict[str, str]] = None


class ExecuteTerraformCommandRequest(BaseModel):
    action: str = Field(
        "plan",
        description="init | validate | plan | apply | continue | refresh | destroy | output | state | unlock | full_deploy | dry_run",
    )
    credentials: Optional[Dict[str, str]] = None
    secrets: Optional[Dict[str, str]] = None
    async_exec: bool = Field(
        True,
        description="Run in background thread to allow live log streaming and immediate cancellation",
    )


def _sync_job_after_terraform(migration_id: str, tf_result: Dict[str, Any]) -> None:
    """
    Synchronize the migration orchestrator state machine when a real cloud Terraform
    action (`apply`, `continue`, `full_deploy`, or `destroy`) completes.
    """
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
    except Exception:
        pass


@router.post("/credentials/validate-external")
def validate_external_credential_endpoint(request: ValidateExternalCredentialRequest):
    """
    Safely validate external BaaS or API credentials without exposing or storing secrets.
    """
    from app.migration.external_services import validate_external_credentials
    return validate_external_credentials(request.service_type, request.credentials)


@router.post("/credentials/verify-cloud")
def verify_cloud_credentials_endpoint(request: VerifyCloudCredentialsRequest):
    """
    Verify cloud provider authentication (e.g. AWS STS Caller Identity) for automated deployment.
    """
    from app.migration.cloud_deployer import cloud_deployer
    return cloud_deployer.verify_cloud_provider_credentials(request.provider, request.credentials)


@router.get("/jobs/{migration_id}/terraform/status")
def get_job_terraform_status_endpoint(migration_id: str):
    """
    Retrieve real-time Terraform execution status, persisted and streaming logs,
    active subprocess state, `terraform.tfstate` resources, and live cloud outputs.
    """
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from app.migration.cloud_deployer import cloud_deployer
    job_dir = cloud_deployer.resolve_job_dir(migration_id, job)
    artifacts = job.get("generated_artifacts") or {}
    files = artifacts.get("files") or {}
    if files and not (job_dir / "main.tf").exists():
        cloud_deployer.materialize_job_files(job_dir, artifacts_files=files)

    return cloud_deployer.get_terraform_status(migration_id, job_dir)


def _infer_public_api_url(request: Optional[Request] = None) -> str:
    env_url = os.getenv("CLOUDMOVE_API_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    if not request:
        return "http://localhost:8000"
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    if "digitalcafeluna.store" in (host or ""):
        proto = "https"
    return f"{proto}://{host}".rstrip("/")


@router.post("/jobs/{migration_id}/terraform/command")
def execute_job_terraform_command_endpoint(
    migration_id: str,
    http_request: Request,
    request: Optional[ExecuteTerraformCommandRequest] = None,
):
    """
    Execute a specific Terraform command (`init`, `validate`, `plan`, `apply`, `continue`,
    `refresh`, `destroy`, `output`, `state`, `unlock`, `full_deploy`, `dry_run`) in the
    job's workspace with real-time log streaming and cancellation support.
    """
    req = request or ExecuteTerraformCommandRequest()
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if job.get("use_case") == "vm_image" and req.action.lower().strip() in ("plan", "apply", "continue", "full_deploy", "dry_run"):
        try:
            job = migration_orchestrator.refresh_uc2_stage_binding(
                migration_id,
                public_api_url=_infer_public_api_url(http_request),
            )
        except Exception:
            pass

    from app.migration.cloud_deployer import cloud_deployer
    job_dir = cloud_deployer.resolve_job_dir(migration_id, job)
    artifacts = job.get("generated_artifacts") or {}
    files = artifacts.get("files") or {}

    return cloud_deployer.execute_terraform_command(
        migration_id=migration_id,
        job_dir=job_dir,
        action=req.action,
        provider=job.get("target_provider", "aws"),
        credentials=req.credentials,
        secrets=req.secrets,
        artifacts_files=files,
        async_exec=req.async_exec,
        on_complete=lambda res: _sync_job_after_terraform(migration_id, res),
    )


@router.post("/jobs/{migration_id}/terraform/cancel")
def cancel_job_terraform_command_endpoint(migration_id: str):
    """
    Immediately cancel the currently running Terraform process for `migration_id`
    and release any stale `.terraform.tfstate.lock.info` lock.
    """
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from app.migration.cloud_deployer import cloud_deployer
    job_dir = cloud_deployer.resolve_job_dir(migration_id, job)
    return cloud_deployer.cancel_terraform_execution(migration_id, job_dir)


@router.delete("/jobs/{migration_id}/terraform/logs")
def clear_job_terraform_logs_endpoint(migration_id: str):
    """
    Clear the persisted and in-memory Terraform execution logs for `migration_id`.
    """
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from app.migration.cloud_deployer import cloud_deployer
    job_dir = cloud_deployer.resolve_job_dir(migration_id, job)
    return cloud_deployer.clear_terraform_logs(migration_id, job_dir)


@router.post("/jobs/{migration_id}/deploy-live")
def deploy_live_migration_job_endpoint(
    migration_id: str,
    http_request: Request,
    request: Optional[DeployLiveJobRequest] = None,
):
    """
    Execute autonomous cloud deployment directly from CloudMove using Terraform & Cloud SDKs.
    """
    req = request or DeployLiveJobRequest()
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if job.get("use_case") == "vm_image":
        try:
            job = migration_orchestrator.refresh_uc2_stage_binding(
                migration_id,
                public_api_url=_infer_public_api_url(http_request),
            )
        except Exception:
            pass

    from app.migration.cloud_deployer import cloud_deployer
    job_dir = cloud_deployer.resolve_job_dir(migration_id, job)

    artifacts = job.get("generated_artifacts") or {}
    files = artifacts.get("files") or {}

    deploy_res = cloud_deployer.execute_job_deployment(
        job_dir=job_dir,
        provider=job.get("target_provider", "aws"),
        dry_run=req.dry_run,
        credentials=req.credentials,
        secrets=req.secrets,
        artifacts_files=files,
        migration_id=migration_id,
    )

    if deploy_res.get("success") and not req.dry_run:
        _sync_job_after_terraform(migration_id, deploy_res)

    return deploy_res


def _sanitize_probe_host(ip: str) -> str:
    """Validate target host/IP for live EC2 probe while preventing loopback/metadata SSRF."""
    clean_ip = (
        str(ip or "")
        .strip()
        .replace("http://", "")
        .replace("https://", "")
        .split("/")[0]
        .split(":")[0]
    )
    if not clean_ip or len(clean_ip) > 253 or not re.match(r"^[A-Za-z0-9.\-]+$", clean_ip):
        raise HTTPException(status_code=400, detail="Dirección IP o hostname inválido")
    lower = clean_ip.lower()
    if lower in ("localhost", "ip6-localhost") or lower.endswith(".local"):
        raise HTTPException(status_code=400, detail="Host local no permitido para sonda externa")
    try:
        ip_obj = ipaddress.ip_address(clean_ip)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_unspecified:
            raise HTTPException(status_code=400, detail="Rango IP privado, reservado o link-local no permitido")
    except ValueError:
        pass
    return clean_ip


def _probe_tcp_port(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _probe_http_endpoint(url: str, timeout: float = 2.5) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "CloudMove-HealthCheck/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"online": True, "status": resp.status, "message": "OK"}
    except urllib.error.HTTPError as exc:
        return {"online": True, "status": exc.code, "message": f"HTTP {exc.code}"}
    except (urllib.error.URLError, socket.timeout, ConnectionRefusedError, OSError) as exc:
        return {"online": False, "status": None, "message": str(exc)}


def _fetch_json_endpoint(url: str, timeout: float = 3.5) -> Dict[str, Any]:
    """Fetch JSON from an EC2 validation endpoint with measured latency."""
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "CloudMove-UC2-Validator/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


@router.get("/probe-instance-status")
def probe_instance_status(
    ip: str = Query(..., description="Public IP address or hostname of the deployed instance"),
):
    """
    Safely probes an external deployed instance endpoint from the CloudMove server.
    Detects if Cloud-Init is still provisioning Docker Compose or if services are ready.
    Avoids browser Mixed Content blocks and CORS issues.
    """
    clean_ip = _sanitize_probe_host(ip)

    ssh_ok = _probe_tcp_port(clean_ip, 22, timeout=2.0)
    fe_probe = _probe_http_endpoint(f"http://{clean_ip}:3000", timeout=2.5)
    be_probe = _probe_http_endpoint(f"http://{clean_ip}:8000/health", timeout=2.5)

    all_ready = fe_probe["online"] and be_probe["online"]

    if all_ready:
        phase = "ready"
        summary = "Servicios en línea y respondiendo exitosamente (HTTP 200). Listo para acceder."
    elif ssh_ok:
        phase = "booting"
        summary = "Instancia EC2 activa. Cloud-Init está completando el aprovisionamiento (~1-2 min)..."
    else:
        phase = "offline"
        summary = "Instancia no accesible aún. Verifica que haya terminado de iniciar en AWS y la sesión del laboratorio esté activa."

    return {
        "ip": clean_ip,
        "ssh": {"port": 22, "open": ssh_ok},
        "frontend": {
            "port": 3000,
            "url": f"http://{clean_ip}:3000",
            "online": fe_probe["online"],
            "status": fe_probe["status"],
            "message": fe_probe["message"],
        },
        "backend": {
            "port": 8000,
            "url": f"http://{clean_ip}:8000/health",
            "online": be_probe["online"],
            "status": be_probe["status"],
            "message": be_probe["message"],
        },
        "all_ready": all_ready,
        "phase": phase,
        "summary": summary,
    }


@router.get("/probe-uc2-validation")
def probe_uc2_validation(
    ip: str = Query(..., description="Public IP of deployed Case 2 EC2 instance"),
):
    """
    Live Case 2 diagnostic assistant ('¿Funcionó mi despliegue?'):
    Probes /health and /files on the deployed EC2 instance server-side,
    avoiding HTTPS->HTTP Mixed Content blocks in the CloudMove browser session.
    """
    clean_ip = _sanitize_probe_host(ip)
    ssh_ok = _probe_tcp_port(clean_ip, 22, timeout=2.0)
    health_res = _fetch_json_endpoint(f"http://{clean_ip}:3000/health", timeout=3.5)
    if not health_res["ok"]:
        health_res = _fetch_json_endpoint(f"http://{clean_ip}:8000/health", timeout=3.0)
    files_res = _fetch_json_endpoint(f"http://{clean_ip}:3000/files", timeout=3.5)

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
    clean_ip = _sanitize_probe_host(ip)
    clean_rel = str(path or "").lstrip("/")
    if not clean_rel or ".." in clean_rel.split("/"):
        raise HTTPException(status_code=400, detail="Ruta de archivo inválida")
    target_url = f"http://{clean_ip}:3000/files/view?path={urllib.parse.quote(clean_rel)}"
    try:
        req = urllib.request.Request(target_url, headers={"User-Agent": "CloudMove-UC2-Viewer/1.0"})
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            return {
                "ok": True,
                "path": clean_rel,
                "origin_path": f"/{clean_rel}",
                "rootfs_path": f"/opt/cloudmove/os_capture/rootfs/{clean_rel}",
                "ebs_path": f"/mnt/cloudmove_ebs/rootfs/{clean_rel}",
                "size_bytes": len(raw),
                "content": text,
            }
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail=f"Archivo no accesible en EC2: HTTP {exc.code}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo leer el archivo desde {clean_ip}: {exc}")


@router.get("/probe-uc2-bundle")
def probe_uc2_bundle(
    ip: str = Query(..., description="Public IP of deployed Case 2 EC2 instance"),
):
    """Download os_real_files_bundle.tar.gz directly from the deployed EC2 instance."""
    clean_ip = _sanitize_probe_host(ip)
    target_url = f"http://{clean_ip}:3000/bundle.tar.gz"
    try:
        req = urllib.request.Request(target_url, headers={"User-Agent": "CloudMove-UC2-Bundle/1.0"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            raw = resp.read()
            return Response(
                content=raw,
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
    clean_ip = _sanitize_probe_host(ip)
    clean_rel = str(path or "").lstrip("/")
    if not clean_rel or ".." in clean_rel.split("/"):
        raise HTTPException(status_code=400, detail="Ruta de archivo inválida")
    target_url = f"http://{clean_ip}:3000/files/download?path={urllib.parse.quote(clean_rel)}"
    fname = Path(clean_rel).name or "migrated-file"
    try:
        req = urllib.request.Request(target_url, headers={"User-Agent": "CloudMove-UC2-DL/1.0"})
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            raw = resp.read()
            return Response(
                content=raw,
                media_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{fname}"'},
            )
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail=f"Archivo no disponible: HTTP {exc.code}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo descargar desde {clean_ip}: {exc}")


class Uc2StageInitRequest(BaseModel):
    stage_id: Optional[str] = None
    selected_paths: List[str] = Field(default_factory=list)
    migration_id: Optional[str] = None
    agent_id: Optional[str] = None


class Uc2StageCommitRequest(BaseModel):
    selected_paths: List[str] = Field(default_factory=list)
    migration_id: Optional[str] = None
    ec2_ip: Optional[str] = None


class Uc2DispatchAgentStageRequest(BaseModel):
    selected_paths: List[str] = Field(default_factory=list)
    migration_id: Optional[str] = None
    agent_id: Optional[str] = None
    max_total_mb: int = Field(1500, ge=10, le=2048)


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


class Uc2BrowserFileItem(BaseModel):
    rel_path: str
    content_b64: str


class Uc2BrowserBatchRequest(BaseModel):
    files: List[Uc2BrowserFileItem] = Field(default_factory=list)
    selected_paths: List[str] = Field(default_factory=list)


@router.post("/uc2-stage/{stage_id}/upload-files")
def upload_uc2_stage_files_batch(
    stage_id: str,
    req: Uc2BrowserBatchRequest,
):
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

    api_url = _infer_public_api_url(http_request)
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
        clean_ip = _sanitize_probe_host(body.ec2_ip)
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
    """Check staging readiness + connected remote agent capabilities for Case 2 file uploads."""
    from app.migration.uc2_staging import find_ready_stage, get_stage_metadata
    from app.api.routers.agents import LATEST_AGENT_VERSION, _is_version_gte

    selected_paths: List[str] = []
    if paths:
        try:
            parsed = json.loads(paths)
            selected_paths = [str(p) for p in parsed] if isinstance(parsed, list) else []
        except Exception:
            selected_paths = [p.strip() for p in paths.split(",") if p.strip()]

    db = get_transactional_db()
    remote_agents = [
        a for a in db.list_agents(include_revoked=False)
        if (a.get("hostname") or "").lower() not in ("cloudmove-server", "localhost")
        and a.get("ip_address") != "100.50.88.231"
    ]
    online = next((a for a in remote_agents if a.get("status") == "ONLINE"), remote_agents[0] if remote_agents else None)
    ag_ver = str((online or {}).get("version") or "2.1.0")
    supports_staging = bool(online and _is_version_gte(ag_ver, LATEST_AGENT_VERSION))

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

    api_url = _infer_public_api_url(http_request)
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
    """Request the enrolled remote agent to pack and upload selected folders/files to staging."""
    from app.migration.uc2_staging import create_or_get_stage, get_stage_metadata
    from app.api.routers.agents import LATEST_AGENT_VERSION, _is_version_gte

    if not req.selected_paths:
        raise HTTPException(status_code=400, detail="Debes seleccionar al menos una carpeta o archivo.")

    db = get_transactional_db()
    remote_agents = [
        a for a in db.list_agents(include_revoked=False)
        if a.get("status") == "ONLINE"
        and (a.get("hostname") or "").lower() not in ("cloudmove-server", "localhost")
        and a.get("ip_address") != "100.50.88.231"
    ]
    agent = (
        next((a for a in remote_agents if a.get("agent_id") == req.agent_id), None)
        if req.agent_id
        else (remote_agents[0] if remote_agents else None)
    )
    if not agent:
        raise HTTPException(status_code=404, detail="No hay ningún agente remoto ONLINE conectado.")

    api_url = _infer_public_api_url(http_request)
    upgrade_cmd = f"curl -sSL {api_url}/api/v1/agents/install.sh | sudo bash -s -- --upgrade"
    ag_ver = str(agent.get("version") or "2.1.0")
    if not _is_version_gte(ag_ver, LATEST_AGENT_VERSION):
        return {
            "dispatched": False,
            "upgrade_required": True,
            "agent_id": agent["agent_id"],
            "agent_version": ag_ver,
            "latest_agent_version": LATEST_AGENT_VERSION,
            "upgrade_command_linux": upgrade_cmd,
            "message": f"El agente instalado en '{agent['hostname']}' usa v{ag_ver}. Actualízalo a v{LATEST_AGENT_VERSION} con el comando sugerido o sube la carpeta directamente desde tu navegador.",
        }

    meta = create_or_get_stage(
        selected_paths=req.selected_paths,
        agent_id=agent["agent_id"],
        migration_id=req.migration_id,
        source_type="agent",
    )
    task = db.create_agent_task(
        agent_id=agent["agent_id"],
        action="stage_selected_paths",
        parameters={
            "stage_id": meta["stage_id"],
            "selected_paths": req.selected_paths,
            "migration_id": req.migration_id,
            "max_total_mb": req.max_total_mb,
        },
        timeout_seconds=900,
    )
    return {
        "dispatched": True,
        "upgrade_required": False,
        "task": task,
        "stage": get_stage_metadata(meta["stage_id"], include_secrets=False),
    }


@router.get("/uc2-stage/{stage_id}/bundle.tar.gz")
def download_uc2_staged_bundle(stage_id: str, token: str = Query(...)):
    """Stream staged Case 2 archive to EC2 instances authenticating with per-stage token."""
    from app.migration.uc2_staging import verify_stage_download_token

    verified = verify_stage_download_token(stage_id, token)
    if not verified:
        raise HTTPException(status_code=403, detail="Token de descarga inválido o paquete no disponible.")
    bundle_path, _ = verified
    return FileResponse(
        path=str(bundle_path),
        media_type="application/gzip",
        filename=f"{stage_id}.tar.gz",
    )


class AwsAccountAuditRequest(BaseModel):
    credentials: Optional[Dict[str, str]] = None


class AwsAuditDeleteResourceRequest(BaseModel):
    resource_type: str = Field(..., description="ec2_instance | ebs_volume | vpc | security_group | terraform_workspace")
    resource_id: str = Field(..., description="Resource ID (e.g. i-..., vol-..., vpc-..., sg-..., mig-...)")
    cleanup_vpc: bool = True
    credentials: Optional[Dict[str, str]] = None


@router.get("/cloud-audit/aws")
def get_aws_account_audit():
    """
    Query active AWS account resources and local Terraform workspaces using cached/env credentials.
    """
    from app.migration.cloud_deployer import cloud_deployer
    res = cloud_deployer.audit_aws_account(credentials=None)
    for ev in res.get("ip_sync_events") or []:
        mig_id = ev.get("migration_id")
        if mig_id:
            try:
                job_dir = cloud_deployer.resolve_job_dir(mig_id)
                st = cloud_deployer.get_terraform_status(mig_id, job_dir)
                _sync_job_after_terraform(mig_id, st)
            except Exception:
                pass
    return res


@router.post("/cloud-audit/aws")
def post_aws_account_audit(request: Optional[AwsAccountAuditRequest] = None):
    """
    Query active AWS account resources (EC2, EBS, VPC, SGs, EIPs) and local Terraform workspaces
    using explicitly provided or cached AWS credentials.
    """
    from app.migration.cloud_deployer import cloud_deployer
    req = request or AwsAccountAuditRequest()
    res = cloud_deployer.audit_aws_account(credentials=req.credentials)
    for ev in res.get("ip_sync_events") or []:
        mig_id = ev.get("migration_id")
        if mig_id:
            try:
                job_dir = cloud_deployer.resolve_job_dir(mig_id)
                st = cloud_deployer.get_terraform_status(mig_id, job_dir)
                _sync_job_after_terraform(mig_id, st)
            except Exception:
                pass
    return res


@router.post("/cloud-audit/aws/delete-resource")
def delete_aws_audit_resource_endpoint(request: AwsAuditDeleteResourceRequest):
    """
    Terminate or delete a specific AWS resource or Terraform workspace discovered in the audit.
    """
    from app.migration.cloud_deployer import cloud_deployer
    return cloud_deployer.delete_aws_audit_resource(
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        credentials=request.credentials,
        cleanup_vpc=request.cleanup_vpc,
    )




