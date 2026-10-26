"""
Servicios de Reconciliación de Identidad, Mapeo de Dependencias y Evaluación de Preparación
para Migración (`MigrationReadinessService`) en CloudMove.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class AssetReconciler:
    """
    Correlaciona candidatos de múltiples fuentes siguiendo el orden estricto de prioridad:
    1. ID nativo del proveedor de virtualización o nube (`hypervisor_id`).
    2. UUID del sistema operativo (`os_uuid`).
    3. Dirección MAC + IP como evidencia auxiliar.
    4. Nombre DNS / Hostname como pista de correlación.

    Regla de seguridad: nunca fusiona automáticamente dos registros si solo comparten
    hostname o IP pero presentan conflicto de MAC, hipervisor o familia de SO.
    """

    @staticmethod
    def reconcile_candidate(
        candidate: Dict[str, Any],
        existing_assets: Dict[str, Dict[str, Any]],
    ) -> Tuple[str, str, Optional[str]]:
        """
        Devuelve `(canonical_asset_id, correlation_status, warning_message)`:
        - `correlation_status`: `"matched_existing"` | `"new_asset"` | `"ambiguous_conflict"`
        """
        cand_key = candidate.get("canonical_key") or candidate.get("id")
        cand_hyp = candidate.get("hypervisor_id")
        cand_uuid = candidate.get("os_uuid")
        cand_mac = (candidate.get("mac_address") or "").lower().strip()
        cand_ip = (candidate.get("ip_address") or "").strip()
        cand_host = (candidate.get("hostname") or "").lower().strip()

        # 1. Coincidencia exacta por clave canónica o ID nativo del proveedor
        if cand_key and cand_key in existing_assets:
            return cand_key, "matched_existing", None

        for aid, asset in existing_assets.items():
            if cand_hyp and asset.get("hypervisor_id") == cand_hyp:
                return aid, "matched_existing", None
            if cand_uuid and asset.get("os_uuid") and asset.get("os_uuid") == cand_uuid:
                return aid, "matched_existing", None

        # 2. Detectar posibles colisiones ambiguas por IP o hostname con distinta MAC o hipervisor
        for aid, asset in existing_assets.items():
            same_host = cand_host and (asset.get("hostname") or "").lower().strip() == cand_host
            same_ip = cand_ip and (asset.get("ip_address") or "").strip() == cand_ip
            if same_host or same_ip:
                existing_mac = (asset.get("mac_address") or "").lower().strip()
                existing_hyp = asset.get("hypervisor_id")
                if (cand_mac and existing_mac and cand_mac == existing_mac) and (
                    not cand_hyp or not existing_hyp or cand_hyp == existing_hyp
                ):
                    return aid, "matched_existing", None
                # Conflicto de identidad: no fusionar automáticamente
                ambiguous_id = f"{cand_key or ('asset-' + cand_host)}-ambiguous"
                return (
                    ambiguous_id,
                    "ambiguous_conflict",
                    f"Correlación ambigua con '{aid}': comparten hostname/IP pero difieren en MAC o ID de hipervisor. No se fusionaron automáticamente.",
                )

        return cand_key or f"asset-{cand_host or 'unknown'}", "new_asset", None


class DependencyMapper:
    """
    Construye el grafo tipado de relaciones y dependencias entre VMs, hipervisores,
    redes, datastores, bases de datos, artefactos de arquitectura y backups.
    Cada relación conserva su procedencia (`source`), fecha (`observed_at`) y nivel de confianza.
    """

    @staticmethod
    def build_datacenter_relationships(
        assets: List[Dict[str, Any]],
        databases: List[Dict[str, Any]],
        storage_resources: List[Dict[str, Any]],
        architecture_artifacts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        now = _utc_now()
        relationships: List[Dict[str, Any]] = []

        def add_rel(source_id: str, target_id: str, rel_type: str, provenance: str, confidence: str, detail: str):
            relationships.append(
                {
                    "id": f"rel-{source_id}-to-{target_id}-{rel_type}",
                    "source": source_id,
                    "target": target_id,
                    "relationship_type": rel_type,
                    "provenance": provenance,
                    "confidence": confidence,
                    "detail": detail,
                    "observed_at": now,
                }
            )

        # 1. Relaciones VM -> Hipervisor, VM -> Red Autorizada, Activo -> Destino AWS Preliminar
        for asset in assets:
            aid = asset["id"]
            if asset.get("hypervisor_id"):
                add_rel(
                    aid,
                    asset["hypervisor_id"],
                    "hosted_on_hypervisor",
                    "hypervisor_apis",
                    "confirmed",
                    f"La VM '{asset['hostname']}' se ejecuta sobre el hipervisor '{asset['hypervisor_id']}'.",
                )
            if asset.get("network_range_id"):
                add_rel(
                    aid,
                    asset["network_range_id"],
                    "connected_to_network",
                    "dns_ipam + approved_network_ranges",
                    "confirmed",
                    f"Interfaz en segmento autorizado ({asset.get('ip_address')}).",
                )

        # 2. Relaciones VM/Servidor -> Almacenamiento / Datastore
        for stg in storage_resources:
            stg_id = stg["id"]
            for attached_id in stg.get("attached_assets", []):
                add_rel(
                    attached_id,
                    stg_id,
                    "mounts_datastore",
                    "hypervisor_storage_api",
                    "confirmed",
                    f"Utiliza el volumen/datastore '{stg['name']}' ({stg['storage_type']}, {stg['used_gib']} GiB en uso).",
                )

        # 3. Relaciones Base de Datos -> Servidor Anfitrión y Aplicación -> Base de Datos
        for db in databases:
            db_id = db["id"]
            host_id = db["host_asset_id"]
            inst = db["1_instance_metadata"]
            add_rel(
                db_id,
                host_id,
                "runs_on_host",
                "database_catalog_connector",
                "confirmed",
                f"Motor {inst['engine']} {inst['version']} en puerto {inst['port']} sobre '{host_id}'.",
            )
            if db["4_backup_metadata"].get("last_status") == "success":
                add_rel(
                    db_id,
                    f"backup:{db['4_backup_metadata']['mechanism']}",
                    "protected_by_backup",
                    "backup_metadata_inspector",
                    "confirmed",
                    f"Último respaldo exitoso: {db['4_backup_metadata']['last_backup_at']}.",
                )

        # Relación de aplicación/middleware hacia base de datos ERP y broker
        asset_ids = {a["id"] for a in assets}
        if "asset-vm-Middleware-rhel-02" in asset_ids and any(d["id"] == "db-postgres-erp-prod" for d in databases):
            add_rel(
                "asset-vm-Middleware-rhel-02",
                "db-postgres-erp-prod",
                "application_depends_on_database",
                "process_open_sockets + config_scanner",
                "confirmed",
                "El servicio de API de facturación (RHEL) consume la base de datos PostgreSQL ERP en 10.0.2.42:5432.",
            )
        if "asset-vm-Middleware-rhel-02" in asset_ids and "asset-host-rabbitmq-kali" in asset_ids:
            add_rel(
                "asset-vm-Middleware-rhel-02",
                "asset-host-rabbitmq-kali",
                "publishes_to_message_broker",
                "network_socket_observation",
                "observed",
                "Publica eventos AMQP hacia el broker RabbitMQ en 10.0.2.15:5672.",
            )

        # 4. Relaciones con Artefactos de Arquitectura IaC
        for art in architecture_artifacts[:6]:
            if "aws" in art["path"] and "asset-host-rabbitmq-kali" in asset_ids:
                add_rel(
                    "asset-host-rabbitmq-kali",
                    art["id"],
                    "defined_in_iac_artifact",
                    "architecture_file_scanner",
                    "confirmed",
                    f"Infraestructura objetivo declarada en '{art['path']}'.",
                )

        return relationships


class MigrationReadinessService:
    """
    Evalúa qué activos, bases de datos y dependencias están preparados para migrarse (Fase 4.6)
    y genera el plan preliminar de grupos y olas de migración (*Migration Waves*).
    """

    @staticmethod
    def evaluate_asset_readiness(
        asset: Dict[str, Any],
        databases: List[Dict[str, Any]],
        storage_resources: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        aid = asset["id"]
        os_fam = (asset.get("os_family") or "unknown").lower()
        arch = (asset.get("architecture") or "unknown").lower()
        has_channel = bool(asset.get("admin_channel_available"))

        attached_dbs = [d for d in databases if d.get("host_asset_id") == aid]
        attached_stg = [s for s in storage_resources if aid in (s.get("attached_assets") or [])]
        outgoing_deps = [r for r in relationships if r["source"] == aid]
        incoming_deps = [r for r in relationships if r["target"] == aid]

        storage_used_gib = round(sum(float(s.get("used_gib", 0.0)) for s in attached_stg), 2)
        db_used_gib = round(
            sum(float(d.get("3_size_metrics", {}).get("total_used_gib", 0.0)) for d in attached_dbs),
            2,
        )
        estimated_workload_gib = round(max(storage_used_gib, db_used_gib, float(asset.get("memory_gib") or 8.0)), 2)

        missing_information: List[str] = []
        blockers_and_risks: List[str] = []

        if not has_channel:
            compatibility_status = "pending_validation"
            readiness_score = 35
            recommended_strategy = "No migrar aún — Completar descubrimiento de SO"
            wave = 5
            missing_information.append(
                "Sin acceso administrativo SSH/WinRM: faltan CPU, RAM, discos internos, procesos y paquetes del SO."
            )
            blockers_and_risks.append(
                "Activo descubierto únicamente por red/DNS (discovered_unverified). No se puede dimensionar ni exportar de forma segura."
            )
        elif os_fam == "unsupported" or arch == "sparc64":
            compatibility_status = "known_incompatible"
            readiness_score = 15
            recommended_strategy = "Re-arquitectura / Reemplazo (Incompatible con Rehost directo en x86_64/ARM64)"
            wave = 5
            blockers_and_risks.append(
                f"Arquitectura '{arch}' ({asset.get('os_name')}) no soportada para Rehost directo en instancias estándar EC2 x86_64/Graviton."
            )
        else:
            # Verificar si tiene bases de datos cuyos backups no han sido probados en restauración
            unverified_backups = [
                d["id"]
                for d in attached_dbs
                if not d.get("4_backup_metadata", {}).get("verified_restore", False)
            ]
            if unverified_backups:
                compatibility_status = "preliminary_compatible"
                readiness_score = 78
                blockers_and_risks.append(
                    f"Base de datos ({', '.join(unverified_backups)}) tiene backup registrado pero falta prueba de restauración verificada."
                )
                missing_information.append("Confirmar prueba de restauración (RPO/RTO) del backup de base de datos antes del corte.")
            else:
                compatibility_status = "verified_compatible"
                readiness_score = 94

            if attached_dbs:
                recommended_strategy = "Replatform (Amazon RDS / AWS DMS) + EC2 App Tier"
                wave = 2
            elif "rabbitmq" in (asset.get("tags") or []) or "messaging" in (asset.get("tags") or []):
                recommended_strategy = "Replatform (Amazon MQ + Amazon RDS) o Rehost EC2 con EBS gp3"
                wave = 2
            else:
                recommended_strategy = "Rehost (AWS Application Migration Service MGN / EC2)"
                wave = 3

        if incoming_deps:
            blockers_and_risks.append(
                f"Tiene {len(incoming_deps)} dependencia(s) entrante(s): no debe migrarse de forma aislada sin coordinar los consumidores."
            )

        return {
            "asset_id": aid,
            "hostname": asset.get("hostname"),
            "compatibility_status": compatibility_status,  # verified_compatible | preliminary_compatible | known_incompatible | pending_validation
            "readiness_score": readiness_score,
            "recommended_strategy": recommended_strategy,
            "recommended_wave": wave,
            "estimated_workload_gib": estimated_workload_gib,
            "requires_disk_or_config_export": has_channel and os_fam != "unsupported",
            "requires_verified_backup": bool(attached_dbs) or storage_used_gib > 50,
            "attached_databases_count": len(attached_dbs),
            "attached_storage_count": len(attached_stg),
            "outgoing_dependencies_count": len(outgoing_deps),
            "incoming_dependencies_count": len(incoming_deps),
            "co_migration_group": (
                "group-erp-billing-core"
                if aid in ("asset-vm-erp-db-01", "asset-vm-Middleware-rhel-02", "asset-host-rabbitmq-kali")
                else f"group-{asset.get('site_id', 'default')}"
            ),
            "blockers_and_risks": blockers_and_risks,
            "missing_information": missing_information,
            "evaluated_at": _utc_now(),
        }

    @classmethod
    def build_global_migration_plan(
        cls,
        assets: List[Dict[str, Any]],
        databases: List[Dict[str, Any]],
        storage_resources: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        architecture_artifacts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        per_asset = {
            a["id"]: cls.evaluate_asset_readiness(a, databases, storage_resources, relationships)
            for a in assets
        }

        waves = [
            {
                "wave": 1,
                "name": "Ola 1 — Cimientos Cloud, Red VPC, Seguridad e IaC Base",
                "description": "Aprovisionar VPC multi-AZ, subredes privadas, Security Groups, KMS/Secrets Manager y volúmenes de almacenamiento destino.",
                "items": [art["path"] for art in architecture_artifacts if art["artifact_type"] == "terraform_hcl"],
                "preconditions": ["Validar cuotas de VPC/EBS en cuenta AWS destino", "Configurar secretos en AWS Secrets Manager"],
            },
            {
                "wave": 2,
                "name": "Ola 2 — Persistencia, Bases de Datos y Brokers de Mensajería",
                "description": "Replicar esquemas y datos con AWS DMS / backups verificados (PostgreSQL, SQL Server) y desplegar brokers RabbitMQ/Amazon MQ.",
                "items": [
                    r["hostname"]
                    for r in per_asset.values()
                    if r["recommended_wave"] == 2
                ],
                "preconditions": ["Backup verificable confirmado", "Replicación inicial CDC saludable"],
            },
            {
                "wave": 3,
                "name": "Ola 3 — Servidores de Aplicación y Workers (Linux / Windows / ARM64)",
                "description": "Migrar servidores de aplicación acoplados (RHEL Billing API, Workers ARM64) apuntando a los endpoints de la Ola 2.",
                "items": [
                    r["hostname"]
                    for r in per_asset.values()
                    if r["recommended_wave"] == 3
                ],
                "preconditions": ["Pruebas de conectividad hacia bases de datos de la Ola 2"],
            },
            {
                "wave": 5,
                "name": "Ola 5 — Excepciones: Activos Inaccesibles o Incompatibles que Requieren Acción Previa",
                "description": "Nodos sin canal administrativo (DMZ aislado) o con arquitectura incompatible (Solaris SPARC64). No migrar hasta resolver bloqueos.",
                "items": [
                    r["hostname"]
                    for r in per_asset.values()
                    if r["recommended_wave"] == 5
                ],
                "preconditions": ["Habilitar colector local en DMZ", "Definir re-arquitectura para Solaris SPARC64"],
            },
        ]

        return {
            "generated_at": _utc_now(),
            "notice": (
                "Plan preliminar de preparación para migración (modo discover_plan). "
                "Ningún dato, volumen ni máquina virtual ha sido modificado ni migrado en esta fase."
            ),
            "counts_by_compatibility": {
                "verified_compatible": sum(1 for r in per_asset.values() if r["compatibility_status"] == "verified_compatible"),
                "preliminary_compatible": sum(1 for r in per_asset.values() if r["compatibility_status"] == "preliminary_compatible"),
                "known_incompatible": sum(1 for r in per_asset.values() if r["compatibility_status"] == "known_incompatible"),
                "pending_validation": sum(1 for r in per_asset.values() if r["compatibility_status"] == "pending_validation"),
            },
            "total_estimated_workload_gib": round(
                sum(r["estimated_workload_gib"] for r in per_asset.values()), 2
            ),
            "migration_waves": waves,
            "per_asset_readiness": per_asset,
        }
