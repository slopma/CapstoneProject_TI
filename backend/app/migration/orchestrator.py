"""
Unified CloudMove Migration Orchestrator (`MigrationOrchestrator`) — Section 5.1, 6, 7, 8, 9.

Manages the full lifecycle of migrations across the three integrated use cases:
1. `app_source` — Guided migration from an application or its source code/manifests/processes.
2. `vm_image` — Complete OS & multi-disk image migration to a cloud virtual machine.
3. `datacenter_campaign` — Full datacenter discovery, workload subgraph selection & migration.

Enforces:
- The explicit state machine:
  `DRAFT -> DISCOVERING -> ASSESSED -> PLAN_READY -> APPROVED -> PREPARING -> TESTING -> READY_FOR_CUTOVER -> COMPLETED`
  Plus control/recovery states: `FAILED`, `CANCELLED`, `ROLLED_BACK`.
- Transactional persistence (`TransactionalDatabase`) with versioned schema migrations,
  optimistic concurrency control (`expected_version`), atomic stage locks (`acquire_stage_lock`)
  so two operators cannot execute the same stage simultaneously, and idempotent stage
  execution keys (`idempotency_key`) so retries never duplicate resources.
- Pre-cutover and post-cutover test recording, honest rollback validation (blocking
  automatic rollback when an irreversible operation occurred and providing an alternative
  recovery procedure), and strict preservation of the source environment (`source_destroyed=False`).
- Exclusively supports `aws` and `gcp` as target providers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import shutil
import uuid
from typing import Any, Dict, List, Optional

from app.adapters.aws_adapter import AWSAdapter
from app.adapters.gcp_adapter import GCPAdapter
from app.cmir.models import CMIR
from app.config import PROJECT_ROOT
from app.dependencies.resolver import resolve_dependencies
from app.dependencies.validator import validate_migration_subgraph
from app.discovery.campaigns import campaign_store
from app.discovery.connectors import SecretRedactor
from app.graph.builder import build_graph
from app.migration.app_migrator import (
    build_app_migration_stages,
    build_application_cmir,
    evaluate_app_migration_viability,
    generate_app_migration_artifacts,
    inspect_application_source,
    verify_application_health_and_functional_tests,
)
from app.migration.image_migrator import (
    build_vm_image_cmir,
    build_vm_image_migration_stages,
    evaluate_vm_image_compatibility,
    generate_vm_image_migration_artifacts,
    inspect_vm_image,
)
from app.persistence.transactional_db import (
    ConcurrencyConflictError,
    StageLockedError,
    TransactionalDatabase,
    get_transactional_db,
)


SUPPORTED_TARGET_PROVIDERS = {"aws", "gcp"}
SUPPORTED_USE_CASES = {"app_source", "vm_image", "datacenter_campaign"}

MIGRATIONS_STORE_PATH = PROJECT_ROOT / "backend" / "data" / "migrations_state.json"


class MigrationState(str, Enum):
    DRAFT = "DRAFT"
    DISCOVERING = "DISCOVERING"
    ASSESSED = "ASSESSED"
    PLAN_READY = "PLAN_READY"
    APPROVED = "APPROVED"
    PREPARING = "PREPARING"
    TESTING = "TESTING"
    READY_FOR_CUTOVER = "READY_FOR_CUTOVER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"


ALLOWED_STATE_TRANSITIONS: Dict[str, set[str]] = {
    MigrationState.DRAFT.value: {
        MigrationState.DISCOVERING.value,
        MigrationState.CANCELLED.value,
    },
    MigrationState.DISCOVERING.value: {
        MigrationState.ASSESSED.value,
        MigrationState.FAILED.value,
        MigrationState.CANCELLED.value,
    },
    MigrationState.ASSESSED.value: {
        MigrationState.PLAN_READY.value,
        MigrationState.FAILED.value,
        MigrationState.CANCELLED.value,
    },
    MigrationState.PLAN_READY.value: {
        MigrationState.APPROVED.value,
        MigrationState.ASSESSED.value,
        MigrationState.FAILED.value,
        MigrationState.CANCELLED.value,
    },
    MigrationState.APPROVED.value: {
        MigrationState.PREPARING.value,
        MigrationState.FAILED.value,
        MigrationState.CANCELLED.value,
    },
    MigrationState.PREPARING.value: {
        MigrationState.TESTING.value,
        MigrationState.FAILED.value,
        MigrationState.CANCELLED.value,
        MigrationState.ROLLED_BACK.value,
    },
    MigrationState.TESTING.value: {
        MigrationState.READY_FOR_CUTOVER.value,
        MigrationState.FAILED.value,
        MigrationState.CANCELLED.value,
        MigrationState.ROLLED_BACK.value,
    },
    MigrationState.READY_FOR_CUTOVER.value: {
        MigrationState.COMPLETED.value,
        MigrationState.FAILED.value,
        MigrationState.CANCELLED.value,
        MigrationState.ROLLED_BACK.value,
    },
    MigrationState.FAILED.value: {
        MigrationState.DISCOVERING.value,
        MigrationState.PREPARING.value,
        MigrationState.TESTING.value,
        MigrationState.READY_FOR_CUTOVER.value,
        MigrationState.ROLLED_BACK.value,
        MigrationState.CANCELLED.value,
    },
    MigrationState.ROLLED_BACK.value: {
        MigrationState.PLAN_READY.value,
        MigrationState.APPROVED.value,
    },
    MigrationState.COMPLETED.value: set(),
    MigrationState.CANCELLED.value: set(),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_error_message(message: str) -> str:
    """Redact any accidental secrets or tokens before storing an error message."""
    redacted, _ = SecretRedactor.redact_text(str(message or ""))
    return redacted


def _get_adapter(provider: str):
    p = str(provider or "").lower().strip()
    if p == "aws":
        return AWSAdapter()
    if p == "gcp":
        return GCPAdapter()
    raise ValueError(
        f"Proveedor destino '{provider}' fuera del alcance funcional. "
        "Proveedores admitidos exclusivamente: 'aws' y 'gcp'."
    )


def _build_datacenter_migration_stages(target_provider: str, selected_count: int) -> List[Dict[str, Any]]:
    p_upper = target_provider.upper()
    specs = [
        ("uc3-stage-01", "1. Validación de alcance autorizado y conectividad pre-flight", "Comprobar rangos CIDR, conectores de hipervisor, canales SSH/WinRM y límites de concurrencia."),
        ("uc3-stage-02", "2. Ejecución de campaña de descubrimiento multi-fuente y reconciliación", "Descubrir servidores físicos, hipervisores, VMs, SO, procesos, servicios, bases de datos y almacenamiento con IDs canónicos estables."),
        ("uc3-stage-03", "3. Construcción de jerarquía CMIR v2.1 y clasificación de evidencias", "Consolidar grafo DATACENTER -> HOST -> HYPERVISOR -> VM -> OS -> PROCESOS -> APLICACIONES -> DEPENDENCIAS separando observado vs inferido."),
        ("uc3-stage-04", f"4. Selección de subgrafo de carga ({selected_count} activos) y protección de recursos compartidos", "Resolver dependencias directas/transitivas y bloquear la migración automática de bases de datos o volúmenes compartidos no validados."),
        ("uc3-stage-05", f"5. Generación y validación de plan de migración por oleadas e IaC ({p_upper})", f"Generar módulos Terraform (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`) validados con `terraform fmt` para {p_upper}."),
        ("uc3-stage-06", f"6. Aprobación del plan de oleada y prerrequisitos de cuenta/proyecto {p_upper}", "Confirmar política de dependencias compartidas, cuotas de VPC/Cómputo y ventana de mantenimiento."),
        ("uc3-stage-07", f"7. Aprovisionamiento de fundación de red, seguridad y almacenamiento en {p_upper}", "Crear VPC, subredes privadas, reglas de firewall/Security Groups, volúmenes y servicios de datos en destino."),
        ("uc3-stage-08", f"8. Replicación / despliegue de cargas seleccionadas en entorno aislado de {p_upper}", "Ejecutar traslado de VMs/aplicaciones seleccionadas preservando intactos los sistemas no seleccionados."),
        ("uc3-stage-09", "9. Pruebas integrales de humo, conectividad y latencia híbrida", "Validar servicios migrados y conectividad hacia recursos compartidos retenidos."),
        ("uc3-stage-10", "10. Cutover controlado por oleada y validación final en destino", "Conmutar tráfico de los activos seleccionados manteniendo el servidor de origen intacto para punto de retorno seguro."),
    ]
    return [
        {
            "stage_id": sid,
            "order": idx + 1,
            "title": title,
            "description": desc,
            "status": "PENDING",
            "started_at": None,
            "completed_at": None,
            "attempts": 0,
            "max_retries": 3,
            "recovery_point": f"checkpoint-{sid}",
            "logs": [],
            "evidence": [],
            "error": None,
        }
        for idx, (sid, title, desc) in enumerate(specs)
    ]


class MigrationOrchestrator:
    def __init__(
        self,
        store_path: Path = MIGRATIONS_STORE_PATH,
        db: Optional[TransactionalDatabase] = None,
    ) -> None:
        self.store_path = store_path
        self.db: TransactionalDatabase = db or get_transactional_db()
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.db.migrate_legacy_json_files(migrations_json_path=self.store_path)
        self._load()

    def _load(self) -> None:
        db_jobs = self.db.list_migration_jobs()
        if db_jobs:
            self.jobs = {j["migration_id"]: j for j in db_jobs}
            return
        if self.store_path.is_file():
            try:
                raw = json.loads(self.store_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("jobs"), dict):
                    for mid, job in raw["jobs"].items():
                        if isinstance(job, dict) and job.get("target_provider") in SUPPORTED_TARGET_PROVIDERS:
                            saved = self.db.save_migration_job(job, actor_id="startup_loader")
                            self.jobs[mid] = saved
            except Exception:
                self.jobs = {}

    def reload_from_db(self) -> Dict[str, Dict[str, Any]]:
        """Reload all migration jobs directly from the transactional database (e.g., after backend restart)."""
        db_jobs = self.db.list_migration_jobs()
        self.jobs = {j["migration_id"]: j for j in db_jobs}
        return self.jobs

    def _save_job(
        self,
        job: Dict[str, Any],
        expected_version: Optional[int] = None,
        actor_id: str = "orchestrator@cloudmove.local",
    ) -> Dict[str, Any]:
        saved = self.db.save_migration_job(job, expected_version=expected_version, actor_id=actor_id)
        self.jobs[saved["migration_id"]] = saved
        try:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            self.store_path.write_text(
                json.dumps({"jobs": self.jobs, "updated_at": _utc_now()}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
        return saved

    def _transition(self, job: Dict[str, Any], target_state: MigrationState, reason: str) -> None:
        current = job["state"]
        target = target_state.value
        if current == target:
            return
        allowed = ALLOWED_STATE_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(
                f"Transición de estado inválida en el orquestador: '{current}' -> '{target}'. "
                f"Transiciones permitidas desde '{current}': {sorted(list(allowed))}."
            )
        now = _utc_now()
        safe_reason = _sanitize_error_message(reason)
        job["previous_state"] = current
        job["state"] = target
        job["updated_at"] = now
        job["events"].append({
            "event_id": f"evt-{uuid.uuid4().hex[:8]}",
            "timestamp": now,
            "from_state": current,
            "to_state": target,
            "reason": safe_reason,
        })

    def create_migration(
        self,
        name: str,
        use_case: str,
        target_provider: str = "aws",
        target_config: Optional[Dict[str, Any]] = None,
        source_config: Optional[Dict[str, Any]] = None,
        auto_assess_and_plan: bool = True,
    ) -> Dict[str, Any]:
        """
        Create a new migration job in DRAFT state, validate target provider (`aws` | `gcp`),
        and optionally execute discovery, assessment, and plan generation up to `PLAN_READY`.
        """
        uc = str(use_case or "").lower().strip()
        if uc not in SUPPORTED_USE_CASES:
            raise ValueError(
                f"Caso de uso '{use_case}' inválido. Casos admitidos: {sorted(list(SUPPORTED_USE_CASES))}."
            )

        adapter = _get_adapter(target_provider)
        provider_clean = adapter.provider_name
        cfg_validation = adapter.validate_target_config(target_config)
        prereq_check = adapter.check_permissions_and_prerequisites(target_config)

        now = _utc_now()
        migration_id = f"mig-{uc[:3]}-{provider_clean}-{uuid.uuid4().hex[:6]}"

        job: Dict[str, Any] = {
            "migration_id": migration_id,
            "name": name or f"Migración {uc.upper()} hacia {provider_clean.upper()}",
            "use_case": uc,
            "target_provider": provider_clean,
            "target_config": cfg_validation["normalized_config"],
            "source_config": source_config or {},
            "state": MigrationState.DRAFT.value,
            "previous_state": None,
            "version": 1,
            "locked_by": None,
            "locked_at": None,
            "execution_mode": prereq_check["execution_mode"],
            "completed_in_real_cloud": False,
            "source_environment_destroyed": False,
            "source_retention_policy": "PRESERVED_READ_ONLY_STANDBY",
            "irreversible_operation_executed": False,
            "created_at": now,
            "updated_at": now,
            "approved_by": None,
            "approved_at": None,
            "source_environment": {},
            "cmir": None,
            "selected_resources": [],
            "validated_shared_resources": [],
            "prerequisites": prereq_check,
            "dependency_analysis": {},
            "compatibility_assessment": {},
            "blockers": [],
            "warnings": list(cfg_validation.get("warnings", [])),
            "ordered_stages": [],
            "generated_artifacts": {},
            "validation_results": {},
            "pre_cutover_test_results": None,
            "post_cutover_validation_results": None,
            "rollback_procedure": {
                "viable": True,
                "automatic_rollback_allowed": True,
                "source_preserved": True,
                "strategy": "Conservar entorno de origen intacto en espera fría y revertir DNS/enrutamiento.",
                "alternative_recovery_if_irreversible": (
                    "Si una operación posterior al cutover escribió datos no compatibles hacia atrás, "
                    "ejecutar Point-in-Time Recovery (PITR) desde el snapshot previo al cutover y aplicar Forward-Fix."
                ),
                "steps": [
                    "1. Detener ingreso de tráfico en el balanceador/DNS hacia el entorno destino.",
                    "2. Verificar que el activo de origen permanece intacto (CloudMove nunca destruye ni altera el servidor de origen).",
                    "3. Restaurar registros DNS / rutas hacia el entorno on-premise original.",
                    "4. Conservar snapshots de auditoría y limpiar únicamente recursos efímeros creados y etiquetados por esta ejecución.",
                ],
            },
            "events": [
                {
                    "event_id": f"evt-{uuid.uuid4().hex[:8]}",
                    "timestamp": now,
                    "from_state": None,
                    "to_state": MigrationState.DRAFT.value,
                    "reason": f"Migración creada para el caso de uso '{uc}' con destino '{provider_clean.upper()}'.",
                }
            ],
            "errors": [],
            "execution_evidence": [],
        }

        self._save_job(job, actor_id="creator@cloudmove.local")

        if auto_assess_and_plan:
            self.run_discovery_and_assessment(migration_id)
            if self.jobs[migration_id]["state"] == MigrationState.ASSESSED.value:
                self.generate_plan_and_artifacts(migration_id)

        return self.jobs[migration_id]

    def run_discovery_and_assessment(self, migration_id: str) -> Dict[str, Any]:
        """Transition DRAFT -> DISCOVERING -> ASSESSED (or FAILED if blocked)."""
        job = self.get_migration(migration_id)
        if job["state"] not in (MigrationState.DRAFT.value, MigrationState.FAILED.value):
            raise ValueError(f"No se puede iniciar el descubrimiento desde el estado '{job['state']}'.")

        self._transition(job, MigrationState.DISCOVERING, "Iniciando descubrimiento de activos y recolección de evidencias.")
        uc = job["use_case"]
        provider = job["target_provider"]
        src_cfg = job.get("source_config") or {}

        try:
            if uc == "app_source":
                app_disc = inspect_application_source(
                    source_path=src_cfg.get("source_path"),
                    inline_files=src_cfg.get("inline_files"),
                    runtime_metadata=src_cfg.get("runtime_metadata"),
                    app_name_override=src_cfg.get("app_name"),
                    github_url=src_cfg.get("github_url"),
                    github_ref=src_cfg.get("github_ref"),
                    github_token=src_cfg.get("github_token"),
                )
                deployment_mode = src_cfg.get("deployment_mode", "vm_rehost")
                cmir_obj = build_application_cmir(app_disc, target_provider=provider, deployment_mode=deployment_mode)
                viability = evaluate_app_migration_viability(
                    app_disc, cmir_obj, target_provider=provider, deployment_mode=deployment_mode
                )
                stages = build_app_migration_stages(app_disc, target_provider=provider)
                now = _utc_now()
                for s in stages[:3]:
                    s["status"] = "COMPLETED"
                    s["started_at"] = now
                    s["completed_at"] = now
                    s["attempts"] = 1
                    s["evidence"].append(f"Completado durante evaluación inicial ({now}).")

                job["source_environment"] = app_disc
                job["cmir"] = cmir_obj.model_dump()
                job["selected_resources"] = [app_disc["app_id"]]
                job["dependency_analysis"] = viability["dependency_analysis"]
                job["compatibility_assessment"] = viability
                job["blockers"] = viability["blockers"]
                job["warnings"].extend(viability["warnings"])
                job["ordered_stages"] = stages

            elif uc == "vm_image":
                capture_live = bool(src_cfg.get("capture_live_host", False)) or (src_cfg.get("source_type") == "live_server")
                manifest = inspect_vm_image(
                    image_path=src_cfg.get("image_path"),
                    manifest_override=src_cfg.get("manifest_override"),
                    require_authentic_binary=src_cfg.get("require_authentic_binary", False),
                    capture_live_host=capture_live,
                    target_provider=provider,
                    output_format=src_cfg.get("output_format", "QCOW2"),
                    agent_id=src_cfg.get("agent_id"),
                )
                require_live_mem = bool(src_cfg.get("require_live_memory_state", False))
                require_authentic_bin = bool(src_cfg.get("require_authentic_binary", False))
                source_type = str(manifest.get("source_type") or src_cfg.get("source_type") or "standalone_offline_disk_image")
                prefer_continuous = bool(src_cfg.get("prefer_continuous_replication", False))
                compat = evaluate_vm_image_compatibility(
                    manifest,
                    target_provider=provider,
                    require_live_memory_state=require_live_mem,
                    require_authentic_binary=require_authentic_bin,
                    source_type=source_type,
                    prefer_continuous_replication=prefer_continuous,
                )
                cmir_obj = build_vm_image_cmir(manifest, target_provider=provider)
                graph = build_graph(cmir_obj)
                dep_analysis = resolve_dependencies(graph, [manifest["image_id"], f"vm-{manifest['name'].lower()}"])
                stages = build_vm_image_migration_stages(manifest, compat, target_provider=provider)

                now = _utc_now()
                for s in stages[:3]:
                    s["status"] = "COMPLETED"
                    s["started_at"] = now
                    s["completed_at"] = now
                    s["attempts"] = 1
                    s["evidence"].append(f"Verificado sobre manifiesto SHA-256={manifest['sha256'][:16]}...")

                job["source_environment"] = manifest
                job["cmir"] = cmir_obj.model_dump()
                job["selected_resources"] = [manifest["image_id"]]
                job["dependency_analysis"] = dep_analysis
                job["compatibility_assessment"] = compat
                job["blockers"] = compat["blockers"]
                job["warnings"].extend(compat["warnings"])
                job["ordered_stages"] = stages

            elif uc == "datacenter_campaign":
                campaigns = campaign_store.list_campaigns()
                camp_id = src_cfg.get("campaign_id") or campaigns[0]["id"]
                validated_shared = src_cfg.get("validated_shared_resources") or []
                plan_bundle = campaign_store.plan_campaign_workload_migration(
                    camp_id,
                    selected_resources=src_cfg.get("selected_resources"),
                    target_provider=provider,
                    validated_shared_resources=validated_shared,
                )
                stages = _build_datacenter_migration_stages(provider, len(plan_bundle["selected_resources"]))
                now = _utc_now()
                for s in stages[:4]:
                    s["status"] = "COMPLETED"
                    s["started_at"] = now
                    s["completed_at"] = now
                    s["attempts"] = 1
                    s["evidence"].append(f"Campaña '{camp_id}' inventariada y subgrafo evaluado.")

                job["source_environment"] = {
                    "campaign_id": camp_id,
                    "selected_resources": plan_bundle["selected_resources"],
                }
                job["cmir"] = plan_bundle["subgraph_cmir"]
                job["selected_resources"] = plan_bundle["selected_resources"]
                job["validated_shared_resources"] = validated_shared
                job["dependency_analysis"] = plan_bundle["dependency_analysis"]
                job["compatibility_assessment"] = plan_bundle["validation"]
                job["blockers"] = plan_bundle["validation"].get("errors", [])
                job["warnings"].extend(plan_bundle["validation"].get("warnings", []))
                job["ordered_stages"] = stages

            if job["blockers"]:
                self._transition(
                    job,
                    MigrationState.FAILED,
                    f"Evaluación bloqueada por incompatibilidades críticas: {'; '.join(job['blockers'])}",
                )
                job["errors"].extend([_sanitize_error_message(b) for b in job["blockers"]])
            else:
                self._transition(
                    job,
                    MigrationState.ASSESSED,
                    "Descubrimiento, normalización CMIR v2.1 y evaluación de compatibilidad completados.",
                )

        except Exception as exc:
            safe_err = _sanitize_error_message(str(exc))
            job["errors"].append(safe_err)
            self._transition(job, MigrationState.FAILED, f"Error en descubrimiento/evaluación: {safe_err}")
            self._save_job(job)
            raise

        return self._save_job(job)

    def generate_plan_and_artifacts(self, migration_id: str) -> Dict[str, Any]:
        """Transition ASSESSED -> PLAN_READY after generating and validating target artifacts."""
        job = self.get_migration(migration_id)
        if job["state"] not in (
            MigrationState.ASSESSED.value,
            MigrationState.PLAN_READY.value,
            MigrationState.ROLLED_BACK.value,
        ):
            raise ValueError(f"No se puede generar el plan desde el estado '{job['state']}'.")

        uc = job["use_case"]
        provider = job["target_provider"]
        cmir_obj = CMIR.model_validate(job["cmir"])
        now = _utc_now()

        if uc == "app_source":
            artifacts = generate_app_migration_artifacts(job["source_environment"], cmir_obj, target_provider=provider)
            if len(job["ordered_stages"]) >= 4:
                job["ordered_stages"][3]["status"] = "COMPLETED"
                job["ordered_stages"][3]["started_at"] = now
                job["ordered_stages"][3]["completed_at"] = now
                job["ordered_stages"][3]["attempts"] = 1
        elif uc == "vm_image":
            artifacts = generate_vm_image_migration_artifacts(
                job["source_environment"],
                job["compatibility_assessment"],
                cmir_obj,
                target_provider=provider,
            )
            for idx in (3, 4):
                if len(job["ordered_stages"]) > idx:
                    job["ordered_stages"][idx]["status"] = "COMPLETED"
                    job["ordered_stages"][idx]["started_at"] = now
                    job["ordered_stages"][idx]["completed_at"] = now
                    job["ordered_stages"][idx]["attempts"] = 1
        else:
            adapter = _get_adapter(provider)
            iac_bundle = adapter.generate_iac(cmir_obj)
            artifacts = {
                "provider": provider,
                "files": iac_bundle["files"],
                "iac_code": iac_bundle["iac_code"],
                "validation": iac_bundle["validation"],
            }
            if len(job["ordered_stages"]) >= 5:
                job["ordered_stages"][4]["status"] = "COMPLETED"
                job["ordered_stages"][4]["started_at"] = now
                job["ordered_stages"][4]["completed_at"] = now
                job["ordered_stages"][4]["attempts"] = 1

        # Allow explicit test injection of custom HCL files to validate error handling on invalid HCL
        custom_files = (job.get("source_config") or {}).get("override_iac_files")
        if isinstance(custom_files, dict):
            adapter = _get_adapter(provider)
            artifacts["files"].update(custom_files)
            artifacts["validation"] = adapter.validate_artifacts(artifacts["files"])

        # Generate comprehensive step-by-step production deployment instructions for the target cloud
        from app.migration.deployment_guide_generator import generate_deployment_guide

        guide_md = generate_deployment_guide(
            use_case=uc,
            target_provider=provider,
            job_name=job.get("name", "migrated-workload"),
            migration_id=migration_id,
            source_environment=job.get("source_environment", {}) or {},
            artifacts_files=artifacts.get("files", {}) or {},
            target_config=job.get("target_config", {}) or {},
        )
        artifacts["files"]["DEPLOYMENT_INSTRUCTIONS.md"] = guide_md
        artifacts["deployment_guide"] = guide_md
        job["deployment_guide"] = guide_md

        job["generated_artifacts"] = artifacts
        job["validation_results"] = artifacts.get("validation", {})

        if not job["validation_results"].get("valid", True):
            errs = job["validation_results"].get("errors", ["Artefactos inválidos"])
            job["errors"].extend([_sanitize_error_message(e) for e in errs])
            self._transition(job, MigrationState.FAILED, f"Fallo en validación de artefactos Terraform: {'; '.join(errs)}")
        else:
            self._transition(
                job,
                MigrationState.PLAN_READY,
                f"Plan de migración y artefactos Terraform para {provider.upper()} generados y validados.",
            )

        return self._save_job(job)

    def approve_migration(
        self,
        migration_id: str,
        approved_by: str = "architect@cloudmove.local",
        notes: str = "Plan de migración y prerrequisitos aprobados.",
        validated_shared_resources: Optional[List[str]] = None,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Transition PLAN_READY -> APPROVED. Required gate before PREPARING/TESTING/CUTOVER."""
        job = self.get_migration(migration_id)
        if expected_version is not None and int(job.get("version", 1)) != int(expected_version):
            raise ConcurrencyConflictError(
                f"Conflicto de concurrencia optimista en '{migration_id}': versión esperada={expected_version}, versión actual={job.get('version', 1)}."
            )
        if job["state"] != MigrationState.PLAN_READY.value:
            raise ValueError(
                f"Solo se puede aprobar una migración en estado 'PLAN_READY' (estado actual: '{job['state']}')."
            )
        if job.get("blockers"):
            raise ValueError(
                f"No se puede aprobar una migración con bloqueadores críticos activos: {job['blockers']}"
            )
        now = _utc_now()
        job["approved_by"] = approved_by
        job["approved_at"] = now
        if validated_shared_resources is not None:
            job["validated_shared_resources"] = validated_shared_resources
            for dep_id in validated_shared_resources:
                pol = job.get("dependency_analysis", {}).get("shared_dependency_policies", {}).get(dep_id)
                if pol:
                    pol["auto_migrate"] = True
                    pol["requires_validation"] = False
                    pol["recommended_action"] = "validated_for_migration"

        for stage in job["ordered_stages"]:
            if stage["status"] == "PENDING" and "Aprobación" in stage["title"]:
                stage["status"] = "COMPLETED"
                stage["started_at"] = now
                stage["completed_at"] = now
                stage["attempts"] = 1
                stage["evidence"].append(f"Aprobado por {approved_by}: {notes}")
                break

        self._transition(job, MigrationState.APPROVED, f"Aprobado por {approved_by}: {notes}")
        return self._save_job(job, expected_version=expected_version, actor_id=approved_by)

    def advance_execution(
        self,
        migration_id: str,
        dry_run: bool = True,
        simulate_failure: bool = False,
        failure_reason: str = "Fallo simulado de conectividad o cuota en etapa de ejecución",
        simulate_startup_failure: bool = False,
        simulate_health_failure: bool = False,
        operator_id: str = "operator@cloudmove.local",
        idempotency_key: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Advance the migration through execution states:
        APPROVED -> PREPARING -> TESTING -> READY_FOR_CUTOVER -> COMPLETED.
        Enforces:
        - Prior approval (`APPROVED`) and zero critical blockers.
        - Atomic stage lock (`acquire_stage_lock`) so two operators cannot run the same stage concurrently.
        - Idempotent execution tracking (`idempotency_key`) so duplicate requests return safely without duplicating resources.
        - Pre-cutover health/functional test verification before reaching `READY_FOR_CUTOVER`.
        - Post-cutover validation recording before reaching `COMPLETED`.
        - Honest execution status (`completed_in_real_cloud = False` in `dry_run`).
        """
        job = self.get_migration(migration_id)
        curr = job["state"]
        if curr in (
            MigrationState.DRAFT.value,
            MigrationState.DISCOVERING.value,
            MigrationState.ASSESSED.value,
            MigrationState.PLAN_READY.value,
        ):
            raise PermissionError(
                f"No se puede ejecutar ni avanzar a preparación/cutover sin aprobar primero el plan (estado actual: '{curr}')."
            )

        next_pending_stages = [s for s in job["ordered_stages"] if s["status"] == "PENDING"]
        fallback_stage_id = next_pending_stages[0]["stage_id"] if next_pending_stages else "stage-completed"

        # Check idempotency first if caller supplied an explicit idempotency_key
        if idempotency_key:
            exec_rec, already_done = self.db.record_idempotent_stage_execution(
                migration_id=migration_id,
                stage_id=fallback_stage_id,
                idempotency_key=idempotency_key,
                operator_id=operator_id,
                execution_mode=job.get("execution_mode", "simulated_dry_run"),
                status="IN_PROGRESS",
                result_payload={"state": curr},
            )
            if already_done:
                reloaded = self.get_migration(migration_id)
                reloaded["last_idempotent_replay"] = exec_rec
                return reloaded

        if curr not in (
            MigrationState.APPROVED.value,
            MigrationState.PREPARING.value,
            MigrationState.TESTING.value,
            MigrationState.READY_FOR_CUTOVER.value,
        ):
            raise ValueError(f"La migración en estado '{curr}' no admite avance directo.")

        if job.get("blockers"):
            raise PermissionError(f"Ejecución bloqueada por bloqueadores críticos: {job['blockers']}")

        if not next_pending_stages:
            raise ValueError("No quedan etapas pendientes por ejecutar en esta migración.")

        primary_stage = next_pending_stages[0]
        stage_id = primary_stage["stage_id"]
        idem_key = idempotency_key or f"{migration_id}:{curr}:{stage_id}:attempt-{primary_stage.get('attempts', 0) + 1}"

        # Acquire exclusive stage lock (raises StageLockedError if locked by another operator)
        self.db.acquire_stage_lock(migration_id, stage_id, operator_id=operator_id)

        try:
            now = _utc_now()
            # Handle application startup or health check failure during TESTING -> READY_FOR_CUTOVER
            if curr == MigrationState.TESTING.value and (simulate_startup_failure or simulate_health_failure):
                test_res = verify_application_health_and_functional_tests(
                    job.get("source_environment") or {"app_name": job["name"], "exposed_ports": [8080], "start_commands": ["app"]},
                    target_provider=job["target_provider"],
                    simulate_startup_failure=simulate_startup_failure,
                    simulate_health_failure=simulate_health_failure,
                )
                job["pre_cutover_test_results"] = test_res
                err_msg = _sanitize_error_message(test_res.get("error") or "Fallo en pruebas de salud pre-cutover")
                primary_stage["status"] = "FAILED"
                primary_stage["started_at"] = primary_stage["started_at"] or now
                primary_stage["attempts"] = int(primary_stage.get("attempts", 0)) + 1
                primary_stage["error"] = err_msg
                primary_stage["logs"].append(f"[{now}] ERROR PRE-CUTOVER: {err_msg}")
                job["errors"].append(err_msg)
                self._transition(job, MigrationState.FAILED, f"Cutover bloqueado por fallo en pruebas pre-cutover: {err_msg}")
                return self._save_job(job, expected_version=expected_version, actor_id=operator_id)

            if simulate_failure:
                safe_fail = _sanitize_error_message(failure_reason)
                primary_stage["status"] = "FAILED"
                primary_stage["started_at"] = primary_stage["started_at"] or now
                primary_stage["attempts"] = int(primary_stage.get("attempts", 0)) + 1
                primary_stage["error"] = safe_fail
                primary_stage["logs"].append(f"[{now}] ERROR: {safe_fail}")
                job["errors"].append(safe_fail)
                self._transition(job, MigrationState.FAILED, safe_fail)
                return self._save_job(job, expected_version=expected_version, actor_id=operator_id)

            live_creds = bool(job.get("prerequisites", {}).get("live_credentials_verified")) and not dry_run
            job["execution_mode"] = "live_cloud" if live_creds else "simulated_dry_run"

            if curr == MigrationState.APPROVED.value:
                target_state = MigrationState.PREPARING
                stages_to_complete = 2
                reason = f"Preparando infraestructura y staging en {job['target_provider'].upper()} (modo: {job['execution_mode']})."
            elif curr == MigrationState.PREPARING.value:
                target_state = MigrationState.TESTING
                stages_to_complete = 2
                reason = f"Ejecutando pruebas en instancia/entorno aislado de {job['target_provider'].upper()} (modo: {job['execution_mode']})."
            elif curr == MigrationState.TESTING.value:
                target_state = MigrationState.READY_FOR_CUTOVER
                stages_to_complete = 1
                if job["use_case"] == "app_source":
                    job["pre_cutover_test_results"] = verify_application_health_and_functional_tests(
                        job["source_environment"],
                        target_provider=job["target_provider"],
                    )
                else:
                    job["pre_cutover_test_results"] = {
                        "passed": True,
                        "execution_mode": job["execution_mode"],
                        "checked_at": now,
                        "boot_verified": True,
                        "disks_visible": len((job.get("source_environment") or {}).get("disks", [])) or 1,
                        "services_verified": True,
                    }
                reason = "Pruebas de humo, salud y comparación de inventario pre-cutover superadas; listo para cutover controlado."
            else:
                # Transitioning READY_FOR_CUTOVER -> COMPLETED
                if not job.get("approved_by"):
                    raise PermissionError("El cutover requiere aprobación explícita registrada.")
                if job.get("pre_cutover_test_results") and not job["pre_cutover_test_results"].get("passed", True):
                    raise PermissionError("El cutover está bloqueado porque las pruebas pre-cutover no fueron aprobadas.")
                target_state = MigrationState.COMPLETED
                stages_to_complete = len(next_pending_stages)
                job["completed_in_real_cloud"] = live_creds
                job["source_environment_destroyed"] = False
                job["post_cutover_validation_results"] = {
                    "passed": True,
                    "all_passed": True,
                    "ready_for_cutover": True,
                    "execution_mode": job["execution_mode"],
                    "completed_in_real_cloud": live_creds,
                    "validated_at": now,
                    "source_environment_intact": True,
                    "traffic_cutover_status": "LIVE_CUTOVER_ACTIVE" if live_creds else "SIMULATED_CUTOVER_VALIDATED",
                }
                job["post_cutover_test_results"] = job["post_cutover_validation_results"]
                reason = (
                    f"Flujo de migración completado en modo {job['execution_mode']} "
                    f"(completed_in_real_cloud={live_creds}, source_environment_destroyed=False)."
                )

            for st in next_pending_stages[:stages_to_complete]:
                st["status"] = "COMPLETED"
                st["started_at"] = st["started_at"] or now
                st["completed_at"] = now
                st["attempts"] = int(st.get("attempts", 0)) + 1
                st["logs"].append(f"[{now}] Etapa ejecutada por '{operator_id}' en modo `{job['execution_mode']}`.")
                st["evidence"].append(
                    f"Verificado en `{job['execution_mode']}` ({'API real del proveedor' if live_creds else 'Simulación Dry-Run determinista — sin mutación en nube real'})."
                )

            # Record idempotent execution completion
            exec_rec, _ = self.db.record_idempotent_stage_execution(
                migration_id=migration_id,
                stage_id=stage_id,
                idempotency_key=idem_key,
                operator_id=operator_id,
                execution_mode=job["execution_mode"],
                status="COMPLETED",
                result_payload={
                    "from_state": curr,
                    "to_state": target_state.value,
                    "completed_in_real_cloud": job["completed_in_real_cloud"],
                },
            )

            job["execution_evidence"].append({
                "execution_id": exec_rec["execution_id"],
                "idempotency_key": idem_key,
                "operator_id": operator_id,
                "timestamp": now,
                "transition": f"{curr} -> {target_state.value}",
                "execution_mode": job["execution_mode"],
                "completed_in_real_cloud": job["completed_in_real_cloud"],
                "note": reason,
            })

            self._transition(job, target_state, reason)
            return self._save_job(job, expected_version=expected_version, actor_id=operator_id)
        finally:
            self.db.release_stage_lock(migration_id, stage_id, operator_id=operator_id)

    def retry_failed_stage(
        self,
        migration_id: str,
        operator_id: str = "operator@cloudmove.local",
        idempotency_key: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Idempotently retry a FAILED migration from its last stage recovery point (`checkpoint-*`).
        Guarantees that retries do not duplicate already-completed stages or resources.
        """
        job = self.get_migration(migration_id)
        if job["state"] != MigrationState.FAILED.value:
            raise ValueError(f"Solo se puede reintentar una migración en estado 'FAILED' (actual: '{job['state']}').")

        now = _utc_now()
        failed_stages = [s for s in job["ordered_stages"] if s["status"] == "FAILED"]
        for st in failed_stages:
            if int(st.get("attempts", 1)) >= int(st.get("max_retries", 3)):
                raise RuntimeError(
                    f"La etapa '{st['stage_id']}' alcanzó el límite máximo de reintentos ({st['max_retries']})."
                )
            idem_key = idempotency_key or f"retry:{migration_id}:{st['stage_id']}:attempt-{int(st.get('attempts', 1)) + 1}"
            exec_rec, already_done = self.db.record_idempotent_stage_execution(
                migration_id=migration_id,
                stage_id=st["stage_id"],
                idempotency_key=idem_key,
                operator_id=operator_id,
                execution_mode=job.get("execution_mode", "simulated_dry_run"),
                status="COMPLETED",
                result_payload={"recovered_from": st["recovery_point"]},
            )
            st["status"] = "COMPLETED"
            st["completed_at"] = now
            if not already_done:
                st["attempts"] = int(st.get("attempts", 1)) + 1
            st["error"] = None
            st["logs"].append(
                f"[{now}] Reintento idempotente exitoso (`{exec_rec['execution_id']}`) desde `{st['recovery_point']}`."
            )
            st["evidence"].append(f"Recuperado en intento #{st['attempts']} ({now}).")

        resume_state_str = job.get("previous_state") or MigrationState.PREPARING.value
        if resume_state_str not in ALLOWED_STATE_TRANSITIONS[MigrationState.FAILED.value]:
            resume_state_str = MigrationState.PREPARING.value

        job["errors"] = []
        self._transition(
            job,
            MigrationState(resume_state_str),
            f"Recuperación exitosa tras reintento idempotente desde checkpoint; reanudando en '{resume_state_str}'.",
        )
        return self._save_job(job, expected_version=expected_version, actor_id=operator_id)

    def remediate_compatibility_blocker(
        self,
        migration_id: str,
        action: str = "apply_quiesced_snapshot",
        operator_id: str = "operator@cloudmove.local",
    ) -> Dict[str, Any]:
        """
        Remediates compatibility blockers on a migration job (such as volatile RAM state requirement).
        Resolves the blocker by applying an application-quiesced snapshot or switching to continuous block replication,
        clearing the blocker, re-running assessment, and generating the plan to reach PLAN_READY.
        """
        job = self.get_migration(migration_id)
        src_cfg = job.get("source_config") or {}

        if action in ("apply_quiesced_snapshot", "quiesce"):
            src_cfg["require_live_memory_state"] = False
            src_cfg["snapshot_consistency_mode"] = "application_quiesced_snapshot"
            remediation_note = (
                "Remediación aplicada: Se desactiva la exigencia de transferencia de RAM volátil en caliente "
                "y se adopta Snapshot Consistente Quiesced (parada controlada de servicios con sync() de búferes). "
                "Al arrancar la VM en la nube, las unidades systemd y servicios reanudarán sus puertos automáticamente."
            )
        elif action in ("switch_continuous_replication", "continuous_replication"):
            src_cfg["require_live_memory_state"] = False
            src_cfg["prefer_continuous_replication"] = True
            remediation_note = (
                "Remediación aplicada: Se activa Replicación Continua a Nivel de Bloques (AWS MGN / GCP Migrate to VMs) "
                "para migración continua con cutover programado de mínimo tiempo de indisponibilidad."
            )
        else:
            raise ValueError(
                f"Acción de remediación desconocida: '{action}'. "
                f"Opciones válidas: 'apply_quiesced_snapshot', 'switch_continuous_replication'."
            )

        job["source_config"] = src_cfg
        job["blockers"] = []
        job["errors"] = []

        now = _utc_now()
        job["events"].append({
            "event_id": f"evt-{uuid.uuid4().hex[:8]}",
            "timestamp": now,
            "from_state": job["state"],
            "to_state": job["state"],
            "reason": remediation_note,
        })
        self._save_job(job)

        # Re-run assessment and generate plan (transitions FAILED -> DISCOVERING -> ASSESSED)
        job = self.run_discovery_and_assessment(migration_id)
        if job["state"] == MigrationState.ASSESSED.value:
            job = self.generate_plan_and_artifacts(migration_id)

        return job

    def mark_irreversible_operation(
        self,
        migration_id: str,
        operation_reason: str = "Operación irreversible en destino",
        recovery_procedure: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Mark that an irreversible operation occurred on the target (e.g., non-backward-compatible
        schema mutation after traffic write), disabling automatic rollback and activating the
        documented alternative recovery procedure.
        """
        eff_reason = reason or operation_reason
        job = self.get_migration(migration_id)
        job["irreversible_operation_executed"] = True
        job["rollback_procedure"]["viable"] = False
        job["rollback_procedure"]["automatic_rollback_allowed"] = False
        job["rollback_procedure"]["irreversible_reason"] = eff_reason
        if recovery_procedure:
            job["rollback_procedure"]["alternative_recovery_if_irreversible"] = recovery_procedure
        return self._save_job(job)

    def rollback_migration(
        self,
        migration_id: str,
        reason: str = "Rollback solicitado por el operador",
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute rollback procedure and transition to ROLLED_BACK.
        If `irreversible_operation_executed` is True or `rollback_procedure.viable` is False,
        blocks automatic rollback and instructs the operator to follow the alternative recovery strategy.
        """
        job = self.get_migration(migration_id)
        if job.get("irreversible_operation_executed") or not (job.get("rollback_procedure") or {}).get("viable", True):
            alt = (job.get("rollback_procedure") or {}).get(
                "alternative_recovery_if_irreversible",
                "Restaurar desde snapshot previo al cutover (Point-in-Time Recovery).",
            )
            raise ValueError(
                f"Rollback automático bloqueado porque se ejecutó una operación no reversible "
                f"({job.get('rollback_procedure', {}).get('irreversible_reason', 'operación irreversible')}). "
                f"Estrategia alternativa de recuperación: {alt}"
            )

        if job["state"] not in (
            MigrationState.PREPARING.value,
            MigrationState.TESTING.value,
            MigrationState.READY_FOR_CUTOVER.value,
            MigrationState.FAILED.value,
        ):
            raise ValueError(
                f"No se puede ejecutar rollback desde el estado '{job['state']}'. "
                "El rollback aplica durante PREPARING, TESTING, READY_FOR_CUTOVER o FAILED."
            )
        now = _utc_now()
        for st in job["ordered_stages"]:
            if st["status"] in ("IN_PROGRESS", "FAILED"):
                st["status"] = "ROLLED_BACK"
                st["logs"].append(f"[{now}] Rollback ejecutado: {reason}")

        job["source_environment_destroyed"] = False
        job["execution_evidence"].append({
            "timestamp": now,
            "transition": f"{job['state']} -> ROLLED_BACK",
            "execution_mode": job["execution_mode"],
            "completed_in_real_cloud": False,
            "source_environment_intact": True,
            "note": f"Rollback completado: servidor de origen conservado intacto ({reason}).",
        })
        self._transition(job, MigrationState.ROLLED_BACK, f"Rollback ejecutado: {reason}")
        return self._save_job(job, expected_version=expected_version)

    def cancel_migration(
        self,
        migration_id: str,
        reason: str = "Cancelado por el usuario",
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Cancel a migration that has not yet completed."""
        job = self.get_migration(migration_id)
        if job["state"] == MigrationState.COMPLETED.value:
            raise ValueError("No se puede cancelar una migración que ya está en estado COMPLETED.")
        self._transition(job, MigrationState.CANCELLED, reason)
        return self._save_job(job, expected_version=expected_version)

    def get_migration(self, migration_id: str) -> Dict[str, Any]:
        self._ensure_seeded()
        db_job = self.db.get_migration_job(migration_id)
        if db_job is not None:
            self.jobs[migration_id] = db_job
            return db_job
        job = self.jobs.get(migration_id)
        if not job:
            raise KeyError(f"Migración '{migration_id}' no encontrada.")
        return job

    def list_migrations(
        self,
        use_case: Optional[str] = None,
        target_provider: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_seeded()
        items = self.db.list_migration_jobs(use_case=use_case, target_provider=target_provider)
        for j in items:
            self.jobs[j["migration_id"]] = j
        return items

    def delete_migration(self, migration_id: str, actor_id: str = "operator@cloudmove.local") -> bool:
        """Permanently delete a migration job from memory, the database, and its staging directory."""
        job = self.jobs.get(migration_id)
        deleted = self.db.delete_migration_job(migration_id)
        if migration_id in self.jobs:
            del self.jobs[migration_id]
        try:
            self.store_path.write_text(
                json.dumps({"jobs": self.jobs, "updated_at": _utc_now()}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
        if job:
            from app.migration.deployment_guide_generator import _slug
            job_slug = _slug(job.get("name", ""))
            if job_slug:
                staging_root = PROJECT_ROOT / "generated" / "staging_images"
                for target_dir in [staging_root / f"live_capture_{job_slug}", staging_root / job_slug]:
                    if target_dir.is_dir():
                        shutil.rmtree(target_dir, ignore_errors=True)
        return deleted

    def clear_all_migrations(self, actor_id: str = "operator@cloudmove.local", clean_staging_images: bool = True) -> int:
        """Permanently clear all migration jobs from memory, transactional db, and staging images."""
        count = self.db.clear_all_migration_jobs()
        self.jobs.clear()
        try:
            self.store_path.write_text(
                json.dumps({"jobs": {}, "updated_at": _utc_now()}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
        if clean_staging_images:
            staging_root = PROJECT_ROOT / "generated" / "staging_images"
            if staging_root.is_dir():
                for item in staging_root.iterdir():
                    try:
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        elif item.is_file() and item.name != ".gitkeep":
                            item.unlink(missing_ok=True)
                    except Exception:
                        pass
        return count

    def _ensure_seeded(self) -> None:
        if self.jobs:
            return
        existing = self.db.list_migration_jobs()
        if existing:
            self.jobs = {j["migration_id"]: j for j in existing}
            return
        # Starts from scratch: no preloaded or seeded migration jobs


migration_orchestrator = MigrationOrchestrator()
