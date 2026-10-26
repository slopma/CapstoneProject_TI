import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import zipfile
from fastapi import APIRouter, HTTPException, Query, Response
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
    use_case: str = Field(..., description="app_source | vm_image | datacenter_campaign")
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
    use_case: Optional[str] = Query(None, description="app_source | vm_image | datacenter_campaign"),
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

    # Include full job metadata report for audit
    files["migration_report.json"] = json.dumps(job, indent=2, ensure_ascii=False)

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
        cmir_obj = build_application_cmir(app_disc, target_provider=target, deployment_mode=req.deployment_mode)
        viability = evaluate_app_migration_viability(app_disc, cmir_obj, target_provider=target, deployment_mode=req.deployment_mode)
        return {
            "use_case": "app_source",
            "target_provider": target,
            "application": app_disc,
            "cmir": cmir_obj.model_dump(),
            "viability": viability,
        }
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectorError as exc:
        status = 404 if exc.code == "GITHUB_NOT_FOUND" else (400 if exc.code in ("GITHUB_REF_NOT_FOUND", "GITHUB_RATE_LIMIT") else 502)
        raise HTTPException(status_code=status, detail=exc.message) from exc


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
                "github_token": req.github_token,
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
        cmir_obj = build_vm_image_cmir(manifest, target_provider=target)
        return {
            "use_case": "vm_image",
            "target_provider": target,
            "manifest": manifest,
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
            },
            auto_assess_and_plan=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
