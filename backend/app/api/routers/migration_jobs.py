"""
Core CMIR Planning & Orchestrator Job Lifecycle Endpoints (`/api/v1/migration/jobs/*`).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, Optional
import zipfile

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse, PlainTextResponse

from app.adapters.aws_adapter import AWSAdapter
from app.api.routers.migration_helpers import sanitize_job_for_export, validate_target_provider
from app.api.routers.migration_schemas import (
    AdvanceMigrationJobRequest,
    ApproveMigrationJobRequest,
    CreateMigrationJobRequest,
    MarkIrreversibleRequest,
    RollbackOrCancelRequest,
    SelectionRequest,
)
from app.cmir.normalizer import normalize_inventory
from app.config import AWS_OUTPUT_PATH, INVENTORY_PATH
from app.dependencies.resolver import resolve_dependencies
from app.dependencies.validator import validate_migration_subgraph
from app.discovery.connectors import ConnectorError
from app.generators.terraform import generate_aws_terraform_files
from app.graph.builder import build_graph
from app.migration.orchestrator import migration_orchestrator
from app.migration.replication_and_import import (
    MACHINE_MIGRATION_COMPATIBILITY_MATRIX,
    select_machine_migration_strategy,
)
from app.persistence.transactional_db import (
    ConcurrencyConflictError,
    StageLockedError,
    get_transactional_db,
)

router = APIRouter()


def _load_cmir():
    if not INVENTORY_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Inventory file not found at {INVENTORY_PATH}")
    with open(INVENTORY_PATH, "r", encoding="utf-8") as file:
        inventory = json.load(file)
    return normalize_inventory(inventory)


@router.get("/providers")
def get_supported_providers():
    """Return supported target provider (`aws` exclusively) and its capabilities."""
    aws = AWSAdapter()
    return {
        "supported_providers": ["aws"],
        "excluded_providers": ["gcp", "azure", "kubernetes"],
        "providers": {
            "aws": {
                "config": aws.validate_target_config({}),
                "prerequisites": aws.check_permissions_and_prerequisites({}),
            },
        },
    }


@router.post("/dependencies")
def get_migration_dependencies(request: SelectionRequest):
    if not request.resources:
        raise HTTPException(status_code=400, detail="Debe seleccionar al menos un recurso o nivel jerárquico.")

    cmir = _load_cmir()
    graph = build_graph(cmir)
    return resolve_dependencies(
        graph,
        request.resources,
        validated_shared_resources=request.validated_shared_resources,
        include_inferred=request.include_inferred,
    )


@router.post("/validate")
def validate_migration(request: SelectionRequest):
    if not request.resources:
        raise HTTPException(status_code=400, detail="Debe seleccionar al menos un recurso para validar.")

    target = validate_target_provider(request.target_provider)
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
    return validate_migration_subgraph(sub_cmir, dep_analysis, target_provider=target)


@router.post("/generate")
def generate_migration_iac(request: SelectionRequest):
    if not request.resources:
        raise HTTPException(status_code=400, detail="Debe seleccionar al menos un recurso para migrar.")

    target = validate_target_provider(request.target_provider)
    cmir = _load_cmir()
    graph = build_graph(cmir)

    dep_analysis = resolve_dependencies(
        graph,
        request.resources,
        validated_shared_resources=request.validated_shared_resources,
        include_inferred=request.include_inferred,
    )
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

    if target != "aws":
        raise HTTPException(status_code=400, detail=f"Proveedor de destino '{target}' no soportado (exclusivo AWS).")

    adapter = AWSAdapter()
    translated_resources = adapter.translate_cmir(sub_cmir)
    files_map = generate_aws_terraform_files(translated_resources)
    output_path = AWS_OUTPUT_PATH
    code = files_map["main.tf"]

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


@router.get("/jobs")
def list_migration_jobs(
    use_case: Optional[str] = Query(None, description="app_source | vm_image"),
    target_provider: Optional[str] = Query(None, description="aws"),
):
    """List orchestrated migration jobs across all use cases."""
    if target_provider:
        validate_target_provider(target_provider)
    jobs = migration_orchestrator.list_migrations(use_case=use_case, target_provider=target_provider)
    return {"count": len(jobs), "jobs": jobs}


@router.post("/jobs")
def create_migration_job(request: CreateMigrationJobRequest):
    """Create and optionally assess/plan a new migration job."""
    target = validate_target_provider(request.target_provider)
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
    """Retrieve full state, stages, CMIR, dependencies, compatibility, artifacts and events."""
    try:
        return migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs/{migration_id}/bundle.zip")
def download_migration_bundle(migration_id: str):
    """Download complete production-ready ZIP package with Terraform IaC, guides, and scripts."""
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    artifacts = job.get("generated_artifacts") or {}
    files = dict(artifacts.get("files") or {})

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
    files["migration_report.json"] = json.dumps(sanitize_job_for_export(job), indent=2, ensure_ascii=False)

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
    """Get step-by-step markdown deployment instructions."""
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
    """Download compressed OS snapshot archive (.tar.gz)."""
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
            staging_dirs = [staging_root / f"live_capture_{job_slug}", staging_root / job_slug] + [
                d for d in staging_root.iterdir() if d.is_dir()
            ]
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
    return FileResponse(path=str(found_path), filename=found_path.name, media_type="application/gzip")


@router.get("/jobs/{migration_id}/disk-image")
def download_disk_image_file(
    migration_id: str,
    format: Optional[str] = Query(None, description="Target hypervisor format: 'vdi', 'vmdk', 'qcow2', 'raw'"),
):
    """Download generated binary virtual disk image, converting on-demand if needed."""
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

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
            if p.stat().st_size < 1024 * 1024 * 1024:
                found_path = p
                break

    if not found_path:
        staging_root = Path("generated/staging_images")
        if staging_root.is_dir():
            staging_dirs = [staging_root / f"live_capture_{job_slug}", staging_root / job_slug] + [
                d for d in staging_root.iterdir() if d.is_dir()
            ]
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
    return FileResponse(path=str(found_path), filename=found_path.name, media_type=media_type)


@router.get("/jobs/{migration_id}/hypervisor-script")
def download_hypervisor_script(
    migration_id: str,
    hypervisor: str = Query("virtualbox", description="Target hypervisor: 'virtualbox' or 'vmware'"),
):
    """Download automated launch script for VirtualBox or VMware."""
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
set -euo pipefail
VM_NAME="CloudMove-{job_slug}"
VMDK_IMAGE="{job_slug}.vmdk"
QCOW_IMAGE="{job_slug}.qcow2"
VMX_FILE="{job_slug}.vmx"
if [ ! -f "$VMDK_IMAGE" ] && [ -f "$QCOW_IMAGE" ]; then
    qemu-img convert -f qcow2 -O vmdk "$QCOW_IMAGE" "$VMDK_IMAGE"
fi
if [ ! -f "$VMDK_IMAGE" ]; then
    CLOUDMOVE_API_URL="${{CLOUDMOVE_API_URL:-http://localhost:8000}}"
    curl -fSL "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/disk-image?format=vmdk" -o "$VMDK_IMAGE" || true
fi
cat << 'EOF_VMX' > "$VMX_FILE"
.encoding = "UTF-8"
config.version = "8"
virtualHW.version = "19"
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
EOF_VMX
echo "Configuración VMware creada en $VMX_FILE."
"""
        filename = f"launch_vmware_{job_slug}.sh"
    else:
        content = f"""#!/usr/bin/env bash
set -euo pipefail
VM_NAME="CloudMove-{job_slug}"
VDI_IMAGE="{job_slug}.vdi"
QCOW_IMAGE="{job_slug}.qcow2"
MEMORY_MB=4096
CPUS=2
command -v VBoxManage >/dev/null 2>&1 || {{ echo "ERROR: VBoxManage no encontrado"; exit 1; }}
if [ ! -f "$VDI_IMAGE" ] && [ -f "$QCOW_IMAGE" ]; then
    qemu-img convert -f qcow2 -O vdi "$QCOW_IMAGE" "$VDI_IMAGE"
fi
if [ ! -f "$VDI_IMAGE" ]; then
    CLOUDMOVE_API_URL="${{CLOUDMOVE_API_URL:-http://localhost:8000}}"
    curl -fSL "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/disk-image?format=vdi" -o "$VDI_IMAGE" || true
fi
[ -f "$VDI_IMAGE" ] || {{ echo "ERROR: No se encontró '$VDI_IMAGE'"; exit 1; }}
VBoxManage showvminfo "$VM_NAME" >/dev/null 2>&1 && {{ VBoxManage controlvm "$VM_NAME" poweroff 2>/dev/null || true; VBoxManage unregistervm "$VM_NAME" --delete 2>/dev/null || true; }}
VBoxManage createvm --name "$VM_NAME" --ostype "Debian_64" --register
VBoxManage modifyvm "$VM_NAME" --memory "$MEMORY_MB" --cpus "$CPUS" --firmware "{boot_mode}" --nic1 nat --audio none --vram 128 --graphicscontroller vmsvga --boot1 disk
VBoxManage storagectl "$VM_NAME" --name "SATA Controller" --add sata --controller IntelAhci --portcount 2
VBoxManage storageattach "$VM_NAME" --storagectl "SATA Controller" --port 0 --device 0 --type hdd --medium "$(realpath "$VDI_IMAGE")"
echo "Máquina virtual '$VM_NAME' lista en VirtualBox."
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
    """Return transactional SQLite WAL status, schema migrations, and row counts."""
    return get_transactional_db().get_schema_status()


@router.get("/compatibility-matrix")
def get_machine_migration_compatibility_matrix(
    target_provider: str = Query("aws", description="aws"),
    source_type: str = Query("standalone_offline_disk_image"),
    disk_format: str = Query("VMDK"),
    os_family: str = Query("linux"),
    firmware_type: str = Query("UEFI"),
    total_size_gb: float = Query(60.0),
    prefer_continuous_replication: bool = Query(False),
):
    """Return AWS MGN & VM Import/Export compatibility matrix."""
    target = validate_target_provider(target_provider)
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
    return {"matrix": MACHINE_MIGRATION_COMPATIBILITY_MATRIX, "recommended_selection": selection}


@router.post("/jobs/{migration_id}/plan")
def plan_migration_job(migration_id: str, expected_version: Optional[int] = Query(None)):
    try:
        return migration_orchestrator.generate_plan_and_artifacts(migration_id, expected_version=expected_version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConcurrencyConflictError, StageLockedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{migration_id}/approve")
def approve_migration_job(migration_id: str, request: Optional[ApproveMigrationJobRequest] = None):
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
    try:
        return migration_orchestrator.retry_failed_stage(migration_id, expected_version=expected_version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConcurrencyConflictError, StageLockedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{migration_id}/mark-irreversible")
def mark_migration_job_irreversible(migration_id: str, request: MarkIrreversibleRequest):
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
    if not migration_orchestrator.delete_migration(migration_id):
        raise HTTPException(status_code=404, detail=f"Trabajo de migración '{migration_id}' no encontrado.")
    return {"status": "DELETED", "migration_id": migration_id}


@router.delete("/jobs")
def clear_all_migration_jobs():
    count = migration_orchestrator.clear_all_migrations()
    return {"status": "CLEARED", "deleted_count": count}
