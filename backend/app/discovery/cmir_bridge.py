from __future__ import annotations

from typing import Any, Dict, List, Tuple
from app.cmir.builder import build_hierarchical_cmir
from app.cmir.models import CMIR
from app.cmir.validator import validate_cmir
from app.discovery.models import DataPointExplanation, DataState


RELATIONSHIP_SEMANTICS = {
    "contains": {
        "label": "Contains (Pertenece a)",
        "nature": "confirmed",
        "badge": "Confirmada · Estructura",
        "description": "El componente o recurso forma parte física o lógica del activo o contenedor padre.",
    },
    "has_interface": {
        "label": "Has Interface (Interfaz de red)",
        "nature": "observed",
        "badge": "Observada · osquery",
        "description": "Interfaz de red configurada directamente sobre el activo.",
    },
    "routes_to": {
        "label": "Routes To (Enruta hacia)",
        "nature": "observed",
        "badge": "Observada · Tabla de rutas",
        "description": "Ruta de red hacia una subred o puerta de enlace según la tabla de encaminamiento.",
    },
    "listens_on": {
        "label": "Listens On (Escucha en)",
        "nature": "confirmed",
        "badge": "Confirmada por PID",
        "description": "El proceso en ejecución mantiene abierto el puerto en escucha con coincidencia exacta de PID.",
    },
    "observed_connection": {
        "label": "Observed Connection (Socket puntual)",
        "nature": "observed_snapshot",
        "badge": "Observada · No confirma dependencia",
        "description": "Socket remoto visto en el instante de la captura. No demuestra por sí solo una dependencia estable entre aplicaciones.",
    },
    "inferred_relation": {
        "label": "Inferred / Derived Relation",
        "nature": "inferred",
        "badge": "Derivada / Inferida",
        "description": "Relación deducida a partir de máscara de red, montaje de dispositivo o módulos cargados, con nota explícita de alcance.",
    },
}


