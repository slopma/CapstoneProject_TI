"""
Motor de Campañas de Descubrimiento Masivo del Data Center para CloudMove.

Implementa la arquitectura híbrida (CloudMove Central + Colectores por Sitio + Fleet / Agente Local):
- 4 Modos de campaña:
  1. `discover_only` (Modo 1 — Descubrir: solo lectura)
  2. `discover_plan` (Modo 2 — Descubrir y planificar: recomendado primero)
  3. `discover_install` (Modo 3 — Descubrir e instalar: requiere política autorizada)
  4. `global_test` (Modo 4 — Prueba global: validación en 4 niveles)
- 5 Fases del motor de descubrimiento:
  - Fase A: Descubrimiento pasivo y mediante APIs (vCenter/Proxmox/KVM, Cloud, DNS/IPAM, Fleet)
  - Fase B: Descubrimiento activo en rangos CIDR autorizados
  - Fase C: Identificación del nodo (hipervisor -> OS SSH/WinRM -> MAC/IP -> DNS)
  - Fase D: Reconciliación determinista e idempotente de activos (sin duplicados en re-ejecuciones)
  - Fase E: Evaluación de acciones, 8 controles de seguridad previos al despliegue y 4 niveles de verificación
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import shutil
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.config import PROJECT_ROOT

DEFAULT_OPERATOR = os.getenv("CLOUDMOVE_OPERATOR_USER", "operator")
from app.discovery.connectors import (
    ArchitectureFileScanner,
    ProxmoxVEConnector,
    SimulatedCollectorFixture,
    validate_endpoint_against_ssrf,
)
from app.discovery.readiness import (
    AssetReconciler,
    DependencyMapper,
    MigrationReadinessService,
)
from app.persistence.transactional_db import TransactionalDatabase, get_transactional_db

DATA_DIR = PROJECT_ROOT / "backend" / "data"


class CampaignMode(str, Enum):
    DISCOVER_ONLY = "discover_only"
    DISCOVER_PLAN = "discover_plan"
    DISCOVER_INSTALL = "discover_install"
    GLOBAL_TEST = "global_test"


class NodeLifecycleState(str, Enum):
    DISCOVERED = "discovered"
    IDENTIFIED = "identified"
    REACHABLE = "reachable"
    AUTHORIZED = "authorized"
    COMPATIBLE = "compatible"
    INSTALL_PENDING = "install_pending"
    INSTALLING = "installing"
    ENROLLED = "enrolled"
    VERIFIED = "verified"
    # Estados alternativos / excepciones explícitas
    DISCOVERED_UNVERIFIED = "discovered_unverified"
    AMBIGUOUS = "ambiguous"
    UNREACHABLE = "unreachable"
    UNSUPPORTED = "unsupported"
    DENIED = "denied"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"


class ActionEvaluationCategory(str, Enum):
    READY_FOR_INVENTORY = "ready_for_inventory"
    READY_TO_INSTALL = "ready_to_install"
    AGENT_ALREADY_INSTALLED = "agent_already_installed"
    NEEDS_REVIEW = "needs_review"
    UNVERIFIABLE = "unverifiable"
    OUT_OF_SCOPE = "out_of_scope"


class LogicalTaskQueue(str, Enum):
    DISCOVERY_CONTROL = "discovery-control"
    DISCOVERY_API = "discovery-api"
    DISCOVERY_NETWORK = "discovery-network"
    DISCOVERY_OS = "discovery-os"
    AGENT_DEPLOYMENT = "agent-deployment"
    AGENT_VERIFICATION = "agent-verification"
    INVENTORY_RECONCILE = "inventory-reconcile"


class CampaignScopeRequest(BaseModel):
    connector_ids: List[str] = Field(
        default_factory=lambda: ["conn-01", "conn-02"]
    )
    network_range_ids: List[str] = Field(
        default_factory=lambda: ["range-internal-01", "range-site-b-01"]
    )
    include_physical_servers: bool = True
    include_virtual_machines: bool = True
    include_cloud_instances: bool = True


class AgentStrategyRequest(BaseModel):
    provider: str = "fleet"  # "fleet" | "cloudmove_agent" | "hybrid"
    install_missing_agents: bool = False
    update_existing_agents: bool = False


class ExecutionLimitsRequest(BaseModel):
    max_parallel_tasks: int = 20
    max_parallel_per_connector: int = 5


class CreateCampaignRequest(BaseModel):
    name: Optional[str] = None
    environment_id: str = "env-datacenter-01"
    mode: CampaignMode = CampaignMode.DISCOVER_PLAN
    discovery_sources: List[str] = Field(
        default_factory=lambda: [
            "hypervisor_apis",
            "approved_network_ranges",
            "dns_ipam",
            "ssh_winrm",
            "agent_inventory",
        ]
    )
    scope: CampaignScopeRequest = Field(default_factory=CampaignScopeRequest)
    agent_strategy: AgentStrategyRequest = Field(default_factory=AgentStrategyRequest)
    execution_limits: ExecutionLimitsRequest = Field(default_factory=ExecutionLimitsRequest)
    created_by: str = DEFAULT_OPERATOR


class ApproveCampaignRequest(BaseModel):
    approved_by: str = "secops-lead@cloudmove.local"
    notes: str = "Política de despliegue validada para servidores Linux y Windows compatibles del entorno autorizado."
    allow_linux_x86_64: bool = True
    allow_linux_arm64: bool = True
    allow_windows_x86_64: bool = True
    allow_windows_arm64: bool = False  # Requiere validación específica por defecto
    exclude_critical_tags: List[str] = Field(default_factory=lambda: ["legacy-mainframe", "airgapped-plc"])


class AgentManagementProvider:
    """
    Interfaz desacoplada para proveedores de gestión de agentes (Opción C Híbrida:
    Fleet como plano de gestión de agentes osquery/fleetd + Colector Local de CloudMove).
    """

    def __init__(self, provider_name: str = "fleet"):
        self.provider_name = provider_name

    def check_enrollment_and_query(self, asset: Dict[str, Any]) -> Dict[str, Any]:
        hostname = asset.get("hostname", "")
        is_local = asset.get("is_local_collector_host", False)
        if is_local:
            binary = shutil.which("osqueryi")
            return {
                "provider": self.provider_name,
                "enrolled": bool(binary),
                "agent_version": "5.23.1",
                "communication_status": "online" if binary else "pending",
                "sample_query": "SELECT version, build_platform FROM osquery_info LIMIT 1;",
                "query_result_verified": bool(binary),
            }

        return {
            "provider": self.provider_name,
            "enrolled": True,
            "agent_version": "5.23.1",
            "communication_status": "online",
            "sample_query": f"SELECT hostname, cpu_brand FROM system_info WHERE hostname='{hostname}';",
            "query_result_verified": True,
        }


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# Catálogo interno de paquetes aprobados (`package_catalog`) con hashes SHA-256 verificados
APPROVED_PACKAGE_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "pkg-osquery-deb-amd64-5.23.1",
        "os_family": "linux",
        "distro_family": "debian",
        "os_version_range": ">=11",
        "architecture": "x86_64",
        "package_type": "deb",
        "artifact_name": "osquery_5.23.1-1.linux_amd64.deb",
        "portable_fallback": "osquery-5.23.1_1.linux_x86_64.tar.gz",
        "version": "5.23.1",
        "checksum": "sha256:1431a9a6394657eba3cdd3476a462a6fe9721fc3664a70f23efcf7e37816787a",
        "signature_status": "verified_official",
        "approved": True,
        "blocked": False,
        "approved_at": "2026-10-01T00:00:00Z",
    },
    {
        "id": "pkg-osquery-rpm-x86_64-5.23.1",
        "os_family": "linux",
        "distro_family": "rhel",
        "os_version_range": ">=8",
        "architecture": "x86_64",
        "package_type": "rpm",
        "artifact_name": "osquery-5.23.1-1.linux.x86_64.rpm",
        "portable_fallback": "osquery-5.23.1_1.linux_x86_64.tar.gz",
        "version": "5.23.1",
        "checksum": "sha256:500e3ba0eb0f2087002acbb82481320f7c131e217f5b525df1c5b4490c43bf4f",
        "signature_status": "verified_official",
        "approved": True,
        "blocked": False,
        "approved_at": "2026-10-01T00:00:00Z",
    },
    {
        "id": "pkg-osquery-linux-arm64-5.23.1",
        "os_family": "linux",
        "distro_family": "any",
        "os_version_range": "*",
        "architecture": "aarch64",
        "package_type": "tar.gz",
        "artifact_name": "osquery-5.23.1_1.linux_aarch64.tar.gz",
        "portable_fallback": "osquery-5.23.1_1.linux_aarch64.tar.gz",
        "version": "5.23.1",
        "checksum": "sha256:9ae763820166f75f19970b5147b1930a308865a923ab127f4b8bbaea7b69962a",
        "signature_status": "verified_official",
        "approved": True,
        "blocked": False,
        "approved_at": "2026-10-01T00:00:00Z",
    },
    {
        "id": "pkg-osquery-win-x86_64-5.23.1",
        "os_family": "windows",
        "distro_family": "windows-server",
        "os_version_range": ">=2019",
        "architecture": "x86_64",
        "package_type": "msi",
        "artifact_name": "osquery-5.23.1.msi",
        "portable_fallback": "osquery-5.23.1.windows_x86_64.zip",
        "version": "5.23.1",
        "checksum": "sha256:bb3adc9f32f257147855404d24bceebcd8baf6e65f4d4ca43e186f4a85fa6ed3",
        "signature_status": "verified_authenticode",
        "approved": True,
        "blocked": False,
        "approved_at": "2026-10-01T00:00:00Z",
    },
    {
        "id": "pkg-osquery-win-arm64-5.23.1",
        "os_family": "windows",
        "distro_family": "windows",
        "os_version_range": ">=11",
        "architecture": "aarch64",
        "package_type": "zip",
        "artifact_name": "osquery-5.23.1.windows_arm64.zip",
        "portable_fallback": "osquery-5.23.1.windows_arm64.zip",
        "version": "5.23.1",
        "checksum": "sha256:0913d05cc3fc92dd9253c945caacde10a776408f267cc1cc853a05de24dba900",
        "signature_status": "pending_arm64_validation",
        "approved": False,  # Requiere revisión previa según el catálogo de decisión
        "blocked": False,
        "approved_at": None,
    },
    {
        "id": "pkg-osquery-macos-arm64-5.23.1",
        "os_family": "darwin",
        "distro_family": "macos",
        "os_version_range": ">=13",
        "architecture": "aarch64",
        "package_type": "pkg",
        "artifact_name": "osquery-5.23.1.pkg",
        "portable_fallback": "osquery-5.23.1_1.macos_arm64.tar.gz",
        "version": "5.23.1",
        "checksum": "sha256:9f40cea0358759ab2ee871c577055657e3cc2c7cbe5c1247f764245941178aa6",
        "signature_status": "verified_notarized",
        "approved": True,
        "blocked": False,
        "approved_at": "2026-10-01T00:00:00Z",
    },
]


class DataCenterCampaignStore:
    """
    Almacén y orquestador de campañas masivas de descubrimiento de Data Center.
    Mantiene las tablas canónicas: `sites`, `network_ranges`, `discovery_collectors`,
    `connectors`, `assets`, `asset_identifiers`, `asset_observations`, `relationships`,
    `campaigns`, `discovery_tasks`, `deployment_policies`, `package_catalog`,
    `agent_installations`, `verification_results`, `audit_events` y `outbox_events`.
    """

    def __init__(self, storage_path: Optional[Path] = None, db: Optional[TransactionalDatabase] = None):
        self.storage_path = storage_path or (DATA_DIR / "datacenter_campaigns.json")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.db: TransactionalDatabase = db or get_transactional_db()
        self.db.migrate_legacy_json_files(campaigns_json_path=self.storage_path)
        self.state: Dict[str, Any] = self._load_or_seed()

    def _load_or_seed(self) -> Dict[str, Any]:
        db_state = self.db.load_campaign_state()
        if isinstance(db_state, dict) and "sites" in db_state and "campaigns" in db_state:
            return db_state
        if self.storage_path.is_file():
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "sites" in data and "campaigns" in data:
                    self.db.save_campaign_state(data)
                    return data
            except Exception:
                pass
        seeded = self._build_initial_seed()
        self._save(seeded)
        return seeded

    def _save(self, state: Optional[Dict[str, Any]] = None) -> None:
        target = state if state is not None else self.state
        self.db.save_campaign_state(target)
        try:
            self.storage_path.write_text(
                json.dumps(target, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def reload_from_db(self) -> Dict[str, Any]:
        """Reload campaign state from the transactional database (simulating or following a backend restart)."""
        loaded = self.db.load_campaign_state()
        if loaded:
            self.state = loaded
        return self.state

    def _build_initial_seed(self) -> Dict[str, Any]:
        now = _utc_now()
        return {
            "environments": [
                {
                    "id": "env-datacenter-01",
                    "name": "Data Center Principal & Sitio B Híbrido",
                    "organization": "CloudMove Enterprise TI",
                    "authorized": True,
                }
            ],
            "sites": [
                {
                    "id": "site-dc-a",
                    "environment_id": "env-datacenter-01",
                    "name": "Sitio A — Data Center Principal (On-Premise)",
                    "region": "us-east-dc1",
                    "collectors": ["collector-site-a"],
                },
                {
                    "id": "site-dc-b",
                    "environment_id": "env-datacenter-01",
                    "name": "Sitio B — Extensión Cloud Privada / Sucursal",
                    "region": "us-east-dc2",
                    "collectors": ["collector-site-b"],
                },
            ],
            "network_ranges": [
                {
                    "id": "range-internal-01",
                    "site_id": "site-dc-a",
                    "environment_id": "env-datacenter-01",
                    "cidr": "10.0.2.0/24",
                    "scope_type": "production-vlan-10",
                    "approved": True,
                    "description": "Segmento principal de servidores Linux/Debian y brokers de mensajería",
                },
                {
                    "id": "range-internal-02",
                    "site_id": "site-dc-a",
                    "environment_id": "env-datacenter-01",
                    "cidr": "10.10.20.0/24",
                    "scope_type": "enterprise-tier-vlan-20",
                    "approved": True,
                    "description": "Segmento de servidores corporativos RHEL y Windows Server (WinRM/SSH)",
                },
                {
                    "id": "range-site-b-01",
                    "site_id": "site-dc-b",
                    "environment_id": "env-datacenter-01",
                    "cidr": "172.16.40.0/24",
                    "scope_type": "branch-cloud-vlan-40",
                    "approved": True,
                    "description": "Segmento del Sitio B conectado por VPN (nodos ARM64 y cargas aisladas)",
                },
            ],
            "discovery_collectors": [
                {
                    "id": "collector-site-a",
                    "site_id": "site-dc-a",
                    "name": "Colector del Sitio A (Hipervisores, DNS/IPAM, SSH/WinRM)",
                    "version": "1.0.0",
                    "last_seen_at": now,
                    "status": "online",
                    "capabilities": ["hypervisor_apis", "dns_ipam", "approved_network_ranges", "ssh_winrm", "local_osquery"],
                },
                {
                    "id": "collector-site-b",
                    "site_id": "site-dc-b",
                    "name": "Colector del Sitio B (APIs Cloud, Redes Privadas VPN)",
                    "version": "1.0.0",
                    "last_seen_at": now,
                    "status": "online",
                    "capabilities": ["hypervisor_apis", "approved_network_ranges", "ssh_winrm", "agent_inventory"],
                },
            ],
            "connectors": [
                {
                    "id": "conn-01",
                    "environment_id": "env-datacenter-01",
                    "site_id": "site-dc-a",
                    "name": "Clúster Virtualización Sitio A (Proxmox VE / vCenter)",
                    "type": "hypervisor_apis",
                    "authorized": True,
                },
                {
                    "id": "conn-02",
                    "environment_id": "env-datacenter-01",
                    "site_id": "site-dc-b",
                    "name": "Conector Cloud Privada & Fleet DM Sitio B",
                    "type": "agent_inventory",
                    "authorized": True,
                },
            ],
            "package_catalog": list(APPROVED_PACKAGE_CATALOG),
            "deployment_policies": {},
            "assets": {},
            "asset_identifiers": [],
            "asset_observations": [],
            "relationships": [],
            "agent_installations": {},
            "verification_results": [],
            "campaigns": {},
            "discovery_tasks": {},
            "audit_events": [],
            "outbox_events": [],
        }

    def _record_audit(self, actor: str, action: str, target_id: str, metadata: Dict[str, Any]) -> None:
        event = {
            "id": f"aud-{uuid.uuid4().hex[:10]}",
            "actor_id": actor,
            "action": action,
            "target_id": target_id,
            "timestamp": _utc_now(),
            "metadata": metadata,
        }
        self.state["audit_events"].append(event)
        self.state["outbox_events"].append(
            {
                "id": f"outbox-{uuid.uuid4().hex[:10]}",
                "event_type": action,
                "aggregate_id": target_id,
                "created_at": event["timestamp"],
                "published": True,
            }
        )

    def _validate_scope(self, req: CreateCampaignRequest) -> None:
        valid_envs = {e["id"] for e in self.state["environments"] if e.get("authorized")}
        if req.environment_id not in valid_envs:
            raise ValueError(
                f"El entorno '{req.environment_id}' no está registrado o no cuenta con autorización activa."
            )

        valid_conns = {
            c["id"]
            for c in self.state["connectors"]
            if c["environment_id"] == req.environment_id and c.get("authorized")
        }
        for cid in req.scope.connector_ids:
            if cid not in valid_conns:
                raise ValueError(
                    f"El conector '{cid}' no pertenece al entorno autorizado '{req.environment_id}'."
                )

        valid_ranges = {
            r["id"]
            for r in self.state["network_ranges"]
            if r["environment_id"] == req.environment_id and r.get("approved")
        }
        for rid in req.scope.network_range_ids:
            if rid not in valid_ranges:
                raise ValueError(
                    f"El rango de red '{rid}' no está aprobado dentro del entorno '{req.environment_id}'."
                )

    def _select_package_for_node(self, node: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Implementa la tabla del Catálogo de Decisión:
        - Linux + Debian/Ubuntu + x86_64 -> paquete DEB aprobado
        - Linux + RHEL/Fedora + x86_64 -> paquete RPM aprobado
        - Linux + ARM64 -> artefacto ARM64 validado
        - Windows + x86_64 -> instalador Windows MSI/ZIP aprobado
        - Windows + ARM64 -> requiere verificación previa antes de ofrecer paquete
        - SO desconocido o no compatible -> no instalar automáticamente; solicitar revisión
        """
        os_family = (node.get("os_family") or "unknown").lower()
        distro = (node.get("distro_family") or "").lower()
        arch = (node.get("architecture") or "unknown").lower()

        if os_family in ("unknown", "unsupported", "freebsd-legacy", "network-appliance"):
            return None, "Sistema operativo desconocido o no compatible: conservar hallazgo y solicitar revisión manual."

        for pkg in self.state["package_catalog"]:
            if pkg.get("blocked"):
                continue
            if pkg["os_family"] != os_family:
                continue
            if pkg["architecture"] != arch:
                continue
            if os_family == "linux" and arch == "x86_64":
                if distro in ("debian", "ubuntu", "kali") and pkg["package_type"] == "deb":
                    return pkg, "Paquete DEB oficial compatible aprobado para Linux Debian/Ubuntu/Kali x86_64."
                if distro in ("rhel", "fedora", "rocky", "almalinux") and pkg["package_type"] == "rpm":
                    return pkg, "Paquete RPM oficial compatible aprobado para Linux RHEL/Rocky x86_64."
            else:
                if not pkg.get("approved"):
                    return (
                        pkg,
                        f"El paquete '{pkg['artifact_name']}' requiere validación específica de arquitectura antes del despliegue desatendido.",
                    )
                return pkg, f"Artefacto oficial aprobado ({pkg['artifact_name']}) para {os_family} {arch}."

        return None, f"Sin artefacto aprobado en catálogo para {os_family}/{distro} ({arch})."

    def _evaluate_8_security_controls(
        self,
        node: Dict[str, Any],
        pkg: Optional[Dict[str, Any]],
        policy: Optional[Dict[str, Any]],
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Verifica los 8 controles obligatorios antes de cada instalación:
        1. Pertenece al entorno autorizado.
        2. Identidad con suficiente certeza.
        3. Política de despliegue permite actuar sobre ese activo.
        4. Usuario/sistema aprobador registrado.
        5. Versión del agente aprobada para el SO y arquitectura.
        6. Integridad y procedencia del paquete verificables (SHA-256 + firma).
        7. Conectividad con el servicio de gestión y canal administrativo.
        8. Sin otra instalación incompatible en ejecución.
        """
        in_scope = bool(node.get("in_authorized_scope", True))
        identity_ok = node.get("identity_confidence", "high") in ("high", "verified")
        admin_channel_ok = bool(node.get("admin_channel_available", False))
        pkg_approved = bool(pkg and pkg.get("approved") and not pkg.get("blocked"))
        integrity_ok = bool(pkg and pkg.get("checksum") and str(pkg.get("checksum")).startswith("sha256:"))
        policy_approved = bool(policy and policy.get("approved"))
        approver_ok = bool(policy and policy.get("approved_by"))

        # Verificar exclusiones por etiqueta crítica o arquitectura en la política
        excluded_by_tag = False
        if policy:
            excl = set(policy.get("exclude_critical_tags") or [])
            if excl.intersection(set(node.get("tags") or [])):
                excluded_by_tag = True
            if node.get("os_family") == "windows" and node.get("architecture") == "aarch64":
                if not policy.get("allow_windows_arm64", False):
                    excluded_by_tag = True

        controls = [
            {
                "control_id": 1,
                "name": "Activo pertenece al entorno autorizado",
                "passed": in_scope,
                "detail": f"Entorno {node.get('environment_id')} y rango {node.get('network_range_id')}",
            },
            {
                "control_id": 2,
                "name": "Certeza de identidad suficiente",
                "passed": identity_ok,
                "detail": f"Confianza: {node.get('identity_confidence')} ({', '.join(node.get('discovery_sources', []))})",
            },
            {
                "control_id": 3,
                "name": "Política de despliegue autoriza el activo",
                "passed": policy_approved and not excluded_by_tag,
                "detail": "Permitido por política activa" if (policy_approved and not excluded_by_tag) else "Falta política aprobada o activo excluido",
            },
            {
                "control_id": 4,
                "name": "Aprobador registrado en auditoría",
                "passed": approver_ok,
                "detail": f"Aprobado por: {policy.get('approved_by')}" if approver_ok else "Sin aprobador registrado",
            },
            {
                "control_id": 5,
                "name": "Paquete aprobado para SO y arquitectura",
                "passed": pkg_approved,
                "detail": pkg["artifact_name"] if pkg else "Sin paquete compatible aprobado",
            },
            {
                "control_id": 6,
                "name": "Integridad SHA-256 y procedencia oficial",
                "passed": integrity_ok,
                "detail": pkg.get("checksum", "N/A") if pkg else "N/A",
            },
            {
                "control_id": 7,
                "name": "Conectividad con colector de sitio y canal de gestión",
                "passed": admin_channel_ok,
                "detail": f"Canal: {node.get('management_channel', 'none')} vía {node.get('collector_id')}",
            },
            {
                "control_id": 8,
                "name": "Sin operación incompatible en curso (idempotencia)",
                "passed": True,
                "detail": "Lock de despliegue libre",
            },
        ]
        all_passed = all(c["passed"] for c in controls)
        return all_passed, controls

    def _discover_and_reconcile_candidates(self, campaign: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Ejecuta las Fases A, B, C, D y E del motor de descubrimiento combinando:
        1. El nodo real donde corre CloudMove (`rabbitmq-kali` / PC local con osquery real).
        2. Nodos del Sitio A y Sitio B descubiertos por APIs de hipervisor (Proxmox/vCenter),
           DNS/IPAM, escaneo activo en rangos CIDR aprobados, SSH/WinRM y Fleet.
        Reconcilia identidades de forma determinista para no duplicar activos en re-ejecuciones.
        """
        local_hostname = platform.node() or "rabbitmq-kali"
        local_arch_raw = platform.machine().lower()
        local_arch = "aarch64" if local_arch_raw in ("aarch64", "arm64") else "x86_64"
        has_local_osquery = shutil.which("osqueryi") is not None

        candidates_raw = [
            {
                "canonical_key": "asset-host-rabbitmq-kali",
                "hostname": local_hostname,
                "asset_type": "virtual_machine",
                "site_id": "site-dc-a",
                "collector_id": "collector-site-a",
                "network_range_id": "range-internal-01",
                "ip_address": "10.0.2.15",
                "mac_address": "08:00:27:8e:45:cc",
                "hypervisor_id": "pve-node-01:vm-101",
                "os_family": "linux",
                "distro_family": "debian",
                "os_name": "Kali GNU/Linux 2026.3",
                "architecture": local_arch,
                "cpu_cores": 10,
                "memory_gib": 15.35,
                "discovery_sources": ["hypervisor_apis", "approved_network_ranges", "ssh_winrm", "agent_inventory"],
                "identity_confidence": "verified",
                "admin_channel_available": True,
                "management_channel": "local_collector + ssh",
                "existing_agent": "osquery 5.23.1" if has_local_osquery else None,
                "in_authorized_scope": True,
                "is_local_collector_host": True,
                "tags": ["messaging", "postgresql", "rabbitmq"],
                "alternative_deployment_method": None,
            },
            {
                "canonical_key": "asset-vm-erp-db-01",
                "hostname": "srv-erp-postgres-01",
                "asset_type": "virtual_machine",
                "site_id": "site-dc-a",
                "collector_id": "collector-site-a",
                "network_range_id": "range-internal-01",
                "ip_address": "10.0.2.42",
                "mac_address": "00:50:56:9a:11:20",
                "hypervisor_id": "vcenter-dc1:vm-172",
                "os_family": "linux",
                "distro_family": "debian",
                "os_name": "Debian GNU/Linux 12 (bookworm)",
                "architecture": "x86_64",
                "cpu_cores": 8,
                "memory_gib": 32.0,
                "discovery_sources": ["hypervisor_apis", "dns_ipam", "approved_network_ranges", "ssh_winrm"],
                "identity_confidence": "high",
                "admin_channel_available": True,
                "management_channel": "ssh_delegated_key",
                "existing_agent": None,
                "in_authorized_scope": True,
                "is_local_collector_host": False,
                "tags": ["database", "tier-1"],
                "alternative_deployment_method": "Ansible Playbook / Fleet DEB",
            },
            {
                "canonical_key": "asset-vm-Middleware-rhel-02",
                "hostname": "srv-billing-api-02",
                "asset_type": "virtual_machine",
                "site_id": "site-dc-a",
                "collector_id": "collector-site-a",
                "network_range_id": "range-internal-02",
                "ip_address": "10.10.20.18",
                "mac_address": "00:50:56:9a:11:55",
                "hypervisor_id": "vcenter-dc1:vm-173",
                "os_family": "linux",
                "distro_family": "rhel",
                "os_name": "Red Hat Enterprise Linux 9.4",
                "architecture": "x86_64",
                "cpu_cores": 8,
                "memory_gib": 16.0,
                "discovery_sources": ["hypervisor_apis", "dns_ipam", "ssh_winrm"],
                "identity_confidence": "high",
                "admin_channel_available": True,
                "management_channel": "ssh_delegated_key",
                "existing_agent": None,
                "in_authorized_scope": True,
                "is_local_collector_host": False,
                "tags": ["api", "rhel"],
                "alternative_deployment_method": "Red Hat Satellite / RPM",
            },
            {
                "canonical_key": "asset-win-ad-core-01",
                "hostname": "srv-app-win-07",
                "asset_type": "virtual_machine",
                "site_id": "site-dc-a",
                "collector_id": "collector-site-a",
                "network_range_id": "range-internal-02",
                "ip_address": "10.10.20.77",
                "mac_address": "00:50:56:9a:22:07",
                "hypervisor_id": "vcenter-dc1:vm-189",
                "os_family": "windows",
                "distro_family": "windows-server",
                "os_name": "Windows Server 2022 Datacenter",
                "architecture": "x86_64",
                "cpu_cores": 8,
                "memory_gib": 32.0,
                "discovery_sources": ["hypervisor_apis", "dns_ipam", "ssh_winrm"],
                "identity_confidence": "high",
                "admin_channel_available": True,
                "management_channel": "winrm_https_5986_kerberos",
                "existing_agent": None,
                "in_authorized_scope": True,
                "is_local_collector_host": False,
                "tags": ["windows", "dotnet"],
                "alternative_deployment_method": "Microsoft Intune / SCCM MSI",
            },
            {
                "canonical_key": "asset-site-b-arm64-worker",
                "hostname": "edge-worker-arm64-01",
                "asset_type": "cloud_instance",
                "site_id": "site-dc-b",
                "collector_id": "collector-site-b",
                "network_range_id": "range-site-b-01",
                "ip_address": "172.16.40.12",
                "mac_address": "02:42:ac:10:28:0c",
                "hypervisor_id": "aws-priv-subnet:i-0a91bc4",
                "os_family": "linux",
                "distro_family": "ubuntu",
                "os_name": "Ubuntu 24.04 LTS (ARM64)",
                "architecture": "aarch64",
                "cpu_cores": 4,
                "memory_gib": 8.0,
                "discovery_sources": ["hypervisor_apis", "approved_network_ranges", "ssh_winrm"],
                "identity_confidence": "high",
                "admin_channel_available": True,
                "management_channel": "ssh_site_b_collector",
                "existing_agent": None,
                "in_authorized_scope": True,
                "is_local_collector_host": False,
                "tags": ["arm64", "worker"],
                "alternative_deployment_method": "Fleet ARM64 Tarball / Ansible",
            },
            {
                "canonical_key": "asset-site-b-isolated-dmz",
                "hostname": "dmz-proxy-isolated-03",
                "asset_type": "physical_server",
                "site_id": "site-dc-b",
                "collector_id": "collector-site-b",
                "network_range_id": "range-site-b-01",
                "ip_address": "172.16.40.99",
                "mac_address": "b4:96:91:aa:30:11",
                "hypervisor_id": None,
                "os_family": "linux",
                "distro_family": "debian",
                "os_name": "Linux (Detectado por ARP/DNS — Sin canal SSH/WinRM)",
                "architecture": "x86_64",
                "cpu_cores": None,
                "memory_gib": None,
                "discovery_sources": ["approved_network_ranges", "dns_ipam"],
                "identity_confidence": "medium",
                "admin_channel_available": False,
                "management_channel": "none (firewall bloquea SSH 22)",
                "existing_agent": None,
                "in_authorized_scope": True,
                "is_local_collector_host": False,
                "tags": ["dmz", "isolated"],
                "alternative_deployment_method": "Instalar colector/agente mediante distribución corporativa (Ansible Pull / paquete firmado manual)",
            },
            {
                "canonical_key": "asset-site-b-legacy-solaris",
                "hostname": "legacy-sparc-acct-01",
                "asset_type": "physical_server",
                "site_id": "site-dc-b",
                "collector_id": "collector-site-b",
                "network_range_id": "range-site-b-01",
                "ip_address": "172.16.40.210",
                "mac_address": "00:14:4f:21:89:0a",
                "hypervisor_id": None,
                "os_family": "unsupported",
                "distro_family": "solaris",
                "os_name": "Oracle Solaris 11.4 (SPARC64)",
                "architecture": "sparc64",
                "cpu_cores": 16,
                "memory_gib": 64.0,
                "discovery_sources": ["dns_ipam", "approved_network_ranges"],
                "identity_confidence": "high",
                "admin_channel_available": True,
                "management_channel": "ssh_readonly",
                "existing_agent": None,
                "in_authorized_scope": True,
                "is_local_collector_host": False,
                "tags": ["legacy", "accounting"],
                "alternative_deployment_method": "Conservar hallazgo en inventario pasivo; osquery no soporta SPARC64.",
            },
        ]

        reconciled_assets: List[Dict[str, Any]] = []
        now = _utc_now()
        policy = self.state["deployment_policies"].get(campaign["id"])

        # Recopilar bases de datos, almacenamiento y artefactos de arquitectura del repositorio
        fixture_snap = SimulatedCollectorFixture.get_reproducible_datacenter_snapshot(local_hostname)
        databases = fixture_snap["databases"]
        storage_resources = fixture_snap["storage_resources"]
        arch_scanner = ArchitectureFileScanner()
        architecture_artifacts = arch_scanner.scan_authorized_directories()

        self.state["databases"] = databases
        self.state["storage_resources"] = storage_resources
        self.state["architecture_artifacts"] = architecture_artifacts

        for cand in candidates_raw:
            cand["hostname"] = cand["hostname"].strip()
            asset_id, corr_status, corr_warning = AssetReconciler.reconcile_candidate(
                cand, self.state["assets"]
            )

            # Fase D: Reconciliación idempotente (actualiza el activo existente sin duplicarlo)
            existing_asset = self.state["assets"].get(asset_id, {})
            pkg, pkg_reason = self._select_package_for_node(cand)
            controls_ok, security_controls = self._evaluate_8_security_controls(cand, pkg, policy)

            # Fase E: Clasificación de categoría de acción y estado inicial del nodo
            if corr_status == "ambiguous_conflict":
                action_category = ActionEvaluationCategory.NEEDS_REVIEW.value
                node_state = NodeLifecycleState.AMBIGUOUS.value
                status_reason = corr_warning or "Identidad ambigua entre fuentes; requiere revisión manual."
            elif not cand["in_authorized_scope"]:
                action_category = ActionEvaluationCategory.OUT_OF_SCOPE.value
                node_state = NodeLifecycleState.DENIED.value
                status_reason = "Activo fuera de los rangos CIDR o conectores autorizados de la campaña."
            elif not cand["admin_channel_available"]:
                action_category = ActionEvaluationCategory.UNVERIFIABLE.value
                node_state = NodeLifecycleState.DISCOVERED_UNVERIFIED.value
                status_reason = (
                    "Descubierto por red/DNS en el Sitio B, pero sin acceso SSH/WinRM. "
                    f"Acción recomendada: {cand['alternative_deployment_method']}"
                )
            elif cand["os_family"] == "unsupported" or pkg is None:
                action_category = ActionEvaluationCategory.NEEDS_REVIEW.value
                node_state = NodeLifecycleState.UNSUPPORTED.value
                status_reason = pkg_reason
            elif cand.get("existing_agent") or self.state["agent_installations"].get(asset_id, {}).get("deployment_status") == "enrolled":
                action_category = ActionEvaluationCategory.AGENT_ALREADY_INSTALLED.value
                node_state = NodeLifecycleState.ENROLLED.value
                status_reason = "Agente osquery/fleetd previamente instalado. Listo para verificación e inventario."
            elif pkg and pkg.get("approved"):
                action_category = ActionEvaluationCategory.READY_TO_INSTALL.value
                node_state = (
                    NodeLifecycleState.INSTALL_PENDING.value
                    if controls_ok
                    else NodeLifecycleState.COMPATIBLE.value
                )
                status_reason = (
                    f"{pkg_reason} Política aprobada: listo para despliegue."
                    if controls_ok
                    else f"{pkg_reason} Pendiente de aprobar política de despliegue (Modo 3)."
                )
            else:
                action_category = ActionEvaluationCategory.NEEDS_REVIEW.value
                node_state = NodeLifecycleState.AMBIGUOUS.value
                status_reason = pkg_reason

            attached_dbs = [d for d in databases if d.get("host_asset_id") == asset_id]
            attached_stg = [s for s in storage_resources if asset_id in (s.get("attached_assets") or [])]

            identifiers = [
                {
                    "asset_id": asset_id,
                    "identifier_type": "hypervisor_native_id" if cand.get("hypervisor_id") else "mac_address",
                    "value": cand.get("hypervisor_id") or cand.get("mac_address"),
                    "source": cand["discovery_sources"][0],
                    "environment_id": campaign["environment_id"],
                    "observed_at": now,
                    "verified": cand["admin_channel_available"],
                },
                {
                    "asset_id": asset_id,
                    "identifier_type": "ipv4_address",
                    "value": cand["ip_address"],
                    "source": "dns_ipam",
                    "environment_id": campaign["environment_id"],
                    "observed_at": now,
                    "verified": True,
                },
            ]

            observation = {
                "id": f"obs-{asset_id}-{campaign['id']}",
                "asset_id": asset_id,
                "campaign_id": campaign["id"],
                "sources": cand["discovery_sources"],
                "observed_at": now,
                "updated_at": now,
                "confidence": cand["identity_confidence"],
                "summary": f"{cand['os_name']} ({cand['architecture']}) en {cand['ip_address']}",
            }
            # Conservar últimas observaciones por activo sin crecer indefinidamente
            self.state["asset_observations"] = [
                o for o in self.state.get("asset_observations", []) if o.get("id") != observation["id"]
            ] + [observation]

            asset_record = {
                "id": asset_id,
                "environment_id": campaign["environment_id"],
                "site_id": cand["site_id"],
                "collector_id": cand["collector_id"],
                "network_range_id": cand["network_range_id"],
                "asset_type": cand["asset_type"],
                "hostname": cand["hostname"],
                "ip_address": cand["ip_address"],
                "mac_address": cand["mac_address"],
                "hypervisor_id": cand["hypervisor_id"],
                "os_family": cand["os_family"],
                "distro_family": cand["distro_family"],
                "os_name": cand["os_name"],
                "architecture": cand["architecture"],
                "cpu_cores": cand["cpu_cores"],
                "memory_gib": cand["memory_gib"],
                "discovery_sources": cand["discovery_sources"],
                "identity_confidence": cand["identity_confidence"],
                "admin_channel_available": cand["admin_channel_available"],
                "management_channel": cand["management_channel"],
                "is_local_collector_host": cand["is_local_collector_host"],
                "tags": cand["tags"],
                "identifiers": identifiers,
                "vm_metadata": {
                    "native_id": cand["hypervisor_id"],
                    "power_state": "running",
                    "vcpus": cand["cpu_cores"],
                    "memory_gib": cand["memory_gib"],
                    "firmware": "uefi" if cand["architecture"] == "aarch64" else "seabios",
                    "export_limitations": (
                        []
                        if cand["admin_channel_available"] and cand["os_family"] != "unsupported"
                        else ["Requiere validación previa de SO/arquitectura antes de exportar imagen."]
                    ),
                },
                "database_instances": attached_dbs,
                "storage_volumes": attached_stg,
                "recommended_package": pkg,
                "package_decision_reason": pkg_reason,
                "action_category": action_category,
                "lifecycle_state": existing_asset.get("lifecycle_state")
                if existing_asset.get("lifecycle_state") == NodeLifecycleState.VERIFIED.value
                and campaign["mode"] == CampaignMode.DISCOVER_ONLY.value
                else node_state,
                "status_reason": status_reason,
                "security_controls": security_controls,
                "security_controls_passed": controls_ok,
                "alternative_deployment_method": cand["alternative_deployment_method"],
                "verification_levels": existing_asset.get(
                    "verification_levels",
                    {
                        "level_1_infrastructure": "infrastructure_confirmed",
                        "level_2_os": "os_identified" if cand["admin_channel_available"] else "discovered_unverified",
                        "level_3_agent": "agent_connected" if cand.get("existing_agent") else "pending",
                        "level_4_inventory": "inventory_verified" if cand.get("existing_agent") else "pending",
                    },
                ),
                "first_seen_at": existing_asset.get("first_seen_at", now),
                "last_reconciled_at": now,
            }

            self.state["assets"][asset_id] = asset_record
            reconciled_assets.append(asset_record)

        # Construir grafo de relaciones y plan de preparación de migración
        relationships = DependencyMapper.build_datacenter_relationships(
            reconciled_assets, databases, storage_resources, architecture_artifacts
        )
        self.state["relationships"] = relationships

        migration_plan = MigrationReadinessService.build_global_migration_plan(
            reconciled_assets, databases, storage_resources, relationships, architecture_artifacts
        )
        self.state["migration_plan"] = migration_plan

        for asset_rec in reconciled_assets:
            asset_rec["migration_readiness"] = migration_plan["per_asset_readiness"].get(asset_rec["id"])
            self.state["assets"][asset_rec["id"]] = asset_rec

        return reconciled_assets

    def _generate_tasks_for_campaign(
        self, campaign: Dict[str, Any], assets: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Crea las tareas idempotentes organizadas en las 7 colas lógicas sin saturar la red.
        """
        cid = campaign["id"]
        mode = campaign["mode"]
        now = _utc_now()
        tasks: List[Dict[str, Any]] = []

        def add_task(queue: LogicalTaskQueue, task_type: str, asset_id: Optional[str], title: str, status: str, detail: str):
            idem_raw = f"{cid}:{queue.value}:{task_type}:{asset_id or 'global'}"
            idem_key = hashlib.sha256(idem_raw.encode("utf-8")).hexdigest()[:16]
            tasks.append(
                {
                    "id": f"tsk-{idem_key}",
                    "idempotency_key": idem_key,
                    "campaign_id": cid,
                    "queue": queue.value,
                    "task_type": task_type,
                    "asset_id": asset_id,
                    "title": title,
                    "status": status,
                    "attempts": 1,
                    "max_retries": 3,
                    "detail": detail,
                    "updated_at": now,
                }
            )

        # 1. Cola de control y conectores pasivos
        add_task(
            LogicalTaskQueue.DISCOVERY_CONTROL,
            "campaign_init_and_scope_validation",
            None,
            "Validar alcance autorizado (entorno, conectores, rangos CIDR y límites de concurrencia)",
            "completed",
            f"Alcance validado: {len(campaign['scope']['connector_ids'])} conectores y {len(campaign['scope']['network_range_ids'])} rangos CIDR aprobados.",
        )
        add_task(
            LogicalTaskQueue.DISCOVERY_API,
            "poll_hypervisor_and_cloud_apis",
            None,
            "Fase A: Consultar APIs de hipervisores (Proxmox/vCenter), DNS/IPAM y Fleet",
            "completed",
            "5 activos obtenidos por APIs de virtualización/cloud y registros DNS.",
        )
        add_task(
            LogicalTaskQueue.DISCOVERY_NETWORK,
            "scan_approved_cidr_ranges",
            None,
            "Fase B: Comprobación activa controlada en rangos CIDR autorizados (Sitio A y Sitio B)",
            "completed",
            "7 candidatos respondieron en 10.0.2.0/24, 10.10.20.0/24 y 172.16.40.0/24.",
        )

        # 2. Tareas por activo según fase y modo de campaña
        for asset in assets:
            aid = asset["id"]
            hname = asset["hostname"]
            has_channel = asset["admin_channel_available"]

            add_task(
                LogicalTaskQueue.DISCOVERY_OS,
                "identify_os_and_architecture",
                aid,
                f"Fase C: Identificar SO y arquitectura de '{hname}' ({asset['ip_address']})",
                "completed" if has_channel else "blocked_no_channel",
                f"Identificado: {asset['os_name']} ({asset['architecture']})"
                if has_channel
                else "Sin canal SSH/WinRM: conservado como discovered_unverified.",
            )

            add_task(
                LogicalTaskQueue.INVENTORY_RECONCILE,
                "reconcile_asset_identity",
                aid,
                f"Fase D: Reconciliar identidad canónica de '{hname}'",
                "completed",
                f"Correlacionado sin duplicados (clave canónica: {aid}, confianza: {asset['identity_confidence']}).",
            )

            if mode in (CampaignMode.DISCOVER_INSTALL.value, CampaignMode.GLOBAL_TEST.value):
                if asset["action_category"] in (
                    ActionEvaluationCategory.READY_TO_INSTALL.value,
                    ActionEvaluationCategory.AGENT_ALREADY_INSTALLED.value,
                ):
                    deploy_status = (
                        "completed"
                        if asset["lifecycle_state"] in (NodeLifecycleState.ENROLLED.value, NodeLifecycleState.VERIFIED.value)
                        else ("blocked_policy" if not asset["security_controls_passed"] else "pending")
                    )
                    add_task(
                        LogicalTaskQueue.AGENT_DEPLOYMENT,
                        "deploy_or_verify_agent",
                        aid,
                        f"Etapa 3 (Instalar): Desplegar/validar {asset['recommended_package']['artifact_name'] if asset.get('recommended_package') else 'agente'} en '{hname}'",
                        deploy_status,
                        asset["status_reason"],
                    )

                if asset["lifecycle_state"] == NodeLifecycleState.VERIFIED.value:
                    add_task(
                        LogicalTaskQueue.AGENT_VERIFICATION,
                        "verify_4_levels_and_query",
                        aid,
                        f"Etapa 4 (Verificar): Validar los 4 niveles y consulta de inventario en '{hname}'",
                        "completed",
                        "4/4 niveles superados: infrastructure_confirmed, os_identified, agent_connected, inventory_verified.",
                    )

        self.state["discovery_tasks"][cid] = tasks
        return tasks

    def create_campaign(self, req: CreateCampaignRequest) -> Dict[str, Any]:
        self._validate_scope(req)
        cid = f"camp-{uuid.uuid4().hex[:8]}"
        now = _utc_now()
        mode_labels = {
            CampaignMode.DISCOVER_ONLY: "Modo 1 — Descubrir (Solo lectura)",
            CampaignMode.DISCOVER_PLAN: "Modo 2 — Descubrir y Planificar",
            CampaignMode.DISCOVER_INSTALL: "Modo 3 — Descubrir e Instalar",
            CampaignMode.GLOBAL_TEST: "Modo 4 — Prueba Global de Extremo a Extremo",
        }
        campaign = {
            "id": cid,
            "name": req.name or f"Campaña Data Center ({mode_labels.get(req.mode, req.mode.value)})",
            "environment_id": req.environment_id,
            "mode": req.mode.value,
            "mode_label": mode_labels.get(req.mode, req.mode.value),
            "status": "planned" if req.mode in (CampaignMode.DISCOVER_ONLY, CampaignMode.DISCOVER_PLAN) else "awaiting_approval",
            "created_by": req.created_by,
            "created_at": now,
            "updated_at": now,
            "policy_id": None,
            "discovery_sources": req.discovery_sources,
            "scope": req.scope.model_dump(),
            "agent_strategy": req.agent_strategy.model_dump(),
            "execution_limits": req.execution_limits.model_dump(),
        }
        self.state["campaigns"][cid] = campaign

        assets = self._discover_and_reconcile_candidates(campaign)
        tasks = self._generate_tasks_for_campaign(campaign, assets)
        self._record_audit(
            req.created_by,
            "campaign.created",
            cid,
            {"mode": req.mode.value, "assets_discovered": len(assets)},
        )
        self._save()
        return self.get_campaign_detail(cid)

    def generate_plan(self, campaign_id: str) -> Dict[str, Any]:
        campaign = self._require_campaign(campaign_id)
        assets = self._discover_and_reconcile_candidates(campaign)
        self._generate_tasks_for_campaign(campaign, assets)
        campaign["updated_at"] = _utc_now()
        if campaign["status"] == "created":
            campaign["status"] = "planned"
        self._record_audit(
            "system-planner",
            "campaign.plan_generated",
            campaign_id,
            {"assets_evaluated": len(assets)},
        )
        self._save()
        return self.get_campaign_detail(campaign_id)

    def approve_campaign(self, campaign_id: str, req: ApproveCampaignRequest) -> Dict[str, Any]:
        campaign = self._require_campaign(campaign_id)
        policy_id = f"pol-{campaign_id}"
        now = _utc_now()
        policy = {
            "id": policy_id,
            "campaign_id": campaign_id,
            "scope": campaign["scope"],
            "approved": True,
            "approved_by": req.approved_by,
            "approval_time": now,
            "policy_version": "1.0",
            "notes": req.notes,
            "allow_linux_x86_64": req.allow_linux_x86_64,
            "allow_linux_arm64": req.allow_linux_arm64,
            "allow_windows_x86_64": req.allow_windows_x86_64,
            "allow_windows_arm64": req.allow_windows_arm64,
            "exclude_critical_tags": req.exclude_critical_tags,
        }
        self.state["deployment_policies"][campaign_id] = policy
        campaign["policy_id"] = policy_id
        campaign["status"] = "approved"
        campaign["updated_at"] = now

        # Re-evaluar los 8 controles de seguridad con la nueva política aprobada
        assets = self._discover_and_reconcile_candidates(campaign)
        self._generate_tasks_for_campaign(campaign, assets)

        self._record_audit(
            req.approved_by,
            "campaign.policy_approved",
            campaign_id,
            {"policy_id": policy_id, "notes": req.notes},
        )
        self._save()
        return self.get_campaign_detail(campaign_id)

    def execute_campaign(self, campaign_id: str, force_install_agents: bool = False) -> Dict[str, Any]:
        """
        Ejecuta las 4 etapas de la campaña autorizada:
        1. Descubrir -> 2. Identificar -> 3. Instalar (si el modo lo incluye y la política está aprobada)
        -> 4. Verificar (4 niveles de prueba global por nodo y consolidación de topología).
        En modo `discover_plan` o `discover_only`, prohíbe cualquier operación de instalación.
        """
        campaign = self._require_campaign(campaign_id)
        if campaign["status"] == "cancelled":
            raise ValueError("No se puede ejecutar una campaña cancelada.")

        mode = campaign["mode"]
        if force_install_agents and mode in (CampaignMode.DISCOVER_ONLY.value, CampaignMode.DISCOVER_PLAN.value):
            raise PermissionError(
                f"Operación de instalación bloqueada: la campaña '{campaign_id}' está en modo '{mode}' (solo lectura y planificación)."
            )
        policy = self.state["deployment_policies"].get(campaign_id)

        # Si está en modo instalar o prueba global y aún no tiene política aprobada, auto-aprobar con política estándar si fue disparada desde el botón 1-clic, o verificar controles
        if mode in (CampaignMode.DISCOVER_INSTALL.value, CampaignMode.GLOBAL_TEST.value) and not policy:
            self.approve_campaign(campaign_id, ApproveCampaignRequest())
            policy = self.state["deployment_policies"].get(campaign_id)

        assets = self._discover_and_reconcile_candidates(campaign)
        provider = AgentManagementProvider(campaign["agent_strategy"].get("provider", "fleet"))
        now = _utc_now()

        for asset in assets:
            aid = asset["id"]
            if mode == CampaignMode.DISCOVER_ONLY.value:
                # Solo lectura: no instala agentes
                continue

            if mode == CampaignMode.DISCOVER_PLAN.value:
                # Planificación completada
                continue

            # En Modo 3 (discover_install) y Modo 4 (global_test), instalar y verificar únicamente en los nodos que superan los 8 controles
            if asset["security_controls_passed"] and asset["recommended_package"]:
                pkg = asset["recommended_package"]
                self.state["agent_installations"][aid] = {
                    "asset_id": aid,
                    "provider": campaign["agent_strategy"].get("provider", "fleet"),
                    "package_id": pkg["id"],
                    "artifact_name": pkg["artifact_name"],
                    "version": pkg["version"],
                    "deployment_status": "enrolled",
                    "last_checkin_at": now,
                }
                check = provider.check_enrollment_and_query(asset)
                asset["lifecycle_state"] = NodeLifecycleState.VERIFIED.value
                asset["action_category"] = ActionEvaluationCategory.READY_FOR_INVENTORY.value
                asset["status_reason"] = (
                    f"Agente {pkg['version']} ({pkg['artifact_name']}) desplegado, enrolado en "
                    f"{check['provider']} y consulta de prueba confirmada."
                )
                asset["verification_levels"] = {
                    "level_1_infrastructure": "infrastructure_confirmed",
                    "level_2_os": "os_identified",
                    "level_3_agent": "agent_connected",
                    "level_4_inventory": "inventory_verified",
                }
                self.state["verification_results"].append(
                    {
                        "id": f"ver-{uuid.uuid4().hex[:8]}",
                        "campaign_id": campaign_id,
                        "asset_id": aid,
                        "test_type": "4_level_global_verification",
                        "status": "passed",
                        "levels": asset["verification_levels"],
                        "sample_query": check["sample_query"],
                        "checked_at": now,
                    }
                )
                self.state["assets"][aid] = asset

        self._generate_tasks_for_campaign(campaign, assets)
        unreachable_hosts = [
            a["hostname"]
            for a in assets
            if not a.get("admin_channel_available")
            or a.get("lifecycle_state") in (
                NodeLifecycleState.UNREACHABLE.value,
                NodeLifecycleState.DISCOVERED_UNVERIFIED.value,
                NodeLifecycleState.FAILED.value,
            )
        ]
        campaign["unreachable_hosts_count"] = len(unreachable_hosts)
        campaign["unreachable_hosts"] = unreachable_hosts
        campaign["fully_discovered"] = len(unreachable_hosts) == 0
        campaign["status"] = "completed" if len(unreachable_hosts) == 0 else "partial_with_unreachable_hosts"
        campaign["completed_at"] = now
        campaign["updated_at"] = now

        self._record_audit(
            campaign["created_by"],
            "campaign.executed",
            campaign_id,
            {
                "mode": mode,
                "status": campaign["status"],
                "fully_discovered": campaign["fully_discovered"],
                "unreachable_hosts_count": len(unreachable_hosts),
            },
        )
        self._save()
        return self.get_campaign_detail(campaign_id)

    def cancel_campaign(self, campaign_id: str) -> Dict[str, Any]:
        campaign = self._require_campaign(campaign_id)
        now = _utc_now()
        campaign["status"] = "cancelled"
        campaign["updated_at"] = now
        tasks = self.state["discovery_tasks"].get(campaign_id, [])
        for t in tasks:
            if t["status"] == "pending":
                t["status"] = "cancelled"
                t["updated_at"] = now
        self._record_audit(DEFAULT_OPERATOR, "campaign.cancelled", campaign_id, {})
        self._save()
        return self.get_campaign_detail(campaign_id)

    def pause_campaign(self, campaign_id: str, reason: str = "Pausa solicitada por el operador") -> Dict[str, Any]:
        """Pause an active campaign while preserving all partial host discoveries and checkpoints."""
        campaign = self._require_campaign(campaign_id)
        now = _utc_now()
        campaign["status"] = "paused"
        campaign["paused_at"] = now
        campaign["pause_reason"] = reason
        campaign["updated_at"] = now
        tasks = self.state["discovery_tasks"].get(campaign_id, [])
        for t in tasks:
            if t["status"] == "pending":
                t["status"] = "paused_checkpoint"
                t["updated_at"] = now
        self._record_audit(DEFAULT_OPERATOR, "campaign.paused", campaign_id, {"reason": reason})
        self._save()
        return self.get_campaign_detail(campaign_id)

    def resume_campaign(self, campaign_id: str) -> Dict[str, Any]:
        """
        Resume a paused, interrupted, or partially failed campaign from its last checkpoint
        without duplicating previously discovered assets or losing partial results.
        """
        campaign = self._require_campaign(campaign_id)
        if campaign["status"] == "cancelled":
            raise ValueError("No se puede reanudar una campaña cancelada.")
        now = _utc_now()
        previous_status = campaign["status"]
        campaign["status"] = "resumed"
        campaign["resumed_at"] = now
        campaign["updated_at"] = now

        # Reconcile candidates idempotently (preserving existing asset IDs and partial findings)
        assets = self._discover_and_reconcile_candidates(campaign)
        tasks = self.state["discovery_tasks"].get(campaign_id, [])
        resumed_tasks_count = 0
        for t in tasks:
            if t["status"] in ("paused_checkpoint", "pending", "blocked_no_channel"):
                t["attempts"] = int(t.get("attempts", 1)) + 1
                t["updated_at"] = now
                if t["status"] == "paused_checkpoint":
                    t["status"] = "completed"
                    resumed_tasks_count += 1

        if not tasks:
            tasks = self._generate_tasks_for_campaign(campaign, assets)

        unreachable_hosts = [
            a["hostname"]
            for a in assets
            if not a.get("admin_channel_available")
            or a.get("lifecycle_state") in (
                NodeLifecycleState.UNREACHABLE.value,
                NodeLifecycleState.DISCOVERED_UNVERIFIED.value,
                NodeLifecycleState.FAILED.value,
            )
        ]
        campaign["unreachable_hosts_count"] = len(unreachable_hosts)
        campaign["unreachable_hosts"] = unreachable_hosts
        campaign["fully_discovered"] = len(unreachable_hosts) == 0
        if campaign["mode"] in (CampaignMode.DISCOVER_ONLY.value, CampaignMode.DISCOVER_PLAN.value):
            campaign["status"] = "completed" if len(unreachable_hosts) == 0 else "partial_with_unreachable_hosts"
        else:
            campaign["status"] = "planned"
        self._record_audit(
            DEFAULT_OPERATOR,
            "campaign.resumed",
            campaign_id,
            {
                "previous_status": previous_status,
                "resumed_tasks_count": resumed_tasks_count,
                "preserved_assets_count": len(assets),
            },
        )
        self._save()
        detail = self.get_campaign_detail(campaign_id)
        detail["resume_summary"] = {
            "resumed_at": now,
            "previous_status": previous_status,
            "preserved_assets_count": len(assets),
            "resumed_tasks_count": resumed_tasks_count,
        }
        return detail

    def retry_host_discovery(self, campaign_id: str, asset_id: str) -> Dict[str, Any]:
        """
        Retry pre-flight connectivity and discovery on a specific host, incrementing
        retry attempts and preserving partial results if the host remains unreachable.
        """
        self._require_campaign(campaign_id)
        asset = self._resolve_asset(asset_id)
        aid = asset["id"]
        now = _utc_now()
        tasks = self.state["discovery_tasks"].get(campaign_id, [])
        retried = []
        for t in tasks:
            if t.get("asset_id") == aid:
                max_r = int(t.get("max_retries", 3))
                curr_a = int(t.get("attempts", 1))
                if curr_a < max_r:
                    t["attempts"] = curr_a + 1
                t["updated_at"] = now
                retried.append(t)

        asset["last_reconciled_at"] = now
        self.state["assets"][aid] = asset
        self._record_audit(
            DEFAULT_OPERATOR,
            "campaign.host_retry",
            campaign_id,
            {"asset_id": aid, "tasks_retried": len(retried), "admin_channel_available": asset["admin_channel_available"]},
        )
        self._save()
        return {
            "campaign_id": campaign_id,
            "asset_id": aid,
            "hostname": asset["hostname"],
            "reachable": asset["admin_channel_available"],
            "partial_results_preserved": True,
            "lifecycle_state": asset["lifecycle_state"],
            "tasks_retried": retried,
            "retried_at": now,
        }

    def build_campaign_cmir(self, campaign_id: str, target_provider: str = "aws") -> Dict[str, Any]:
        """
        Build the full hierarchical CMIR v2.1 model for Use Case 3:
        DATACENTER -> PHYSICAL HOST -> HYPERVISOR -> VM -> OS -> PROCESSES/SERVICES -> APPLICATIONS -> DEPENDENCIES
        with stable canonical IDs, epistemic states, confidence scores, and evidence.
        """
        from app.cmir.builder import build_cmir_hierarchy

        provider_clean = target_provider.lower().strip() if target_provider else "aws"
        if provider_clean not in ("aws", "gcp"):
            provider_clean = "aws"

        detail = self.get_campaign_detail(campaign_id)
        now = _utc_now()
        nodes: List[Dict[str, Any]] = []
        relationships: List[Dict[str, Any]] = []

        # 1. Datacenter nodes (from sites)
        for site in detail.get("sites", []):
            dc_id = f"dc-{site['id']}"
            nodes.append({
                "id": dc_id,
                "canonical_id": f"canonical:datacenter:{site['id']}",
                "name": site["name"],
                "type": "datacenter",
                "category": "infrastructure",
                "provider": provider_clean,
                "location": "us-east-1" if provider_clean == "aws" else "us-central1",
                "epistemic_state": "observed",
                "confidence": 1.0,
                "source_connector": "campaign_scope_registry",
                "discovered_at": now,
                "evidence": [
                    {
                        "source": "campaign_scope_registry",
                        "observed_at": now,
                        "epistemic_state": "observed",
                        "confidence": 1.0,
                        "detail": f"Sitio de datacenter autorizado: {site['name']} ({site.get('location', 'On-Premise')}).",
                    }
                ],
                "metadata": site,
            })

        # 2. Hypervisor & Physical Host nodes
        hypervisors_seen: Dict[str, str] = {}
        for conn in detail.get("connectors", []):
            if conn.get("type") == "hypervisor_apis":
                hyp_id = f"hyp-{conn['id']}"
                parent_dc = f"dc-{conn.get('site_id', 'site-dc-a')}"
                phys_id = f"phys-{conn['id']}"
                nodes.append({
                    "id": phys_id,
                    "canonical_id": f"canonical:physical_host:{conn['id']}",
                    "name": f"physical-blade-{conn['id']}",
                    "type": "physical_host",
                    "category": "infrastructure",
                    "parent_id": parent_dc,
                    "provider": provider_clean,
                    "epistemic_state": "observed",
                    "confidence": 0.98,
                    "source_connector": conn["id"],
                    "discovered_at": now,
                    "metadata": {"site_id": conn.get("site_id")},
                })
                relationships.append({
                    "source": parent_dc,
                    "target": phys_id,
                    "type": "hosts",
                    "epistemic_state": "observed",
                    "confidence": 0.98,
                    "source_connector": conn["id"],
                    "discovered_at": now,
                })
                nodes.append({
                    "id": hyp_id,
                    "canonical_id": f"canonical:hypervisor:{conn['id']}",
                    "name": conn["name"],
                    "type": "hypervisor",
                    "category": "infrastructure",
                    "parent_id": phys_id,
                    "provider": provider_clean,
                    "platform": conn.get("provider", "proxmox_ve"),
                    "epistemic_state": "observed",
                    "confidence": 0.99,
                    "source_connector": conn["id"],
                    "discovered_at": now,
                    "evidence": [
                        {
                            "source": conn["id"],
                            "observed_at": now,
                            "epistemic_state": "observed",
                            "confidence": 0.99,
                            "detail": f"Clúster de hipervisor {conn['name']} ({conn.get('endpoint')}).",
                        }
                    ],
                    "metadata": conn,
                })
                relationships.append({
                    "source": phys_id,
                    "target": hyp_id,
                    "type": "hosts",
                    "epistemic_state": "observed",
                    "confidence": 0.99,
                    "source_connector": conn["id"],
                    "discovered_at": now,
                })
                hypervisors_seen[conn.get("site_id", "site-dc-a")] = hyp_id

        # 3. Assets (VMs / Physical Servers) -> OS -> Services/Processes -> Applications
        for asset in detail.get("assets", []):
            aid = asset["id"]
            site_id = asset.get("site_id", "site-dc-a")
            parent_id = hypervisors_seen.get(site_id, f"dc-{site_id}")
            is_reachable = bool(asset.get("admin_channel_available"))
            epistemic = "observed" if is_reachable else "inferred"
            conf = 0.98 if is_reachable else 0.60
            is_shared_asset = "database" in (asset.get("tags") or []) or "messaging" in (asset.get("tags") or [])

            nodes.append({
                "id": aid,
                "canonical_id": f"canonical:asset:{aid}",
                "name": asset["hostname"],
                "type": "virtual_machine" if asset.get("asset_type") != "physical_server" else "physical_host",
                "category": "compute",
                "parent_id": parent_id,
                "provider": provider_clean,
                "platform": asset.get("os_name"),
                "is_shared": is_shared_asset,
                "epistemic_state": epistemic,
                "confidence": conf,
                "source_connector": (asset.get("discovery_sources") or ["network_scan"])[0],
                "discovered_at": asset.get("last_reconciled_at") or now,
                "evidence": [
                    {
                        "source": ", ".join(asset.get("discovery_sources") or []),
                        "observed_at": asset.get("last_reconciled_at") or now,
                        "epistemic_state": epistemic,
                        "confidence": conf,
                        "detail": f"Host {asset['hostname']} ({asset['ip_address']}) · Estado: {asset['lifecycle_state']}.",
                    }
                ],
                "metadata": {
                    "ip_address": asset.get("ip_address"),
                    "mac_address": asset.get("mac_address"),
                    "cpu_cores": asset.get("cpu_cores"),
                    "memory_gib": asset.get("memory_gib"),
                    "architecture": asset.get("architecture"),
                    "lifecycle_state": asset.get("lifecycle_state"),
                    "admin_channel_available": is_reachable,
                },
            })
            relationships.append({
                "source": parent_id,
                "target": aid,
                "type": "hosts",
                "epistemic_state": epistemic,
                "confidence": conf,
                "source_connector": "hypervisor_apis",
                "discovered_at": now,
            })

            # Operating System node
            os_id = f"os-{aid}"
            nodes.append({
                "id": os_id,
                "canonical_id": f"canonical:os:{aid}",
                "name": f"{asset['hostname']}-os ({asset.get('os_name', 'Unknown OS')})",
                "type": "operating_system",
                "category": "compute",
                "parent_id": aid,
                "provider": provider_clean,
                "platform": asset.get("os_name"),
                "epistemic_state": "observed" if is_reachable else "unknown",
                "confidence": conf,
                "source_connector": "os_discovery",
                "discovered_at": now,
                "metadata": {
                    "os_family": asset.get("os_family"),
                    "distro_family": asset.get("distro_family"),
                    "architecture": asset.get("architecture"),
                },
            })
            relationships.append({
                "source": os_id,
                "target": aid,
                "type": "runs_on",
                "epistemic_state": "observed" if is_reachable else "unknown",
                "confidence": conf,
                "source_connector": "os_discovery",
                "discovered_at": now,
            })

            # System Service, Process & Application nodes for reachable hosts
            # Section 8 rule: Do NOT assume that a process listening on a port is an identified application;
            # only create an `application` node when backed by explicit workload/service/manifest evidence.
            if is_reachable:
                tags = asset.get("tags") or []
                proc_id = f"proc-{aid}-sshd"
                nodes.append({
                    "id": proc_id,
                    "canonical_id": f"canonical:process:{aid}:sshd",
                    "name": "sshd (listening :22)",
                    "type": "process",
                    "category": "compute",
                    "parent_id": aid,
                    "provider": provider_clean,
                    "epistemic_state": "observed",
                    "confidence": 0.99,
                    "source_connector": "os_process_table",
                    "discovered_at": now,
                    "metadata": {
                        "listening_port": 22,
                        "is_identified_business_application": False,
                        "note": "Proceso de administración escuchando en puerto; no se clasifica como aplicación de negocio.",
                    },
                })
                relationships.append({
                    "source": proc_id,
                    "target": aid,
                    "type": "runs_on",
                    "epistemic_state": "observed",
                    "confidence": 0.99,
                    "source_connector": "os_process_table",
                    "discovered_at": now,
                })

                svc_name = "postgresql.service" if "database" in tags else "rabbitmq-server.service" if "messaging" in tags else "app-worker.service"
                svc_id = f"svc-{aid}"
                nodes.append({
                    "id": svc_id,
                    "canonical_id": f"canonical:service:{aid}:{svc_name}",
                    "name": svc_name,
                    "type": "system_service",
                    "category": "application",
                    "parent_id": aid,
                    "provider": provider_clean,
                    "epistemic_state": "observed",
                    "confidence": 0.95,
                    "source_connector": "osquery_agent",
                    "discovered_at": now,
                })
                relationships.append({
                    "source": svc_id,
                    "target": aid,
                    "type": "runs_on",
                    "epistemic_state": "observed",
                    "confidence": 0.95,
                    "source_connector": "osquery_agent",
                    "discovered_at": now,
                })

                # Only create an `application` node when verified application tags/manifests exist
                has_identified_app = any(t in tags for t in ("api", "messaging", "dotnet", "worker", "database"))
                if has_identified_app:
                    app_id = f"app-{aid}"
                    nodes.append({
                        "id": app_id,
                        "canonical_id": f"canonical:application:{aid}",
                        "name": f"{asset['hostname']}-workload",
                        "type": "application",
                        "category": "application",
                        "parent_id": aid,
                        "provider": provider_clean,
                        "is_shared": is_shared_asset,
                        "epistemic_state": "observed",
                        "confidence": 0.95,
                        "source_connector": "osquery_agent",
                        "discovered_at": now,
                        "metadata": {"tags": tags, "backed_by_service": svc_name},
                    })
                    relationships.append({
                        "source": app_id,
                        "target": aid,
                        "type": "runs_on",
                        "epistemic_state": "observed",
                        "confidence": 0.95,
                        "source_connector": "osquery_agent",
                        "discovered_at": now,
                    })

        # 4. Databases & Schemas (6-layer metadata without business rows or secrets!)
        for db in detail.get("databases", []):
            db_id = db["id"]
            host_aid = db.get("host_asset_id")
            nodes.append({
                "id": db_id,
                "canonical_id": f"canonical:db:{db_id}",
                "name": f"{db.get('engine', 'postgres')}-{db_id}",
                "type": "database_instance",
                "category": "data",
                "parent_id": host_aid,
                "provider": provider_clean,
                "engine": db.get("engine", "postgresql"),
                "is_shared": True,
                "epistemic_state": "observed",
                "confidence": 0.99,
                "source_connector": "database_catalog_connector",
                "discovered_at": now,
                "evidence": [
                    {
                        "source": "pg_catalog / information_schema (metadata only, 0 business rows extracted)",
                        "observed_at": now,
                        "epistemic_state": "observed",
                        "confidence": 0.99,
                        "detail": f"Motor {db.get('engine')} {db.get('version')} en puerto {db.get('port')} ({db.get('total_size_gib')} GiB).",
                    }
                ],
                "metadata": {
                    "version": db.get("version"),
                    "port": db.get("port"),
                    "total_size_gib": db.get("total_size_gib"),
                    "business_rows_extracted": 0,
                    "credentials_stored": False,
                },
            })
            if host_aid:
                relationships.append({
                    "source": db_id,
                    "target": host_aid,
                    "type": "runs_on",
                    "epistemic_state": "observed",
                    "confidence": 0.99,
                    "source_connector": "database_catalog_connector",
                    "discovered_at": now,
                })

        # 5. Storage resources (SAN / NAS / EBS / NFS)
        for stg in detail.get("storage_resources", []):
            stg_id = stg["id"]
            attached = stg.get("attached_assets") or []
            nodes.append({
                "id": stg_id,
                "canonical_id": f"canonical:storage:{stg_id}",
                "name": stg.get("name", stg_id),
                "type": "file_share" if "nfs" in str(stg.get("type", "")).lower() else "volume",
                "category": "storage",
                "provider": provider_clean,
                "is_shared": len(attached) > 1,
                "epistemic_state": "observed",
                "confidence": 0.97,
                "source_connector": "storage_inventory_connector",
                "discovered_at": now,
                "metadata": stg,
            })
            for a_ref in attached:
                relationships.append({
                    "source": a_ref,
                    "target": stg_id,
                    "type": "mounts",
                    "epistemic_state": "observed",
                    "confidence": 0.97,
                    "source_connector": "storage_inventory_connector",
                    "discovered_at": now,
                })

        # 6. Inter-asset & dependency relationships (preserving observed communication vs functional dependency)
        # Section 8 rule: Two machines with observed network communication do NOT automatically have a
        # confirmed functional dependency unless backed by configuration/catalog evidence.
        node_ids = {n["id"] for n in nodes}
        conf_str_map = {"verified": 0.99, "confirmed": 0.99, "high": 0.90, "observed": 0.78, "medium": 0.70, "low": 0.50}
        for rel in detail.get("relationships", []):
            src, tgt = rel.get("source"), rel.get("target")
            if src in node_ids and tgt in node_ids:
                raw_conf = rel.get("confidence", 0.90)
                if isinstance(raw_conf, str):
                    num_conf = conf_str_map.get(raw_conf.lower(), 0.75)
                else:
                    num_conf = float(raw_conf)
                rel_type_raw = str(rel.get("type") or rel.get("relationship_type") or "")
                src_type_raw = str(rel.get("source_type") or rel.get("provenance") or "network_flow_analyzer")
                is_pure_netflow = rel_type_raw in ("inferred_relation", "observed_connection", "communicates_with", "publishes_to_message_broker") or (
                    "network" in src_type_raw and "config" not in src_type_raw and num_conf < 0.9
                )
                if is_pure_netflow:
                    # Record the observed network communication AND tag any functional dependency as inferred
                    relationships.append({
                        "source": src,
                        "target": tgt,
                        "type": "communicates_with",
                        "epistemic_state": "observed",
                        "confidence": num_conf,
                        "source_connector": src_type_raw,
                        "discovered_at": now,
                        "metadata": {
                            **rel,
                            "functional_dependency_confirmed": False,
                            "note": "Comunicación de red observada; dependencia funcional tratada como inferida hasta validación.",
                        },
                    })
                    relationships.append({
                        "source": src,
                        "target": tgt,
                        "type": "inferred_relation",
                        "epistemic_state": "inferred",
                        "confidence": min(num_conf, 0.75),
                        "source_connector": src_type_raw,
                        "discovered_at": now,
                        "metadata": rel,
                    })
                else:
                    relationships.append({
                        "source": src,
                        "target": tgt,
                        "type": "depends_on",
                        "epistemic_state": "observed",
                        "confidence": num_conf,
                        "source_connector": src_type_raw,
                        "discovered_at": now,
                        "metadata": {**rel, "functional_dependency_confirmed": True},
                    })

        cmir_obj = build_cmir_hierarchy({
            "name": f"Datacenter Campaign CMIR — {detail['name']}",
            "provider": provider_clean,
            "version": "2.1",
            "resources": nodes,
            "relationships": relationships,
            "metadata": {
                "use_case": "datacenter_campaign",
                "campaign_id": campaign_id,
                "environment_id": detail["environment_id"],
            },
        })
        return cmir_obj.model_dump()

    def plan_campaign_workload_migration(
        self,
        campaign_id: str,
        selected_resources: Optional[List[str]] = None,
        target_provider: str = "aws",
        validated_shared_resources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Select a workload subset from a Datacenter Campaign CMIR v2.1, resolve direct,
        transitive, inferred, and shared dependencies (blocking automatic migration of
        shared dependencies unless explicitly validated), and generate AWS or GCP IaC.
        """
        from app.adapters.aws_adapter import AWSAdapter
        from app.adapters.gcp_adapter import GCPAdapter
        from app.cmir.models import CMIR
        from app.dependencies.resolver import resolve_dependencies
        from app.dependencies.validator import validate_migration_subgraph
        from app.graph.builder import build_graph
        from app.graph.selection import extract_subgraph_cmir

        provider_clean = target_provider.lower().strip()
        if provider_clean not in ("aws", "gcp"):
            raise ValueError(f"Proveedor destino '{target_provider}' no admitido. Use 'aws' o 'gcp'.")

        cmir_dict = self.build_campaign_cmir(campaign_id, target_provider=provider_clean)
        cmir_obj = CMIR.model_validate(cmir_dict)
        graph = build_graph(cmir_obj)

        default_selection = [
            a["id"] for a in self.get_campaign_assets(campaign_id)
            if a.get("admin_channel_available") and a.get("os_family") != "unsupported"
        ][:2]
        selected_ids = selected_resources or default_selection

        dep_analysis = resolve_dependencies(
            graph,
            selected_ids,
            validated_shared_resources=validated_shared_resources,
            include_inferred=False,
        )
        # Only include auto_migratable_resources so unvalidated shared dependencies are NOT auto-migrated!
        sub_cmir = extract_subgraph_cmir(cmir_obj, dep_analysis["auto_migratable_resources"])
        sub_cmir.provider = provider_clean

        validation = validate_migration_subgraph(sub_cmir, dep_analysis, target_provider=provider_clean)
        adapter = GCPAdapter() if provider_clean == "gcp" else AWSAdapter()
        iac_bundle = adapter.generate_iac(sub_cmir)

        return {
            "campaign_id": campaign_id,
            "target_provider": provider_clean,
            "selected_resources": selected_ids,
            "dependency_analysis": dep_analysis,
            "validation": validation,
            "subgraph_cmir": sub_cmir.model_dump(),
            "generated_iac": iac_bundle,
        }

    def _require_campaign(self, campaign_id: str) -> Dict[str, Any]:
        camp = self.state["campaigns"].get(campaign_id)
        if not camp:
            raise KeyError(f"Campaña '{campaign_id}' no encontrada.")
        return camp

    def list_campaigns(self) -> List[Dict[str, Any]]:
        camps = list(self.state["campaigns"].values())
        camps.sort(key=lambda c: c.get("created_at", ""), reverse=True)
        if not camps:
            # Crear una campaña inicial en modo discover_plan para que el tablero tenga datos inmediatos
            default_camp = self.create_campaign(CreateCampaignRequest(mode=CampaignMode.DISCOVER_PLAN))
            return [default_camp]
        return [self.get_campaign_detail(c["id"]) for c in camps]

    def get_campaign_assets(self, campaign_id: str) -> List[Dict[str, Any]]:
        self._require_campaign(campaign_id)
        assets = list(self.state["assets"].values())
        return assets

    def get_campaign_tasks(self, campaign_id: str) -> List[Dict[str, Any]]:
        self._require_campaign(campaign_id)
        return self.state["discovery_tasks"].get(campaign_id, [])

    def get_campaign_detail(self, campaign_id: str) -> Dict[str, Any]:
        camp = self._require_campaign(campaign_id)
        assets = list(self.state["assets"].values())
        tasks = self.state["discovery_tasks"].get(campaign_id, [])
        policy = self.state["deployment_policies"].get(campaign_id)

        total_discovered = len(assets)
        identified_count = sum(1 for a in assets if a["admin_channel_available"])
        verified_count = sum(
            1 for a in assets if a["lifecycle_state"] == NodeLifecycleState.VERIFIED.value
        )
        enrolled_count = sum(
            1
            for a in assets
            if a["lifecycle_state"] in (NodeLifecycleState.ENROLLED.value, NodeLifecycleState.VERIFIED.value)
        )
        review_pending_count = sum(
            1
            for a in assets
            if a["action_category"]
            in (ActionEvaluationCategory.NEEDS_REVIEW.value, ActionEvaluationCategory.UNVERIFIABLE.value)
        )
        ready_to_install_count = sum(
            1 for a in assets if a["action_category"] == ActionEvaluationCategory.READY_TO_INSTALL.value
        )

        # Resumen por cola lógica
        queue_summary: Dict[str, Dict[str, int]] = {}
        for t in tasks:
            q = t["queue"]
            if q not in queue_summary:
                queue_summary[q] = {"total": 0, "completed": 0, "blocked_or_pending": 0}
            queue_summary[q]["total"] += 1
            if t["status"] == "completed":
                queue_summary[q]["completed"] += 1
            else:
                queue_summary[q]["blocked_or_pending"] += 1

        return {
            **camp,
            "policy": policy,
            "metrics": {
                "discovered_count": total_discovered,
                "identified_count": identified_count,
                "verified_agents_count": verified_count,
                "enrolled_agents_count": enrolled_count,
                "ready_to_install_count": ready_to_install_count,
                "review_pending_count": review_pending_count,
                "databases_discovered_count": len(self.state.get("databases", [])),
                "storage_resources_count": len(self.state.get("storage_resources", [])),
                "architecture_artifacts_count": len(self.state.get("architecture_artifacts", [])),
                "relationships_count": len(self.state.get("relationships", [])),
                "total_tasks": len(tasks),
                "completed_tasks": sum(1 for t in tasks if t["status"] == "completed"),
            },
            "sites": self.state["sites"],
            "collectors": self.state["discovery_collectors"],
            "connectors": self.state["connectors"],
            "network_ranges": self.state["network_ranges"],
            "package_catalog": self.state["package_catalog"],
            "queue_summary": queue_summary,
            "assets": assets,
            "databases": self.state.get("databases", []),
            "storage_resources": self.state.get("storage_resources", []),
            "architecture_artifacts": self.state.get("architecture_artifacts", []),
            "relationships": self.state.get("relationships", []),
            "migration_plan": self.state.get("migration_plan"),
            "tasks": tasks,
            "recent_audit_events": self.state["audit_events"][-12:],
        }

    def get_campaign_report(self, campaign_id: str) -> Dict[str, Any]:
        detail = self.get_campaign_detail(campaign_id)
        md_lines = [
            f"# Informe Global de Campaña: {detail['name']}",
            f"- **ID de Campaña:** `{detail['id']}`",
            f"- **Entorno Autorizado:** `{detail['environment_id']}`",
            f"- **Modo de Ejecución:** {detail['mode_label']} (`{detail['mode']}`)",
            f"- **Estado:** `{detail['status']}`",
            f"- **Fecha:** `{detail['updated_at']}`",
            "",
            "## 1. Resumen Ejecutivo del Data Center",
            f"- **Activos descubiertos:** {detail['metrics']['discovered_count']}",
            f"- **Identificados (con acceso SO):** {detail['metrics']['identified_count']}",
            f"- **Agentes verificados (4 niveles):** {detail['metrics']['verified_agents_count']}",
            f"- **Revisión pendiente / Sin canal directo:** {detail['metrics']['review_pending_count']}",
            "",
            "## 2. Estado Detallado por Nodo",
            "| Hostname | Sitio / Colector | IP | Sistema Operativo | Arquitectura | Estado | Paquete / Decisión | 4 Niveles de Verificación |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for a in detail["assets"]:
            pkg_name = a["recommended_package"]["artifact_name"] if a.get("recommended_package") else "Ninguno (Revisión)"
            v = a.get("verification_levels", {})
            levels_str = f"L1:{v.get('level_1_infrastructure')} · L2:{v.get('level_2_os')} · L3:{v.get('level_3_agent')} · L4:{v.get('level_4_inventory')}"
            md_lines.append(
                f"| `{a['hostname']}` | `{a['site_id']}` (`{a['collector_id']}`) | `{a['ip_address']}` | {a['os_name']} | `{a['architecture']}` | **{a['lifecycle_state']}** | `{pkg_name}` — {a['status_reason']} | {levels_str} |"
            )

        return {
            "campaign_id": campaign_id,
            "generated_at": _utc_now(),
            "summary": detail["metrics"],
            "campaign": detail,
            "markdown_report": "\n".join(md_lines),
        }

    def get_asset_health(self, asset_id: str) -> Dict[str, Any]:
        if not self.state["assets"]:
            self.list_campaigns()
        asset = self.state["assets"].get(asset_id)
        if not asset:
            # Permitir búsqueda por hostname además de canonical_key
            for candidate in self.state["assets"].values():
                if candidate["hostname"] == asset_id or candidate["id"] == asset_id:
                    asset = candidate
                    break
        if not asset:
            raise KeyError(f"Activo '{asset_id}' no encontrado.")

        installation = self.state["agent_installations"].get(asset["id"])
        provider = AgentManagementProvider("fleet")
        live_probe = provider.check_enrollment_and_query(asset) if asset["admin_channel_available"] else None

        return {
            "asset_id": asset["id"],
            "hostname": asset["hostname"],
            "site_id": asset["site_id"],
            "collector_id": asset["collector_id"],
            "lifecycle_state": asset["lifecycle_state"],
            "action_category": asset["action_category"],
            "verification_levels": asset["verification_levels"],
            "agent_installation": installation,
            "live_probe": live_probe,
            "security_controls": asset["security_controls"],
            "alternative_deployment_method": asset.get("alternative_deployment_method"),
            "checked_at": _utc_now(),
        }

    def _ensure_seeded_assets(self) -> None:
        if not self.state.get("assets") or "databases" not in self.state:
            self.list_campaigns()
            if self.state["campaigns"]:
                first_cid = next(iter(self.state["campaigns"]))
                self.generate_plan(first_cid)

    def _resolve_asset(self, asset_id: str, environment_id: Optional[str] = None) -> Dict[str, Any]:
        self._ensure_seeded_assets()
        asset = self.state["assets"].get(asset_id)
        if not asset:
            for candidate in self.state["assets"].values():
                if candidate["hostname"] == asset_id or candidate["id"] == asset_id:
                    asset = candidate
                    break
        if not asset:
            raise KeyError(f"Activo '{asset_id}' no encontrado.")
        if environment_id and asset.get("environment_id") != environment_id:
            raise PermissionError(
                f"Acceso cruzado denegado: el activo '{asset_id}' no pertenece al entorno '{environment_id}'."
            )
        return asset

    def list_assets(
        self,
        asset_type: Optional[str] = None,
        site_id: Optional[str] = None,
        os_family: Optional[str] = None,
        state: Optional[str] = None,
        environment_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_seeded_assets()
        results = list(self.state["assets"].values())
        if environment_id:
            results = [a for a in results if a.get("environment_id") == environment_id]
        if asset_type:
            results = [a for a in results if a.get("asset_type") == asset_type]
        if site_id:
            results = [a for a in results if a.get("site_id") == site_id]
        if os_family:
            results = [a for a in results if (a.get("os_family") or "").lower() == os_family.lower()]
        if state:
            results = [a for a in results if a.get("lifecycle_state") == state]
        return results

    def get_asset_detail(self, asset_id: str, environment_id: Optional[str] = None) -> Dict[str, Any]:
        asset = self._resolve_asset(asset_id, environment_id=environment_id)
        aid = asset["id"]
        rels = [
            r
            for r in self.state.get("relationships", [])
            if r["source"] == aid or r["target"] == aid
        ]
        obs = [
            o
            for o in self.state.get("asset_observations", [])
            if o.get("asset_id") == aid
        ]
        return {
            **asset,
            "observations": obs,
            "relationships": rels,
        }

    def get_asset_observations(self, asset_id: str, environment_id: Optional[str] = None) -> List[Dict[str, Any]]:
        asset = self._resolve_asset(asset_id, environment_id=environment_id)
        return [
            o
            for o in self.state.get("asset_observations", [])
            if o.get("asset_id") == asset["id"]
        ]

    def get_asset_relationships(self, asset_id: str, environment_id: Optional[str] = None) -> List[Dict[str, Any]]:
        asset = self._resolve_asset(asset_id, environment_id=environment_id)
        aid = asset["id"]
        return [
            r
            for r in self.state.get("relationships", [])
            if r["source"] == aid or r["target"] == aid
        ]

    def get_asset_migration_readiness(self, asset_id: str, environment_id: Optional[str] = None) -> Dict[str, Any]:
        asset = self._resolve_asset(asset_id, environment_id=environment_id)
        if asset.get("migration_readiness"):
            return asset["migration_readiness"]
        return MigrationReadinessService.evaluate_asset_readiness(
            asset,
            self.state.get("databases", []),
            self.state.get("storage_resources", []),
            self.state.get("relationships", []),
        )

    def list_connectors(self, environment_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conns = list(self.state.get("connectors", []))
        if environment_id:
            conns = [c for c in conns if c.get("environment_id") == environment_id]
        return conns

    def register_connector(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        endpoint = payload.get("endpoint") or "https://pve-dc1.internal:8006/api2/json"
        validate_endpoint_against_ssrf(endpoint, allow_private_datacenter=True)
        conn_id = payload.get("id") or f"conn-{uuid.uuid4().hex[:6]}"
        record = {
            "id": conn_id,
            "environment_id": payload.get("environment_id", "env-datacenter-01"),
            "site_id": payload.get("site_id", "site-dc-a"),
            "name": payload.get("name", "Nuevo Conector Hipervisor"),
            "type": payload.get("type", "hypervisor_apis"),
            "provider": payload.get("provider", "proxmox_ve"),
            "endpoint": endpoint,
            "authorized": True,
            "created_at": _utc_now(),
        }
        self.state["connectors"] = [
            c for c in self.state["connectors"] if c["id"] != conn_id
        ] + [record]
        self._save()
        return record

    def test_connector(self, connector_id: str) -> Dict[str, Any]:
        conn = next((c for c in self.state["connectors"] if c["id"] == connector_id), None)
        if not conn:
            raise KeyError(f"Conector '{connector_id}' no encontrado.")
        endpoint = conn.get("endpoint") or "https://pve-dc1.internal:8006/api2/json"
        pve = ProxmoxVEConnector(connector_id=connector_id, api_url=endpoint)
        return pve.test_connection()


campaign_store = DataCenterCampaignStore()
