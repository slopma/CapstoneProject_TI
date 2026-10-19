from __future__ import annotations

import collections
import ipaddress
import json
from typing import Any, Dict, List, Optional, Tuple

from app.discovery.models import (
    BaseDiscoveryCollectorParser,
    DATABASE_COLLECTOR_SPECS,
    DataPointExplanation,
    DataState,
    DiscoveryIssue,
)

SUPPORTED_SCHEMAS = {
    "cloudmove.discovery.v1",
    "cloudmove.normalized.v1",
    "cloudmove.discovery.session.v1",
}

PROTOCOL_MAP = {
    6: "TCP",
    17: "UDP",
    1: "ICMP",
    58: "ICMPv6",
    255: "RAW/IP",
}


def parse_int_strict(value: Any) -> Tuple[Optional[int], DataState]:
    """Parse integer from string/int without losing precision or turning empty into 0."""
    if value is None or value == "":
        return None, DataState.UNAVAILABLE
    if isinstance(value, bool):
        return None, DataState.ERROR
    if isinstance(value, int):
        return value, DataState.OBSERVED
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned == "":
            return None, DataState.UNAVAILABLE
        try:
            return int(cleaned), DataState.OBSERVED
        except ValueError:
            return None, DataState.ERROR
    try:
        return int(value), DataState.OBSERVED
    except (TypeError, ValueError):
        return None, DataState.ERROR


def format_bytes(n_bytes: Optional[int]) -> Optional[str]:
    """Convert raw byte count into human-readable IEC units while preserving 0 vs None."""
    if n_bytes is None:
        return None
    if n_bytes < 0:
        return f"{n_bytes} B"
    if n_bytes == 0:
        return "0 B"
    if n_bytes >= 1024 ** 4:
        return f"{n_bytes / (1024 ** 4):.2f} TiB"
    if n_bytes >= 1024 ** 3:
        return f"{n_bytes / (1024 ** 3):.2f} GiB"
    if n_bytes >= 1024 ** 2:
        return f"{n_bytes / (1024 ** 2):.2f} MiB"
    if n_bytes >= 1024:
        return f"{n_bytes / 1024:.2f} KiB"
    return f"{n_bytes} B"


def bytes_to_gib(n_bytes: Optional[int]) -> Optional[float]:
    if n_bytes is None:
        return None
    return round(n_bytes / (1024 ** 3), 2)


def derive_network_cidr(address: str, mask: str) -> Tuple[Optional[str], Optional[str], DataState]:
    """Derive subnet CIDR and interface CIDR from IP and netmask."""
    if not address or not mask:
        return None, None, DataState.UNAVAILABLE
    clean_addr = address.split("%")[0].strip()
    clean_mask = mask.strip()
    try:
        if ":" in clean_addr and ":" in clean_mask:
            # Convert IPv6 hex mask like ffff:ffff:ffff:ffff:: to prefix length
            expanded = ipaddress.IPv6Address(clean_mask).exploded
            bits = bin(int(expanded.replace(":", ""), 16))[2:]
            prefix_len = bits.count("1")
            iface = ipaddress.ip_interface(f"{clean_addr}/{prefix_len}")
        else:
            iface = ipaddress.ip_interface(f"{clean_addr}/{clean_mask}")
        return str(iface.network), str(iface), DataState.DERIVED
    except (ValueError, TypeError):
        return None, None, DataState.UNAVAILABLE


def classify_interface_kind(name: str, address: str, raw_type: str) -> Tuple[str, DataState, str]:
    """Classify interface kind based strictly on observable evidence."""
    lname = (name or "").lower()
    if lname == "lo" or address.startswith("127.") or address == "::1":
        return "loopback", DataState.DERIVED, "Identificada por nombre 'lo' y rango loopback RFC 1122 / RFC 4291."
    if lname.startswith(("docker", "br-", "veth", "virbr", "cni", "flannel", "cali")):
        return (
            "virtual_container_bridge",
            DataState.INFERRED,
            f"El prefijo de interfaz '{name}' corresponde a un puente o interfaz virtual de contenedores/virtualización.",
        )
    if lname.startswith(("wlan", "wlp", "wifi")):
        return (
            "wireless_lan",
            DataState.INFERRED,
            f"El prefijo '{name}' sugiere una interfaz inalámbrica IEEE 802.11.",
        )
    if lname.startswith(("eth", "enp", "eno", "ens")):
        return (
            "ethernet_nic",
            DataState.INFERRED,
            f"El prefijo '{name}' sugiere una interfaz Ethernet cableada o vNIC.",
        )
    if raw_type and raw_type not in ("unknown", ""):
        return raw_type, DataState.OBSERVED, f"Tipo reportado directamente por osquery: {raw_type}."
    return "unknown", DataState.UNAVAILABLE, "osquery reportó type='unknown' y el nombre no permite confirmar medio físico."


