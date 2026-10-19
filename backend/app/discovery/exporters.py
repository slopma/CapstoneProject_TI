from __future__ import annotations

from typing import Any, Dict


def generate_markdown_report(normalized: Dict[str, Any]) -> str:
    """Generate a structured Markdown technical discovery and AWS assessment report."""
    summary = normalized.get("summary") or {}
    source = normalized.get("source") or {}
    metrics = summary.get("metrics") or {}
    quality = summary.get("collection_quality") or {}
    os_info = summary.get("os") or {}
    sections = normalized.get("sections") or {}
    hw = sections.get("hardware") or {}
    net = sections.get("network") or {}
    db = sections.get("databases") or {}
    assess = sections.get("assessment") or {}
    issues = normalized.get("issues") or []

    lines = [
        f"# CloudMove Discovery Report — `{summary.get('hostname') or 'unknown'}`",
        "",
        f"- **Esquema Normalizado:** `{normalized.get('schema_version')}`",
        f"- **Herramienta Origen:** `{source.get('tool')}` (`{source.get('tool_version')}`)",
        f"- **Recolector:** `{source.get('collector')}` en `{source.get('collector_host')}`",
        f"- **Fecha de Recolección (UTC):** `{source.get('collected_at') or 'No registrada'}`",
        f"- **Cobertura de Consultas:** `{quality.get('successful_query_count')}/{quality.get('query_count')}` exitosas ({quality.get('completeness_percent')}% completitud de secciones)",
        "",
        "---",
        "",
        "## 1. Resumen Ejecutivo del Activo (Summary)",
        "",
        f"- **Hostname:** `{summary.get('hostname')}`",
        f"- **UUID:** `{summary.get('uuid') or 'No disponible'}`",
        f"- **Fabricante / Modelo:** {summary.get('vendor') or 'N/A'} · {summary.get('model') or 'N/A'}",
        f"- **Sistema Operativo:** {os_info.get('name') or 'N/A'} {os_info.get('version') or ''} ({os_info.get('codename') or 'N/A'}) · Arquitectura `{summary.get('architecture') or 'N/A'}`",
        f"- **CPU:** {metrics.get('cpu_model') or 'N/A'} ({metrics.get('cpu_physical_cores') or '?'} núcleos físicos / {metrics.get('cpu_logical_cores') or '?'} lógicos)",
        f"- **Memoria Física:** {metrics.get('memory_total_formatted') or 'N/A'} total · {metrics.get('memory_available_formatted') or 'N/A'} disponible ({metrics.get('memory_utilization_percent') or 0}% uso en instantánea)",
        f"- **Almacenamiento Físico:** {metrics.get('physical_disks_count', 0)} disco(s) físico(s) ({metrics.get('total_physical_disk_formatted') or 'N/A'}) · {metrics.get('partitions_count', 0)} particiones",
        f"- **Software & Runtime:** {metrics.get('installed_packages_count', 0):,} paquetes instalados · {metrics.get('running_services_count', 0)} servicios systemd activos · {metrics.get('processes_count', 0)} procesos",
        f"- **Red:** {metrics.get('interfaces_count', 0)} direcciones · {metrics.get('listening_ports_count', 0)} puertos en escucha · {metrics.get('unique_remote_endpoints_count', 0)} endpoints remotos observados",
        "",
        "---",
        "",
        "## 2. Almacenamiento Físico, Particiones y Montajes",
        "",
        "| Dispositivo | Rol | Padre | Sistema de Archivos | Tamaño Derivado | Punto de Montaje |",
        "|---|---|---|---|---:|---|",
    ]

    storage = hw.get("storage") or {}
    for d in (storage.get("physical_disks") or []) + (storage.get("partitions") or []):
        lines.append(
            f"| `{d.get('name')}` | {d.get('role')} | `{d.get('parent') or '—'}` | "
            f"`{d.get('filesystem_type') or '—'}` | {d.get('size_formatted') or 'No disponible'} | `{d.get('mount_point') or '—'}` |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 3. Interfaces de Red y Subredes Derivadas",
        "",
        "| Interfaz | Dirección / CIDR | Subred Derivada | Clasificación | Estado |",
        "|---|---|---|---|---|",
    ])
    for iface in net.get("interfaces") or []:
        lines.append(
            f"| `{iface.get('interface')}` | `{iface.get('cidr') or iface.get('address')}` | "
            f"`{iface.get('subnet') or '—'}` | `{iface.get('classified_kind')}` | `{iface.get('state')}` |"
        )

    lines.extend([
        "",
        f"**Puerta(s) de enlace por defecto:** `{', '.join(net.get('default_gateways') or []) or 'No detectada'}`",
        "",
        "## 4. Puertos en Escucha (Listening Ports)",
        "",
        "| Protocolo/Puerto | Dirección | Proceso | PID | Exposición |",
        "|---|---|---|---|---|",
    ])
    for l in net.get("listening_ports") or []:
        lines.append(
            f"| `{l.get('protocol')}/{l.get('port')}` | `{l.get('address')}` | "
            f"`{l.get('process_name')}` | `{l.get('pid')}` | {l.get('exposure_label')} |"
        )

    lines.extend([
        "",
        "## 5. Endpoints Remotos Observados (Instantánea Puntual)",
        "",
        "> **Nota crítica:** Estas conexiones provienen de una observación puntual de `process_open_sockets` y **no confirman una dependencia estable de aplicación**.",
        "",
        "| IP Remota | Puerto/Proto | Observaciones | Procesos | Tipo IP |",
        "|---|---|---:|---|---|",
    ])
    for p in net.get("observed_remote_endpoints") or []:
        procs = ", ".join(x["name"] for x in (p.get("processes") or []))
        lines.append(
            f"| `{p.get('remote_ip')}` | `{p.get('protocol')}/{p.get('remote_port')}` | "
            f"{p.get('observation_count')} | `{procs}` | {'Pública' if p.get('is_public_ip') else 'Privada/LAN'} |"
        )

    lines.extend([
        "",
        "## 6. Estado de Bases de Datos",
        "",
        f"**Estado de metadatos de catálogo:** {db.get('summary_badge')}",
        "",
        db.get("summary_explanation") or "",
        "",
    ])
    for ev in db.get("detected_engine_evidence") or []:
        pkgs = ", ".join(f"{x['name']} ({x['version']})" for x in (ev.get("packages_detected") or [])[:6])
        lines.append(
            f"- **{ev.get('engine_name')}:** Estado runtime=`{ev.get('runtime_status')}` · "
            f"Paquetes=`{pkgs or 'ninguno'}` · Metadatos internos=`{ev.get('catalog_metadata_status')}`"
        )

    lines.extend([
        "",
        "## 7. Evaluación de Preparación para Migración a AWS (Assessment)",
        "",
        f"**Postura actual:** {assess.get('readiness_summary')}",
        "",
        "### Información Disponible",
    ])
    for item in assess.get("available_information") or []:
        lines.append(f"- {item}")

    lines.extend(["", "### Información Pendiente de Recopilar"])
    for item in assess.get("pending_information") or []:
        lines.append(f"- {item}")

    lines.extend(["", "### Riesgos y Advertencias Detectadas"])
    for risk in assess.get("identified_risks") or []:
        lines.append(f"- **[{risk.get('severity', 'info').upper()}] {risk.get('title')}:** {risk.get('detail')}")
    for issue in issues:
        lines.append(f"- **[{issue.get('code')}] ({issue.get('section')}):** {issue.get('message')}")

    lines.extend(["", "### Próximos Pasos Recomendados"])
    for step in assess.get("recommended_next_steps") or []:
        lines.append(f"- {step}")

    return "\n".join(lines) + "\n"


