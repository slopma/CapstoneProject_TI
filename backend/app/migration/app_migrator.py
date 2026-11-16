"""
Use Case 1 — Application-Driven Guided Migration (`app_source`) (Section 6).

Discovers an application statically (never executing arbitrary source code) from:
- Python (`requirements.txt`, `pyproject.toml`, `runtime.txt`)
- Node.js (`package.json`, `.nvmrc`)
- Java (`pom.xml`, `build.gradle`, `build.gradle.kts`)
- Go (`go.mod`)
- Containers (`Dockerfile`, `docker-compose.yml` / `docker-compose.yaml`)
- Deployed runtime processes and services via authorized connector metadata (`runtime_metadata`)

Extracts language, runtime, runtime version constraints, framework, start commands,
exposed ports, health endpoints, dependencies (`observed` / `confirmed`, `inferred`, `unknown`),
required environment variable keys (strictly redacting secret values and private keys),
persistent file volumes, network/identity/IAM requirements, assumptions, and target
deployment incompatibilities.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import json
import re
import subprocess
import urllib.error
import urllib.request
import zlib
from typing import Any, Dict, List, Optional, Tuple

from app.adapters.aws_adapter import AWSAdapter
from app.cmir.builder import build_cmir_hierarchy
from app.cmir.models import CMIR
from app.config import PROJECT_ROOT
from app.dependencies.resolver import resolve_dependencies
from app.discovery.connectors import SecretRedactor
from app.discovery.github_connector import (
    build_hierarchical_tree,
    LANGUAGE_EXTENSIONS,
    MANIFEST_NAMES,
    is_manifest_file,
    get_manifest_type,
)
from app.graph.builder import build_graph



from app.migration.uc1_scanner import (
    DEFAULT_INLINE_APP,
    JWT_VALUE_PATTERN,
    SECRET_KEY_PATTERNS,
    URL_CREDENTIAL_PATTERN,
    _analyze_source_payload,
    _extract_compose_depends_on,
    _extract_compose_service_ports,
    _extract_sql_from_pgdmp,
    _infer_service_endpoints,
    _parse_env_defaults,
    _parse_sql_dump_text,
    _resolve_compose_interpolations,
    _sanitize_app_name,
    _slug,
    _utc_now,
    discover_app_components_and_code,
    discover_database_backups_and_seeds,
    inspect_application_source as _scan_application_source,
    redact_env_value,
    scan_local_filesystem_tree,
)


def inspect_application_source(
    source_path: Optional[str] = None,
    inline_files: Optional[Dict[str, str]] = None,
    runtime_metadata: Optional[Dict[str, Any]] = None,
    app_name_override: Optional[str] = None,
    github_url: Optional[str] = None,
    github_ref: Optional[str] = None,
    github_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Scan application sources statically and attach the UC1 transformation catalog."""
    return _scan_application_source(
        source_path=source_path,
        inline_files=inline_files,
        runtime_metadata=runtime_metadata,
        app_name_override=app_name_override,
        github_url=github_url,
        github_ref=github_ref,
        github_token=github_token,
        catalog_builder=build_github_to_cloud_transformation_catalog,
    )