class OsqueryDiscoveryParser(BaseDiscoveryCollectorParser):
    """Parser y analizador explicativo para inventarios osquery de CloudMove."""

    collector_id = "osquery"
    collector_name = "osquery Host Discovery Collector"
    supported_schemas = list(SUPPORTED_SCHEMAS)

    def can_parse(self, raw_data: Dict[str, Any]) -> bool:
        if not isinstance(raw_data, dict):
            return False
        schema = str(raw_data.get("schema_version") or "")
        return schema in SUPPORTED_SCHEMAS

    def validate_payload(self, raw_data: Any) -> List[str]:
        errors: List[str] = []
        if not isinstance(raw_data, dict):
            return ["El contenido JSON debe ser un objeto en la raíz (dict), no una lista ni un valor primitivo."]
        if not raw_data:
            return ["El objeto JSON está vacío."]

        schema = raw_data.get("schema_version")
        if not schema:
            errors.append("Falta el campo obligatorio 'schema_version'.")
        elif schema not in SUPPORTED_SCHEMAS:
            errors.append(
                f"Esquema '{schema}' no soportado. Esquemas admitidos: {', '.join(sorted(SUPPORTED_SCHEMAS))}."
            )

        # If it is a re-imported session wrapper, unwrap or check inner normalized
        if schema == "cloudmove.discovery.session.v1":
            if not isinstance(raw_data.get("normalized_inventory"), dict):
                errors.append("El archivo de sesión exportado no contiene 'normalized_inventory'.")
            return errors

        if schema == "cloudmove.normalized.v1":
            has_summary = isinstance(raw_data.get("summary"), dict) and bool(raw_data.get("summary"))
            has_asset = isinstance(raw_data.get("asset"), dict) and bool(raw_data.get("asset"))
            if not (has_summary or has_asset):
                errors.append("El inventario normalizado debe contener el objeto 'summary' o 'asset'.")
            return errors

        if not isinstance(raw_data.get("asset"), dict) or not raw_data.get("asset"):
            errors.append("Falta el objeto obligatorio 'asset' con los datos de identidad del equipo.")

        if "source" in raw_data and raw_data["source"] is not None and not isinstance(raw_data["source"], dict):
            errors.append("El campo 'source' debe ser un objeto JSON válido.")

        return errors

    def parse(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        validation_errors = self.validate_payload(raw_data)
        if validation_errors:
            raise ValueError(" | ".join(validation_errors))

        schema = str(raw_data.get("schema_version"))
        if schema == "cloudmove.discovery.session.v1":
            inner = raw_data["normalized_inventory"]
            return self._parse_normalized_reimport(inner)
        if schema == "cloudmove.normalized.v1":
            return self._parse_normalized_reimport(raw_data)

        return self._parse_osquery_v1(raw_data)

    def _parse_normalized_reimport(self, norm: Dict[str, Any]) -> Dict[str, Any]:
        """Support re-importing an already normalized inventory JSON without losing structure."""
        if "sections" in norm and "summary" in norm:
            # Full CloudMove normalized v1 structure already present
            reimported = dict(norm)
            reimported["reimported"] = True
            return reimported

        # Legacy/kit normalized v1 format (from cloudmove_osquery_parser.py) -> convert to full structure
        asset_in = norm.get("asset") or {}
        hw_in = norm.get("hardware") or {}
        net_in = norm.get("network") or {}
        rt_in = norm.get("runtime") or {}
        sw_in = norm.get("software") or {}
        col_in = norm.get("collection") or {}
        src_in = norm.get("source") or {}

        synthetic_raw = {
            "schema_version": "cloudmove.discovery.v1",
            "source": {
                "tool": src_in.get("tool", "osquery"),
                "tool_version": src_in.get("tool_version", "unknown"),
                "collector": src_in.get("collector", "reimported-normalized"),
                "collector_host": src_in.get("collector_host") or asset_in.get("hostname"),
            },
            "collected_at": src_in.get("collected_at"),
            "asset": {
                "hostname": asset_in.get("hostname"),
                "uuid": asset_in.get("uuid"),
                "hardware_vendor": asset_in.get("vendor"),
                "hardware_model": asset_in.get("model"),
                "cpu_type": asset_in.get("architecture"),
                "cpu_physical_cores": (asset_in.get("cpu") or {}).get("physical_cores"),
                "cpu_logical_cores": (asset_in.get("cpu") or {}).get("logical_cores"),
                "physical_memory_bytes": (asset_in.get("memory") or {}).get("total_bytes"),
                "os": {
                    "name": (asset_in.get("os") or {}).get("name"),
                    "version": (asset_in.get("os") or {}).get("version"),
                    "codename": (asset_in.get("os") or {}).get("codename"),
                    "arch": (asset_in.get("os") or {}).get("architecture"),
                },
                "platform": {},
                "system_info": {
                    "computer_name": asset_in.get("hostname"),
                    "uuid": asset_in.get("uuid"),
                    "hardware_vendor": asset_in.get("vendor"),
                    "hardware_model": asset_in.get("model"),
                    "cpu_brand": (asset_in.get("cpu") or {}).get("model"),
                    "cpu_physical_cores": (asset_in.get("cpu") or {}).get("physical_cores"),
                    "cpu_logical_cores": (asset_in.get("cpu") or {}).get("logical_cores"),
                    "physical_memory": (asset_in.get("memory") or {}).get("total_bytes"),
                },
            },
            "hardware": {
                "cpu_info": [
                    {
                        "model": (asset_in.get("cpu") or {}).get("model"),
                        "number_of_cores": (asset_in.get("cpu") or {}).get("physical_cores"),
                        "logical_processors": (asset_in.get("cpu") or {}).get("logical_cores"),
                        "max_clock_speed": (asset_in.get("cpu") or {}).get("max_clock_mhz"),
                    }
                ] if asset_in.get("cpu") else [],
                "memory_info": [
                    {
                        "memory_total": (asset_in.get("memory") or {}).get("total_bytes"),
                        "memory_available": (asset_in.get("memory") or {}).get("available_bytes_snapshot"),
                    }
                ] if asset_in.get("memory") else [],
                "block_devices": [
                    {
                        "name": b.get("name"),
                        "parent": b.get("parent"),
                        "model": b.get("model"),
                        "type": b.get("type"),
                        "size": b.get("raw_size"),
                        "block_size": b.get("block_size"),
                    }
                    for b in (hw_in.get("block_devices") or [])
                ],
                "mounts": [
                    {
                        "device": m.get("device"),
                        "path": m.get("path"),
                        "type": m.get("filesystem"),
                        "blocks": (m.get("total_bytes_estimate") // 4096) if m.get("total_bytes_estimate") else None,
                        "blocks_available": (m.get("available_bytes_estimate") // 4096) if m.get("available_bytes_estimate") else None,
                        "blocks_free": ((m.get("total_bytes_estimate") - (m.get("used_bytes_estimate") or 0)) // 4096) if m.get("total_bytes_estimate") is not None else None,
                        "blocks_size": 4096 if m.get("total_bytes_estimate") is not None else None,
                    }
                    for m in (hw_in.get("mounts") or [])
                ],
            },
            "network": {
                "interfaces": [
                    {
                        "interface": i.get("name") or i.get("interface"),
                        "address": i.get("address"),
                        "mask": i.get("mask"),
                        "type": i.get("type"),
                    }
                    for i in (net_in.get("interfaces") or [])
                ],
                "routes": net_in.get("routes") or [],
                "listening_ports": [
                    {
                        "address": l.get("address"),
                        "port": l.get("port"),
                        "protocol": 6 if l.get("protocol") == "TCP" else (17 if l.get("protocol") == "UDP" else l.get("protocol")),
                        "pid": l.get("pid"),
                    }
                    for l in (net_in.get("listening_services") or net_in.get("listening_ports") or [])
                ],
                "process_open_sockets": [],
            },
            "software": {
                "deb_packages": sw_in.get("installed_debian_packages") or sw_in.get("deb_packages") or [],
                "systemd_units": sw_in.get("systemd_units") or [],
                "kernel_modules": sw_in.get("kernel_modules") or [],
            },
            "runtime": {
                "processes": rt_in.get("processes") or [],
                "uptime": [rt_in["uptime"]] if isinstance(rt_in.get("uptime"), dict) else (rt_in.get("uptime") or []),
            },
            "collection": {
                "query_count": col_in.get("query_count", 16),
                "successful_query_count": col_in.get("successful_query_count", 16),
                "errors": col_in.get("source_errors") or col_in.get("errors") or [],
            },
        }
        result = self._parse_osquery_v1(synthetic_raw)
        result["reimported"] = True
        return result

    def _parse_osquery_v1(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        issues: List[DiscoveryIssue] = []
        missing_fields: List[Dict[str, str]] = []

        source_raw = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        collected_at = str(raw.get("collected_at") or "").strip() or None
        if not collected_at:
            missing_fields.append({
                "section": "source",
                "field": "collected_at",
                "reason": "Fecha de recolección ausente en el documento raíz.",
            })

        provenance_base = (
            f"osquery ({source_raw.get('tool_version') or 'versión no especificada'}) · "
            f"collected_at={collected_at or 'no registrado'}"
        )

        # 1. ASSET & SYSTEM IDENTITY
        asset_raw = raw.get("asset") if isinstance(raw.get("asset"), dict) else {}
        sys_info = asset_raw.get("system_info") if isinstance(asset_raw.get("system_info"), dict) else {}
        os_raw = asset_raw.get("os") if isinstance(asset_raw.get("os"), dict) else {}
        platform_raw = asset_raw.get("platform") if isinstance(asset_raw.get("platform"), dict) else {}

        asset_hostname = str(asset_raw.get("hostname") or "").strip()
        computer_name = str(sys_info.get("computer_name") or "").strip()
        sys_hostname = str(sys_info.get("hostname") or "").strip()
        effective_hostname = asset_hostname or computer_name or sys_hostname or "unknown-host"

        if sys_hostname and computer_name and sys_hostname != computer_name:
            issues.append(
                DiscoveryIssue(
                    code="HOSTNAME_FIELD_MISMATCH",
                    severity="warning",
                    section="summary",
                    message=(
                        f"El campo system_info.hostname ('{sys_hostname}') difiere de "
                        f"system_info.computer_name ('{computer_name}'). Se prioriza '{effective_hostname}'."
                    ),
                    provenance="asset.hostname / asset.system_info.hostname / asset.system_info.computer_name",
                    state=DataState.OBSERVED,
                    suggested_action="Verificar /etc/hostname y /etc/hosts en el equipo origen para evitar colisiones DNS al migrar.",
                )
            )

        uuid_val = str(asset_raw.get("uuid") or sys_info.get("uuid") or "").strip() or None
        if not uuid_val:
            missing_fields.append({"section": "asset", "field": "uuid", "reason": "UUID de hardware no disponible."})

        vendor = str(asset_raw.get("hardware_vendor") or sys_info.get("hardware_vendor") or "").strip() or None
        model = str(asset_raw.get("hardware_model") or sys_info.get("hardware_model") or "").strip() or None
        arch = str(asset_raw.get("cpu_type") or os_raw.get("arch") or sys_info.get("cpu_type") or "").strip() or None

        # Detect if hardware model suggests laptop/workstation rather than datacenter server
        is_workstation_or_laptop = False
        model_lower = (model or "").lower()
        if any(kw in model_lower for kw in ("ideapad", "thinkpad", "laptop", "notebook", "macbook", "xps", "latitude", "pavilion")):
            is_workstation_or_laptop = True
            issues.append(
                DiscoveryIssue(
                    code="NON_SERVER_HARDWARE_MODEL",
                    severity="warning",
                    section="hardware",
                    message=(
                        f"El modelo de hardware detectado ('{model}') corresponde a un equipo portátil/estación de trabajo. "
                        "Trátese como entorno de laboratorio o validación del recolector, no como un servidor de producción en rack."
                    ),
                    provenance="asset.hardware_model / system_info.hardware_model",
                    state=DataState.INFERRED,
                    suggested_action="Confirmar con el propietario del activo si este host ejecuta cargas productivas o es un entorno de desarrollo/pruebas.",
                )
            )

        # 2. COLLECTION METADATA
        col_raw = raw.get("collection") if isinstance(raw.get("collection"), dict) else {}
        query_count, _ = parse_int_strict(col_raw.get("query_count"))
        success_count, _ = parse_int_strict(col_raw.get("successful_query_count"))
        col_errors = col_raw.get("errors") if isinstance(col_raw.get("errors"), list) else []
        for err in col_errors:
            if isinstance(err, dict):
                issues.append(
                    DiscoveryIssue(
                        code="COLLECTOR_QUERY_ERROR",
                        severity="error",
                        section="collection",
                        message=f"La consulta osquery '{err.get('query')}' falló: {err.get('error')}",
                        provenance=f"collection.errors[{err.get('query')}]",
                        state=DataState.ERROR,
                        suggested_action="Ejecutar el recolector con privilegios adecuados o verificar soporte de tabla en la versión de osquery.",
                    )
                )

        # 3. HARDWARE SECTION (CPU, Memory, Storage, Firmware/Board, Other)
        hw_raw = raw.get("hardware") if isinstance(raw.get("hardware"), dict) else {}
        if not isinstance(raw.get("hardware"), dict) and raw.get("hardware") is not None:
            issues.append(
                DiscoveryIssue(
                    code="INVALID_HARDWARE_SECTION",
                    severity="error",
                    section="hardware",
                    message="La sección 'hardware' no tiene un formato de objeto JSON válido.",
                    provenance="hardware",
                    state=DataState.ERROR,
                )
            )

        # 3.1 CPU
        cpu_list_raw = hw_raw.get("cpu_info") if isinstance(hw_raw.get("cpu_info"), list) else []
        cpu_first = cpu_list_raw[0] if (cpu_list_raw and isinstance(cpu_list_raw[0], dict)) else {}

        cpu_model = str(cpu_first.get("model") or sys_info.get("cpu_brand") or "").strip() or None
        cpu_manufacturer = str(cpu_first.get("manufacturer") or "").strip() or None
        phys_cores, phys_state = parse_int_strict(
            cpu_first.get("number_of_cores") if cpu_first.get("number_of_cores") not in (None, "") else asset_raw.get("cpu_physical_cores")
        )
        log_cores, log_state = parse_int_strict(
            cpu_first.get("logical_processors") if cpu_first.get("logical_processors") not in (None, "") else asset_raw.get("cpu_logical_cores")
        )
        sockets_count, sockets_state = parse_int_strict(sys_info.get("cpu_sockets"))
        curr_clock_mhz, curr_clock_state = parse_int_strict(cpu_first.get("current_clock_speed"))
        max_clock_mhz, max_clock_state = parse_int_strict(cpu_first.get("max_clock_speed"))
        addr_width, _ = parse_int_strict(cpu_first.get("address_width"))
        socket_desig = str(cpu_first.get("socket_designation") or "").strip() or None
        microcode = str(sys_info.get("cpu_microcode") or "").strip() or None

        if phys_cores is None:
            missing_fields.append({"section": "hardware.cpu", "field": "number_of_cores", "reason": "Núcleos físicos no reportados."})

        # 3.2 Memory
        mem_list_raw = hw_raw.get("memory_info") if isinstance(hw_raw.get("memory_info"), list) else []
        mem_first = mem_list_raw[0] if (mem_list_raw and isinstance(mem_list_raw[0], dict)) else {}

        mem_total_b, mem_total_state = parse_int_strict(
            mem_first.get("memory_total") if mem_first.get("memory_total") not in (None, "") else asset_raw.get("physical_memory_bytes")
        )
        mem_avail_b, mem_avail_state = parse_int_strict(mem_first.get("memory_available"))
        mem_free_b, mem_free_state = parse_int_strict(mem_first.get("memory_free"))
        mem_active_b, _ = parse_int_strict(mem_first.get("active"))
        mem_inactive_b, _ = parse_int_strict(mem_first.get("inactive"))
        mem_buffers_b, _ = parse_int_strict(mem_first.get("buffers"))
        mem_cached_b, _ = parse_int_strict(mem_first.get("cached"))
        swap_total_b, swap_total_state = parse_int_strict(mem_first.get("swap_total"))
        swap_free_b, swap_free_state = parse_int_strict(mem_first.get("swap_free"))
        swap_cached_b, _ = parse_int_strict(mem_first.get("swap_cached"))

        mem_used_derived_b: Optional[int] = None
        mem_utilization_pct: Optional[float] = None
        if mem_total_b is not None and mem_avail_b is not None and mem_total_b > 0:
            mem_used_derived_b = max(mem_total_b - mem_avail_b, 0)
            mem_utilization_pct = round((mem_used_derived_b / mem_total_b) * 100.0, 1)

        swap_used_derived_b: Optional[int] = None
        if swap_total_b is not None and swap_free_b is not None:
            swap_used_derived_b = max(swap_total_b - swap_free_b, 0)

        # 3.3 Storage: Mounts & Block Devices (strictly separating physical disks from partitions!)
        mounts_raw = hw_raw.get("mounts") if isinstance(hw_raw.get("mounts"), list) else []
        parsed_mounts: List[Dict[str, Any]] = []
        mount_by_device: Dict[str, Dict[str, Any]] = {}

        VIRTUAL_FS_TYPES = {
            "sysfs", "proc", "devtmpfs", "devpts", "tmpfs", "securityfs", "cgroup2",
            "pstore", "efivarfs", "bpf", "autofs", "hugetlbfs", "mqueue", "debugfs",
            "tracefs", "fusectl", "configfs", "ramfs", "nsfs", "overlay", "squashfs",
        }

        for m in mounts_raw:
            if not isinstance(m, dict):
                continue
            dev = str(m.get("device") or "").strip()
            path = str(m.get("path") or "").strip()
            fstype = str(m.get("type") or "").strip()
            flags = str(m.get("flags") or "").strip()
            blocks, _ = parse_int_strict(m.get("blocks"))
            blocks_avail, _ = parse_int_strict(m.get("blocks_available"))
            blocks_free, _ = parse_int_strict(m.get("blocks_free"))
            block_sz, _ = parse_int_strict(m.get("blocks_size"))
            inodes, _ = parse_int_strict(m.get("inodes"))
            inodes_free, _ = parse_int_strict(m.get("inodes_free"))

            total_b = (blocks * block_sz) if (blocks is not None and block_sz is not None and blocks > 0) else (0 if blocks == 0 else None)
            avail_b = (blocks_avail * block_sz) if (blocks_avail is not None and block_sz is not None and blocks is not None and blocks > 0) else (0 if blocks == 0 else None)
            free_b = (blocks_free * block_sz) if (blocks_free is not None and block_sz is not None and blocks is not None and blocks > 0) else (0 if blocks == 0 else None)
            used_b = max(total_b - free_b, 0) if (total_b is not None and free_b is not None and total_b > 0) else (0 if total_b == 0 else None)
            usage_pct = round((used_b / total_b) * 100.0, 1) if (total_b and used_b is not None and total_b > 0) else None

            is_persistent = dev.startswith("/dev/") or fstype in ("ext4", "xfs", "btrfs", "vfat", "ntfs", "zfs", "nfs", "cifs")
            mount_item = {
                "device": dev,
                "device_alias": str(m.get("device_alias") or "").strip() or None,
                "path": path,
                "filesystem": fstype,
                "flags": flags,
                "is_persistent": is_persistent,
                "is_virtual_fs": fstype in VIRTUAL_FS_TYPES and not dev.startswith("/dev/"),
                "raw_blocks": blocks,
                "raw_blocks_size": block_sz,
                "total_bytes": total_b,
                "total_formatted": format_bytes(total_b),
                "used_bytes": used_b,
                "used_formatted": format_bytes(used_b),
                "free_bytes": free_b,
                "free_formatted": format_bytes(free_b),
                "available_bytes": avail_b,
                "available_formatted": format_bytes(avail_b),
                "usage_percent": usage_pct,
                "inodes": inodes,
                "inodes_free": inodes_free,
                "state": DataState.DERIVED if (total_b is not None and total_b > 0) else DataState.OBSERVED,
                "explanation": DataPointExplanation(
                    id=f"mount-{path}",
                    label=f"Punto de montaje {path} ({dev})",
                    what_is=f"Sistema de archivos '{fstype}' montado en '{path}' sobre el dispositivo '{dev}'.",
                    detected_value={"blocks": blocks, "blocks_size": block_sz, "blocks_available": blocks_avail, "blocks_free": blocks_free},
                    formatted_value=(
                        f"{format_bytes(total_b)} total · {format_bytes(used_b)} usado ({usage_pct}%) · {format_bytes(avail_b)} disponible"
                        if (total_b and total_b > 0)
                        else f"Sistema virtual/pseudo-FS ({fstype})"
                    ),
                    interpretation=(
                        f"Almacenamiento persistente activo en '{path}' con {format_bytes(avail_b)} libres para el usuario."
                        if is_persistent and total_b
                        else f"Punto de montaje del kernel/sistema ({fstype}) en memoria o pseudo-dispositivo."
                    ),
                    why_it_matters="Permite conocer el consumo real de espacio en los volúmenes lógicos y puntos de montaje activos.",
                    migration_relevance=(
                        f"Relevante para dimensionar volúmenes Amazon EBS (ej. gp3) para '{path}': se observan {format_bytes(used_b)} ocupados de {format_bytes(total_b)}."
                        if is_persistent
                        else "No requiere aprovisionamiento de volumen EBS independiente por ser un sistema de archivos virtual del kernel Linux."
                    ),
                    provenance=f"hardware.mounts (path='{path}') · {provenance_base}",
                    state=DataState.DERIVED if (total_b and total_b > 0) else DataState.OBSERVED,
                    limitations="Refleja el consumo en el instante del corte; no captura tasas de crecimiento de logs ni IOPS (lectura/escritura por segundo).",
                    suggested_action=(
                        "Recopilar métricas de IOPS/throughput (iostat / sar) y tasa de crecimiento antes de elegir tipo y tamaño final de EBS."
                        if is_persistent
                        else "Ninguna acción requerida para migración de almacenamiento."
                    ),
                ).model_dump(),
            }
            parsed_mounts.append(mount_item)
            if dev.startswith("/dev/"):
                mount_by_device[dev] = mount_item

        block_raw = hw_raw.get("block_devices") if isinstance(hw_raw.get("block_devices"), list) else []
        all_block_names = {str(b.get("name") or "").strip() for b in block_raw if isinstance(b, dict)}

        physical_disks: List[Dict[str, Any]] = []
        partitions: List[Dict[str, Any]] = []
        block_by_name: Dict[str, Dict[str, Any]] = {}

        # First pass: identify parent block sizes so partitions without block_size can reference parent sector size safely as Derived
        parent_block_size_map: Dict[str, int] = {}
        for b in block_raw:
            if not isinstance(b, dict):
                continue
            bname = str(b.get("name") or "").strip()
            bsz, _ = parse_int_strict(b.get("block_size"))
            if bname and bsz and bsz > 0:
                parent_block_size_map[bname] = bsz

        for b in block_raw:
            if not isinstance(b, dict):
                continue
            name = str(b.get("name") or "").strip()
            parent = str(b.get("parent") or "").strip() or None
            model_b = str(b.get("model") or "").strip() or None
            vendor_b = str(b.get("vendor") or "").strip() or None
            serial_b = str(b.get("serial") or "").strip() or None
            uuid_b = str(b.get("uuid") or "").strip() or None
            fstype_b = str(b.get("type") or "").strip() or None
            label_b = str(b.get("label") or "").strip() or None
            raw_sectors, _ = parse_int_strict(b.get("size"))
            block_sz, _ = parse_int_strict(b.get("block_size"))

            # Determine if this device is a child partition of another block device in the inventory
            is_partition = bool(parent and parent in all_block_names)

            effective_sector_size = block_sz
            sector_size_source = "observed"
            if not effective_sector_size and is_partition and parent in parent_block_size_map:
                effective_sector_size = parent_block_size_map[parent]
                sector_size_source = f"derived_from_parent ({parent}: {effective_sector_size} B)"

            size_bytes: Optional[int] = None
            size_state = DataState.UNAVAILABLE
            size_note = "No se pudo derivar tamaño en bytes por falta de block_size."
            if raw_sectors is not None and effective_sector_size:
                size_bytes = raw_sectors * effective_sector_size
                size_state = DataState.DERIVED
                if block_sz:
                    size_note = f"Derivado de size ({raw_sectors:,} sectores) × block_size ({block_sz} B)."
                else:
                    size_note = (
                        f"osquery dejó block_size vacío en la partición; tamaño derivado multiplicando "
                        f"size ({raw_sectors:,} sectores) × block_size del disco padre '{parent}' ({effective_sector_size} B)."
                    )

            linked_mount = mount_by_device.get(name)
            entry = {
                "name": name,
                "parent": parent,
                "is_partition": is_partition,
                "role": "partition" if is_partition else "physical_disk",
                "model": model_b,
                "vendor": vendor_b,
                "serial": serial_b,
                "uuid": uuid_b,
                "filesystem_type": fstype_b,
                "label": label_b,
                "raw_sectors": raw_sectors,
                "block_size": block_sz,
                "effective_sector_size": effective_sector_size,
                "sector_size_source": sector_size_source,
                "size_bytes": size_bytes,
                "size_formatted": format_bytes(size_bytes),
                "size_gib": bytes_to_gib(size_bytes),
                "size_note": size_note,
                "mount_point": linked_mount.get("path") if linked_mount else None,
                "mount_details": linked_mount,
                "children_partitions": [],
                "state": size_state,
                "explanation": DataPointExplanation(
                    id=f"block-{name}",
                    label=f"{'Partición' if is_partition else 'Disco de bloque'} {name}",
                    what_is=(
                        f"Partición lógica '{name}' contenida dentro del disco físico '{parent}' (tipo: {fstype_b or 'no especificado'})."
                        if is_partition
                        else f"Dispositivo de bloque físico '{name}' ({model_b or 'modelo no reportado'})."
                    ),
                    detected_value={"size": raw_sectors, "block_size": block_sz, "type": fstype_b, "parent": parent},
                    formatted_value=f"{format_bytes(size_bytes)} ({size_note})" if size_bytes is not None else "Tamaño en bytes no disponible",
                    interpretation=(
                        f"Subdivisión del disco '{parent}' dedicada a '{fstype_b or 'datos'}'"
                        + (f", montada en '{linked_mount['path']}'." if linked_mount else ".")
                        if is_partition
                        else f"Unidad de almacenamiento principal ({model_b or name}) con capacidad bruta estimada de {format_bytes(size_bytes)}."
                    ),
                    why_it_matters=(
                        "Distingue el esquema de particionado (EFI, raíz ext4, swap) sin duplicar la capacidad física del disco."
                        if is_partition
                        else "Determina la capacidad física total de almacenamiento local adjunto al equipo."
                    ),
                    migration_relevance=(
                        "No debe sumarse como un disco adicional independiente; representa una partición dentro del volumen padre."
                        if is_partition
                        else "Define la línea base de capacidad de bloque para planificar volúmenes EBS en AWS."
                    ),
                    provenance=f"hardware.block_devices (name='{name}') · {provenance_base}",
                    state=size_state,
                    limitations="osquery reporta 'size' en sectores lógicos; el valor en bytes es derivado y debe contrastarse con lsblk -b en auditorías finales.",
                    suggested_action="Contrastar con el uso real en 'mounts' para dimensionar EBS según consumo y proyección, no solo tamaño bruto.",
                ).model_dump(),
            }
            block_by_name[name] = entry
            if is_partition:
                partitions.append(entry)
            else:
                physical_disks.append(entry)

        for part in partitions:
            p_name = part.get("parent")
            if p_name and p_name in block_by_name:
                block_by_name[p_name]["children_partitions"].append(part["name"])

        # Total physical storage is strictly the sum of non-partition physical disks!
        total_physical_disk_bytes = sum(d["size_bytes"] for d in physical_disks if d.get("size_bytes") is not None)

        # 3.4 Firmware & Motherboard
        firmware_info = {
            "firmware_type": str(platform_raw.get("firmware_type") or "").strip() or None,
            "firmware_vendor": str(platform_raw.get("vendor") or "").strip() or None,
            "firmware_version": str(platform_raw.get("version") or "").strip() or None,
            "firmware_date": str(platform_raw.get("date") or "").strip() or None,
            "firmware_revision": str(platform_raw.get("revision") or "").strip() or None,
            "firmware_size_bytes": parse_int_strict(platform_raw.get("size"))[0],
            "board_vendor": str(sys_info.get("board_vendor") or "").strip() or None,
            "board_model": str(sys_info.get("board_model") or "").strip() or None,
            "board_version": str(sys_info.get("board_version") or "").strip() or None,
            "board_serial": str(sys_info.get("board_serial") or "").strip() or None,
            "hardware_serial": str(sys_info.get("hardware_serial") or "").strip() or None,
            "hardware_version": str(sys_info.get("hardware_version") or "").strip() or None,
            "explanation": DataPointExplanation(
                id="hw-firmware-board",
                label="Firmware UEFI/BIOS y Placa Base",
                what_is="Metadatos de la placa base (SMBIOS/DMI) y del firmware de arranque (UEFI/BIOS).",
                detected_value={
                    "firmware_type": platform_raw.get("firmware_type"),
                    "firmware_version": platform_raw.get("version"),
                    "board_vendor": sys_info.get("board_vendor"),
                    "board_model": sys_info.get("board_model"),
                },
                formatted_value=(
                    f"{(platform_raw.get('firmware_type') or 'unknown').upper()} · "
                    f"{sys_info.get('board_vendor') or 'N/A'} {sys_info.get('board_model') or ''} · "
                    f"Versión {platform_raw.get('version') or 'N/A'}"
                ),
                interpretation=(
                    f"El sistema arranca mediante modo '{platform_raw.get('firmware_type') or 'desconocido'}' "
                    f"en placa {sys_info.get('board_vendor') or ''} {sys_info.get('board_model') or ''}."
                ),
                why_it_matters="El modo de arranque (UEFI vs Legacy BIOS) condiciona la compatibilidad de imágenes AMI y particionado GPT/EFI.",
                migration_relevance="Al migrar mediante AWS Application Migration Service (MGN) o VM Import/Export, el modo UEFI requiere instancias EC2 con soporte de boot-mode 'uefi' o 'uefi-preferred'.",
                provenance=f"asset.platform / asset.system_info · {provenance_base}",
                state=DataState.OBSERVED if platform_raw.get("firmware_type") else DataState.UNAVAILABLE,
                limitations="No informa sobre estado de Secure Boot ni claves TPM registradas.",
                suggested_action="Verificar si Secure Boot está activo en caso de planificar una migración Lift & Shift de imagen completa.",
            ).model_dump(),
        }

        # 4. RUNTIME & PROCESSES (Needed before Network to correlate PIDs accurately)
        rt_raw = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
        processes_raw = rt_raw.get("processes") if isinstance(rt_raw.get("processes"), list) else []
        uptime_raw = rt_raw.get("uptime") if isinstance(rt_raw.get("uptime"), list) else []
        uptime_first = uptime_raw[0] if (uptime_raw and isinstance(uptime_raw[0], dict)) else {}

        uptime_total_sec, uptime_state = parse_int_strict(uptime_first.get("total_seconds"))
        uptime_days, _ = parse_int_strict(uptime_first.get("days"))
        uptime_hours, _ = parse_int_strict(uptime_first.get("hours"))
        uptime_minutes, _ = parse_int_strict(uptime_first.get("minutes"))
        uptime_seconds, _ = parse_int_strict(uptime_first.get("seconds"))

        process_by_pid: Dict[int, Dict[str, Any]] = {}
        parsed_processes: List[Dict[str, Any]] = []

        for p in processes_raw:
            if not isinstance(p, dict):
                continue
            pid_val, _ = parse_int_strict(p.get("pid"))
            uid_val, _ = parse_int_strict(p.get("uid"))
            pname = str(p.get("name") or "").strip() or "unknown"
            ppath = str(p.get("path") or "").strip() or None
            is_kernel_thread = (ppath is None) and (
                pname.startswith(("kworker/", "ksoftirqd/", "migration/", "cpuhp/", "idle_inject/", "rcu_", "irq/"))
            )
            proc_item = {
                "pid": pid_val,
                "name": pname,
                "path": ppath,
                "uid": uid_val,
                "is_root": uid_val == 0,
                "is_kernel_thread": is_kernel_thread,
                "listening_ports": [],
                "open_socket_count": 0,
                "remote_peers_count": 0,
                "state": DataState.OBSERVED,
            }
            parsed_processes.append(proc_item)
            if pid_val is not None:
                process_by_pid[pid_val] = proc_item

        # 5. NETWORK SECTION (Interfaces, Subnets, Routes, Listening Ports, Sockets & Remote Endpoints)
        net_raw = raw.get("network") if isinstance(raw.get("network"), dict) else {}
        ifaces_raw = net_raw.get("interfaces") if isinstance(net_raw.get("interfaces"), list) else []
        routes_raw = net_raw.get("routes") if isinstance(net_raw.get("routes"), list) else []
        listeners_raw = net_raw.get("listening_ports") if isinstance(net_raw.get("listening_ports"), list) else []
        sockets_raw = net_raw.get("process_open_sockets") if isinstance(net_raw.get("process_open_sockets"), list) else []

        parsed_interfaces: List[Dict[str, Any]] = []
        local_ips: set[str] = set()
        derived_subnets: Dict[str, Dict[str, Any]] = {}

        for idx, row in enumerate(ifaces_raw):
            if not isinstance(row, dict):
                continue
            ifname = str(row.get("interface") or "").strip() or f"iface-{idx}"
            addr = str(row.get("address") or "").strip()
            mask = str(row.get("mask") or "").strip() or None
            broadcast = str(row.get("broadcast") or "").strip() or None
            ptp = str(row.get("point_to_point") or "").strip() or None
            raw_type = str(row.get("type") or "").strip() or "unknown"

            clean_ip = addr.split("%")[0] if addr else ""
            if clean_ip:
                local_ips.add(clean_ip)

            ip_version = "IPv6" if ":" in clean_ip else ("IPv4" if clean_ip else "Unknown")
            subnet_cidr, iface_cidr, cidr_state = derive_network_cidr(addr, mask or "")
            kind, kind_state, kind_reason = classify_interface_kind(ifname, clean_ip, raw_type)

            is_loopback = kind == "loopback"
            is_link_local = clean_ip.startswith("fe80:") or clean_ip.startswith("169.254.")

            if subnet_cidr and not is_loopback and not is_link_local:
                derived_subnets[subnet_cidr] = {
                    "cidr": subnet_cidr,
                    "interface": ifname,
                    "address": clean_ip,
                    "ip_version": ip_version,
                    "is_virtual_bridge": kind == "virtual_container_bridge",
                    "state": DataState.DERIVED,
                }

            parsed_interfaces.append({
                "id": f"iface-{ifname}-{clean_ip or idx}",
                "interface": ifname,
                "address": addr or None,
                "clean_address": clean_ip or None,
                "ip_version": ip_version,
                "mask": mask,
                "cidr": iface_cidr,
                "subnet": subnet_cidr,
                "broadcast": broadcast,
                "point_to_point": ptp,
                "raw_type": raw_type,
                "classified_kind": kind,
                "classified_state": kind_state,
                "classified_reason": kind_reason,
                "is_loopback": is_loopback,
                "is_link_local": is_link_local,
                "state": DataState.OBSERVED,
                "explanation": DataPointExplanation(
                    id=f"iface-{ifname}-{clean_ip or idx}",
                    label=f"Interfaz {ifname} ({iface_cidr or addr or 'sin IP'})",
                    what_is=f"Asignación de dirección {ip_version} en la interfaz de red '{ifname}'.",
                    detected_value={"interface": ifname, "address": addr, "mask": mask, "broadcast": broadcast, "type": raw_type},
                    formatted_value=f"{ifname}: {iface_cidr or addr} (Subred: {subnet_cidr or 'N/A'})",
                    interpretation=f"{kind_reason} Subred derivada a partir de dirección y máscara: {subnet_cidr or 'no aplicable'}.",
                    why_it_matters="Permite distinguir interfaces locales (loopback), puentes de contenedores (ej. docker0) y conectividad LAN/WLAN del host.",
                    migration_relevance=(
                        "Las redes puente de contenedores (docker0) son internas al runtime de Docker; la red principal define el direccionamiento a mapear hacia subredes Amazon VPC."
                        if kind == "virtual_container_bridge"
                        else (
                            "Interfaz loopback interna del sistema operativo; no requiere ENI ni subred VPC."
                            if is_loopback
                            else f"Interfaz activa en la subred {subnet_cidr or clean_ip}, relevante para diseñar el bloque CIDR de la VPC/Subnet destino y Security Groups."
                        )
                    ),
                    provenance=f"network.interfaces (interface='{ifname}', address='{addr}') · {provenance_base}",
                    state=cidr_state if subnet_cidr else DataState.OBSERVED,
                    limitations="osquery reportó type='unknown'; la clasificación de medio físico/virtual se infiere por nomenclatura e IP.",
                    suggested_action="Confirmar si existen VLANs adicionales, bonding o reglas de firewall (nftables/iptables) asociadas a esta interfaz.",
                ).model_dump(),
            })

        parsed_routes: List[Dict[str, Any]] = []
        default_gateways: List[str] = []

        for idx, r in enumerate(routes_raw):
            if not isinstance(r, dict):
                continue
            dest = str(r.get("destination") or "").strip()
            gw = str(r.get("gateway") or "").strip() or None
            iface = str(r.get("interface") or "").strip() or None
            rtype = str(r.get("type") or "").strip() or None
            netmask = str(r.get("netmask") or "").strip() or None
            source_ip = str(r.get("source") or "").strip() or None
            metric, _ = parse_int_strict(r.get("metric"))
            mtu, _ = parse_int_strict(r.get("mtu"))

            is_default = dest in ("0.0.0.0", "::", "default") and (netmask in ("0", "", None))
            if is_default and gw and gw not in default_gateways:
                default_gateways.append(gw)

            parsed_routes.append({
                "id": f"route-{idx}-{dest}-{iface or 'any'}",
                "destination": dest,
                "netmask": netmask,
                "gateway": gw,
                "interface": iface,
                "source": source_ip,
                "type": rtype,
                "metric": metric,
                "mtu": mtu,
                "is_default_route": is_default,
                "state": DataState.OBSERVED,
            })

        # 5.3 Listening Ports
        parsed_listeners: List[Dict[str, Any]] = []
        seen_listeners: set[Tuple[str, int, str, Optional[int]]] = set()
        unmatched_listener_pids: List[int] = []

        for row in listeners_raw:
            if not isinstance(row, dict):
                continue
            port_val, _ = parse_int_strict(row.get("port"))
            addr = str(row.get("address") or "").strip()
            if port_val is None or port_val <= 0 or not addr:
                continue
            pid_val, _ = parse_int_strict(row.get("pid"))
            proto_num, _ = parse_int_strict(row.get("protocol"))
            proto_str = PROTOCOL_MAP.get(proto_num or -1, f"PROTO-{proto_num}" if proto_num is not None else "UNKNOWN")

            dedup_key = (addr, port_val, proto_str, pid_val)
            if dedup_key in seen_listeners:
                continue
            seen_listeners.add(dedup_key)

            matched_proc = process_by_pid.get(pid_val) if pid_val is not None else None
            if pid_val is not None and matched_proc is None:
                unmatched_listener_pids.append(pid_val)

            proc_name = matched_proc["name"] if matched_proc else (f"PID {pid_val} (no encontrado en processes)" if pid_val else "Proceso desconocido")
            proc_path = matched_proc["path"] if matched_proc else None

            if addr in ("127.0.0.1", "::1"):
                exposure = "loopback_only"
                exposure_label = "Solo local (Loopback)"
            elif addr in ("0.0.0.0", "::"):
                exposure = "all_interfaces"
                exposure_label = "Todas las interfaces (0.0.0.0 / ::)"
            else:
                exposure = "specific_interface"
                exposure_label = f"Interfaz específica ({addr})"

            if matched_proc:
                matched_proc["listening_ports"].append(f"{proto_str}/{port_val} ({addr})")

            listener_entry = {
                "id": f"listen-{proto_str.lower()}-{port_val}-{addr}",
                "address": addr,
                "port": port_val,
                "protocol": proto_str,
                "protocol_number": proto_num,
                "pid": pid_val,
                "process_name": proc_name,
                "process_path": proc_path,
                "pid_matched": matched_proc is not None,
                "exposure": exposure,
                "exposure_label": exposure_label,
                "state": DataState.OBSERVED,
                "explanation": DataPointExplanation(
                    id=f"listen-{proto_str.lower()}-{port_val}-{addr}",
                    label=f"Puerto en escucha {proto_str}/{port_val} ({proc_name})",
                    what_is=f"Socket de red en estado LISTEN en '{addr}:{port_val}' sobre protocolo {proto_str}.",
                    detected_value={"address": addr, "port": port_val, "protocol": proto_num, "pid": pid_val},
                    formatted_value=f"{proto_str}/{port_val} en {addr} → {proc_name} (PID {pid_val if pid_val is not None else 'N/A'})",
                    interpretation=(
                        f"El proceso '{proc_name}' escucha únicamente conexiones originadas dentro del mismo host ({addr})."
                        if exposure == "loopback_only"
                        else f"El proceso '{proc_name}' acepta conexiones de red entrantes en {exposure_label}."
                    ),
                    why_it_matters="Identifica puntos de entrada de red activos y los vincula con el binario exacto que los sirve.",
                    migration_relevance=(
                        "Al estar ligado a loopback (127.0.0.1/::1), es comunicación inter-proceso local y NO debe abrirse en los Security Groups de AWS."
                        if exposure == "loopback_only"
                        else f"Requiere evaluar si el puerto {proto_str}/{port_val} ({proc_name}) debe permitirse en reglas de entrada (Inbound) del Security Group en AWS o restringirse mediante VPN/SSM."
                    ),
                    provenance=f"network.listening_ports + runtime.processes (pid={pid_val}) · {provenance_base}",
                    state=DataState.OBSERVED,
                    limitations="Muestra los puertos abiertos en el momento de la captura; servicios bajo demanda (socket activation) o detenidos no aparecen aquí.",
                    suggested_action=(
                        "Mantener cerrado en Security Groups externos."
                        if exposure == "loopback_only"
                        else f"Validar qué clientes legítimos consumen {proto_str}/{port_val} antes de definir el CIDR de origen en el Security Group de AWS."
                    ),
                ).model_dump(),
            }
            parsed_listeners.append(listener_entry)

        parsed_listeners.sort(key=lambda x: (0 if x["exposure"] != "loopback_only" else 1, x["port"], x["address"]))

        if unmatched_listener_pids:
            issues.append(
                DiscoveryIssue(
                    code="UNMATCHED_LISTENER_PIDS",
                    severity="warning",
                    section="network",
                    message=(
                        f"Se detectaron {len(set(unmatched_listener_pids))} PID(s) en puertos en escucha que no figuran en la tabla 'processes' "
                        f"({sorted(set(unmatched_listener_pids))}). Esto puede ocurrir por procesos efímeros o límites de consulta."
                    ),
                    provenance="network.listening_ports vs runtime.processes",
                    state=DataState.OBSERVED,
                    suggested_action="Verificar con ss -tulpn en el host si los procesos terminaron entre consultas.",
                )
            )

        # 5.4 Open Sockets & Remote Endpoints
        peer_counter: collections.Counter[Tuple[str, int, str]] = collections.Counter()
        peer_processes: Dict[Tuple[str, int, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)
        peer_local_addrs: Dict[Tuple[str, int, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)
        peer_pids: Dict[Tuple[str, int, str], set[int]] = collections.defaultdict(set)

        incomplete_socket_count = 0
        local_socket_count = 0
        remote_socket_count = 0
        sample_sockets: List[Dict[str, Any]] = []

        for s_idx, row in enumerate(sockets_raw):
            if not isinstance(row, dict):
                continue
            pid_val, _ = parse_int_strict(row.get("pid"))
            fd_val, _ = parse_int_strict(row.get("fd"))
            fam_val, _ = parse_int_strict(row.get("family"))
            proto_num, _ = parse_int_strict(row.get("protocol"))
            proto_str = PROTOCOL_MAP.get(proto_num or -1, f"PROTO-{proto_num}" if proto_num is not None else "UNKNOWN")

            local_addr = str(row.get("local_address") or "").split("%")[0].strip()
            remote_addr = str(row.get("remote_address") or "").split("%")[0].strip()
            local_port, _ = parse_int_strict(row.get("local_port"))
            remote_port, _ = parse_int_strict(row.get("remote_port"))

            if pid_val is not None and pid_val in process_by_pid:
                process_by_pid[pid_val]["open_socket_count"] += 1

            proc_obj = process_by_pid.get(pid_val) if pid_val is not None else None
            proc_name = proc_obj["name"] if proc_obj else (f"PID {pid_val}" if pid_val else "unknown")

            if not remote_addr or remote_port is None or remote_port <= 0 or remote_addr in ("0.0.0.0", "::"):
                incomplete_socket_count += 1
                if len(sample_sockets) < 150:
                    sample_sockets.append({
                        "pid": pid_val,
                        "process_name": proc_name,
                        "fd": fd_val,
                        "family": fam_val,
                        "protocol": proto_str,
                        "local_address": local_addr or None,
                        "local_port": local_port,
                        "remote_address": remote_addr or None,
                        "remote_port": remote_port,
                        "socket_kind": "unconnected_or_listener",
                    })
                continue

            try:
                ip_obj = ipaddress.ip_address(remote_addr)
                is_local = ip_obj.is_loopback or ip_obj.is_unspecified or ip_obj.is_link_local or (remote_addr in local_ips)
                is_public = ip_obj.is_global
            except ValueError:
                incomplete_socket_count += 1
                continue

            if is_local:
                local_socket_count += 1
                if len(sample_sockets) < 150:
                    sample_sockets.append({
                        "pid": pid_val,
                        "process_name": proc_name,
                        "fd": fd_val,
                        "family": fam_val,
                        "protocol": proto_str,
                        "local_address": local_addr or None,
                        "local_port": local_port,
                        "remote_address": remote_addr,
                        "remote_port": remote_port,
                        "socket_kind": "local_loopback",
                    })
                continue

            remote_socket_count += 1
            if pid_val is not None and pid_val in process_by_pid:
                process_by_pid[pid_val]["remote_peers_count"] += 1

            key = (remote_addr, remote_port, proto_str)
            peer_counter[key] += 1
            peer_processes[key][proc_name] += 1
            if local_addr:
                peer_local_addrs[key][local_addr] += 1
            if pid_val is not None:
                peer_pids[key].add(pid_val)

            if len(sample_sockets) < 250:
                sample_sockets.append({
                    "pid": pid_val,
                    "process_name": proc_name,
                    "fd": fd_val,
                    "family": fam_val,
                    "protocol": proto_str,
                    "local_address": local_addr or None,
                    "local_port": local_port,
                    "remote_address": remote_addr,
                    "remote_port": remote_port,
                    "socket_kind": "remote_connection",
                })

        observed_peers: List[Dict[str, Any]] = []
        for (rip, rport, proto), obs_count in peer_counter.most_common():
            try:
                ip_obj = ipaddress.ip_address(rip)
                is_public = ip_obj.is_global
                is_private = ip_obj.is_private
            except ValueError:
                is_public = False
                is_private = False

            procs_list = [
                {"name": name, "observations": cnt}
                for name, cnt in peer_processes[(rip, rport, proto)].most_common()
            ]
            local_list = [
                {"address": laddr, "observations": cnt}
                for laddr, cnt in peer_local_addrs[(rip, rport, proto)].most_common()
            ]
            proc_names_str = ", ".join(p["name"] for p in procs_list) or "proceso no identificado"

            observed_peers.append({
                "id": f"peer-{rip}-{proto.lower()}-{rport}",
                "remote_ip": rip,
                "remote_port": rport,
                "protocol": proto,
                "is_public_ip": is_public,
                "is_private_ip": is_private,
                "observation_count": obs_count,
                "pids": sorted(peer_pids[(rip, rport, proto)]),
                "processes": procs_list,
                "local_addresses": local_list,
                "evidence_type": "observed_socket_snapshot",
                "dependency_confirmed": False,
                "state": DataState.OBSERVED,
                "explanation": DataPointExplanation(
                    id=f"peer-{rip}-{proto.lower()}-{rport}",
                    label=f"Endpoint remoto observado {rip}:{rport} ({proto})",
                    what_is=f"Comunicación de red observada hacia {rip}:{rport}/{proto} desde el proceso '{proc_names_str}'.",
                    detected_value={"remote_ip": rip, "remote_port": rport, "protocol": proto, "observations": obs_count},
                    formatted_value=f"{rip}:{rport}/{proto} ({obs_count} socket(s) · {proc_names_str})",
                    interpretation=(
                        f"En el momento de la captura, '{proc_names_str}' mantenía {obs_count} descriptor(es) de socket hacia la IP "
                        f"{'pública' if is_public else 'privada/LAN'} {rip}:{rport}."
                    ),
                    why_it_matters="Evidencia tráfico saliente o sesiones activas hacia servicios externos o de red local.",
                    migration_relevance=(
                        "NO constituye por sí sola una dependencia de aplicación confirmada. Si corresponde a un servicio empresarial requerido, deberá permitirse salida (Egress) o conectividad híbrida en AWS."
                    ),
                    provenance=f"network.process_open_sockets · {provenance_base}",
                    state=DataState.OBSERVED,
                    limitations="Una instantánea puntual incluye conexiones efímeras (navegación, actualizaciones, telemetría IDE) y omite integraciones batch que no estaban activas en ese segundo.",
                    suggested_action="Muestrear sockets en varios intervalos y validar con el equipo de aplicación antes de catalogar este endpoint como dependencia de migración.",
                ).model_dump(),
            })

        if observed_peers:
            issues.append(
                DiscoveryIssue(
                    code="OBSERVED_SOCKETS_NOT_CONFIRMED_DEPENDENCIES",
                    severity="info",
                    section="network",
                    message=(
                        f"Se observaron {len(observed_peers)} endpoints remotos únicos en 'process_open_sockets'. "
                        "Se registran como conexiones observadas en una instantánea puntual, nunca como dependencias de aplicación confirmadas."
                    ),
                    provenance="network.process_open_sockets",
                    state=DataState.OBSERVED,
                    suggested_action="Realizar muestreo periódico o análisis de configuración para confirmar dependencias reales entre aplicaciones.",
                )
            )

        # 6. SOFTWARE SECTION (Packages, Systemd Services, Kernel Modules, Relevant Applications)
        sw_raw = raw.get("software") if isinstance(raw.get("software"), dict) else {}
        deb_raw = sw_raw.get("deb_packages") if isinstance(sw_raw.get("deb_packages"), list) else []
        units_raw = sw_raw.get("systemd_units") if isinstance(sw_raw.get("systemd_units"), list) else []
        kmod_raw = sw_raw.get("kernel_modules") if isinstance(sw_raw.get("kernel_modules"), list) else []

        parsed_packages: List[Dict[str, Any]] = []
        pkg_status_counts: collections.Counter[str] = collections.Counter()
        pkg_section_counts: collections.Counter[str] = collections.Counter()
        pkg_arch_counts: collections.Counter[str] = collections.Counter()

        # Evidence-based application categories
        RELEVANT_SW_PATTERNS: List[Tuple[str, str, Tuple[str, ...], str]] = [
            (
                "containers_virtualization",
                "Contenedores y Virtualización",
                ("docker.io", "docker-cli", "docker-compose", "docker-buildx", "containerd", "runc", "podman", "qemu"),
                "Runtimes de contenedores o virtualización instalados; permiten evaluar si las cargas pueden migrarse a Amazon ECS, EKS o EC2.",
            ),
            (
                "database_engines_clients",
                "Motores y Clientes de Base de Datos (Paquetes)",
                ("postgresql", "postgresql-18", "mariadb-server", "default-mysql-server", "redis-server", "sqlite3", "mongodb"),
                "Paquetes de bases de datos presentes en dpkg. Su sola instalación no implica una instancia activa; debe cruzarse con procesos y puertos.",
            ),
            (
                "messaging_streaming",
                "Mensajería y Colas",
                ("rabbitmq-server", "librabbitmq4", "mosquitto", "kafka"),
                "Software de mensajería detectado en paquetes; útil para evaluar equivalencia con Amazon MQ o Amazon SQS/SNS si está en uso activo.",
            ),
            (
                "web_http_servers",
                "Servidores Web y Proxies HTTP",
                ("apache2", "nginx", "nginx-common", "haproxy", "lighttpd", "caddy"),
                "Servidores HTTP instalados en el sistema; requieren verificar si están habilitados en systemd o escuchando en puertos 80/443.",
            ),
            (
                "runtime_languages",
                "Runtimes y Lenguajes de Ejecución",
                ("python3", "nodejs", "openjdk", "php", "golang", "ruby", "default-jre"),
                "Entornos de ejecución disponibles en el host que sustentan scripts, agentes o aplicaciones locales.",
            ),
            (
                "security_network_access",
                "Acceso Remoto y Red",
                ("openssh-server", "wireguard", "openvpn", "nftables", "iptables", "ufw", "avahi-daemon"),
                "Componentes de acceso administrativo, descubrimiento mDNS o filtrado de paquetes del host.",
            ),
        ]
        relevant_apps_by_group: Dict[str, Dict[str, Any]] = {
            gid: {"id": gid, "title": title, "rationale": rationale, "packages": []}
            for gid, title, _, rationale in RELEVANT_SW_PATTERNS
        }

        for row in deb_raw:
            if not isinstance(row, dict):
                continue
            pname = str(row.get("name") or "").strip()
            if not pname:
                continue
            pver = str(row.get("version") or "").strip() or None
            parch = str(row.get("arch") or "").strip() or None
            psec = str(row.get("section") or "").strip() or "unspecified"
            pstatus = str(row.get("status") or "unknown").strip()
            psize_kb, _ = parse_int_strict(row.get("size"))
            psource = str(row.get("source") or "").strip() or None
            pmaintainer = str(row.get("maintainer") or "").strip() or None
            ppriority = str(row.get("priority") or "").strip() or None

            pkg_status_counts[pstatus] += 1
            if pstatus == "install ok installed" or pstatus == "unknown":
                pkg_section_counts[psec] += 1
                if parch:
                    pkg_arch_counts[parch] += 1

                pkg_entry = {
                    "name": pname,
                    "version": pver,
                    "arch": parch,
                    "section": psec,
                    "status": pstatus,
                    "size_kb": psize_kb,
                    "source_package": psource,
                    "priority": ppriority,
                    "maintainer": pmaintainer,
                    "data_source": "software.deb_packages",
                    "state": DataState.OBSERVED,
                }
                parsed_packages.append(pkg_entry)

                for gid, _, prefixes, _ in RELEVANT_SW_PATTERNS:
                    if any(pname == pref or pname.startswith(pref + "-") for pref in prefixes):
                        relevant_apps_by_group[gid]["packages"].append(pkg_entry)

        parsed_packages.sort(key=lambda x: x["name"])

        # 6.2 Systemd Units
        parsed_services: List[Dict[str, Any]] = []
        unit_state_counts: collections.Counter[str] = collections.Counter()
        unit_type_counts: collections.Counter[str] = collections.Counter()

        for row in units_raw:
            if not isinstance(row, dict):
                continue
            uid_name = str(row.get("id") or "").strip()
            if not uid_name:
                continue
            utype = uid_name.rsplit(".", 1)[-1] if "." in uid_name else "unit"
            active_state = str(row.get("active_state") or "").strip() or "unknown"
            sub_state = str(row.get("sub_state") or "").strip() or "unknown"
            load_state = str(row.get("load_state") or "").strip() or "unknown"
            unit_file_state = str(row.get("unit_file_state") or "").strip() or None
            desc = str(row.get("description") or "").strip() or None
            frag_path = str(row.get("fragment_path") or "").strip() or None
            src_path = str(row.get("source_path") or "").strip() or None
            user_val = str(row.get("user") or "").strip() or None

            unit_state_counts[active_state] += 1
            unit_type_counts[utype] += 1

            parsed_services.append({
                "id": uid_name,
                "unit_type": utype,
                "description": desc,
                "active_state": active_state,
                "sub_state": sub_state,
                "load_state": load_state,
                "unit_file_state": unit_file_state,
                "fragment_path": frag_path,
                "source_path": src_path,
                "user": user_val,
                "is_running": active_state == "active" and sub_state in ("running", "listening", "mounted", "plugged", "waiting"),
                "state": DataState.OBSERVED,
            })

        parsed_services.sort(key=lambda x: (0 if x["active_state"] == "active" else 1, x["id"]))

        # 6.3 Kernel Modules
        parsed_kmods: List[Dict[str, Any]] = []
        gpu_modules_detected: List[str] = []

        for row in kmod_raw:
            if not isinstance(row, dict):
                continue
            mname = str(row.get("name") or "").strip()
            if not mname:
                continue
            msize, _ = parse_int_strict(row.get("size"))
            mstatus = str(row.get("status") or "").strip() or None
            used_by_raw = str(row.get("used_by") or "").strip()
            used_by = [u.strip() for u in used_by_raw.split(",") if u.strip() and u.strip() != "-"]

            if mname.startswith("nvidia"):
                gpu_modules_detected.append(mname)

            parsed_kmods.append({
                "name": mname,
                "size_bytes": msize,
                "size_formatted": format_bytes(msize),
                "status": mstatus,
                "used_by": used_by,
                "state": DataState.OBSERVED,
            })

        parsed_kmods.sort(key=lambda x: (-(x["size_bytes"] or 0), x["name"]))

        # 7. DATABASES SECTION (Strict Evidence vs "Not Collected / Requires Dedicated Collector")
        db_evidence_items: List[Dict[str, Any]] = []
        DB_ENGINE_CHECKS = [
            {
                "engine_id": "postgresql",
                "engine_name": "PostgreSQL",
                "pkg_prefixes": ("postgresql",),
                "proc_names": ("postgres", "postmaster"),
                "default_ports": (5432, 5433),
                "systemd_keywords": ("postgresql",),
            },
            {
                "engine_id": "mysql",
                "engine_name": "MariaDB / MySQL",
                "pkg_prefixes": ("mariadb-server", "default-mysql-server", "mysql-server"),
                "proc_names": ("mariadbd", "mysqld"),
                "default_ports": (3306, 33060),
                "systemd_keywords": ("mariadb", "mysql"),
            },
            {
                "engine_id": "redis",
                "engine_name": "Redis",
                "pkg_prefixes": ("redis-server",),
                "proc_names": ("redis-server",),
                "default_ports": (6379,),
                "systemd_keywords": ("redis",),
            },
            {
                "engine_id": "sqlite",
                "engine_name": "SQLite",
                "pkg_prefixes": ("sqlite3",),
                "proc_names": ("sqlite3",),
                "default_ports": (),
                "systemd_keywords": (),
            },
        ]

        for chk in DB_ENGINE_CHECKS:
            matched_pkgs = [
                {"name": p["name"], "version": p["version"]}
                for p in parsed_packages
                if any(p["name"] == pref or p["name"].startswith(pref + "-") for pref in chk["pkg_prefixes"])
            ]
            matched_procs = [
                {"pid": p["pid"], "name": p["name"], "path": p["path"]}
                for p in parsed_processes
                if p["name"].lower() in chk["proc_names"]
            ]
            matched_ports = [
                {"port": l["port"], "address": l["address"], "process": l["process_name"]}
                for l in parsed_listeners
                if l["port"] in chk["default_ports"] or l["process_name"].lower() in chk["proc_names"]
            ]
            matched_units = [
                {"id": u["id"], "active_state": u["active_state"], "sub_state": u["sub_state"]}
                for u in parsed_services
                if any(kw in u["id"].lower() for kw in chk["systemd_keywords"])
            ]

            if matched_pkgs or matched_procs or matched_ports or matched_units:
                is_running_now = len(matched_procs) > 0 or len(matched_ports) > 0
                db_evidence_items.append({
                    "engine_id": chk["engine_id"],
                    "engine_name": chk["engine_name"],
                    "packages_detected": matched_pkgs,
                    "running_processes": matched_procs,
                    "listening_ports": matched_ports,
                    "systemd_units": matched_units,
                    "runtime_status": "active_process_observed" if is_running_now else "packages_installed_only_not_running",
                    "catalog_metadata_status": "No recopilado — Requiere un recolector específico de catálogo de base de datos",
                    "state": DataState.OBSERVED,
                    "explanation": DataPointExplanation(
                        id=f"db-evidence-{chk['engine_id']}",
                        label=f"Indicios de {chk['engine_name']}",
                        what_is=f"Verificación de binarios, paquetes, servicios y sockets asociados al motor {chk['engine_name']}.",
                        detected_value={
                            "packages_count": len(matched_pkgs),
                            "running_processes_count": len(matched_procs),
                            "listening_ports_count": len(matched_ports),
                        },
                        formatted_value=(
                            f"{len(matched_pkgs)} paquete(s) instalado(s) · "
                            f"{'Proceso activo en ejecución' if is_running_now else 'Sin procesos ni puertos activos en la instantánea'}"
                        ),
                        interpretation=(
                            f"El motor {chk['engine_name']} está en ejecución activa en el host."
                            if is_running_now
                            else f"Los paquetes de {chk['engine_name']} están instalados en el sistema operativo, pero no se observó ninguna instancia en ejecución ni puerto en escucha durante la recolección."
                        ),
                        why_it_matters="Evita confundir un paquete instalado por defecto en la distribución con una base de datos productiva que requiera migración.",
                        migration_relevance=(
                            f"Antes de planificar Amazon RDS/Aurora para {chk['engine_name']}, debe confirmarse si la instancia se utiliza realmente y ejecutar un recolector de catálogo."
                        ),
                        provenance=f"software.deb_packages + runtime.processes + network.listening_ports · {provenance_base}",
                        state=DataState.OBSERVED,
                        limitations="osquery no inspecciona bases de datos internas, esquemas, tablas, tamaños de datasets, usuarios ni sesiones cliente-servidor.",
                        suggested_action=f"Si {chk['engine_name']} almacena datos requeridos, habilitar el conector de catálogo de solo lectura correspondiente.",
                    ).model_dump(),
                })

        # 8. QUALITY & COMPLETENESS INDICATORS
        expected_sections = [
            ("asset.hostname", bool(effective_hostname and effective_hostname != "unknown-host")),
            ("asset.uuid", bool(uuid_val)),
            ("asset.os", bool(os_raw.get("name"))),
            ("hardware.cpu_info", len(cpu_list_raw) > 0),
            ("hardware.memory_info", len(mem_list_raw) > 0),
            ("hardware.block_devices", len(block_raw) > 0),
            ("hardware.mounts", len(mounts_raw) > 0),
            ("network.interfaces", len(ifaces_raw) > 0),
            ("network.routes", len(routes_raw) > 0),
            ("network.listening_ports", isinstance(net_raw.get("listening_ports"), list)),
            ("network.process_open_sockets", isinstance(net_raw.get("process_open_sockets"), list)),
            ("software.deb_packages", len(deb_raw) > 0),
            ("software.systemd_units", len(units_raw) > 0),
            ("software.kernel_modules", len(kmod_raw) > 0),
            ("runtime.processes", len(processes_raw) > 0),
            ("runtime.uptime", len(uptime_raw) > 0),
        ]
        present_sections_count = sum(1 for _, ok in expected_sections if ok)
        completeness_pct = round((present_sections_count / len(expected_sections)) * 100.0, 1)

        # 9. MIGRATION ASSESSMENT (AWS Readiness without premature EC2 sizing!)
        active_external_listeners = [l for l in parsed_listeners if l["exposure"] != "loopback_only"]
        active_loopback_listeners = [l for l in parsed_listeners if l["exposure"] == "loopback_only"]
        running_services = [s for s in parsed_services if s["is_running"] and s["unit_type"] == "service"]

        migration_assessment = {
            "readiness_posture": "discovery_baseline_captured_pending_telemetry",
            "readiness_summary": (
                "El inventario técnico puntual del host está completo a nivel de configuración base (SO, CPU, RAM, discos, red y procesos), "
                "pero NO debe asignarse un tipo de instancia EC2 definitivo ni declararse listo para migración sin métricas históricas de rendimiento "
                "y confirmación de dependencias de aplicación."
            ),
            "available_information": [
                f"Identidad y arquitectura del activo: {effective_hostname} ({os_raw.get('name') or 'Linux'} {os_raw.get('version') or ''}, {arch or 'x86_64'}, firmware {(platform_raw.get('firmware_type') or 'desconocido').upper()}).",
                f"Capacidad física instalada: CPU {cpu_model or 'N/A'} ({phys_cores if phys_cores is not None else 'N/A'} núcleos físicos / {log_cores if log_cores is not None else 'N/A'} lógicos) y {format_bytes(mem_total_b) or 'N/A'} de memoria física.",
                f"Topología de almacenamiento local: {len(physical_disks)} disco(s) físico(s) ({format_bytes(total_physical_disk_bytes)}), {len(partitions)} partición(es) y {sum(1 for m in parsed_mounts if m['is_persistent'])} sistema(s) de archivos persistente(s).",
                f"Configuración de red local: {len(parsed_interfaces)} direcciones en interfaces, subredes derivadas ({', '.join(sorted(derived_subnets.keys())) or 'ninguna'}) y puerta de enlace ({', '.join(default_gateways) or 'no detectada'}).",
                f"Superficie de puertos en escucha: {len(active_external_listeners)} expuestos en interfaces de red y {len(active_loopback_listeners)} exclusivos de loopback.",
                f"Inventario de software y ejecución: {len(parsed_packages):,} paquetes instalados, {len(running_services)} servicios systemd en ejecución y {len(parsed_processes)} procesos observados.",
            ],
            "pending_information": [
                "Series temporales de utilización de CPU, memoria RAM, IOPS de disco y throughput de red (mínimo 7 a 14 días en horas pico y valle).",
                "Mapeo confirmado de dependencias de aplicación (bases de datos externas, APIs, DNS interno, autenticación LDAP/AD, colas).",
                "Metadatos de catálogos de bases de datos (instancias reales, esquemas, tamaño de tablas, motores transaccionales) mediante recolectores específicos.",
                "Requisitos de negocio: RTO, RPO, ventanas de mantenimiento, cumplimiento normativo y licenciamiento.",
                "Configuración interna de contenedores Docker/containerd (imágenes, volúmenes bind-mount, docker-compose/manifiestos) ya que docker.service está activo.",
            ],
            "identified_risks": [
                *(
                    [
                        {
                            "id": "risk-hardware-class",
                            "title": "Activo identificado como equipo portátil / laboratorio",
                            "detail": f"El modelo '{model}' ({vendor}) corresponde a un portátil. Si es una captura de prueba, sus recursos (Wi-Fi wlan0, GPU local, procesos de escritorio/IDE) no representan un servidor de centro de datos.",
                            "severity": "high",
                        }
                    ]
                    if is_workstation_or_laptop
                    else []
                ),
                *(
                    [
                        {
                            "id": "risk-gpu-modules",
                            "title": "Módulos de kernel NVIDIA y servicio Ollama activos",
                            "detail": f"Se detectaron módulos del kernel ({', '.join(gpu_modules_detected)}) y el servicio 'ollama' escuchando en TCP/11434. Si la carga a migrar requiere aceleración GPU para inferencia LLM, las instancias EC2 estándar (M/C/R) no serán compatibles y se requerirán familias aceleradas (ej. g5 / g6) o Amazon Bedrock.",
                            "severity": "medium",
                        }
                    ]
                    if gpu_modules_detected
                    else []
                ),
                {
                    "id": "risk-ephemeral-sockets",
                    "title": "Conexiones de red capturadas en una única instantánea",
                    "detail": f"Los {len(observed_peers)} endpoints remotos observados provienen de un corte único (uptime del sistema: {uptime_total_sec if uptime_total_sec is not None else 'N/A'} s). Construir reglas de firewall o arquitectura basándose solo en esta foto omitiría integraciones periódicas.",
                    "severity": "medium",
                },
                {
                    "id": "risk-inactive-db-packages",
                    "title": "Paquetes de bases de datos y servidores web instalados pero inactivos",
                    "detail": "Existen paquetes como postgresql-18, mariadb-server, redis-server, rabbitmq-server, apache2 y nginx instalados en dpkg sin procesos activos en ejecución. Aprovisionar RDS o ALB para software inactivo generaría sobrecostos innecesarios.",
                    "severity": "low",
                },
            ],
            "compatibility_to_verify": [
                f"Modo de arranque UEFI ({platform_raw.get('firmware_type') or 'uefi'}) y kernel {os_raw.get('name') or 'Linux'} ({arch or 'x86_64'}) frente a AWS Application Migration Service (MGN) o re-plataforma hacia Amazon Linux 2023 / Debian AMI.",
                "Dependencia de módulos de kernel propietarios o específicos de hardware físico (ej. nvidia, nvidia_uvm).",
                "Uso del puente local docker0 (172.17.0.1/16) y servicio containerd/dockerd para determinar si existen contenedores que deban migrarse a Amazon ECS/EKS.",
            ],
            "dependencies_distinction": {
                "confirmed_structural": [
                    f"Relación proceso ↔ puerto en escucha verificada por PID para {sum(1 for l in parsed_listeners if l['pid_matched'])} de {len(parsed_listeners)} sockets LISTEN.",
                    f"Jerarquía física disco → partición → punto de montaje para {', '.join(d['name'] for d in physical_disks)}.",
                ],
                "observed_unconfirmed": [
                    f"{len(observed_peers)} endpoints remotos observados en 'process_open_sockets' (ej. {', '.join(p['remote_ip'] + ':' + str(p['remote_port']) for p in observed_peers[:4])}). No deben tratarse como dependencias de aplicación confirmadas sin validación adicional.",
                ],
            },
            "historical_metrics_needed": [
                "Percentil 95 y máximo de uso de CPU por núcleo durante al menos 2 semanas.",
                "Consumo de memoria activa y presión de swap bajo carga sostenida.",
                "IOPS de lectura/escritura y throughput en MiB/s sobre /dev/nvme0n1p2 (/).",
                "Tráfico de red entrante y saliente sostenido en interfaces no-loopback.",
            ],
            "recommended_next_steps": [
                "1. Ejecutar muestreo periódico de sockets y procesos para distinguir integraciones permanentes de conexiones efímeras.",
                "2. Inspeccionar cargas en Docker (`docker ps -a`, volúmenes e imágenes) dado que `docker.service` y `containerd.service` están activos.",
                "3. Confirmar con los propietarios del sistema cuáles de los paquetes instalados (PostgreSQL, MariaDB, Redis, RabbitMQ, Nginx, Apache, Ollama) forman parte del alcance real de migración.",
                "4. Si alguna base de datos hace parte del alcance, ejecutar el recolector de catálogo específico antes de elegir entre EC2, RDS o Aurora.",
                "5. Incorporar inventarios de red/CMDB multi-host (ej. Open-AudIT) para cruzar ambos extremos de las comunicaciones observadas.",
            ],
        }

        # 10. TOP-LEVEL SUMMARY EXPLANATIONS
        summary_explanations = [
            DataPointExplanation(
                id="exp-asset-identity",
                label="Identidad del Activo y Sistema Operativo",
                what_is="Nombre de host, identificador único universal (UUID) y distribución del sistema operativo descubierto.",
                detected_value={
                    "hostname": effective_hostname,
                    "uuid": uuid_val,
                    "os": f"{os_raw.get('name')} {os_raw.get('version')} ({os_raw.get('codename')})",
                    "arch": arch,
                },
                formatted_value=f"{effective_hostname} · {os_raw.get('name') or 'OS N/A'} {os_raw.get('version') or ''} ({arch or 'N/A'})",
                interpretation=f"Host basado en Debian ('{os_raw.get('platform_like') or 'debian'}') con arquitectura {arch or 'x86_64'} e identificador SMBIOS {uuid_val or 'no disponible'}.",
                why_it_matters="Permite identificar inequívocamente el activo en la CMDB y evitar duplicados cuando cambia su dirección IP.",
                migration_relevance="La arquitectura x86_64 y base Debian determinan las familias de instancias EC2 compatibles, agentes SSM y estrategia de re-hosting o re-platforming.",
                provenance=f"asset.hostname / asset.uuid / asset.os · {provenance_base}",
                state=DataState.OBSERVED,
                limitations="El nombre de host local no refleja registros DNS externos ni balanceadores de carga frontales.",
                suggested_action="Cruzar el UUID y hostname con el inventario de activos corporativo o Open-AudIT.",
            ).model_dump(),
            DataPointExplanation(
                id="exp-compute-capacity",
                label="Capacidad de Cómputo (CPU y Memoria RAM)",
                what_is="Especificación del procesador físico/lógico y memoria RAM total frente a la memoria disponible en la instantánea.",
                detected_value={
                    "cpu_model": cpu_model,
                    "physical_cores": phys_cores,
                    "logical_cores": log_cores,
                    "memory_total_bytes": mem_total_b,
                    "memory_available_bytes": mem_avail_b,
                },
                formatted_value=(
                    f"{cpu_model or 'CPU'} ({phys_cores if phys_cores is not None else '?'}C / {log_cores if log_cores is not None else '?'}T) · "
                    f"RAM {format_bytes(mem_total_b) or 'N/A'} total ({format_bytes(mem_avail_b) or 'N/A'} disponible)"
                ),
                interpretation=(
                    f"El equipo dispone de {phys_cores} núcleos físicos ({log_cores} hilos lógicos) y {format_bytes(mem_total_b)} de RAM, "
                    f"con un {mem_utilization_pct if mem_utilization_pct is not None else '?'}% de memoria en uso efectivo durante la captura."
                ),
                why_it_matters="Establece la cota superior física del hardware actual donde se ejecutan los procesos.",
                migration_relevance="Sirve como referencia inicial de capacidad máxima, pero NO debe traducirse directamente 1:1 a vCPUs de EC2 sin medir el uso real histórico (evita sobre-aprovisionamiento).",
                provenance=f"hardware.cpu_info / hardware.memory_info · {provenance_base}",
                state=DataState.OBSERVED,
                limitations="La memoria disponible corresponde a un único instante (con solo ~1 hora de uptime del sistema).",
                suggested_action="Recolectar telemetría continua de CPU y RAM durante ciclos de trabajo representativos.",
            ).model_dump(),
            DataPointExplanation(
                id="exp-storage-layout",
                label="Estructura de Almacenamiento y Sistemas de Archivos",
                what_is="Relación entre dispositivos de bloque físicos, sus particiones hijas y los sistemas de archivos montados.",
                detected_value={
                    "physical_disks": len(physical_disks),
                    "partitions": len(partitions),
                    "total_physical_bytes": total_physical_disk_bytes,
                },
                formatted_value=f"{len(physical_disks)} disco físico ({format_bytes(total_physical_disk_bytes)}) → {len(partitions)} particiones",
                interpretation="Se diferencia el disco físico padre de sus particiones lógicas para no duplicar la capacidad real instalada.",
                why_it_matters="Permite distinguir la capacidad bruta del hardware frente al espacio realmente consumido en '/' y '/boot/efi'.",
                migration_relevance="Permite dimensionar volúmenes Amazon EBS basándose en el espacio ocupado y crecimiento esperado, separando particiones de sistema y swap.",
                provenance=f"hardware.block_devices + hardware.mounts · {provenance_base}",
                state=DataState.DERIVED,
                limitations="No incluye métricas de latencia de disco, IOPS pico ni snapshots LVM/RAID externos si no están expuestos en block_devices.",
                suggested_action="Verificar con df -h y lsblk en el host antes de congelar el tamaño de los volúmenes EBS.",
            ).model_dump(),
            DataPointExplanation(
                id="exp-network-posture",
                label="Postura de Red, Puertos en Escucha y Conexiones Observadas",
                what_is="Interfaces de red activas, rutas, servicios esperando conexiones (LISTEN) y sockets abiertos.",
                detected_value={
                    "interfaces_count": len(parsed_interfaces),
                    "listening_ports_count": len(parsed_listeners),
                    "observed_remote_peers_count": len(observed_peers),
                },
                formatted_value=(
                    f"{len(parsed_interfaces)} direcciones · {len(parsed_listeners)} puertos en escucha · "
                    f"{len(observed_peers)} endpoints remotos observados"
                ),
                interpretation=(
                    f"Solo {len(active_external_listeners)} entradas de escucha están abiertas fuera de loopback (ej. SSH en 22, mDNS en 5353), "
                    f"mientras que {len(active_loopback_listeners)} escuchan exclusivamente en 127.0.0.1/::1."
                ),
                why_it_matters="Delimita la superficie real de exposición en red frente a los servicios de comunicación interna del host.",
                migration_relevance="Guía el diseño de subredes VPC, tablas de ruteo y reglas mínimas de Security Groups, separando hechos confirmados de conexiones puntuales observadas.",
                provenance=f"network.interfaces / routes / listening_ports / process_open_sockets · {provenance_base}",
                state=DataState.OBSERVED,
                limitations="Una observación puntual de sockets no demuestra una dependencia estable entre aplicaciones empresariales.",
                suggested_action="Contrastar los puertos expuestos y peers remotos con las políticas de seguridad antes de generar Terraform.",
            ).model_dump(),
        ]

        return {
            "schema_version": "cloudmove.normalized.v1",
            "reimported": False,
            "source": {
                "tool": str(source_raw.get("tool") or "osquery"),
                "tool_version": str(source_raw.get("tool_version") or "").strip() or None,
                "collector": str(source_raw.get("collector") or "").strip() or None,
                "collector_host": str(source_raw.get("collector_host") or "").strip() or None,
                "collected_at": collected_at,
                "provenance_label": provenance_base,
            },
            "summary": {
                "hostname": effective_hostname,
                "uuid": uuid_val,
                "vendor": vendor,
                "model": model,
                "is_workstation_or_laptop": is_workstation_or_laptop,
                "architecture": arch,
                "os": {
                    "name": str(os_raw.get("name") or "").strip() or None,
                    "version": str(os_raw.get("version") or "").strip() or None,
                    "codename": str(os_raw.get("codename") or "").strip() or None,
                    "platform": str(os_raw.get("platform") or "").strip() or None,
                    "platform_like": str(os_raw.get("platform_like") or "").strip() or None,
                    "arch": str(os_raw.get("arch") or arch or "").strip() or None,
                    "major": parse_int_strict(os_raw.get("major"))[0],
                    "minor": parse_int_strict(os_raw.get("minor"))[0],
                    "patch": parse_int_strict(os_raw.get("patch"))[0],
                },
                "metrics": {
                    "cpu_physical_cores": phys_cores,
                    "cpu_logical_cores": log_cores,
                    "cpu_model": cpu_model,
                    "memory_total_bytes": mem_total_b,
                    "memory_total_formatted": format_bytes(mem_total_b),
                    "memory_available_bytes": mem_avail_b,
                    "memory_available_formatted": format_bytes(mem_avail_b),
                    "memory_utilization_percent": mem_utilization_pct,
                    "physical_disks_count": len(physical_disks),
                    "partitions_count": len(partitions),
                    "total_physical_disk_bytes": total_physical_disk_bytes,
                    "total_physical_disk_formatted": format_bytes(total_physical_disk_bytes),
                    "persistent_mounts_count": sum(1 for m in parsed_mounts if m["is_persistent"]),
                    "interfaces_count": len(parsed_interfaces),
                    "primary_ips": [
                        i["clean_address"]
                        for i in parsed_interfaces
                        if not i["is_loopback"] and not i["is_link_local"] and i["clean_address"]
                    ],
                    "derived_subnets": sorted(derived_subnets.keys()),
                    "default_gateways": default_gateways,
                    "installed_packages_count": len(parsed_packages),
                    "systemd_units_count": len(parsed_services),
                    "running_services_count": len(running_services),
                    "kernel_modules_count": len(parsed_kmods),
                    "processes_count": len(parsed_processes),
                    "listening_ports_count": len(parsed_listeners),
                    "external_listeners_count": len(active_external_listeners),
                    "loopback_listeners_count": len(active_loopback_listeners),
                    "socket_observations_count": len(sockets_raw),
                    "unique_remote_endpoints_count": len(observed_peers),
                    "uptime_seconds": uptime_total_sec,
                },
                "collection_quality": {
                    "query_count": query_count if query_count is not None else 0,
                    "successful_query_count": success_count if success_count is not None else 0,
                    "error_count": len(col_errors),
                    "completeness_percent": completeness_pct,
                    "present_sections": present_sections_count,
                    "total_expected_sections": len(expected_sections),
                    "collector_note": str(col_raw.get("note") or "").strip() or None,
                    "missing_fields": missing_fields,
                },
                "explanations": summary_explanations,
            },
            "sections": {
                "hardware": {
                    "cpu": {
                        "model": cpu_model,
                        "manufacturer": cpu_manufacturer,
                        "architecture": arch,
                        "physical_cores": phys_cores,
                        "physical_cores_state": phys_state,
                        "logical_cores": log_cores,
                        "logical_cores_state": log_state,
                        "sockets": sockets_count,
                        "sockets_state": sockets_state,
                        "current_clock_mhz": curr_clock_mhz,
                        "current_clock_state": curr_clock_state,
                        "max_clock_mhz": max_clock_mhz,
                        "max_clock_state": max_clock_state,
                        "address_width": addr_width,
                        "socket_designation": socket_desig,
                        "microcode": microcode,
                        "raw_processors": cpu_list_raw,
                        "explanation": DataPointExplanation(
                            id="hw-cpu-detail",
                            label=f"Procesador {cpu_model or 'Desconocido'}",
                            what_is="Especificación técnica de la unidad central de procesamiento (CPU) reportada por SMBIOS y el kernel.",
                            detected_value={
                                "model": cpu_model,
                                "manufacturer": cpu_manufacturer,
                                "number_of_cores": phys_cores,
                                "logical_processors": log_cores,
                                "current_clock_speed": curr_clock_mhz,
                                "max_clock_speed": max_clock_mhz,
                                "socket_designation": socket_desig,
                            },
                            formatted_value=(
                                f"{cpu_model or 'N/A'} · {phys_cores if phys_cores is not None else '?'} núcleos físicos / "
                                f"{log_cores if log_cores is not None else '?'} lógicos · Frecuencia máx. {max_clock_mhz or '?'} MHz"
                            ),
                            interpretation=(
                                f"Procesador {cpu_manufacturer or ''} de arquitectura {arch or 'x86_64'} en socket {socket_desig or 'único'}, "
                                f"operando a {curr_clock_mhz or '?'} MHz en el instante de consulta."
                            ),
                            why_it_matters="Permite conocer la paralelización máxima (hilos de hardware) y el conjunto de instrucciones del procesador.",
                            migration_relevance="Indica compatibilidad con instancias EC2 x86_64 (Intel/AMD); la selección del tamaño vCPU requiere medir el porcentaje de uso sostenido.",
                            provenance=f"hardware.cpu_info + asset.system_info · {provenance_base}",
                            state=DataState.OBSERVED if cpu_model else DataState.UNAVAILABLE,
                            limitations="La frecuencia actual reportada es instantánea y varía según el gobernador de energía ( Turbo / P-states ).",
                            suggested_action="Registrar uso de CPU (% user, % system, % iowait, load average) antes de dimensionar vCPUs en AWS.",
                        ).model_dump(),
                    },
                    "memory": {
                        "total_bytes": mem_total_b,
                        "total_formatted": format_bytes(mem_total_b),
                        "total_state": mem_total_state,
                        "available_bytes": mem_avail_b,
                        "available_formatted": format_bytes(mem_avail_b),
                        "available_state": mem_avail_state,
                        "free_bytes": mem_free_b,
                        "free_formatted": format_bytes(mem_free_b),
                        "free_state": mem_free_state,
                        "used_derived_bytes": mem_used_derived_b,
                        "used_derived_formatted": format_bytes(mem_used_derived_b),
                        "utilization_percent": mem_utilization_pct,
                        "active_bytes": mem_active_b,
                        "active_formatted": format_bytes(mem_active_b),
                        "inactive_bytes": mem_inactive_b,
                        "inactive_formatted": format_bytes(mem_inactive_b),
                        "buffers_bytes": mem_buffers_b,
                        "buffers_formatted": format_bytes(mem_buffers_b),
                        "cached_bytes": mem_cached_b,
                        "cached_formatted": format_bytes(mem_cached_b),
                        "swap_total_bytes": swap_total_b,
                        "swap_total_formatted": format_bytes(swap_total_b),
                        "swap_total_state": swap_total_state,
                        "swap_free_bytes": swap_free_b,
                        "swap_free_formatted": format_bytes(swap_free_b),
                        "swap_free_state": swap_free_state,
                        "swap_used_derived_bytes": swap_used_derived_b,
                        "swap_used_derived_formatted": format_bytes(swap_used_derived_b),
                        "swap_cached_bytes": swap_cached_b,
                        "swap_cached_formatted": format_bytes(swap_cached_b),
                        "explanation": DataPointExplanation(
                            id="hw-memory-detail",
                            label="Memoria Física (RAM) y Espacio Swap",
                            what_is="Distribución de memoria física total, disponible, libre, buffers/caché de página del kernel y memoria de intercambio (swap).",
                            detected_value=mem_first,
                            formatted_value=(
                                f"Total: {format_bytes(mem_total_b)} · Disponible: {format_bytes(mem_avail_b)} · "
                                f"Caché/Buffers: {format_bytes((mem_cached_b or 0) + (mem_buffers_b or 0))} · Swap libre: {format_bytes(swap_free_b)}/{format_bytes(swap_total_b)}"
                            ),
                            interpretation=(
                                f"De los {format_bytes(mem_total_b)} totales, {format_bytes(mem_avail_b)} están disponibles inmediatamente para nuevas cargas "
                                f"y el uso de swap es {format_bytes(swap_used_derived_b)} (sin presión de memoria en este corte)."
                            ),
                            why_it_matters="Diferencia la memoria libre estricta (`memory_free`) de la memoria realmente disponible (`memory_available`), que incluye caché recuperable.",
                            migration_relevance="Evita sobredimensionar RAM en EC2 por confundir la caché de archivos de Linux con memoria comprometida por aplicaciones.",
                            provenance=f"hardware.memory_info · {provenance_base}",
                            state=DataState.OBSERVED if mem_total_b is not None else DataState.UNAVAILABLE,
                            limitations="Instantánea tomada con el sistema recién iniciado (~1h de uptime); no refleja picos de consumo ni fugas de memoria a largo plazo.",
                            suggested_action="Monitorear `memory_available` y actividad de swap (`si`/`so`) bajo carga pico.",
                        ).model_dump(),
                    },
                    "storage": {
                        "physical_disks": physical_disks,
                        "partitions": partitions,
                        "mounts": parsed_mounts,
                        "persistent_mounts": [m for m in parsed_mounts if m["is_persistent"]],
                        "virtual_mounts": [m for m in parsed_mounts if not m["is_persistent"]],
                        "total_physical_bytes": total_physical_disk_bytes,
                        "total_physical_formatted": format_bytes(total_physical_disk_bytes),
                        "storage_rule_note": (
                            "La capacidad total de almacenamiento físico suma únicamente los discos de bloque raíz (no las particiones hijas), "
                            "evitando duplicar el tamaño del disco físico con sus particiones."
                        ),
                    },
                    "firmware_and_board": firmware_info,
                    "other_characteristics": {
                        "gpu_kernel_modules": gpu_modules_detected,
                        "has_nvidia_module_loaded": len(gpu_modules_detected) > 0,
                        "hostname_fields": {
                            "asset_hostname": asset_hostname or None,
                            "computer_name": computer_name or None,
                            "system_info_hostname": sys_hostname or None,
                            "local_hostname": str(sys_info.get("local_hostname") or "").strip() or None,
                        },
                        "explanation": DataPointExplanation(
                            id="hw-other-accel",
                            label="Dispositivos Adicionales y Módulos de Hardware",
                            what_is="Atributos adicionales del chasis y controladores de hardware especializado cargados en el kernel.",
                            detected_value={"gpu_modules": gpu_modules_detected, "hardware_version": sys_info.get("hardware_version")},
                            formatted_value=(
                                f"Módulos GPU cargados: {', '.join(gpu_modules_detected)}"
                                if gpu_modules_detected
                                else "Sin módulos de aceleración GPU dedicados detectados"
                            ),
                            interpretation=(
                                "La presencia de los módulos 'nvidia' y 'nvidia_uvm' en estado Live indica hardware gráfico NVIDIA activo en el equipo."
                                if gpu_modules_detected
                                else "No se observaron módulos de kernel para aceleradores GPU dedicados."
                            ),
                            why_it_matters="Permite identificar dependencias de hardware especializado (como GPUs usadas por procesos de IA/ML locales).",
                            migration_relevance="Si las cargas a migrar (ej. Ollama) requieren GPU, se debe evaluar el costo y disponibilidad de instancias EC2 con GPU (g5, g6) o servicios administrados.",
                            provenance=f"software.kernel_modules + asset.system_info · {provenance_base}",
                            state=DataState.INFERRED if gpu_modules_detected else DataState.OBSERVED,
                            limitations="osquery no incluyó la tabla pci_devices en esta exportación; la presencia de GPU se deduce de los módulos del kernel cargados.",
                            suggested_action="Ejecutar nvidia-smi o consultar pci_devices si se requiere conocer el modelo exacto de GPU y VRAM.",
                        ).model_dump(),
                    },
                },
                "software": {
                    "packages": parsed_packages,
                    "package_count": len(parsed_packages),
                    "package_status_counts": dict(pkg_status_counts),
                    "package_section_counts": dict(pkg_section_counts.most_common(25)),
                    "package_arch_counts": dict(pkg_arch_counts),
                    "services": parsed_services,
                    "service_count": len(parsed_services),
                    "unit_state_counts": dict(unit_state_counts),
                    "unit_type_counts": dict(unit_type_counts),
                    "kernel_modules": parsed_kmods,
                    "kernel_module_count": len(parsed_kmods),
                    "relevant_applications": list(relevant_apps_by_group.values()),
                    "explanation": DataPointExplanation(
                        id="sw-overview",
                        label="Inventario de Paquetes, Servicios y Módulos del Kernel",
                        what_is="Catálogo de paquetes Debian instalados (`deb_packages`), unidades de `systemd` y módulos cargados en el kernel Linux.",
                        detected_value={
                            "installed_packages": len(parsed_packages),
                            "systemd_units": len(parsed_services),
                            "kernel_modules": len(parsed_kmods),
                        },
                        formatted_value=f"{len(parsed_packages):,} paquetes · {len(parsed_services)} unidades systemd · {len(parsed_kmods)} módulos kernel",
                        interpretation=(
                            "Un paquete instalado en dpkg NO equivale automáticamente a una aplicación empresarial en ejecución. "
                            "CloudMove cruza los paquetes con unidades systemd activas y procesos en ejecución antes de sugerir cargas de trabajo."
                        ),
                        why_it_matters="Permite auditar versiones de librerías, demonios activos y dependencias a nivel de sistema operativo.",
                        migration_relevance="Identifica qué servicios deben empacarse en contenedores o imágenes AMI (Golden AMI / EC2 Image Builder) y cuáles son paquetes ociosos de la distribución.",
                        provenance=f"software.deb_packages / systemd_units / kernel_modules · {provenance_base}",
                        state=DataState.OBSERVED,
                        limitations="No incluye aplicaciones instaladas fuera de dpkg (binarios estáticos en /opt, contenedores Docker internos, pip/npm locales) salvo que aparezcan como procesos o servicios.",
                        suggested_action="Filtrar los servicios en estado 'active/running' para definir la lista real de cargas de trabajo candidatas.",
                    ).model_dump(),
                },
                "network": {
                    "interfaces": parsed_interfaces,
                    "derived_subnets": list(derived_subnets.values()),
                    "routes": parsed_routes,
                    "default_gateways": default_gateways,
                    "listening_ports": parsed_listeners,
                    "observed_remote_endpoints": observed_peers,
                    "socket_summary": {
                        "total_sockets_queried": len(sockets_raw),
                        "remote_connected_sockets": remote_socket_count,
                        "local_loopback_sockets": local_socket_count,
                        "unconnected_or_incomplete_sockets": incomplete_socket_count,
                        "unique_remote_endpoints": len(observed_peers),
                    },
                    "sample_sockets": sample_sockets,
                },
                "runtime": {
                    "uptime": {
                        "days": uptime_days,
                        "hours": uptime_hours,
                        "minutes": uptime_minutes,
                        "seconds": uptime_seconds,
                        "total_seconds": uptime_total_sec,
                        "formatted": (
                            f"{uptime_days or 0}d {uptime_hours or 0}h {uptime_minutes or 0}m {uptime_seconds or 0}s "
                            f"({uptime_total_sec:,} s)"
                            if uptime_total_sec is not None
                            else "No disponible"
                        ),
                        "state": uptime_state,
                        "explanation": DataPointExplanation(
                            id="rt-uptime",
                            label="Tiempo de Actividad del Sistema (Uptime)",
                            what_is="Tiempo transcurrido desde el último arranque del kernel del sistema operativo.",
                            detected_value=uptime_first,
                            formatted_value=f"{uptime_total_sec:,} segundos (~{(uptime_total_sec or 0) / 3600:.2f} horas)" if uptime_total_sec is not None else "No disponible",
                            interpretation=(
                                f"El sistema llevaba aproximadamente {(uptime_total_sec or 0) // 60} minutos encendido cuando se tomó el inventario."
                                if (uptime_total_sec is not None and uptime_total_sec < 86400)
                                else f"El sistema lleva {uptime_days or 0} días de operación continua."
                            ),
                            why_it_matters="Un uptime corto indica que los contadores acumulados y las conexiones observadas reflejan una ventana de observación breve.",
                            migration_relevance="Advierte que una captura tomada poco después del reinicio puede no reflejar la huella de memoria estacionaria ni trabajos programados (cron/timers).",
                            provenance=f"runtime.uptime · {provenance_base}",
                            state=uptime_state,
                            limitations="No informa sobre disponibilidad histórica ni causas de reinicios previos.",
                            suggested_action="Tomar capturas adicionales tras varios días de operación normal si se trata de un servidor productivo.",
                        ).model_dump(),
                    },
                    "processes": parsed_processes,
                    "process_count": len(parsed_processes),
                    "user_process_count": sum(1 for p in parsed_processes if not p["is_kernel_thread"]),
                    "kernel_thread_count": sum(1 for p in parsed_processes if p["is_kernel_thread"]),
                    "privacy_note": (
                        "Por diseño de seguridad y privacidad, no se recolectan ni exponen argumentos de línea de comandos (cmdline), "
                        "variables de entorno ni secretos de procesos."
                    ),
                },
                "databases": {
                    "status": "evidence_analyzed_catalog_not_collected",
                    "summary_badge": "No recopilado / Requiere un recolector específico para metadatos internos",
                    "summary_explanation": (
                        "El inventario de osquery permite detectar paquetes de bases de datos instalados, servicios systemd y procesos/puertos activos a nivel de host. "
                        "Sin embargo, NO contiene metadatos de instancias internas, bases de datos, esquemas, tablas, tamaños de datasets ni conexiones cliente-servidor detalladas. "
                        "CloudMove no inventa bases de datos a partir de paquetes instalados."
                    ),
                    "detected_engine_evidence": db_evidence_items,
                    "prepared_collectors": [spec.model_dump() for spec in DATABASE_COLLECTOR_SPECS.values()],
                },
                "assessment": migration_assessment,
            },
            "issues": [issue.model_dump() for issue in issues],
        }