def build_discovery_cmir_and_graph(normalized: Dict[str, Any]) -> Tuple[CMIR, Dict[str, Any], Dict[str, Any]]:
    """Build a valid CMIR model and an interactive React Flow Discovery Graph from normalized discovery data."""
    summary = normalized.get("summary") or {}
    sections = normalized.get("sections") or {}
    source = normalized.get("source") or {}
    provenance = source.get("provenance_label") or "osquery"

    hostname = summary.get("hostname") or "discovered-host"
    os_info = summary.get("os") or {}
    metrics = summary.get("metrics") or {}

    hw = sections.get("hardware") or {}
    sw = sections.get("software") or {}
    net = sections.get("network") or {}
    rt = sections.get("runtime") or {}

    resources: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []

    def add_node(
        node_id: str,
        name: str,
        node_type: str,
        category_group: str,
        level: int,
        parent_id: str | None = None,
        section_target: str = "summary",
        subsection_target: str | None = None,
        data_state: str = DataState.OBSERVED.value,
        subtitle: str = "",
        explanation: Dict[str, Any] | None = None,
        details: Dict[str, Any] | None = None,
        default_expanded: bool = True,
    ) -> None:
        exp = explanation or DataPointExplanation(
            id=node_id,
            label=name,
            what_is=f"Recurso descubierto de tipo '{node_type}' ({subtitle or category_group}).",
            detected_value=details or {"name": name, "type": node_type},
            formatted_value=subtitle or name,
            interpretation=f"Elemento registrado bajo la categoría '{category_group}' del activo '{hostname}'.",
            why_it_matters="Aporta visibilidad granular sobre la composición técnica del host descubierto.",
            migration_relevance="Debe evaluarse dentro del alcance del activo antes de generar plantillas IaC o dimensionar servicios en AWS.",
            provenance=provenance,
            state=DataState(data_state) if data_state in DataState._value2member_map_ else DataState.OBSERVED,
            limitations="Basado en una instantánea puntual de solo lectura.",
            suggested_action="Consultar la sección detallada correspondiente para inspeccionar todos sus atributos.",
        ).model_dump()

        resources.append({
            "id": node_id,
            "name": name,
            "type": node_type,
            "category": category_group,
            "parent_id": parent_id,
            "level": level,
            "provider": "on-premise",
            "platform": f"{os_info.get('name') or 'Linux'} {os_info.get('version') or ''}".strip(),
            "engine": subtitle or None,
            "location": source.get("collector_host") or hostname,
            "environment": "discovery",
            "status": "DISCOVERED",
            "is_shared": False,
            "metadata": {
                "category_group": category_group,
                "section_target": section_target,
                "subsection_target": subsection_target,
                "data_state": data_state,
                "subtitle": subtitle,
                "default_expanded": default_expanded,
                "explanation": exp,
                "details": details or {},
                "provenance": provenance,
            },
        })

    def add_rel(
        source_id: str,
        target_id: str,
        rel_type: str,
        evidence: str,
        uncertainty_note: str | None = None,
    ) -> None:
        sem = RELATIONSHIP_SEMANTICS.get(rel_type, RELATIONSHIP_SEMANTICS["contains"])
        relationships.append({
            "source": source_id,
            "target": target_id,
            "type": rel_type,
            "metadata": {
                "label": sem["label"],
                "nature": sem["nature"],
                "badge": sem["badge"],
                "description": sem["description"],
                "evidence": evidence,
                "uncertainty_note": uncertainty_note,
            },
        })

    # 1. CENTRAL ROOT HOST NODE
    host_id = f"host-{hostname}"
    os_label = f"{os_info.get('name') or 'OS'} {os_info.get('version') or ''}".strip()
    add_node(
        node_id=host_id,
        name=hostname,
        node_type="host",
        category_group="asset",
        level=1,
        parent_id=None,
        section_target="summary",
        subsection_target="identity",
        data_state=DataState.OBSERVED.value,
        subtitle=f"{os_label} · {summary.get('architecture') or 'x86_64'}",
        explanation=(summary.get("explanations") or [None])[0],
        details={
            "uuid": summary.get("uuid"),
            "vendor": summary.get("vendor"),
            "model": summary.get("model"),
            "os": os_label,
            "collected_at": source.get("collected_at"),
            "osquery_version": source.get("tool_version"),
        },
        default_expanded=True,
    )

    # 2. HARDWARE GROUP (CPU, Memory, Firmware/Board)
    grp_hw_id = "grp-hardware"
    cpu_data = hw.get("cpu") or {}
    mem_data = hw.get("memory") or {}
    fw_data = hw.get("firmware_and_board") or {}
    other_hw = hw.get("other_characteristics") or {}

    add_node(
        node_id=grp_hw_id,
        name="Hardware, CPU & Memoria",
        node_type="discovery_group",
        category_group="hardware",
        level=2,
        parent_id=None,
        section_target="hardware",
        subsection_target="cpu",
        data_state=DataState.OBSERVED.value,
        subtitle=f"{cpu_data.get('physical_cores') or '?'}C/{cpu_data.get('logical_cores') or '?'}T · RAM {mem_data.get('total_formatted') or 'N/A'}",
        explanation=(summary.get("explanations") or [None, None])[1],
        details={
            "vendor": summary.get("vendor"),
            "model": summary.get("model"),
            "cpu_model": cpu_data.get("model"),
            "memory_total": mem_data.get("total_formatted"),
        },
    )
    add_rel(host_id, grp_hw_id, "contains", "Componentes físicos de hardware reportados en cpu_info, memory_info y platform_info.")

    cpu_node_id = "hw-cpu-0"
    add_node(
        node_id=cpu_node_id,
        name=cpu_data.get("model") or "CPU Principal",
        node_type="cpu",
        category_group="hardware",
        level=3,
        parent_id=grp_hw_id,
        section_target="hardware",
        subsection_target="cpu",
        data_state=DataState.OBSERVED.value,
        subtitle=f"{cpu_data.get('physical_cores') or '?'} físicos / {cpu_data.get('logical_cores') or '?'} lógicos · {cpu_data.get('max_clock_mhz') or '?'} MHz",
        explanation=cpu_data.get("explanation"),
        details={
            "manufacturer": cpu_data.get("manufacturer"),
            "physical_cores": cpu_data.get("physical_cores"),
            "logical_cores": cpu_data.get("logical_cores"),
            "current_clock_mhz": cpu_data.get("current_clock_mhz"),
            "max_clock_mhz": cpu_data.get("max_clock_mhz"),
            "socket": cpu_data.get("socket_designation"),
        },
    )
    add_rel(grp_hw_id, cpu_node_id, "contains", "Procesador detectado en hardware.cpu_info.")

    mem_node_id = "hw-memory-0"
    add_node(
        node_id=mem_node_id,
        name=f"Memoria RAM ({mem_data.get('total_formatted') or 'N/A'})",
        node_type="memory",
        category_group="hardware",
        level=3,
        parent_id=grp_hw_id,
        section_target="hardware",
        subsection_target="memory",
        data_state=DataState.OBSERVED.value,
        subtitle=f"Disp: {mem_data.get('available_formatted') or 'N/A'} · Swap: {mem_data.get('swap_total_formatted') or 'N/A'}",
        explanation=mem_data.get("explanation"),
        details={
            "total": mem_data.get("total_formatted"),
            "available": mem_data.get("available_formatted"),
            "free": mem_data.get("free_formatted"),
            "cached": mem_data.get("cached_formatted"),
            "buffers": mem_data.get("buffers_formatted"),
            "swap_total": mem_data.get("swap_total_formatted"),
            "swap_free": mem_data.get("swap_free_formatted"),
        },
    )
    add_rel(grp_hw_id, mem_node_id, "contains", "Memoria física y swap reportados en hardware.memory_info.")

    fw_node_id = "hw-firmware-0"
    add_node(
        node_id=fw_node_id,
        name=f"Firmware {(fw_data.get('firmware_type') or 'UEFI').upper()} & Placa {fw_data.get('board_model') or ''}".strip(),
        node_type="firmware",
        category_group="hardware",
        level=3,
        parent_id=grp_hw_id,
        section_target="hardware",
        subsection_target="firmware",
        data_state=DataState.OBSERVED.value,
        subtitle=f"{fw_data.get('board_vendor') or 'N/A'} · {fw_data.get('firmware_version') or 'N/A'}",
        explanation=fw_data.get("explanation"),
        details={
            "firmware_type": fw_data.get("firmware_type"),
            "firmware_version": fw_data.get("firmware_version"),
            "firmware_date": fw_data.get("firmware_date"),
            "board_vendor": fw_data.get("board_vendor"),
            "board_model": fw_data.get("board_model"),
        },
    )
    add_rel(grp_hw_id, fw_node_id, "contains", "Datos SMBIOS/UEFI en asset.platform y asset.system_info.")

    # 3. STORAGE GROUP (Physical Disks -> Partitions -> Mounts)
    grp_storage_id = "grp-storage"
    storage_data = hw.get("storage") or {}
    phys_disks = storage_data.get("physical_disks") or []
    parts = storage_data.get("partitions") or []
    persist_mounts = storage_data.get("persistent_mounts") or []

    add_node(
        node_id=grp_storage_id,
        name="Almacenamiento, Particiones y Montajes",
        node_type="discovery_group",
        category_group="storage",
        level=2,
        parent_id=None,
        section_target="hardware",
        subsection_target="storage",
        data_state=DataState.DERIVED.value,
        subtitle=f"{len(phys_disks)} disco(s) ({storage_data.get('total_physical_formatted') or 'N/A'}) · {len(parts)} particiones",
        explanation=(summary.get("explanations") or [None, None, None])[2],
        details={
            "physical_disks_count": len(phys_disks),
            "partitions_count": len(parts),
            "persistent_mounts_count": len(persist_mounts),
            "total_physical_capacity": storage_data.get("total_physical_formatted"),
        },
    )
    add_rel(host_id, grp_storage_id, "contains", "Subsistema de bloques y sistemas de archivos del host.")

    disk_node_ids: Dict[str, str] = {}
    for d in phys_disks:
        dname = d.get("name") or "disk"
        did = f"disk-{dname.replace('/', '_')}"
        disk_node_ids[dname] = did
        add_node(
            node_id=did,
            name=f"Disco {dname} ({d.get('model') or 'Block Device'})",
            node_type="block_device",
            category_group="storage",
            level=3,
            parent_id=grp_storage_id,
            section_target="hardware",
            subsection_target="storage",
            data_state=d.get("state") or DataState.DERIVED.value,
            subtitle=f"{d.get('size_formatted') or 'Tamaño N/A'} · Block {d.get('block_size') or '?'}B",
            explanation=d.get("explanation"),
            details={
                "device": dname,
                "model": d.get("model"),
                "raw_sectors": d.get("raw_sectors"),
                "block_size": d.get("block_size"),
                "size_formatted": d.get("size_formatted"),
                "partitions": d.get("children_partitions"),
            },
        )
        add_rel(grp_storage_id, did, "contains", f"Dispositivo físico de bloque {dname}.")

    part_node_ids: Dict[str, str] = {}
    for p in parts:
        pname = p.get("name") or "part"
        pid = f"part-{pname.replace('/', '_')}"
        part_node_ids[pname] = pid
        parent_disk_id = disk_node_ids.get(p.get("parent") or "", grp_storage_id)
        add_node(
            node_id=pid,
            name=f"Partición {pname} ({p.get('filesystem_type') or 'raw'})",
            node_type="partition",
            category_group="storage",
            level=4,
            parent_id=grp_storage_id,
            section_target="hardware",
            subsection_target="storage",
            data_state=p.get("state") or DataState.DERIVED.value,
            subtitle=f"{p.get('size_formatted') or 'N/A'}" + (f" → {p.get('mount_point')}" if p.get("mount_point") else ""),
            explanation=p.get("explanation"),
            details={
                "partition": pname,
                "parent_disk": p.get("parent"),
                "filesystem": p.get("filesystem_type"),
                "size_formatted": p.get("size_formatted"),
                "mount_point": p.get("mount_point"),
                "uuid": p.get("uuid"),
            },
        )
        add_rel(
            parent_disk_id,
            pid,
            "contains",
            f"Partición hija de {p.get('parent')} según block_devices.parent.",
        )

    for m in persist_mounts:
        mpath = m.get("path") or "/"
        mdev = m.get("device") or ""
        mid = f"mount-{mpath.replace('/', '_') or 'root'}"
        add_node(
            node_id=mid,
            name=f"Filesystem '{mpath}' ({m.get('filesystem')})",
            node_type="filesystem",
            category_group="storage",
            level=5,
            parent_id=grp_storage_id,
            section_target="hardware",
            subsection_target="storage",
            data_state=DataState.DERIVED.value,
            subtitle=f"{m.get('used_formatted') or '?'} usado / {m.get('total_formatted') or '?'} ({m.get('usage_percent') or 0}%)",
            explanation=m.get("explanation"),
            details={
                "path": mpath,
                "device": mdev,
                "filesystem": m.get("filesystem"),
                "total": m.get("total_formatted"),
                "used": m.get("used_formatted"),
                "available": m.get("available_formatted"),
                "usage_percent": m.get("usage_percent"),
            },
        )
        if mdev in part_node_ids:
            add_rel(
                part_node_ids[mdev],
                mid,
                "inferred_relation",
                f"El punto de montaje '{mpath}' monta el dispositivo '{mdev}' según hardware.mounts.",
                uncertainty_note="Relación derivada cruzando mounts.device con block_devices.name.",
            )
        else:
            add_rel(grp_storage_id, mid, "contains", f"Punto de montaje persistente en {mpath}.")

    # 4. OPERATING SYSTEM & SOFTWARE GROUP
    grp_sw_id = "grp-software"
    add_node(
        node_id=grp_sw_id,
        name="Sistema Operativo, Paquetes y Aplicaciones",
        node_type="discovery_group",
        category_group="software",
        level=2,
        parent_id=None,
        section_target="software",
        subsection_target="packages",
        data_state=DataState.OBSERVED.value,
        subtitle=f"{os_label} · {sw.get('package_count', 0):,} paquetes · {sw.get('kernel_module_count', 0)} módulos",
        explanation=sw.get("explanation"),
        details={
            "os_name": os_info.get("name"),
            "os_version": os_info.get("version"),
            "os_codename": os_info.get("codename"),
            "installed_packages": sw.get("package_count"),
            "kernel_modules": sw.get("kernel_module_count"),
        },
    )
    add_rel(host_id, grp_sw_id, "contains", "Entorno de sistema operativo y catálogo de software instalado.")

    os_node_id = "sw-os-release"
    add_node(
        node_id=os_node_id,
        name=f"{os_info.get('name') or 'Linux'} {os_info.get('version') or ''}".strip(),
        node_type="os",
        category_group="software",
        level=3,
        parent_id=grp_sw_id,
        section_target="summary",
        subsection_target="identity",
        data_state=DataState.OBSERVED.value,
        subtitle=f"Codename: {os_info.get('codename') or 'N/A'} · Base: {os_info.get('platform_like') or 'debian'}",
        details=os_info,
    )
    add_rel(grp_sw_id, os_node_id, "contains", "Versión del sistema operativo reportada en asset.os.")

    # Add aggregated nodes for relevant software categories that actually have packages
    for app_grp in sw.get("relevant_applications") or []:
        pkgs = app_grp.get("packages") or []
        if not pkgs:
            continue
        ag_id = f"sw-cat-{app_grp['id']}"
        sample_names = ", ".join(p["name"] for p in pkgs[:4])
        add_node(
            node_id=ag_id,
            name=f"{app_grp['title']} ({len(pkgs)})",
            node_type="package_group",
            category_group="software",
            level=3,
            parent_id=grp_sw_id,
            section_target="software",
            subsection_target="relevant_apps",
            data_state=DataState.OBSERVED.value,
            subtitle=sample_names,
            explanation=DataPointExplanation(
                id=ag_id,
                label=app_grp["title"],
                what_is=f"Agrupación de {len(pkgs)} paquete(s) instalados en la categoría '{app_grp['title']}'.",
                detected_value=[{"name": p["name"], "version": p["version"]} for p in pkgs[:10]],
                formatted_value=f"{len(pkgs)} paquetes ({sample_names})",
                interpretation=app_grp.get("rationale") or "Paquetes instalados detectados en dpkg.",
                why_it_matters="Agrupa miles de paquetes en categorías comprensibles sin afirmar que cada paquete sea un servicio activo.",
                migration_relevance="Ayuda a identificar binarios de servidores web, motores de base de datos o runtimes que deben contrastarse con procesos en ejecución.",
                provenance=f"software.deb_packages · {provenance}",
                state=DataState.OBSERVED,
                limitations="La presencia de un paquete en dpkg no implica que el software esté en ejecución ni configurado.",
                suggested_action="Revisar en las secciones de Servicios y Procesos cuáles de estos paquetes tienen demonios activos.",
            ).model_dump(),
            details={"count": len(pkgs), "packages": [p["name"] for p in pkgs[:20]]},
        )
        add_rel(grp_sw_id, ag_id, "contains", f"{len(pkgs)} paquetes instalados en deb_packages.")

    kmod_node_id = "sw-kernel-modules"
    gpu_mods = other_hw.get("gpu_kernel_modules") or []
    add_node(
        node_id=kmod_node_id,
        name=f"Módulos del Kernel ({sw.get('kernel_module_count', 0)} activos)",
        node_type="kernel_module",
        category_group="software",
        level=3,
        parent_id=grp_sw_id,
        section_target="software",
        subsection_target="kernel_modules",
        data_state=DataState.OBSERVED.value,
        subtitle=f"Destacados: {', '.join(gpu_mods + ['xt_conntrack'])}" if gpu_mods else "Módulos Live en memoria",
        explanation=other_hw.get("explanation"),
        details={
            "total_modules": sw.get("kernel_module_count"),
            "gpu_modules": gpu_mods,
        },
    )
    add_rel(grp_sw_id, kmod_node_id, "contains", "Módulos cargados en el kernel según software.kernel_modules.")

    # 5. SERVICES & RUNTIME PROCESSES GROUP
    grp_rt_id = "grp-runtime"
    services_list = sw.get("services") or []
    running_svcs = [s for s in services_list if s.get("is_running") and s.get("unit_type") == "service"]
    processes_list = rt.get("processes") or []

    add_node(
        node_id=grp_rt_id,
        name="Servicios Systemd & Procesos en Ejecución",
        node_type="discovery_group",
        category_group="runtime",
        level=2,
        parent_id=None,
        section_target="runtime",
        subsection_target="processes",
        data_state=DataState.OBSERVED.value,
        subtitle=f"{len(running_svcs)} servicios activos · {len(processes_list)} procesos",
        explanation=(rt.get("uptime") or {}).get("explanation"),
        details={
            "running_services_count": len(running_svcs),
            "total_systemd_units": len(services_list),
            "total_processes": len(processes_list),
            "uptime": (rt.get("uptime") or {}).get("formatted"),
        },
    )
    add_rel(host_id, grp_rt_id, "contains", "Procesos y unidades systemd en ejecución en la instantánea.")

    # Key systemd services node
    KEY_SERVICE_NAMES = {"ssh.service", "docker.service", "containerd.service", "ollama.service"}
    for svc in running_svcs:
        if svc["id"] in KEY_SERVICE_NAMES or len([x for x in resources if x["type"] == "systemd_service"]) < 5:
            sid = f"svc-{svc['id'].replace('.', '_')}"
            add_node(
                node_id=sid,
                name=f"Servicio {svc['id']}",
                node_type="systemd_service",
                category_group="services",
                level=3,
                parent_id=grp_rt_id,
                section_target="software",
                subsection_target="services",
                data_state=DataState.OBSERVED.value,
                subtitle=f"{svc.get('active_state')}/{svc.get('sub_state')} · {svc.get('unit_file_state') or 'loaded'}",
                details=svc,
            )
            add_rel(grp_rt_id, sid, "contains", f"Unidad systemd activa '{svc['id']}'.")

    # Key processes that either listen on ports or have remote sockets or are key daemons
    proc_node_by_pid: Dict[int, str] = {}
    key_procs = [
        p for p in processes_list
        if p.get("listening_ports") or p.get("remote_peers_count", 0) > 0 or p.get("name") in ("sshd", "dockerd", "containerd", "ollama", "avahi-daemon", "NetworkManager")
    ]
    # Keep diagram legible: deduplicate or cap individual process nodes to top 12 active network processes
    key_procs.sort(key=lambda p: (-(len(p.get("listening_ports") or [])), -(p.get("remote_peers_count") or 0), p.get("pid") or 0))
    for p in key_procs[:12]:
        pid_val = p.get("pid")
        if pid_val is None:
            continue
        pnode_id = f"proc-{pid_val}"
        proc_node_by_pid[pid_val] = pnode_id
        add_node(
            node_id=pnode_id,
            name=f"{p.get('name')} (PID {pid_val})",
            node_type="process",
            category_group="processes",
            level=3,
            parent_id=grp_rt_id,
            section_target="runtime",
            subsection_target="processes",
            data_state=DataState.OBSERVED.value,
            subtitle=f"{p.get('path') or 'binario'} · UID {p.get('uid')}",
            explanation=DataPointExplanation(
                id=pnode_id,
                label=f"Proceso {p.get('name')} (PID {pid_val})",
                what_is=f"Proceso del sistema operativo con PID {pid_val} ejecutando '{p.get('path') or p.get('name')}'.",
                detected_value=p,
                formatted_value=f"{p.get('name')} (PID {pid_val}, UID {p.get('uid')}) · Puertos: {', '.join(p.get('listening_ports') or ['ninguno'])}",
                interpretation=(
                    f"Proceso activo con {len(p.get('listening_ports') or [])} puerto(s) en escucha y "
                    f"{p.get('open_socket_count', 0)} socket(s) abiertos."
                ),
                why_it_matters="Vincula la actividad de red (puertos y sockets) con el ejecutable responsable en el sistema.",
                migration_relevance="Determina si se trata de un demonio de infraestructura (SSH, Docker), un servicio de aplicación (Ollama) o un proceso de usuario local.",
                provenance=f"runtime.processes (pid={pid_val}) · {provenance}",
                state=DataState.OBSERVED,
                limitations="No se exponen argumentos de línea de comandos ni variables de entorno por privacidad.",
                suggested_action="Verificar si este proceso corresponde a un servicio gestionado por systemd o a una sesión interactiva.",
            ).model_dump(),
            details=p,
        )
        add_rel(grp_rt_id, pnode_id, "contains", f"Proceso activo PID {pid_val} en runtime.processes.")

    remaining_procs_count = max(len(processes_list) - len(proc_node_by_pid), 0)
    if remaining_procs_count > 0:
        agg_proc_id = "proc-aggregated-others"
        add_node(
            node_id=agg_proc_id,
            name=f"Otros procesos del sistema ({remaining_procs_count} agrupados)",
            node_type="process",
            category_group="processes",
            level=3,
            parent_id=grp_rt_id,
            section_target="runtime",
            subsection_target="processes",
            data_state=DataState.OBSERVED.value,
            subtitle=f"{rt.get('user_process_count', 0)} usuario · {rt.get('kernel_thread_count', 0)} hilos kernel",
            details={
                "aggregated_count": remaining_procs_count,
                "total_processes": len(processes_list),
                "note": "Agrupados para preservar el rendimiento y legibilidad del grafo. Consultables íntegramente en la sección Runtime.",
            },
        )
        add_rel(grp_rt_id, agg_proc_id, "contains", f"{remaining_procs_count} procesos adicionales sin sockets expuestos.")

    # 6. NETWORK INTERFACES, SUBNETS & ROUTES GROUP
    grp_net_id = "grp-network"
    ifaces_list = net.get("interfaces") or []
    subnets_list = net.get("derived_subnets") or []
    gateways_list = net.get("default_gateways") or []

    add_node(
        node_id=grp_net_id,
        name="Interfaces de Red, Subredes y Rutas",
        node_type="discovery_group",
        category_group="network",
        level=2,
        parent_id=None,
        section_target="network",
        subsection_target="interfaces",
        data_state=DataState.OBSERVED.value,
        subtitle=f"{len(ifaces_list)} direcciones · {len(subnets_list)} subredes · GW {', '.join(gateways_list) or 'N/A'}",
        explanation=(summary.get("explanations") or [None, None, None, None])[3],
        details={
            "interfaces_count": len(ifaces_list),
            "derived_subnets": [s.get("cidr") for s in subnets_list],
            "default_gateways": gateways_list,
        },
    )
    add_rel(host_id, grp_net_id, "has_interface", "Configuración de interfaces y tablas de encaminamiento del activo.")

    # Group interfaces by interface name so IPv4 + IPv6 on the same NIC are clear
    iface_by_name: Dict[str, List[Dict[str, Any]]] = {}
    for iface in ifaces_list:
        iface_by_name.setdefault(iface.get("interface") or "iface", []).append(iface)

    iface_node_ids: Dict[str, str] = {}
    for ifname, rows in iface_by_name.items():
        if_id = f"net-iface-{ifname}"
        iface_node_ids[ifname] = if_id
        addrs_summary = ", ".join(r.get("cidr") or r.get("address") or "" for r in rows if r.get("address"))
        primary_row = rows[0]
        add_node(
            node_id=if_id,
            name=f"Interfaz {ifname} ({primary_row.get('classified_kind')})",
            node_type="network_interface",
            category_group="network",
            level=3,
            parent_id=grp_net_id,
            section_target="network",
            subsection_target="interfaces",
            data_state=DataState.OBSERVED.value,
            subtitle=addrs_summary or "Sin dirección",
            explanation=primary_row.get("explanation"),
            details={"interface": ifname, "addresses": rows},
        )
        add_rel(grp_net_id, if_id, "has_interface", f"Interfaz '{ifname}' reportada en network.interfaces.")

    for sub in subnets_list:
        cidr = sub.get("cidr") or "subnet"
        sub_id = f"net-subnet-{cidr.replace('/', '_').replace(':', '_')}"
        ifname = sub.get("interface") or ""
        add_node(
            node_id=sub_id,
            name=f"Subred {cidr}",
            node_type="subnet",
            category_group="network",
            level=4,
            parent_id=grp_net_id,
            section_target="network",
            subsection_target="subnets",
            data_state=DataState.DERIVED.value,
            subtitle=f"Derivada de {sub.get('address')} en {ifname}",
            details=sub,
        )
        src_if_id = iface_node_ids.get(ifname, grp_net_id)
        add_rel(
            src_if_id,
            sub_id,
            "inferred_relation",
            f"Subred {cidr} calculada de forma determinista a partir de la IP {sub.get('address')} y su máscara en '{ifname}'.",
            uncertainty_note="Calculada por prefijo de red; verificar topología VLAN en switches/routers.",
        )

    for gw in gateways_list:
        gw_id = f"net-gw-{gw.replace('.', '_').replace(':', '_')}"
        add_node(
            node_id=gw_id,
            name=f"Default Gateway ({gw})",
            node_type="gateway",
            category_group="network",
            level=4,
            parent_id=grp_net_id,
            section_target="network",
            subsection_target="routes",
            data_state=DataState.OBSERVED.value,
            subtitle="Ruta por defecto (0.0.0.0/0)",
            details={"gateway": gw, "destination": "0.0.0.0/0"},
        )
        # Connect from interface that routes to this gateway if known
        gw_route = next((r for r in (net.get("routes") or []) if r.get("gateway") == gw), None)
        gw_if_id = iface_node_ids.get((gw_route or {}).get("interface") or "", grp_net_id)
        add_rel(
            gw_if_id,
            gw_id,
            "routes_to",
            f"Ruta por defecto hacia puerta de enlace {gw} en network.routes.",
        )

    # 7. LISTENING PORTS GROUP
    grp_listen_id = "grp-listeners"
    listeners_list = net.get("listening_ports") or []
    add_node(
        node_id=grp_listen_id,
        name="Puertos en Escucha (Listening Sockets)",
        node_type="discovery_group",
        category_group="listeners",
        level=2,
        parent_id=None,
        section_target="network",
        subsection_target="listening_ports",
        data_state=DataState.OBSERVED.value,
        subtitle=f"{len(listeners_list)} sockets en escucha ({metrics.get('external_listeners_count', 0)} expuestos)",
        details={
            "total_listeners": len(listeners_list),
            "external_listeners": metrics.get("external_listeners_count", 0),
            "loopback_listeners": metrics.get("loopback_listeners_count", 0),
        },
    )
    add_rel(host_id, grp_listen_id, "contains", "Puertos TCP/UDP en estado LISTEN sobre el activo.")

    # Collapse IPv4 + IPv6 bindings of the exact same (port, protocol, pid) into a single clean graph node
    grouped_listeners: Dict[Tuple[int, str, int | None, str], Dict[str, Any]] = {}
    for l in listeners_list:
        gkey = (l["port"], l["protocol"], l.get("pid"), l.get("process_name") or "")
        if gkey not in grouped_listeners:
            grouped_listeners[gkey] = {
                **l,
                "addresses": [l["address"]],
            }
        else:
            if l["address"] not in grouped_listeners[gkey]["addresses"]:
                grouped_listeners[gkey]["addresses"].append(l["address"])

    for (port_val, proto_str, pid_val, proc_name), ldata in grouped_listeners.items():
        lid = f"listen-node-{proto_str.lower()}-{port_val}-{pid_val or 'nopid'}"
        addrs_str = ", ".join(ldata["addresses"])
        add_node(
            node_id=lid,
            name=f"{proto_str}/{port_val} · {proc_name}",
            node_type="listening_port",
            category_group="listeners",
            level=3,
            parent_id=grp_listen_id,
            section_target="network",
            subsection_target="listening_ports",
            data_state=DataState.OBSERVED.value,
            subtitle=fBindLabel(addrs_str, ldata["exposure_label"]),
            explanation=ldata.get("explanation"),
            details=ldata,
        )
        add_rel(grp_listen_id, lid, "contains", f"Puerto {proto_str}/{port_val} en escucha ({addrs_str}).")
        if pid_val is not None and pid_val in proc_node_by_pid:
            add_rel(
                proc_node_by_pid[pid_val],
                lid,
                "listens_on",
                f"Coincidencia exacta de PID={pid_val} entre runtime.processes y network.listening_ports.",
            )

    # 8. OBSERVED REMOTE ENDPOINTS GROUP
    grp_peers_id = "grp-remote-peers"
    peers_list = net.get("observed_remote_endpoints") or []
    add_node(
        node_id=grp_peers_id,
        name="Endpoints Remotos Observados (Instantánea)",
        node_type="discovery_group",
        category_group="remote_endpoints",
        level=2,
        parent_id=None,
        section_target="network",
        subsection_target="remote_endpoints",
        data_state=DataState.OBSERVED.value,
        subtitle=f"{len(peers_list)} endpoints remotos únicos (No confirman dependencia)",
        details={
            "unique_remote_endpoints": len(peers_list),
            "warning": "Evidencia puntual de process_open_sockets; no representa dependencias confirmadas de aplicación.",
        },
    )
    add_rel(
        grp_net_id,
        grp_peers_id,
        "observed_connection",
        f"{len(peers_list)} endpoints remotos observados en process_open_sockets.",
        uncertainty_note="Instantánea puntual de sockets abiertos; no confirma dependencia estable.",
    )

    for peer in peers_list[:14]:
        peer_id = peer["id"].replace(":", "_").replace(".", "_")
        proc_names = ", ".join(p["name"] for p in (peer.get("processes") or []))
        add_node(
            node_id=peer_id,
            name=f"{peer['remote_ip']}:{peer['remote_port']} ({peer['protocol']})",
            node_type="remote_endpoint",
            category_group="remote_endpoints",
            level=3,
            parent_id=grp_peers_id,
            section_target="network",
            subsection_target="remote_endpoints",
            data_state=DataState.OBSERVED.value,
            subtitle=f"{peer['observation_count']} obs · {proc_names} · {'IP Pública' if peer.get('is_public_ip') else 'IP Privada/LAN'}",
            explanation=peer.get("explanation"),
            details=peer,
        )
        add_rel(grp_peers_id, peer_id, "contains", f"Endpoint remoto observado {peer['remote_ip']}:{peer['remote_port']}.")
        for pid_val in peer.get("pids") or []:
            if pid_val in proc_node_by_pid:
                add_rel(
                    proc_node_by_pid[pid_val],
                    peer_id,
                    "observed_connection",
                    f"Socket abierto por PID {pid_val} ({proc_names}) hacia {peer['remote_ip']}:{peer['remote_port']}.",
                    uncertainty_note="Observación puntual en socket; no debe asumirse como dependencia de aplicación confirmada.",
                )

    # Build and validate the CMIR model using CloudMove's core engine
    cmir = build_hierarchical_cmir(
        resources_data=resources,
        relationships_data=relationships,
        architecture_meta={
            "name": f"Discovery · {hostname}",
            "provider": "on-premise",
            "version": "2.0",
            "metadata": {
                "schema_version": normalized.get("schema_version"),
                "source": source,
                "discovery_mode": True,
            },
        },
    )
    cmir_validation = validate_cmir(cmir)

    graph_payload = {
        "root_node_id": host_id,
        "architecture_name": cmir.name,
        "provider": cmir.provider,
        "nodes": [res.model_dump() for res in cmir.resources],
        "edges": [
            {
                "id": f"e-{idx}-{rel.source}-{rel.target}-{rel.type}",
                "source": rel.source,
                "target": rel.target,
                "type": rel.type,
                "is_hierarchy": rel.type == "contains",
                "metadata": rel.metadata,
            }
            for idx, rel in enumerate(cmir.relationships)
        ],
        "categories": [
            {"id": "asset", "label": "Activo Principal", "count": 1},
            {"id": "hardware", "label": "Hardware, CPU & RAM", "count": sum(1 for r in resources if r["category"] == "hardware")},
            {"id": "storage", "label": "Almacenamiento & Montajes", "count": sum(1 for r in resources if r["category"] == "storage")},
            {"id": "software", "label": "SO, Paquetes & Módulos", "count": sum(1 for r in resources if r["category"] == "software")},
            {"id": "services", "label": "Servicios Systemd", "count": sum(1 for r in resources if r["category"] == "services")},
            {"id": "processes", "label": "Procesos Runtime", "count": sum(1 for r in resources if r["category"] == "processes")},
            {"id": "network", "label": "Red, Subredes & Rutas", "count": sum(1 for r in resources if r["category"] == "network")},
            {"id": "listeners", "label": "Puertos en Escucha", "count": sum(1 for r in resources if r["category"] == "listeners")},
            {"id": "remote_endpoints", "label": "Endpoints Remotos (Snapshot)", "count": sum(1 for r in resources if r["category"] == "remote_endpoints")},
        ],
        "legend": {
            "relationships": list(RELATIONSHIP_SEMANTICS.values()),
            "data_states": [
                {"state": "observed", "label": "Observado (osquery directo)", "tone": "emerald"},
                {"state": "derived", "label": "Derivado (cálculo determinista)", "tone": "blue"},
                {"state": "inferred", "label": "Inferido (hipótesis con nota)", "tone": "amber"},
                {"state": "unavailable", "label": "No disponible / No recopilado", "tone": "slate"},
                {"state": "error", "label": "Error de consulta o parseo", "tone": "red"},
            ],
        },
        "validation": cmir_validation,
    }

    return cmir, graph_payload, cmir_validation


def fBindLabel(addrs: str, exposure_label: str) -> str:
    return f"{addrs} · {exposure_label}"