def generate_mermaid_diagram(normalized: Dict[str, Any]) -> str:
    """Generate a Mermaid flowchart representing the discovered host topology."""
    summary = normalized.get("summary") or {}
    metrics = summary.get("metrics") or {}
    hostname = summary.get("hostname") or "host"
    os_info = summary.get("os") or {}

    lines = [
        "flowchart LR",
        f'  HOST["{hostname}<br/>{os_info.get("name") or "Linux"} {os_info.get("version") or ""}<br/>{metrics.get("cpu_physical_cores") or "?"}C/{metrics.get("cpu_logical_cores") or "?"}T · RAM {metrics.get("memory_total_formatted") or "N/A"}"]',
        f'  HW["Hardware & Firmware<br/>{metrics.get("cpu_model") or "CPU"}<br/>{summary.get("vendor") or ""} {summary.get("model") or ""}"]',
        f'  STG["Storage<br/>{metrics.get("physical_disks_count", 0)} Disk(s) ({metrics.get("total_physical_disk_formatted") or "N/A"})<br/>{metrics.get("partitions_count", 0)} Partitions"]',
        f'  SW["Software & Kernel<br/>{metrics.get("installed_packages_count", 0):,} Packages<br/>{metrics.get("kernel_modules_count", 0)} Kernel Modules"]',
        f'  RT["Runtime & Services<br/>{metrics.get("running_services_count", 0)} Active Services<br/>{metrics.get("processes_count", 0)} Processes"]',
        f'  NET["Network<br/>Subnets: {", ".join(metrics.get("derived_subnets") or ["none"])}<br/>GW: {", ".join(metrics.get("default_gateways") or ["none"])}"]',
        f'  LST["Listening Ports<br/>{metrics.get("listening_ports_count", 0)} Listeners ({metrics.get("external_listeners_count", 0)} non-loopback)"]',
        f'  PEERS["Observed Remote Peers<br/>{metrics.get("unique_remote_endpoints_count", 0)} Unique Endpoints<br/>(Snapshot - Unconfirmed)"]',
        "  HOST -->|contains| HW",
        "  HOST -->|contains| STG",
        "  HOST -->|contains| SW",
        "  HOST -->|contains| RT",
        "  HOST -->|has_interface| NET",
        "  HOST -->|contains| LST",
        "  RT -->|listens_on| LST",
        "  NET -.->|observed_connection| PEERS",
    ]
    return "\n".join(lines) + "\n"