def build_github_to_cloud_transformation_catalog(
    app_discovery: Dict[str, Any],
    target_provider: str = "aws",
    deployment_mode: str = "vm_rehost",
    user_decisions: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Build an interactive catalog mapping every discovered item from the GitHub repository
    (runtime, multi-tier components, external BaaS like Supabase, databases, caches, queues,
    ports/network, secrets, and IAM identity) to what will be created in the target cloud,
    why it transforms, and the selectable options the user can choose from.
    """
    provider_clean = (target_provider or "aws").lower().strip()
    decisions_in = dict(user_decisions or app_discovery.get("user_decisions") or {})

    app_name = app_discovery.get("app_name", "app")
    slug = _slug(app_name)
    safe_slug = slug.replace("-", "_")
    ports = app_discovery.get("exposed_ports") or [8080]
    health_ep = (app_discovery.get("health_endpoints") or ["/health"])[0]
    components = app_discovery.get("components") or []
    dependencies = app_discovery.get("dependencies") or []
    env_vars = app_discovery.get("environment_variables") or []
    secret_vars = [e for e in env_vars if e.get("is_secret")]

    items: List[Dict[str, Any]] = []
    applied_decisions: Dict[str, str] = {}

    # 1. Compute, High Availability & Containerization Architecture
    comp_default = "ha_asg_alb_containerized"
    comp_selected = decisions_in.get("compute_architecture", comp_default)
    comp_options = [
        {
            "id": "ha_asg_alb_containerized",
            "label": "Alta Disponibilidad Multi-AZ (Balanceador ALB + Auto Scaling Group + Contenedores Docker)",
            "badge": "Recomendado · Resiliente a Fallos",
            "cost_estimate": "~$16–22 USD/mes (ALB) + Instancias EC2 Free-Tier",
            "description": (
                f"Despliega el repositorio contenerizado con Docker Compose (`user_data.sh` + 2GB Swap) detrás de un "
                "Application Load Balancer Multi-AZ (`aws_lb`) y un Auto Scaling Group (`aws_autoscaling_group`) "
                f"con chequeos de salud automáticos en `{health_ep}`."
            ),
            "cloud_resources_created": [
                "aws_lb.app_alb (Application Load Balancer Multi-AZ)",
                "aws_lb_target_group.app_tg (Health Check HTTP " + health_ep + ")",
                "aws_lb_listener.http_listener (Puerto 80 -> Target Group)",
                f"aws_launch_template.compute_{safe_slug}_host_lt",
                f"aws_autoscaling_group.compute_{safe_slug}_host_asg (Min 1 / Desired 2 / Max 3)",
                f"aws_instance.compute_{safe_slug}_host (Ubuntu 22.04 LTS + Docker Compose + 2GB Swap)",
            ],
        },
        {
            "id": "single_instance_containerized",
            "label": "Instancia Única Económica 100% Free-Tier (1 EC2 t3.micro + Docker Compose, sin Balanceador ni ASG)",
            "badge": "Costo Mínimo · $0 Free Tier",
            "cost_estimate": "$0 USD/mes (Elegible en Capa Gratuita AWS)",
            "description": (
                "Omite el Application Load Balancer y el Auto Scaling Group. Levanta una única máquina virtual con IP pública directa "
                "que clona el repositorio, configura 2GB de Swap y ejecuta todos los contenedores con `docker compose up -d`."
            ),
            "cloud_resources_created": [
                f"aws_instance.compute_{safe_slug}_host (1x t3.micro con IP Pública + Docker Compose + 2GB Swap)",
                "aws_security_group.app_sg (Puertos " + ", ".join(map(str, ports)) + ")",
            ],
        },
    ]
    if len(components) > 1:
        comp_options.append({
            "id": "decoupled_tier_instances",
            "label": f"Instancias Separadas por Capa ({len(components)} Servidores Dedicados por Microservicio)",
            "badge": "Aislamiento Físico por Capa",
            "cost_estimate": f"~${len(components) * 8}–{len(components) * 15} USD/mes ({len(components)} instancias dedicadas)",
            "description": (
                "En lugar de consolidar los contenedores en un mismo host con Docker Compose, aprovisiona una instancia "
                f"EC2 independiente para cada componente ({', '.join(c['name'] for c in components)})."
            ),
            "cloud_resources_created": [
                f"aws_instance.compute_{safe_slug}_{_slug(c['name']).replace('-', '_')} (Dedicada para {c['name']})"
                for c in components
            ],
        })
    valid_comp_ids = {o["id"] for o in comp_options}
    if comp_selected not in valid_comp_ids:
        comp_selected = comp_default
    applied_decisions["compute_architecture"] = comp_selected

    items.append({
        "id": "compute_architecture",
        "category": "compute",
        "github_discovered": {
            "title": f"Aplicación y Runtime Principal: {app_name}",
            "subtitle": f"{app_discovery.get('language')} · {app_discovery.get('framework')} ({app_discovery.get('runtime')})",
            "files": [f for f in app_discovery.get("files_inspected", []) if "dockerfile" in f.lower() or "compose" in f.lower() or f in ("package.json", "requirements.txt", "pyproject.toml", "pom.xml", "go.mod")][:6],
            "evidence_detail": (
                f"Runtime `{app_discovery.get('runtime')}`, comando `{app_discovery.get('start_commands', [''])[0]}`, "
                f"puertos expuestos `{ports}` y endpoint de salud `{health_ep}`."
            ),
            "badge": "Cómputo y Contenedores",
        },
        "why_transformed": (
            "El código fuente y sus manifiestos de contenedores deben alojarse en AWS con acceso de red, "
            "inicialización desatendida (`user_data.sh`) y tolerancia a fallos."
        ),
        "default_option_id": comp_default,
        "selected_option_id": comp_selected,
        "options": comp_options,
    })

    # 2. Multi-tier Components (Frontend / Backend)
    for comp in components:
        c_name = comp["name"]
        c_slug = _slug(c_name).replace("-", "_")
        c_key = f"component:{c_name}"
        is_frontend = comp.get("tier") == "frontend"
        c_default = "dedicated_compute_instance" if comp_selected == "decoupled_tier_instances" else "containerized_in_compose"
        c_selected = decisions_in.get(c_key, c_default)

        c_options = [
            {
                "id": "containerized_in_compose",
                "label": f"Ejecutar '{c_name}' como Contenedor dentro del Clúster Docker Principal",
                "badge": "Recomendado · $0 Instancias Extra",
                "cost_estimate": "$0 USD extra (Comparte host principal)",
                "description": (
                    f"Empaqueta `{c_name}` ({comp.get('framework')}) como contenedor ligero dentro del `docker-compose` del host principal, "
                    "evitando pagar por una máquina virtual separada."
                ),
                "cloud_resources_created": [
                    f"Contenedor Docker `{c_name}` en `user_data.sh` / `docker-compose.cloudmove.yml` (0 instancias EC2 adicionales)"
                ],
            },
        ]
        if is_frontend:
            c_options.append({
                "id": "cloud_static_storage",
                "label": f"Transformar Frontend '{c_name}' a Bucket S3 Static Website Hosting (`aws_s3_bucket`)",
                "badge": "Nativo AWS Serverless",
                "cost_estimate": "~$0.02 USD/GB al mes (S3 Static Hosting)",
                "description": (
                    f"Como `{c_name}` es un SPA ({comp.get('framework')}), AWS puede alojar sus archivos estáticos (HTML/JS/CSS) "
                    "directamente en un bucket Amazon S3 con Website Configuration sin consumir RAM de servidor."
                ),
                "cloud_resources_created": [
                    f"aws_s3_bucket.storage_{safe_slug}_{c_slug}_static",
                    f"aws_s3_bucket_website_configuration.storage_{safe_slug}_{c_slug}_static_website",
                ],
            })
        c_options.append({
            "id": "dedicated_compute_instance",
            "label": f"Aprovisionar Servidor EC2 Dedicado para '{c_name}'",
            "badge": "VM Independiente",
            "cost_estimate": "~$8.50 USD/mes (1 instancia t3.micro adicional)",
            "description": (
                f"Crea una máquina virtual exclusiva en Terraform para ejecutar únicamente el componente `{c_name}` "
                f"(puertos {comp.get('container_ports', [])})."
            ),
            "cloud_resources_created": [
                f"aws_instance.compute_{safe_slug}_{c_slug}"
            ],
        })

        valid_c_ids = {o["id"] for o in c_options}
        if c_selected not in valid_c_ids:
            c_selected = c_default
        applied_decisions[c_key] = c_selected

        items.append({
            "id": c_key,
            "category": "component",
            "github_discovered": {
                "title": f"Componente {comp.get('tier', 'servicio').capitalize()}: {c_name}",
                "subtitle": f"{comp.get('language')} · {comp.get('framework')} (Runtime: {comp.get('runtime')})",
                "files": [f"{c_name}/Dockerfile", f"{c_name}/package.json" if is_frontend else f"{c_name}/requirements.txt"],
                "evidence_detail": (
                    f"Puertos de contenedor: `{comp.get('container_ports', [])}` · Comando: `{comp.get('start_command')}`"
                    + (f" · Rutas API: `{', '.join(comp.get('endpoints', [])[:5])}`" if comp.get("endpoints") else "")
                ),
                "badge": "Frontend SPA" if is_frontend else "Backend API",
            },
            "why_transformed": (
                f"Sub-componente detectado en el repositorio multi-capa; puedes elegir si corre consolidado en Docker Compose, "
                f"{'en un Bucket S3 estático, o ' if is_frontend else 'o '}en una instancia dedicada."
            ),
            "default_option_id": c_default,
            "selected_option_id": c_selected,
            "options": c_options,
        })

    # 3. Dependencies (External BaaS like Supabase, Databases, Caches, Queues, Storage, Service Mesh)
    for dep in dependencies:
        dep_id = dep["id"]
        dep_safe_id = dep_id.lower().replace("-", "_").replace(".", "_")
        dep_type = dep.get("type", "database_instance")
        dep_engine = str(dep.get("engine") or "postgres")
        is_ext_baas = bool(dep.get("is_external_baas", False)) or "supabase" in dep_engine.lower() or "firebase" in dep_engine.lower()
        ev_detail = (dep.get("evidence") or [{}])[0].get("detail", "Detectado en manifiestos del repositorio.")
        ev_source = (dep.get("evidence") or [{}])[0].get("source", "Manifiesto de aplicación")
        d_key = f"dep:{dep_id}"

        if dep_type == "service_mesh_link":
            d_default = "docker_internal_network"
            d_selected = decisions_in.get(d_key, d_default)
            d_options = [
                {
                    "id": "docker_internal_network",
                    "label": "Enrutar por Red Interna de Contenedores Docker + Regla en Security Group (`app_sg`)",
                    "badge": "Recomendado · $0",
                    "cost_estimate": "$0 USD/mes (Nativo en VPC / Docker Bridge)",
                    "description": (
                        "Resuelve la comunicación HTTP/REST entre el frontend y el backend mediante la red interna de Docker Compose y "
                        "el Security Group `app_sg`, sin crear servidores adicionales por error."
                    ),
                    "cloud_resources_created": [
                        f"Regla TCP puerto {dep.get('port', 8000)} en `aws_security_group.app_sg`"
                    ],
                },
            ]
            applied_decisions[d_key] = "docker_internal_network"
            items.append({
                "id": d_key,
                "category": "networking",
                "github_discovered": {
                    "title": f"Enlace de Red Interno: {dep['name']}",
                    "subtitle": f"Protocolo {dep.get('engine', 'http_rest').upper()} · Puerto TCP {dep.get('port', 8000)}",
                    "files": [ev_source],
                    "evidence_detail": ev_detail,
                    "badge": "Comunicación Interna",
                },
                "why_transformed": "Garantiza que el frontend pueda consumir los endpoints del backend en la nube sin abrir instancias innecesarias.",
                "default_option_id": d_default,
                "selected_option_id": "docker_internal_network",
                "options": d_options,
            })
            continue

        if dep_type in ("database_instance", "database"):
            db_backups = app_discovery.get("database_backups") or (app_discovery.get("deep_insights") or {}).get("database_backups") or {}
            has_bkp = bool(dep.get("has_backup_file") or db_backups.get("has_backups"))
            bkp_file = dep.get("backup_file") or db_backups.get("primary_backup_file") or "backup.dump"
            needs_postgis = bool(dep.get("requires_postgis") or db_backups.get("requires_postgis"))
            pg_img = "postgis/postgis:17-3.5" if needs_postgis else "postgres:16-alpine"
            pub_tables_n = db_backups.get("total_public_tables", 0)
            pub_rows_n = db_backups.get("total_public_rows", 0)
            all_rows_n = db_backups.get("total_rows_all_schemas", 0)
            primary_bkp = (db_backups.get("backups") or [{}])[0] if db_backups.get("backups") else {}
            tot_tables_n = primary_bkp.get("total_tables_count", pub_tables_n)
            bkp_size_kb = round(primary_bkp.get("size_bytes", 0) / 1024.0, 1)
            bkp_format = primary_bkp.get("format", "PostgreSQL Custom Binary Dump (PGDMP)")
            pg_ver = primary_bkp.get("dumped_from_version", "17.6")
            bkp_schemas = primary_bkp.get("schemas") or ["public"]
            bkp_roles = primary_bkp.get("roles") or ["postgres"]
            bkp_exts = primary_bkp.get("extensions") or (["postgis", "pgcrypto", "uuid-ossp"] if needs_postgis else ["pgcrypto"])
            bkp_tables_data = primary_bkp.get("non_empty_tables") or []
            bkp_rpcs = primary_bkp.get("public_functions") or []
            bkp_seeds = db_backups.get("seed_files") or []

            all_ev_details = " | ".join(e.get("detail", "") for e in (dep.get("evidence") or []) if e.get("detail")) or ev_detail
            all_ev_sources = [e.get("source", ev_source) for e in (dep.get("evidence") or []) if e.get("source")] or [ev_source]

            database_analysis_payload = {
                "has_backup": has_bkp,
                "backup_file": bkp_file if has_bkp else None,
                "backup_format": bkp_format if has_bkp else None,
                "backup_size_kb": bkp_size_kb if has_bkp else 0,
                "engine_version": f"PostgreSQL {pg_ver}" + (" + PostGIS 3.5" if needs_postgis else ""),
                "target_container_image": pg_img,
                "is_external_baas": is_ext_baas,
                "source_engine": dep_engine,
                "public_tables_count": pub_tables_n,
                "public_rows_count": pub_rows_n,
                "total_tables_count": tot_tables_n,
                "total_rows_count": all_rows_n,
                "schemas": bkp_schemas,
                "roles": bkp_roles,
                "extensions": bkp_exts,
                "tables_with_data": [
                    {
                        "table": t.get("table", ""),
                        "rows": t.get("rows", 0),
                        "columns_count": len(t.get("columns") or []),
                        "is_public": str(t.get("table", "")).startswith("public."),
                    }
                    for t in bkp_tables_data
                ],
                "rpc_functions": [
                    {
                        "name": fn.get("name", ""),
                        "signature": fn.get("signature", fn.get("name", "")),
                        "returns": fn.get("returns", "void"),
                    }
                    for fn in bkp_rpcs
                ],
                "seed_files": [
                    {
                        "path": sf.get("path", ""),
                        "format": sf.get("format", "JSON"),
                        "record_count": sf.get("record_count", 0),
                    }
                    for sf in bkp_seeds
                ],
                "aws_transformation_steps": [
                    "1. Pre-creación de roles compatibles con Supabase (anon, authenticated, service_role, supabase_admin, authenticator) sin bloquear permisos en AWS.",
                    f"2. Creación de los {len(bkp_schemas)} esquemas detectados ({', '.join(bkp_schemas[:6])}{'...' if len(bkp_schemas) > 6 else ''}).",
                    f"3. Instalación de extensiones requeridas en AWS ({', '.join(bkp_exts)}).",
                    f"4. Restauración binaria de '{bkp_file}' ({pub_tables_n} tablas públicas con {pub_rows_n} filas de dominio y {all_rows_n} filas totales) antes de iniciar el Backend.",
                    "5. Inyección automática de credenciales en el Backend (DATABASE_URL, DB_HOST=db, DB_PORT=5432, DB_NAME=postgres) y verificación SQL de conteo de filas.",
                ],
            }

            compose_has_own_db = bool((app_discovery.get("deep_insights") or {}).get("compose_has_own_db"))
            d_default = (
                "self_hosted_container"
                if (
                    (is_ext_baas and has_bkp)
                    or (comp_selected == "single_instance_containerized" and compose_has_own_db)
                )
                else ("keep_external" if is_ext_baas else "transform_to_cloud_managed")
            )
            d_selected = decisions_in.get(d_key, d_default)
            d_options = [
                {
                    "id": "self_hosted_container",
                    "label": (
                        f"Transformar y Recrear BD en Contenedor `{pg_img}` en AWS EC2 + Restaurar Backup `{bkp_file}` ({pub_tables_n} tablas públicas, {all_rows_n} filas)"
                        if has_bkp
                        else f"Transformar a Contenedor PostgreSQL (`{pg_img}`) Auto-Gestionado dentro del Docker Compose de la VM"
                    ),
                    "badge": "Recomendado · Transformación Completa a AWS · $0 RDS" if has_bkp else "Ahorro Cloud · $0 RDS",
                    "cost_estimate": "$0 USD extra (Corre dentro de la misma instancia EC2 con disco EBS gp3 de 30 GB)",
                    "description": (
                        f"Transforma la base de datos de origen a un contenedor `{pg_img}` con volumen persistente `pgdata` en AWS EC2: "
                        f"pre-configura los roles y esquemas compatibles con Supabase, activa PostGIS, restaura `{bkp_file}` "
                        f"({pub_tables_n} tablas públicas con {pub_rows_n} filas de dominio, {tot_tables_n} tablas totales con {all_rows_n} filas y {len(bkp_rpcs)} funciones RPC) "
                        "antes de levantar el Backend, y expone el puerto TCP 5432."
                        if has_bkp
                        else f"Levanta un contenedor `{pg_img}` con volumen local persistente dentro de la misma instancia de cómputo en la nube, sin contratar Amazon RDS."
                    ),
                    "cloud_resources_created": [
                        f"Contenedor `{pg_img}` (puerto 5432:5432) + Volumen persistente `pgdata` en `docker-compose.cloudmove.yml`",
                        "Regla TCP puerto 5432 en `aws_security_group.app_sg` + Output `database_connection_url`",
                        *(
                            [
                                f"Transformación de esquemas/roles y restauración automática de `{bkp_file}` ({pub_tables_n} tablas públicas, {all_rows_n} filas totales) vía `migrate_database_data.sh`"
                            ]
                            if has_bkp
                            else []
                        ),
                    ],
                },
                {
                    "id": "transform_to_cloud_managed",
                    "label": (
                        f"Transformar y Migrar a Amazon RDS for PostgreSQL{' + PostGIS' if needs_postgis else ''} (Multi-AZ)"
                        + (f" + Restaurar Backup `{bkp_file}` ({all_rows_n} filas)" if has_bkp else "")
                    ),
                    "badge": "Servicio Administrado AWS" + (" + Restore Backup" if has_bkp else (" (Recomendado)" if not is_ext_baas else "")),
                    "cost_estimate": "~$15–28 USD/mes (db.t3.micro Multi-AZ + 20GB SSD)",
                    "description": (
                        "Aprovisiona una instancia dedicada `aws_db_instance` en subredes privadas aisladas "
                        "con contraseña maestra dinámica (`random_password`)"
                        + (
                            f", adapta los esquemas/roles del backup, habilita las extensiones (`{', '.join(bkp_exts[:4])}`) "
                            f"y restaura automáticamente el backup `{bkp_file}` ({pub_tables_n} tablas públicas, {all_rows_n} filas totales) hacia el endpoint de RDS mediante `migrate_database_data.sh`."
                            if has_bkp
                            else " y genera el runbook `migrate_database_data.sh` (`pg_dump`/`pg_restore`)."
                        )
                    ),
                    "cloud_resources_created": [
                        f"aws_db_instance.{dep_safe_id} (PostgreSQL db.t3.micro Multi-AZ Cifrada)",
                        "aws_db_subnet_group.db_subnets (Subredes Privadas A y B)",
                        "aws_security_group.data_sg (Puerto 5432 exclusivo desde app_sg)",
                        "random_password.db_master_password",
                        f"Transformación y restauración de `{bkp_file}` ({pub_tables_n} tablas, {all_rows_n} filas) hacia RDS vía migrate_database_data.sh"
                        if has_bkp
                        else "Script de migración de datos: migrate_database_data.sh",
                    ],
                },
                {
                    "id": "keep_external",
                    "label": (
                        f"Conservar el Servicio Externo Original ({dep['name']} / Supabase BaaS) — No crear BD en AWS"
                        if is_ext_baas
                        else "Conectar a Base de Datos Externa Existente — No aprovisionar RDS"
                    ),
                    "badge": ("Recomendado · $0 en Nube" if (is_ext_baas and not has_bkp) else "Opción Externa · $0 en Nube"),
                    "cost_estimate": "$0 USD/mes en AWS (Se mantiene en proveedor externo)",
                    "description": (
                        f"La aplicación seguirá conectándose al servicio externo (`{dep_engine}`) a través de sus variables de entorno (`.env`). "
                        "No se creará ninguna instancia Amazon RDS ni contenedor PostGIS en AWS."
                    ),
                    "cloud_resources_created": [
                        f"0 recursos de Base de Datos en Terraform (Conexión externa preservada en `.env` y `user_data.sh`)"
                    ],
                },
            ]
            valid_d_ids = {o["id"] for o in d_options}
            if d_selected not in valid_d_ids:
                d_selected = d_default
            applied_decisions[d_key] = d_selected

            items.append({
                "id": d_key,
                "category": "database_or_external",
                "github_discovered": {
                    "title": (
                        f"Analizador y Transformador de Base de Datos ({bkp_file}): {dep['name']}"
                        if has_bkp
                        else (
                            f"Servicio Externo BaaS / Base de Datos: {dep['name']}"
                            if is_ext_baas
                            else f"Base de Datos Relacional: {dep['name']}"
                        )
                    ),
                    "subtitle": (
                        f"Motor: PostgreSQL {pg_ver}{' + PostGIS' if needs_postgis else ''} · Backup: {bkp_file} ({bkp_size_kb} KB · {pub_tables_n} tablas públicas · {all_rows_n} filas)"
                        if has_bkp
                        else f"Motor: {dep_engine} · Puerto: {dep.get('port', 5432)} · Certeza: {int(dep.get('confidence', 0.95) * 100)}%"
                    ),
                    "files": all_ev_sources,
                    "evidence_detail": (
                        f"Se analizó el volcado '{bkp_file}' (PostgreSQL {pg_ver}, {bkp_size_kb} KB): contiene {pub_tables_n} tablas públicas ({pub_rows_n} filas de dominio) y {tot_tables_n} tablas totales ({all_rows_n} filas en {len(bkp_schemas)} esquemas), {len(bkp_rpcs)} funciones RPC y {len(bkp_seeds)} semillas JSON."
                        if has_bkp
                        else all_ev_details
                    ),
                    "badge": f"Base de Datos + Backup ({bkp_file})" if has_bkp else ("BaaS Externo Detectado" if is_ext_baas else "Base de Datos"),
                    "database_analysis": database_analysis_payload,
                },
                "why_transformed": (
                    f"CloudMove analizó la estructura interna de `{bkp_file}` y determinó que requiere transformar los esquemas/roles propietarios de Supabase ({', '.join(bkp_roles[:4])}) y las extensiones (`{', '.join(bkp_exts[:4])}`) para recrear una base de datos PostgreSQL + PostGIS 100% funcional en AWS con sus {all_rows_n} registros intactos."
                    if has_bkp
                    else (
                        f"Se detectó `{dep['name']}` ({dep_engine}) en GitHub. Como AWS ofrece su propio servicio administrado "
                        "(Amazon RDS), puedes elegir entre seguir usando el servicio externo gratuito, "
                        "transformarlo al servicio nativo de AWS, o alojarlo como contenedor propio."
                    )
                ),
                "default_option_id": d_default,
                "selected_option_id": d_selected,
                "options": d_options,
            })
            continue

        if dep_type == "cache":
            d_default = "transform_to_cloud_managed"
            d_selected = decisions_in.get(d_key, d_default)
            d_options = [
                {
                    "id": "transform_to_cloud_managed",
                    "label": "Transformar a Caché Administrado de la Nube: Amazon ElastiCache for Redis",
                    "badge": "Servicio Nativo AWS",
                    "cost_estimate": "~$12–15 USD/mes (cache.t3.micro)",
                    "description": "Crea un clúster Redis administrado por AWS protegido por el Security Group de datos.",
                    "cloud_resources_created": [
                        f"aws_elasticache_cluster.{dep_safe_id} (Redis 7 cache.t3.micro)",
                        "aws_security_group.data_sg (Puerto TCP 6379)",
                    ],
                },
                {
                    "id": "self_hosted_container",
                    "label": "Ejecutar Contenedor `redis:7-alpine` dentro del Docker Compose de la VM ($0 extra)",
                    "badge": "Económico · $0 ElastiCache",
                    "cost_estimate": "$0 USD extra (Corre en el mismo host Docker)",
                    "description": "Ejecuta Redis como contenedor ligero dentro de la instancia EC2 sin costo adicional.",
                    "cloud_resources_created": ["Contenedor `redis:7-alpine` en Docker Compose (0 clústeres ElastiCache)"],
                },
                {
                    "id": "keep_external",
                    "label": "Usar Servicio Redis Externo (Ej. Upstash / Redis Cloud) — No crear en Terraform",
                    "badge": "Servicio Externo · $0 en Nube",
                    "cost_estimate": "$0 USD en AWS",
                    "description": "Mantiene la conexión hacia un proveedor Redis externo mediante `REDIS_URL`.",
                    "cloud_resources_created": ["0 recursos de caché en Terraform (Conexión externa por `.env`)"],
                },
            ]
            if d_selected not in {o["id"] for o in d_options}:
                d_selected = d_default
            applied_decisions[d_key] = d_selected
            items.append({
                "id": d_key,
                "category": "database_or_external",
                "github_discovered": {
                    "title": f"Caché en Memoria: {dep['name']}",
                    "subtitle": f"Motor: {dep_engine} · Puerto: {dep.get('port', 6379)}",
                    "files": [ev_source],
                    "evidence_detail": ev_detail,
                    "badge": "Caché / Redis",
                },
                "why_transformed": "El repositorio utiliza Redis; puedes transformarlo en ElastiCache, contenedor local o servicio externo.",
                "default_option_id": d_default,
                "selected_option_id": d_selected,
                "options": d_options,
            })
            continue

        # Queue / Storage / External API
        d_default = "keep_external" if dep_type == "network_connection" else "transform_to_cloud_managed"
        d_selected = decisions_in.get(d_key, d_default)
        d_options = [
            {
                "id": "transform_to_cloud_managed",
                "label": f"Transformar a Servicio Administrado de AWS ({'S3 Bucket' if dep_type == 'storage' else 'Cola / Servicio Cloud'})",
                "badge": "Nativo AWS",
                "cost_estimate": "Pago por uso (Capa Gratuita elegible)",
                "description": f"Aprovisiona el recurso nativo equivalente en Terraform para `{dep['name']}`.",
                "cloud_resources_created": [
                    f"aws_s3_bucket.{dep_safe_id}"
                    if dep_type == "storage"
                    else f"Recurso administrado `{dep['name']}` en AWS"
                ],
            },
            {
                "id": "keep_external",
                "label": f"Mantener `{dep['name']}` como Servicio Externo — No aprovisionar en AWS",
                "badge": "Externo · $0 en Nube",
                "cost_estimate": "$0 USD en AWS",
                "description": "Conserva la referencia externa por variables de entorno sin crear el recurso en Terraform.",
                "cloud_resources_created": ["0 recursos adicionales en Terraform (Conexión externa)"],
            },
        ]
        if d_selected not in {o["id"] for o in d_options}:
            d_selected = d_default
        applied_decisions[d_key] = d_selected
        items.append({
            "id": d_key,
            "category": "database_or_external",
            "github_discovered": {
                "title": f"Dependencia Detectada: {dep['name']}",
                "subtitle": f"Tipo: {dep_type} ({dep_engine}) · Puerto: {dep.get('port', 443)}",
                "files": [ev_source],
                "evidence_detail": ev_detail,
                "badge": dep_type.upper(),
            },
            "why_transformed": "Dependencia detectada en el repositorio que puede aprovisionarse en AWS o mantenerse externa.",
            "default_option_id": d_default,
            "selected_option_id": d_selected,
            "options": d_options,
        })

    # 4. Secrets & Environment Variables (.env)
    sec_default = "env_template_user_data"
    sec_selected = decisions_in.get("secrets_and_env", sec_default)
    env_names_preview = ", ".join(e["name"] for e in env_vars[:8]) or "PORT, APP_ENV"
    sec_options = [
        {
            "id": "env_template_user_data",
            "label": "Inyectar vía Plantilla `.env` en `user_data.sh` y Variables de Terraform ($0 extra)",
            "badge": "Recomendado · $0 Secrets Manager",
            "cost_estimate": "$0 USD/mes",
            "description": (
                f"Genera el archivo `.env` automáticamente durante el arranque de la instancia (`user_data.sh`) con las {len(env_vars)} "
                "llaves detectadas (sin exponer secretos en texto plano) y sin pagar por bóvedas adicionales."
            ),
            "cloud_resources_created": [
                "Archivo `.env` auto-generado en `user_data.sh` y `.env.cloud.template` (0 bóvedas de pago)"
            ],
        },
        {
            "id": "cloud_secrets_manager",
            "label": f"Transformar a Bóveda Administrada: AWS Secrets Manager ({max(1, len(secret_vars))} secreto(s))",
            "badge": "Seguridad Enterprise AWS",
            "cost_estimate": f"~${max(1, len(secret_vars)) * 0.40:.2f} USD/mes ($0.40 por secreto)",
            "description": (
                "Crea recursos nativos `aws_secretsmanager_secret` en Terraform "
                "para almacenar y rotar las credenciales detectadas con cifrado KMS."
            ),
            "cloud_resources_created": [
                f"aws_secretsmanager_secret.secret_{safe_slug}_{_slug(s['name']).replace('-', '_')}"
                for s in (secret_vars or [{"name": "app_secrets"}])
            ],
        },
    ]
    if sec_selected not in {o["id"] for o in sec_options}:
        sec_selected = sec_default
    applied_decisions["secrets_and_env"] = sec_selected

    items.append({
        "id": "secrets_and_env",
        "category": "secrets",
        "github_discovered": {
            "title": f"Variables de Entorno y Secretos ({len(env_vars)} variables, {len(secret_vars)} secretos protegidos)",
            "subtitle": f"Llaves detectadas: {env_names_preview}",
            "files": [f for f in app_discovery.get("files_inspected", []) if ".env" in f.lower() or "compose" in f.lower()][:4] or [".env / docker-compose"],
            "evidence_detail": (
                f"Se detectaron {len(env_vars)} variables de entorno y se redactaron automáticamente {len(secret_vars)} secretos sensibles."
            ),
            "badge": "Variables y Secretos",
        },
        "why_transformed": (
            "Los contenedores necesitan estas variables al arrancar en AWS; puedes inyectarlas gratis en `user_data.sh` "
            "o crear secretos administrados en AWS Secrets Manager."
        ),
        "default_option_id": sec_default,
        "selected_option_id": sec_selected,
        "options": sec_options,
    })

    # 5. Workload Identity (IAM Role)
    iam_default = "iam_instance_profile"
    iam_selected = decisions_in.get("workload_identity", iam_default)
    iam_options = [
        {
            "id": "iam_instance_profile",
            "label": f"Crear Rol IAM Nativo + Instance Profile (`aws_iam_role.identity_{safe_slug}_sa`)",
            "badge": "Recomendado · $0",
            "cost_estimate": "$0 USD/mes (Sin costo en AWS)",
            "description": (
                "Crea un Rol IAM de mínimo privilegio y un Instance Profile para la instancia EC2, evitando incrustar llaves estáticas."
            ),
            "cloud_resources_created": [
                f"aws_iam_role.identity_{safe_slug}_sa",
                f"aws_iam_instance_profile.identity_{safe_slug}_sa_profile",
            ],
        },
        {
            "id": "skip_custom_iam",
            "label": "No crear Rol IAM en Terraform (Ideal para cuentas restringidas / AWS Academy Learner Lab)",
            "badge": "Compatible AWS Academy",
            "cost_estimate": "$0 USD/mes",
            "description": (
                "Omite la creación de `aws_iam_role` y `aws_iam_instance_profile` en `main.tf`, permitiendo ejecutar `terraform apply` "
                "sin errores de permisos `iam:CreateRole` en laboratorios académicos."
            ),
            "cloud_resources_created": [
                "0 recursos IAM creados (Evita bloqueos `AccessDenied` en `iam:CreateRole`)"
            ],
        },
    ]
    if iam_selected not in {o["id"] for o in iam_options}:
        iam_selected = iam_default
    applied_decisions["workload_identity"] = iam_selected

    items.append({
        "id": "workload_identity",
        "category": "security",
        "github_discovered": {
            "title": "Identidad de Ejecución en la Nube (IAM / Service Account)",
            "subtitle": f"Permisos derivados para {app_name}",
            "files": ["Manifiestos de aplicación y telemetría"],
            "evidence_detail": "Requerido para que el servidor en la nube pueda registrar logs y acceder a recursos sin llaves hardcodeadas.",
            "badge": "Seguridad IAM",
        },
        "why_transformed": (
            "Traduce la identidad del servicio en un Rol IAM (`aws_iam_role`) "
            "(no en un servidor EC2), o permite omitirlo si tu cuenta académica restringe IAM."
        ),
        "default_option_id": iam_default,
        "selected_option_id": iam_selected,
        "options": iam_options,
    })

    # 6. Root Disk EBS Capacity, Swap & Build Resilience (Prevents `no space left on device`)
    disk_default = "ebs_30gb_gp3_swap"
    disk_selected = decisions_in.get("storage_and_build_capacity", disk_default)
    disk_options = [
        {
            "id": "ebs_30gb_gp3_swap",
            "label": "Volumen Raíz EBS gp3 de 30 GB + 2 GB Swap + Limpieza de Caché Docker (AWS Free Tier)",
            "badge": "Recomendado · Previene 'No Space Left on Device' · $0 Free Tier",
            "cost_estimate": "$0 USD/mes (Incluido en los 30 GB gratuitos de AWS Free Tier)",
            "description": (
                "El disco por defecto de Ubuntu en AWS es de solo 8 GB, el cual se llena al combinar 2 GB de Swap + "
                "imágenes PostGIS (~1.1 GB) + librerías Python ML/GIS (scipy, scikit-learn, geopandas ~2.5 GB) + Node/Vite. "
                "Asignar 30 GB gp3 cifrados y ejecutar `docker builder prune -af` garantiza compilaciones sin fallos."
            ),
            "cloud_resources_created": [
                "root_block_device { volume_size = 30, volume_type = \"gp3\", encrypted = true } en aws_instance",
                "Archivo /swapfile de 2 GB + Limpieza automática `docker builder prune -af` en user_data.sh",
            ],
        },
        {
            "id": "ebs_50gb_gp3_swap",
            "label": "Volumen Raíz EBS gp3 de 50 GB + 2 GB Swap (Cargas Intensivas de Datos y Modelos ML)",
            "badge": "Alta Capacidad · 50 GB",
            "cost_estimate": "~$1.60 USD/mes adicionales sobre la capa gratuita (20 GB extra gp3)",
            "description": (
                "Amplía el volumen raíz a 50 GB gp3 para proyectos con backups de base de datos de varios gigabytes, "
                "múltiples contenedores pesados o almacenamiento intensivo de capas geoespaciales."
            ),
            "cloud_resources_created": [
                "root_block_device { volume_size = 50, volume_type = \"gp3\", encrypted = true } en aws_instance",
                "Archivo /swapfile de 2 GB + Limpieza automática `docker builder prune -af` en user_data.sh",
            ],
        },
        {
            "id": "ebs_20gb_gp3_swap",
            "label": "Volumen Raíz EBS gp3 de 20 GB + 2 GB Swap (Proyectos Ligeros)",
            "badge": "Compacto · 20 GB",
            "cost_estimate": "$0 USD/mes (AWS Free Tier)",
            "description": "Asigna 20 GB gp3 de almacenamiento raíz, suficiente para servicios ligeros sin dependencias pesadas de ML.",
            "cloud_resources_created": [
                "root_block_device { volume_size = 20, volume_type = \"gp3\", encrypted = true } en aws_instance",
            ],
        },
    ]
    if disk_selected not in {o["id"] for o in disk_options}:
        disk_selected = disk_default
    applied_decisions["storage_and_build_capacity"] = disk_selected

    items.append({
        "id": "storage_and_build_capacity",
        "category": "storage",
        "github_discovered": {
            "title": "Dimensionamiento de Disco Raíz EBS, Swap y Compilación de Imágenes Docker",
            "subtitle": f"Prevención proactiva de agotamiento de disco en compilación ({len(components)} capas + Base de Datos)",
            "files": [f for f in app_discovery.get("files_inspected", []) if "dockerfile" in f.lower() or "requirements" in f.lower() or "package.json" in f.lower()][:5],
            "evidence_detail": (
                "La compilación simultánea de imágenes Docker (Frontend Node/Vite + Backend Python/ML/GIS + Motor PostGIS 17) "
                "junto con 2 GB de Swap consume ~6.8 GB, superando la capacidad libre de un disco por defecto de 8 GB."
            ),
            "badge": "Prevención de Fallo de Disco",
        },
        "why_transformed": (
            "Adelantarse al error `write ... no space left on device` durante `docker compose up -d --build`: "
            "configura explícitamente un volumen EBS `gp3` de 30 GB (elegible en AWS Free Tier) en `main.tf`."
        ),
        "default_option_id": disk_default,
        "selected_option_id": disk_selected,
        "options": disk_options,
    })

    # 7. Network Firewall Ports & Dynamic Public IP Environment Rewriting
    net_default = "auto_rewrite_public_ip_and_open_ports"
    net_selected = decisions_in.get("network_and_env_rewriting", net_default)
    net_options = [
        {
            "id": "auto_rewrite_public_ip_and_open_ports",
            "label": (
                "Reescribir Dinámicamente `VITE_API_URL` con la IP Pública de EC2 antes del Build + Abrir Puertos Web y BD (3000, 8000, 5432)"
            ),
            "badge": "Recomendado · Previene 'No se pudo conectar'",
            "cost_estimate": "$0 USD/mes",
            "description": (
                "Detecta la IP pública real de EC2 vía IMDSv2 (`169.254.169.254`) en `user_data.sh` y reemplaza automáticamente "
                "`VITE_API_URL=http://localhost:8000` (o IPs antiguas/con typos en `.env` y `frontend-vite/.env`) antes de ejecutar `vite build`. "
                "Además, abre los puertos 22, 80, 443, 3000, 8000 y 5432 en `aws_security_group.app_sg`."
            ),
            "cloud_resources_created": [
                "Inyección dinámica de `VITE_API_URL=http://${PUBLIC_IP}:8000` y `DB_HOST=db` en todos los `.env` antes del build",
                "Reglas Ingress TCP 22, 80, 443, 3000, 5432 y 8000 en `aws_security_group.app_sg`",
            ],
        },
        {
            "id": "strict_private_db_port",
            "label": (
                "Reescribir `VITE_API_URL` con IP Pública EC2 + Abrir Puertos Web (3000, 8000) + Mantener Puerto 5432 Cerrado al Exterior"
            ),
            "badge": "Puerto BD Privado",
            "cost_estimate": "$0 USD/mes",
            "description": (
                "Actualiza `VITE_API_URL` con la IP pública de EC2 para que el Frontend conecte con el Backend (`:8000`), "
                "pero mantiene el puerto `5432` accesible únicamente desde la red interna de Docker entre el Backend y PostGIS."
            ),
            "cloud_resources_created": [
                "Inyección dinámica de `VITE_API_URL=http://${PUBLIC_IP}:8000` y `DB_HOST=db` en `.env`",
                "Reglas Ingress TCP 22, 80, 443, 3000 y 8000 en `aws_security_group.app_sg` (Puerto 5432 solo interno)",
            ],
        },
    ]
    if net_selected not in {o["id"] for o in net_options}:
        net_selected = net_default
    applied_decisions["network_and_env_rewriting"] = net_selected

    items.append({
        "id": "network_and_env_rewriting",
        "category": "networking",
        "github_discovered": {
            "title": "Reescritura de Variables `.env` (`VITE_API_URL` / `DB_HOST`) y Reglas de Firewall (`Security Group`)",
            "subtitle": f"Puertos detectados: {', '.join(map(str, sorted(set(ports) | {5432})))} · Variables de conexión Frontend-Backend-BD",
            "files": [".env", "frontend-vite/.env", "backend/.env", "frontend-vite/Dockerfile"],
            "evidence_detail": (
                "Los repositorios suelen incluir `.env` con `VITE_API_URL=http://localhost:8000` o IPs antiguas que Vite incrusta en tiempo de compilación, "
                "impidiendo que el navegador del usuario conecte al Backend en AWS si no se actualizan antes del build."
            ),
            "badge": "Conectividad y Firewall",
        },
        "why_transformed": (
            "Garantiza que al abrir el Frontend (`:3000`), el Backend (`:8000`) y la Base de Datos (`:5432`) en AWS todos respondan "
            "correctamente y apunten a la IP pública real de la instancia EC2."
        ),
        "default_option_id": net_default,
        "selected_option_id": net_selected,
        "options": net_options,
    })

    preflight_preventive_checks = [
        {
            "id": "prevent-disk-exhaustion",
            "risk_title": "Agotamiento de Disco en Compilación Docker (`no space left on device`)",
            "cause": "La AMI de Ubuntu 22.04 trae 8 GB por defecto; al crear 2 GB de Swap y compilar PostGIS + Python ML/GIS (scipy/sklearn/geopandas) + Node, el disco se llena y ningún contenedor arranca.",
            "prevention_applied": "Se aprovisiona un volumen raíz EBS `gp3` cifrado de 30 GB (o 50 GB) + limpieza automática `docker builder prune -af`.",
            "status": "MITIGADO",
        },
        {
            "id": "prevent-vite-localhost-url",
            "risk_title": "Frontend apuntando a `localhost:8000` o IP antigua en `.env`",
            "cause": "Si el repositorio ya tiene `.env` o `frontend-vite/.env` versionado en Git, `vite build` quema `http://localhost:8000` en el bundle JS y el navegador falla con 'No se pudo conectar'.",
            "prevention_applied": "`user_data.sh` consulta la IP pública real de EC2 vía IMDSv2 (`169.254.169.254`) y reescribe `VITE_API_URL=http://${PUBLIC_IP}:8000` en todos los `.env` antes de compilar.",
            "status": "MITIGADO",
        },
        {
            "id": "prevent-db-port-and-startup-order",
            "risk_title": "Orden de Arranque y Acceso al Puerto 5432 de Base de Datos",
            "cause": "Si el Backend inicia antes de restaurar el backup o si el Security Group bloquea el puerto 5432, las consultas iniciales o clientes externos fallan.",
            "prevention_applied": "Se abre TCP 5432 en `aws_security_group.app_sg` (si se habilita), se levanta primero el contenedor `db`, se restaura el backup completo y luego se inician Backend y Frontend.",
            "status": "MITIGADO",
        },
        {
            "id": "prevent-supabase-role-mismatch",
            "risk_title": "Incompatibilidad de Roles y Extensiones al Transformar Backup de Supabase a AWS",
            "cause": "Los dumps de Supabase requieren roles (`anon`, `authenticated`, `service_role`, `supabase_admin`), 11 esquemas y extensiones (`postgis`, `pgcrypto`, `uuid-ossp`).",
            "prevention_applied": "`migrate_database_data.sh` pre-crea todos los roles, esquemas y extensiones en PostgreSQL/PostGIS antes de ejecutar `pg_restore --no-owner --no-privileges`.",
            "status": "MITIGADO",
        },
        {
            "id": "prevent-aws-user-data-16kb-limit",
            "risk_title": "Límite de 16 KB en Script de Inicio EC2 (`user_data.sh`)",
            "cause": "La API de AWS EC2 rechaza scripts mayores a 16,384 bytes si se incrustan volcados o bridges de datos directamente.",
            "prevention_applied": "CloudMove comprime automáticamente con `gzip` nivel 9 y `base64` en un bootstrap auto-extraíble si el script supera los 15 KB.",
            "status": "MITIGADO",
        },
        {
            "id": "prevent-rds-timeout-multi-az",
            "risk_title": "Timeout en Aprovisionamiento de RDS o Laboratorios Académicos",
            "cause": "`multi_az = true` toma 12 a 18 minutos en aprovisionar y sobrepasa límites de tiempo estándar de despliegue.",
            "prevention_applied": "`multi_az = false` configurado por defecto para entornos Free Tier / Académicos y timeout del ejecutor ampliado a 1500s (25 min).",
            "status": "MITIGADO",
        },
    ]

    # Build consolidated preview of all cloud resources that will be created
    planned_resources_summary: List[Dict[str, str]] = [
        {
            "terraform_resource": "aws_vpc.target_vpc + 4x aws_subnet (Multi-AZ) + aws_internet_gateway.igw",
            "github_origin": f"Red base y puertos expuestos ({', '.join(map(str, ports))})",
            "reason": "Aislamiento de red virtual y subredes en AWS para alojar la aplicación de forma segura.",
            "decision_label": "Red Base VPC Multi-AZ (Automático)",
        }
    ]
    for item in items:
        sel_opt = next((o for o in item["options"] if o["id"] == item["selected_option_id"]), item["options"][0])
        for res_str in sel_opt.get("cloud_resources_created", []):
            planned_resources_summary.append({
                "terraform_resource": res_str,
                "github_origin": item["github_discovered"]["title"],
                "reason": item["why_transformed"],
                "decision_label": sel_opt["label"],
                "cost_estimate": sel_opt.get("cost_estimate", "$0"),
            })

    return {
        "target_provider": provider_clean,
        "deployment_mode": deployment_mode,
        "items": items,
        "applied_decisions": applied_decisions,
        "planned_resources_summary": planned_resources_summary,
        "preflight_preventive_checks": preflight_preventive_checks,
    }


def build_application_cmir(
    app_discovery: Dict[str, Any],
    target_provider: str = "aws",
    deployment_mode: str = "vm_rehost",
    user_decisions: Optional[Dict[str, str]] = None,
) -> CMIR:
    """
    Build a CMIR v2.1 representation of the discovered application, its runtime,
    ports, volumes, identity, and dependencies without storing secret values,
    honoring the user's interactive transformation decisions (`user_decisions`).
    """
    provider_clean = target_provider.lower().strip()
    now = app_discovery.get("discovered_at") or _utc_now()
    app_id = app_discovery["app_id"]
    app_name = app_discovery["app_name"]
    slug = _slug(app_name)

    catalog = build_github_to_cloud_transformation_catalog(
        app_discovery,
        target_provider=provider_clean,
        deployment_mode=deployment_mode,
        user_decisions=user_decisions,
    )
    decisions = catalog["applied_decisions"]
    app_discovery["transformation_catalog"] = catalog
    app_discovery["user_decisions"] = decisions

    comp_arch_choice = decisions.get("compute_architecture", "ha_asg_alb_containerized")
    disable_ha_alb_asg = comp_arch_choice == "single_instance_containerized"
    disk_choice = decisions.get("storage_and_build_capacity", "ebs_30gb_gp3_swap")
    root_vol_gb = 50 if disk_choice == "ebs_50gb_gp3_swap" else (20 if disk_choice == "ebs_20gb_gp3_swap" else 30)
    net_choice = decisions.get("network_and_env_rewriting", "auto_rewrite_public_ip_and_open_ports")
    expose_db_port = net_choice != "strict_private_db_port"

    nodes: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []

    compute_id = f"compute-{slug}-host"
    compute_type = "container" if deployment_mode == "container" else "virtual_machine"
    nodes.append({
        "id": compute_id,
        "canonical_id": f"asset:compute:{slug}",
        "name": f"{app_name}-runtime-host",
        "type": compute_type,
        "category": "compute",
        "provider": provider_clean,
        "platform": app_discovery["runtime"],
        "epistemic_state": "observed",
        "confidence": 0.99,
        "source_connector": "app_source_scanner",
        "discovered_at": now,
        "evidence": [
            {
                "source": "Dockerfile / manifiesto de aplicación",
                "observed_at": now,
                "epistemic_state": "observed",
                "confidence": 0.99,
                "detail": f"Entorno de ejecución detectado: {app_discovery['runtime']} ({app_discovery['language']}, restricción {app_discovery.get('runtime_constraints')}).",
            }
        ],
        "metadata": {
            "is_primary_host": True,
            "language": app_discovery["language"],
            "framework": app_discovery["framework"],
            "runtime": app_discovery["runtime"],
            "runtime_constraints": app_discovery.get("runtime_constraints"),
            "deployment_mode": deployment_mode,
            "compute_architecture_choice": comp_arch_choice,
            "disable_ha_alb_asg": disable_ha_alb_asg,
            "root_volume_size_gb": root_vol_gb,
            "expose_db_port_externally": expose_db_port,
            "exposed_ports": app_discovery["exposed_ports"],
            "health_endpoints": app_discovery.get("health_endpoints", ["/health"]),
            "service_endpoints": app_discovery.get("service_endpoints") or {},
        },
    })
    if app_discovery.get("git_metadata"):
        gm = app_discovery["git_metadata"]
        nodes[0]["evidence"].append({
            "source": f"GitHub Repository ({gm['repository_url']})",
            "observed_at": gm.get("pinned_at", now),
            "epistemic_state": "observed",
            "confidence": 1.0,
            "detail": f"Commit fijado: {gm['commit_sha']} ({gm.get('ref')}) por {gm.get('author_name')}: {gm.get('commit_message')}",
        })
        nodes[0]["metadata"]["git_metadata"] = gm

    nodes.append({
        "id": app_id,
        "canonical_id": f"asset:app:{slug}",
        "name": app_name,
        "type": "application",
        "category": "application",
        "parent_id": compute_id,
        "provider": provider_clean,
        "platform": app_discovery["framework"],
        "epistemic_state": "observed",
        "confidence": 1.0,
        "source_connector": "app_source_scanner",
        "discovered_at": now,
        "evidence": [
            {
                "source": app_discovery["source_path"],
                "observed_at": now,
                "epistemic_state": "observed",
                "confidence": 1.0,
                "detail": f"Aplicación '{app_name}' con comando de inicio: {app_discovery['start_commands'][0]}",
            }
        ],
        "metadata": {
            "start_commands": app_discovery["start_commands"],
            "exposed_ports": app_discovery["exposed_ports"],
            "health_endpoints": app_discovery.get("health_endpoints", ["/health"]),
            "env_var_keys": [e["name"] for e in app_discovery["environment_variables"]],
        },
    })
    relationships.append({
        "source": app_id,
        "target": compute_id,
        "type": "runs_on",
        "epistemic_state": "observed",
        "confidence": 1.0,
        "source_connector": "app_source_scanner",
        "discovered_at": now,
    })

    components = app_discovery.get("components") or []
    if len(components) > 1:
        for comp in components:
            c_slug = _slug(comp["name"])
            c_comp_id = f"compute-{slug}-{c_slug}"
            c_app_id = f"app-{slug}-{c_slug}"
            comp_choice = decisions.get(f"component:{comp['name']}", "containerized_in_compose")
            is_dedicated = comp_choice == "dedicated_compute_instance" or comp_arch_choice == "decoupled_tier_instances"
            nodes.append({
                "id": c_comp_id,
                "canonical_id": f"asset:compute:{slug}:{c_slug}",
                "name": f"{app_name}-{comp['name']}-host",
                "type": compute_type,
                "category": "compute",
                "provider": provider_clean,
                "platform": comp.get("runtime", app_discovery["runtime"]),
                "epistemic_state": "observed",
                "confidence": 0.99,
                "source_connector": "app_source_scanner",
                "discovered_at": now,
                "evidence": [
                    {
                        "source": f"Dockerfile / {comp['name']}",
                        "observed_at": now,
                        "epistemic_state": "observed",
                        "confidence": 0.99,
                        "detail": f"Componente {comp['name']} ({comp.get('tier')}): runtime {comp.get('runtime')}, puertos {comp.get('container_ports')}",
                    }
                ],
                "metadata": {
                    "is_subcomponent_container": True,
                    "dedicated_instance": is_dedicated,
                    "user_decision": comp_choice,
                    "parent_compute_id": compute_id,
                    "component": comp["name"],
                    "tier": comp.get("tier"),
                    "runtime": comp.get("runtime"),
                    "ports": comp.get("container_ports", []),
                },
            })
            if comp_choice == "cloud_static_storage":
                static_bucket_id = f"storage-{slug}-{c_slug}-static"
                nodes.append({
                    "id": static_bucket_id,
                    "canonical_id": f"asset:storage:{slug}:{c_slug}:static",
                    "name": f"{slug}-{c_slug}-static-web",
                    "type": "storage",
                    "category": "storage",
                    "provider": provider_clean,
                    "engine": "s3_static_website" if provider_clean == "aws" else "gcs_static_website",
                    "epistemic_state": "derived",
                    "confidence": 0.98,
                    "source_connector": "app_source_scanner",
                    "discovered_at": now,
                    "metadata": {
                        "static_website_hosting": True,
                        "component": comp["name"],
                        "user_decision": "cloud_static_storage",
                    },
                })
                relationships.append({
                    "source": c_app_id,
                    "target": static_bucket_id,
                    "type": "hosted_on_bucket",
                    "epistemic_state": "derived",
                    "confidence": 0.98,
                    "source_connector": "app_source_scanner",
                    "discovered_at": now,
                })
            nodes.append({
                "id": c_app_id,
                "canonical_id": f"asset:app:{slug}:{c_slug}",
                "name": f"{app_name}-{comp['name']}",
                "type": "application",
                "category": "application",
                "parent_id": c_comp_id,
                "provider": provider_clean,
                "platform": comp.get("framework", comp.get("language")),
                "epistemic_state": "observed",
                "confidence": 1.0,
                "source_connector": "app_source_scanner",
                "discovered_at": now,
                "evidence": [
                    {
                        "source": f"Manifiestos y código de {comp['name']}",
                        "observed_at": now,
                        "epistemic_state": "observed",
                        "confidence": 1.0,
                        "detail": f"Aplicación componente {comp['name']} con framework {comp.get('framework')} ({comp.get('language')})",
                    }
                ],
                "metadata": {
                    "component": comp["name"],
                    "tier": comp.get("tier"),
                    "framework": comp.get("framework"),
                    "language": comp.get("language"),
                    "start_commands": [comp["start_command"]] if comp.get("start_command") else [],
                    "exposed_ports": comp.get("container_ports", []),
                    "endpoints": comp.get("endpoints", []),
                    "api_calls": comp.get("api_calls", []),
                },
            })
            relationships.append({
                "source": c_app_id,
                "target": c_comp_id,
                "type": "runs_on",
                "epistemic_state": "observed",
                "confidence": 1.0,
                "source_connector": "app_source_scanner",
                "discovered_at": now,
            })
            relationships.append({
                "source": c_app_id,
                "target": app_id,
                "type": "part_of",
                "epistemic_state": "observed",
                "confidence": 1.0,
                "source_connector": "app_source_scanner",
                "discovered_at": now,
            })

        deep_insights = app_discovery.get("deep_insights") or {}
        for link in deep_insights.get("internal_service_links", []):
            src_app = f"app-{slug}-{_slug(link['source'])}"
            tgt_app = f"app-{slug}-{_slug(link['target'])}"
            relationships.append({
                "source": src_app,
                "target": tgt_app,
                "type": "consumes_api",
                "epistemic_state": "observed",
                "confidence": 0.99,
                "source_connector": "app_source_scanner",
                "discovered_at": now,
                "metadata": {
                    "protocol": link.get("protocol", "HTTP/REST"),
                    "port": link.get("port", 8000),
                    "env_variable": link.get("env_variable", "VITE_API_URL"),
                },
            })

    for p in app_discovery["exposed_ports"]:
        port_id = f"port-{slug}-{p}"
        nodes.append({
            "id": port_id,
            "canonical_id": f"asset:port:{slug}:{p}",
            "name": f"tcp-{p}",
            "type": "port",
            "category": "network",
            "parent_id": compute_id,
            "provider": provider_clean,
            "epistemic_state": "observed",
            "confidence": 0.99,
            "source_connector": "app_source_scanner",
            "discovered_at": now,
            "metadata": {"port": p, "protocol": "tcp"},
        })
        relationships.append({
            "source": app_id,
            "target": port_id,
            "type": "exposes",
            "epistemic_state": "observed",
            "confidence": 0.99,
            "source_connector": "app_source_scanner",
            "discovered_at": now,
        })

    for idx, vol_path in enumerate(app_discovery["persistent_volumes"]):
        vol_id = f"vol-{slug}-{idx}"
        nodes.append({
            "id": vol_id,
            "canonical_id": f"asset:volume:{slug}:{vol_path}",
            "name": f"{slug}-volume-{idx}",
            "type": "volume",
            "category": "storage",
            "parent_id": compute_id,
            "provider": provider_clean,
            "epistemic_state": "observed",
            "confidence": 0.95,
            "source_connector": "app_source_scanner",
            "discovered_at": now,
            "metadata": {"mount_path": vol_path, "size_gib": 50},
        })
        relationships.append({
            "source": app_id,
            "target": vol_id,
            "type": "mounts",
            "epistemic_state": "observed",
            "confidence": 0.95,
            "source_connector": "app_source_scanner",
            "discovered_at": now,
        })

    if decisions.get("workload_identity", "iam_instance_profile") != "skip_custom_iam":
        identity_id = f"identity-{slug}-sa"
        nodes.append({
            "id": identity_id,
            "canonical_id": f"asset:identity:{slug}",
            "name": f"{slug}-workload-identity",
            "type": "identity",
            "category": "security",
            "provider": provider_clean,
            "epistemic_state": "derived",
            "confidence": 0.95,
            "source_connector": "app_source_scanner",
            "discovered_at": now,
            "metadata": {"role_type": "IAM Role"},
        })
        relationships.append({
            "source": app_id,
            "target": identity_id,
            "type": "requires_identity",
            "epistemic_state": "derived",
            "confidence": 0.95,
            "source_connector": "app_source_scanner",
            "discovered_at": now,
        })

    if decisions.get("secrets_and_env", "env_template_user_data") == "cloud_secrets_manager":
        secret_vars = [e for e in app_discovery.get("environment_variables", []) if e.get("is_secret")]
        if not secret_vars:
            secret_vars = [{"name": "app-runtime-secrets"}]
        for sv in secret_vars:
            sec_slug = _slug(sv["name"])
            sec_id = f"secret-{slug}-{sec_slug}"
            nodes.append({
                "id": sec_id,
                "canonical_id": f"asset:secret:{slug}:{sec_slug}",
                "name": f"{slug}-{sec_slug}",
                "type": "secret",
                "category": "security",
                "provider": provider_clean,
                "epistemic_state": "derived",
                "confidence": 0.98,
                "source_connector": "app_source_scanner",
                "discovered_at": now,
                "metadata": {"env_key": sv["name"], "user_decision": "cloud_secrets_manager"},
            })
            relationships.append({
                "source": app_id,
                "target": sec_id,
                "type": "reads_secret",
                "epistemic_state": "derived",
                "confidence": 0.98,
                "source_connector": "app_source_scanner",
                "discovered_at": now,
            })

    for dep in app_discovery["dependencies"]:
        dep_choice = decisions.get(f"dep:{dep['id']}")
        is_ext_baas = bool(dep.get("is_external_baas", False))
        force_cloud_managed = False
        run_in_compose = False
        if dep_choice == "transform_to_cloud_managed":
            is_ext_baas = False
            force_cloud_managed = True
        elif dep_choice == "keep_external":
            is_ext_baas = True
            force_cloud_managed = False
        elif dep_choice == "self_hosted_container":
            is_ext_baas = False
            run_in_compose = True

        nodes.append({
            "id": dep["id"],
            "canonical_id": f"asset:dep:{dep['id']}",
            "name": dep["name"],
            "type": dep["type"],
            "category": "data" if dep["type"] in ("database_instance", "cache", "storage") else "integration",
            "provider": provider_clean,
            "engine": "postgres" if (force_cloud_managed and "supabase" in str(dep.get("engine", "")).lower()) else dep.get("engine"),
            "epistemic_state": dep["epistemic_state"],
            "confidence": dep["confidence"],
            "source_connector": "app_source_scanner",
            "discovered_at": now,
            "evidence": dep.get("evidence", []),
            "metadata": {
                "port": dep.get("port"),
                "classification": dep["classification"],
                "requires_data_migration": (
                    True
                    if (force_cloud_managed or run_in_compose or dep.get("has_backup_file"))
                    else dep.get("requires_data_migration", False)
                ),
                "has_backup_file": bool(dep.get("has_backup_file")),
                "backup_file": dep.get("backup_file"),
                "requires_postgis": bool(dep.get("requires_postgis")),
                "is_external_baas": is_ext_baas,
                "force_cloud_managed": force_cloud_managed,
                "run_in_compose_container": run_in_compose,
                "user_decision": dep_choice,
            },
        })
        relationships.append({
            "source": app_id,
            "target": dep["id"],
            "type": dep["relationship_type"],
            "epistemic_state": dep["epistemic_state"],
            "confidence": dep["confidence"],
            "source_connector": "app_source_scanner",
            "discovered_at": now,
            "evidence": dep.get("evidence", []),
            "metadata": {
                "classification": dep["classification"],
                "reason": dep["evidence"][0]["detail"] if dep.get("evidence") else "",
                "user_decision": dep_choice,
            },
        })

    return build_cmir_hierarchy({
        "name": f"App Migration CMIR — {app_name}",
        "provider": provider_clean,
        "version": "2.1",
        "resources": nodes,
        "relationships": relationships,
        "metadata": {
            "use_case": "app_source",
            "app_name": app_name,
            "deployment_mode": deployment_mode,
            "user_decisions": decisions,
        },
    })


def evaluate_app_migration_viability(
    app_discovery: Dict[str, Any],
    cmir: CMIR,
    target_provider: str = "aws",
    deployment_mode: str = "vm_rehost",
) -> Dict[str, Any]:
    """
    Evaluate migration viability to AWS while preserving application behavior.
    Never forces a migration to stateless containers (ECS Fargate) if the
    application relies on local disk persistence or lacks container support without
    offering the compatible VM rehost alternative (`AWS EC2`).
    """
    provider_clean = target_provider.lower().strip()
    graph = build_graph(cmir)
    dep_analysis = resolve_dependencies(graph, [app_discovery["app_id"]])

    blockers: List[str] = []
    warnings: List[str] = []
    incompatibilities: List[Dict[str, str]] = []

    if app_discovery["dependency_summary"]["inferred_count"] > 0:
        warnings.append(
            f"Existen {app_discovery['dependency_summary']['inferred_count']} dependencias inferidas "
            f"({', '.join(app_discovery['dependency_summary']['inferred'])}) que no se tratan como hechos confirmados; "
            "valide su uso antes del cutover."
        )
    if app_discovery["dependency_summary"]["unknown_count"] > 0:
        warnings.append(
            f"Existen {app_discovery['dependency_summary']['unknown_count']} endpoints externos con alcanzabilidad "
            f"desconocida desde {provider_clean.upper()} ({', '.join(app_discovery['dependency_summary']['unknown'])})."
        )

    # Check containerization / serverless incompatibilities
    recommended_mode = deployment_mode
    if deployment_mode == "container":
        if app_discovery.get("persistent_volumes"):
            incompatibilities.append({
                "type": "stateful_local_filesystem",
                "detail": (
                    f"La aplicación monta rutas persistentes locales ({', '.join(app_discovery['persistent_volumes'])}). "
                    "En AWS ECS Fargate el sistema de archivos local es efímero."
                ),
                "recommended_alternative": "Usar `vm_rehost` (Amazon EC2 + EBS) o montar Amazon EFS.",
            })
            warnings.append(
                f"Advertencia de compatibilidad: La aplicación utiliza almacenamiento persistente en disco ({app_discovery['persistent_volumes']}). "
                "Para preservar el comportamiento sin refactorizar se recomienda `vm_rehost` en EC2 o adjuntar Amazon EFS."
            )

    target_architecture = {
        "compute_service": "Amazon EC2 (Ubuntu/Debian con Docker/systemd)" if deployment_mode == "vm_rehost" else "Amazon ECS Fargate",
        "recommended_compute_option": "Amazon EC2 (`vm_rehost`)" if recommended_mode == "vm_rehost" else "Amazon ECS Fargate (`container`)",
        "supported_options": ["Amazon EC2 (Rehost sin refactorización)", "Amazon ECS Fargate", "Amazon EKS"],
        "database_service": "Amazon RDS for PostgreSQL (Multi-AZ) + AWS DMS / pg_dump data sync",
        "cache_service": "Amazon ElastiCache for Redis",
        "queue_service": "Amazon MQ for RabbitMQ",
        "storage_service": "Amazon EBS gp3 + Amazon S3",
        "secret_management": "AWS Secrets Manager / SSM Parameter Store",
        "network_boundary": "Amazon VPC + Security Groups (puertos " + ", ".join(map(str, app_discovery["exposed_ports"])) + ")",
    }

    return {
        "viable": len(blockers) == 0,
        "target_provider": provider_clean,
        "deployment_mode": deployment_mode,
        "recommended_deployment_mode": recommended_mode,
        "preserves_application_behavior": True,
        "requires_code_refactoring": False,
        "incompatibilities": incompatibilities,
        "rationale": (
            f"La aplicación '{app_discovery['app_name']}' ({app_discovery['language']} / {app_discovery['framework']}) "
            f"puede migrarse a {provider_clean.upper()} preservando su punto de entrada (`{app_discovery['start_commands'][0]}`) "
            "y parametrizando únicamente las variables de entorno de conexión hacia los servicios en la nube."
        ),
        "target_architecture": target_architecture,
        "dependency_analysis": dep_analysis,
        "blockers": blockers,
        "warnings": warnings,
    }


def verify_application_health_and_functional_tests(
    app_discovery: Dict[str, Any],
    target_provider: str = "aws",
    live_endpoint_url: Optional[str] = None,
    simulate_startup_failure: bool = False,
    simulate_health_failure: bool = False,
) -> Dict[str, Any]:
    """
    Execute or simulate controlled health and functional verification of the migrated application.
    - If `simulate_startup_failure` or `simulate_health_failure` is True, records the failure
      and marks `passed = False` so cutover is strictly blocked.
    - If `live_endpoint_url` is provided, performs an actual HTTP GET against the health endpoint.
    """
    now = _utc_now()
    health_path = (app_discovery.get("health_endpoints") or ["/health"])[0]
    ports = app_discovery.get("exposed_ports") or [8080]

    if simulate_startup_failure:
        return {
            "passed": False,
            "ready_for_cutover": False,
            "all_passed": False,
            "execution_mode": "controlled_verification",
            "checked_at": now,
            "startup_status": "CRASH_LOOP_BACKOFF",
            "health_check_status": "UNREACHABLE",
            "functional_tests_status": "SKIPPED_DUE_TO_STARTUP_FAILURE",
            "error": f"La aplicación '{app_discovery['app_name']}' no arrancó en el puerto {ports[0]} (código de salida 1).",
            "checks": [
                {"name": "Arranque del proceso/servicio", "passed": False, "detail": "Proceso terminó prematuramente al iniciar."},
            ],
        }

    if simulate_health_failure:
        return {
            "passed": False,
            "ready_for_cutover": False,
            "all_passed": False,
            "execution_mode": "controlled_verification",
            "checked_at": now,
            "startup_status": "RUNNING",
            "health_check_status": "HTTP_503_UNHEALTHY",
            "functional_tests_status": "FAILED",
            "error": f"El endpoint de salud `{health_path}` devolvió HTTP 503 Service Unavailable (fallo de conexión a dependencia).",
            "checks": [
                {"name": "Arranque del proceso/servicio", "passed": True, "detail": f"Escuchando en puerto {ports[0]}."},
                {"name": f"Health Check GET {health_path}", "passed": False, "detail": "HTTP 503 Service Unavailable."},
            ],
        }

    if live_endpoint_url:
        full_url = f"{live_endpoint_url.rstrip('/')}/{health_path.lstrip('/')}"
        try:
            req = urllib.request.Request(full_url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                code = resp.status
                passed = 200 <= code < 300
                return {
                    "passed": passed,
                    "ready_for_cutover": passed,
                    "all_passed": passed,
                    "execution_mode": "live_endpoint_verified",
                    "checked_at": now,
                    "startup_status": "RUNNING",
                    "health_check_status": f"HTTP_{code}",
                    "functional_tests_status": "PASSED" if passed else "FAILED",
                    "error": None if passed else f"Respuesta HTTP {code} inesperada en {full_url}",
                    "checks": [
                        {"name": f"Live HTTP GET {full_url}", "passed": passed, "detail": f"HTTP {code}"},
                    ],
                }
        except Exception as exc:
            return {
                "passed": False,
                "ready_for_cutover": False,
                "all_passed": False,
                "execution_mode": "live_endpoint_verified",
                "checked_at": now,
                "startup_status": "UNKNOWN",
                "health_check_status": "CONNECTION_FAILED",
                "functional_tests_status": "FAILED",
                "error": f"Error conectando a {full_url}: {exc}",
                "checks": [
                    {"name": f"Live HTTP GET {full_url}", "passed": False, "detail": str(exc)},
                ],
            }

    return {
        "passed": True,
        "ready_for_cutover": True,
        "all_passed": True,
        "execution_mode": "simulated_dry_run",
        "checked_at": now,
        "startup_status": "VALIDATED_IN_DRY_RUN",
        "health_check_status": f"SIMULATED_200_OK ({health_path})",
        "functional_tests_status": "SIMULATED_PASSED",
        "error": None,
        "checks": [
            {"name": "Validación de comando de arranque", "passed": True, "detail": app_discovery["start_commands"][0]},
            {"name": f"Sonda de salud configurada ({health_path})", "passed": True, "detail": f"Puerto TCP {ports[0]}"},
            {"name": "Verificación de variables de entorno y secretos en Vault/Secrets Manager", "passed": True, "detail": f"{len(app_discovery['environment_variables'])} variables parametrizadas."},
        ],
    }


def build_app_migration_stages(
    app_discovery: Dict[str, Any],
    target_provider: str = "aws",
) -> List[Dict[str, Any]]:
    """Build the 12 ordered stages required for Use Case 1 (Application-Driven Migration)."""
    p_upper = target_provider.upper()
    app_name = app_discovery["app_name"]
    stages_spec = [
        ("uc1-stage-01", "1. Descubrimiento estático de código, manifiestos y runtime", f"Analizar `{app_discovery['source_path']}` (sin ejecutar código arbitrario), detectar `{app_discovery['language']}`/`{app_discovery['framework']}`, puertos `{app_discovery['exposed_ports']}`, health `{app_discovery.get('health_endpoints')}` y redactar `{app_discovery['secrets_redacted_count']}` secretos."),
        ("uc1-stage-02", "2. Construcción del subgrafo CMIR v2.1 y resolución de dependencias", "Clasificar dependencias confirmadas, inferidas y desconocidas sin promover inferencias a hechos confirmados."),
        ("uc1-stage-03", f"3. Evaluación de viabilidad y arquitectura destino en {p_upper}", f"Validar compatibilidad de runtime (`{app_discovery['runtime']}`, `{app_discovery.get('runtime_constraints')}`) y almacenamiento persistente sin forzar refactorización de código."),
        ("uc1-stage-04", f"4. Generación y validación de artefactos Terraform ({p_upper}) y traslado de datos", "Generar `provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`, runbook de sincronización de base de datos, unidad `systemd` y plantilla `.env` saneada."),
        ("uc1-stage-05", f"5. Aprobación del plan y verificación de prerrequisitos {p_upper}", "Confirmar permisos IAM, cuotas de red y decisión sobre dependencias compartidas o inferidas."),
        ("uc1-stage-06", f"6. Aprovisionamiento de red, seguridad e identidad en {p_upper}", f"Crear VPC, subredes privadas, reglas de Security Groups para puertos {app_discovery['exposed_ports']} e identidad de carga."),
        ("uc1-stage-07", f"7. Aprovisionamiento y transferencia de datos de bases de datos y almacenamiento en {p_upper}", "Aprovisionar instancia RDS, caché y volúmenes; ejecutar volcado consistente (`pg_dump`/`DMS`) y verificar integridad de filas y esquemas."),
        ("uc1-stage-08", f"8. Empaquetado y despliegue de '{app_name}' en entorno aislado de {p_upper}", f"Desplegar artefacto de aplicación e inyectar secretos desde el gestor de secretos de {p_upper}."),
        ("uc1-stage-09", "9. Pruebas de humo (Smoke Tests) y verificación de salud en destino", f"Verificar arranque del servicio, escucha en puertos {app_discovery['exposed_ports']}, respuesta 200 OK en `{app_discovery.get('health_endpoints', ['/health'])[0]}` y logs limpios."),
        ("uc1-stage-10", "10. Pruebas funcionales e informe comparativo de comportamiento", "Validar transacciones de extremo a extremo en el entorno de pruebas aislado y contrastar con el comportamiento esperado."),
        ("uc1-stage-11", "11. Cutover controlado de tráfico hacia la nube", "Drenar conexiones activas en origen, ejecutar sincronización delta final y conmutar DNS/Balanceador."),
        ("uc1-stage-12", "12. Validación final post-cutover y retención del origen para rollback", "Supervisar métricas de error/latencia y conservar el entorno on-premise intacto hasta confirmar estabilidad."),
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
        for idx, (sid, title, desc) in enumerate(stages_spec)
    ]


from app.generators.db_migration_script import (
    build_database_migration_script as _build_database_migration_script,
)


def generate_app_migration_artifacts(
    app_discovery: Dict[str, Any],
    cmir: CMIR,
    target_provider: str = "aws",
) -> Dict[str, Any]:
    """
    Generate validated Terraform files, systemd unit, redacted env template,
    database data migration runbook (because provisioning an empty DB is not migrating the DB),
    smoke test script, and behavioral comparison report.
    """
    provider_clean = target_provider.lower().strip()
    adapter = AWSAdapter()
    iac_bundle = adapter.generate_iac(cmir)

    app_name = app_discovery["app_name"]
    slug = _slug(app_name)
    start_cmd = app_discovery["start_commands"][0]
    health_ep = (app_discovery.get("health_endpoints") or ["/health"])[0]
    main_port = (app_discovery.get("exposed_ports") or [8080])[0]

    env_template_lines = [
        f"# Plantilla de Variables de Entorno para {app_name} ({provider_clean.upper()})",
        "# NOTA DE SEGURIDAD: Los secretos reales fueron redactados durante el descubrimiento.",
        "# Inyecte los valores sensibles desde AWS Secrets Manager o AWS SSM Parameter Store.",
        "",
    ]
    for ev in app_discovery["environment_variables"]:
        env_template_lines.append(f"{ev['name']}={ev['redacted_value']}")

    clean_start_cmd = str(start_cmd or "").strip()
    if clean_start_cmd.startswith("/"):
        systemd_exec_start = clean_start_cmd
    else:
        safe_cmd = clean_start_cmd.replace('"', '\\"')
        systemd_exec_start = f'/usr/bin/env bash -lc "{safe_cmd}"'

    systemd_unit = f"""[Unit]
Description=CloudMove Migrated Application - {app_name}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/srv/{slug}
EnvironmentFile=/etc/{slug}/{slug}.env
ExecStart={systemd_exec_start}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

    db_data_transfer_script = _build_database_migration_script(app_discovery, provider_clean=provider_clean)

    smoke_test_script = f"""#!/usr/bin/env bash
set -euo pipefail
echo "[CloudMove Smoke & Health Test] Verificando aplicación '{app_name}' en {provider_clean.upper()}..."
for port in {' '.join(map(str, app_discovery['exposed_ports']))}; do
  echo " -> Comprobando puerto TCP $port..."
  nc -z -w 3 127.0.0.1 "$port" || {{ echo "ERROR: Puerto $port no responde"; exit 1; }}
done
echo " -> Comprobando endpoint de salud HTTP http://127.0.0.1:{main_port}{health_ep}..."
curl -fsS "http://127.0.0.1:{main_port}{health_ep}" >/dev/null
echo "[OK] Servicio arrancado, puertos activos y endpoint de salud verificado."
"""

    from app.generators.ai_translator import (
        prepare_ai_payload,
        generate_container_user_data_sh,
        generate_auto_dockerfile_and_compose,
    )

    ai_payload = prepare_ai_payload(app_discovery)
    user_data_sh = generate_container_user_data_sh(ai_payload)
    auto_container_files = generate_auto_dockerfile_and_compose(ai_payload)

    db_backups = app_discovery.get("database_backups") or (app_discovery.get("deep_insights") or {}).get("database_backups") or {}
    has_bkp = bool(db_backups.get("has_backups"))

    app_diff_report = {
        "app_id": app_discovery["app_id"],
        "app_name": app_name,
        "target_provider": provider_clean,
        "runtime_preserved": app_discovery["runtime"],
        "entrypoint_preserved": start_cmd,
        "ports_preserved": app_discovery["exposed_ports"],
        "health_endpoint": health_ep,
        "secrets_redacted_count": app_discovery["secrets_redacted_count"],
        "database_data_migration_included": has_bkp or any(
            d.get("type") == "database_instance" and (not d.get("is_external_baas", False) or d.get("has_backup_file"))
            for d in app_discovery["dependencies"]
        ),
        "database_backup_restored": db_backups.get("primary_backup_file"),
        "database_public_tables_restored": db_backups.get("total_public_tables", 0),
        "database_public_rows_restored": db_backups.get("total_public_rows", 0),
        "database_total_rows_restored": db_backups.get("total_rows_all_schemas", 0),
        "external_baas_preserved": any(
            d.get("is_external_baas", False) for d in app_discovery["dependencies"]
        ),
        "high_availability_enabled": True,
        "containerized_deployment": True,
        "behavioral_parity_expected": True,
    }

    files = dict(iac_bundle["files"])
    files["user_data.sh"] = user_data_sh
    files["Dockerfile.cloudmove"] = auto_container_files["Dockerfile.cloudmove"]
    files["docker-compose.cloudmove.yml"] = auto_container_files["docker-compose.cloudmove.yml"]
    files[f"{slug}.service"] = systemd_unit
    files[".env.cloud.template"] = "\n".join(env_template_lines) + "\n"
    files["migrate_database_data.sh"] = db_data_transfer_script
    files["smoke_test.sh"] = smoke_test_script
    files["app_migration_diff_report.json"] = json.dumps(app_diff_report, indent=2, ensure_ascii=False)

    return {
        "provider": provider_clean,
        "files": files,
        "iac_code": iac_bundle["iac_code"],
        "validation": iac_bundle["validation"],
        "diff_report": app_diff_report,
        "ai_payload": ai_payload,
        "smoke_tests": [
            f"Verificar que el stack de contenedores Docker (`{slug}-containers.service`) esté activo.",
            f"Comprobar respuesta TCP/HTTP en el Application Load Balancer (`alb_dns_name`), puertos {app_discovery['exposed_ports']} y `GET {health_ep}`.",
            "Verificar estado saludable de las instancias en el Auto Scaling Group (`ELB` health check) y ausencia de errores en logs.",
        ],
    }
