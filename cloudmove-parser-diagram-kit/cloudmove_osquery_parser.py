#!/usr/bin/env python3
"""Parse an osquery CloudMove inventory JSON and create normalized data + diagrams.

Uses Python standard library only. If Graphviz `dot` is installed, renders SVG and PNG.
Otherwise leaves .dot and Mermaid source files ready for rendering elsewhere.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import ipaddress
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def as_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def gib(value: Any) -> float | None:
    n = as_int(value)
    return round(n / (1024 ** 3), 2) if n is not None else None


def fmt_size(n_bytes: int | None) -> str:
    if n_bytes is None:
        return "unknown"
    if n_bytes >= 1024 ** 3:
        return f"{n_bytes / (1024 ** 3):.1f} GiB"
    if n_bytes >= 1024 ** 2:
        return f"{n_bytes / (1024 ** 2):.1f} MiB"
    return f"{n_bytes / (1024 ** 1):.1f} KiB"


def esc_dot(text: Any) -> str:
    s = str(text)
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def esc_mermaid(text: Any) -> str:
    return str(text).replace('"', "'").replace("[", "(").replace("]", ")").replace("\n", "<br/>")


def map_protocol(value: Any) -> str:
    num = as_int(value, -1)
    return {6: "TCP", 17: "UDP", 1: "ICMP", 58: "ICMPv6"}.get(num, f"PROTO {num}")


def network_prefix(address: str, mask: str) -> tuple[str | None, str | None]:
    try:
        if ":" in address:
            iface = ipaddress.ip_interface(f"{address.split('%')[0]}/{mask}")
        else:
            iface = ipaddress.ip_interface(f"{address}/{mask}")
        return str(iface.network), str(iface)
    except (ValueError, TypeError):
        return None, None


def resolve_process(pid: Any, process_by_pid: dict[str, dict[str, Any]]) -> str:
    row = process_by_pid.get(str(pid), {})
    return str(row.get("name") or (f"PID {pid}" if pid else "unknown process"))


def parse_inventory(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("asset"), dict):
        raise ValueError("Input is not a supported CloudMove osquery inventory: missing asset object.")
    asset_raw = raw["asset"]
    hw_raw = raw.get("hardware") or {}
    net_raw = raw.get("network") or {}
    sw_raw = raw.get("software") or {}
    rt_raw = raw.get("runtime") or {}
    source = raw.get("source") or {}
    system = asset_raw.get("system_info") or {}
    os_raw = asset_raw.get("os") or {}

    cpu_rows = hw_raw.get("cpu_info") or []
    cpu = cpu_rows[0] if cpu_rows else {}
    mem_rows = hw_raw.get("memory_info") or []
    mem = mem_rows[0] if mem_rows else {}
    total_mem_bytes = as_int(mem.get("memory_total"), as_int(asset_raw.get("physical_memory_bytes")))
    available_mem_bytes = as_int(mem.get("memory_available"))

    processes = rt_raw.get("processes") or []
    process_by_pid = {str(p.get("pid")): p for p in processes if p.get("pid") is not None}

    # Normalize network interfaces and infer CIDRs only when the recorded mask is valid.
    interfaces = []
    local_ips: set[str] = set()
    inferred_subnets: set[str] = set()
    for row in net_raw.get("interfaces") or []:
        address = str(row.get("address") or "")
        mask = str(row.get("mask") or "")
        if not address:
            continue
        local_ips.add(address.split("%")[0])
        subnet, cidr_address = network_prefix(address, mask) if mask else (None, None)
        if subnet and not address.startswith("127.") and address != "::1" and not address.startswith("fe80:"):
            inferred_subnets.add(subnet)
        interfaces.append({
            "name": row.get("interface"),
            "address": address,
            "mask": mask or None,
            "cidr": cidr_address,
            "subnet": subnet,
            "type": row.get("type"),
        })

    routes = []
    gateways: list[str] = []
    for row in net_raw.get("routes") or []:
        destination = str(row.get("destination") or "")
        gateway = str(row.get("gateway") or "")
        if gateway and destination in ("0.0.0.0", "::", "default"):
            gateways.append(gateway)
        routes.append({
            "destination": destination,
            "netmask": row.get("netmask"),
            "gateway": gateway or None,
            "interface": row.get("interface"),
            "type": row.get("type"),
            "metric": as_int(row.get("metric")),
        })

    block_devices = []
    for row in hw_raw.get("block_devices") or []:
        raw_size = as_int(row.get("size"))
        block_size = as_int(row.get("block_size"))
        # osquery's block_devices.size is interpreted as number of sectors when block_size is present.
        size_bytes = raw_size * block_size if raw_size is not None and block_size else None
        block_devices.append({
            "name": row.get("name"),
            "parent": row.get("parent") or None,
            "model": row.get("model") or None,
            "type": row.get("type") or None,
            "raw_size": raw_size,
            "block_size": block_size,
            "size_bytes_estimate": size_bytes,
            "size_display_estimate": fmt_size(size_bytes) if size_bytes else None,
            "size_unit_note": "Estimated as raw size × block_size only where block_size was supplied; verify against OS disk tools.",
        })

    mounts = []
    for row in hw_raw.get("mounts") or []:
        block_count = as_int(row.get("blocks"))
        block_bytes = as_int(row.get("blocks_size"))
        available_count = as_int(row.get("blocks_available"))
        free_count = as_int(row.get("blocks_free"))
        total_bytes = block_count * block_bytes if block_count is not None and block_bytes else None
        available_bytes = available_count * block_bytes if available_count is not None and block_bytes else None
        used_bytes = max(total_bytes - (free_count or 0) * block_bytes, 0) if total_bytes is not None and block_bytes else None
        mounts.append({
            "device": row.get("device"),
            "path": row.get("path"),
            "filesystem": row.get("type"),
            "total_bytes_estimate": total_bytes,
            "available_bytes_estimate": available_bytes,
            "used_bytes_estimate": used_bytes,
            "total_display_estimate": fmt_size(total_bytes) if total_bytes else None,
            "available_display_estimate": fmt_size(available_bytes) if available_bytes else None,
            "used_display_estimate": fmt_size(used_bytes) if used_bytes is not None else None,
        })

    listeners = []
    listener_seen = set()
    for row in net_raw.get("listening_ports") or []:
        port = as_int(row.get("port"), 0) or 0
        address = str(row.get("address") or "")
        if port <= 0 or not address:
            continue
        pid = str(row.get("pid") or "")
        proto = map_protocol(row.get("protocol"))
        key = (address, port, proto, pid)
        if key in listener_seen:
            continue
        listener_seen.add(key)
        listeners.append({
            "address": address,
            "port": port,
            "protocol": proto,
            "pid": as_int(pid),
            "process": resolve_process(pid, process_by_pid),
            "exposure": "loopback_only" if address in ("127.0.0.1", "::1") else ("all_interfaces_or_unspecified" if address in ("0.0.0.0", "::") else "specific_address"),
        })
    listeners.sort(key=lambda x: (x["port"], x["address"], x["protocol"]))

    # Deduplicate observations into destination endpoint summaries. Mark these as observed snapshots, not confirmed dependencies.
    peer_counter: collections.Counter[tuple[str, int, str]] = collections.Counter()
    peer_processes: dict[tuple[str, int, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)
    peer_sources: dict[tuple[str, int, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for row in net_raw.get("process_open_sockets") or []:
        pid = as_int(row.get("pid"), -1)
        remote_port = as_int(row.get("remote_port"), 0) or 0
        remote = str(row.get("remote_address") or "").split("%")[0]
        if pid is None or pid <= 0 or remote_port <= 0 or not remote:
            continue
        try:
            ip_obj = ipaddress.ip_address(remote)
        except ValueError:
            continue
        if ip_obj.is_loopback or ip_obj.is_unspecified or ip_obj.is_link_local or remote in local_ips:
            continue
        proto = map_protocol(row.get("protocol"))
        key = (remote, remote_port, proto)
        peer_counter[key] += 1
        pname = resolve_process(pid, process_by_pid)
        peer_processes[key][pname] += 1
        local_ip = str(row.get("local_address") or "")
        if local_ip:
            peer_sources[key][local_ip] += 1

    peers = []
    for (ip, port, proto), observations in peer_counter.most_common():
        try:
            public = ipaddress.ip_address(ip).is_global
        except ValueError:
            public = False
        peers.append({
            "remote_ip": ip,
            "remote_port": port,
            "protocol": proto,
            "public_ip": public,
            "observation_count": observations,
            "processes": [
                {"name": name, "observations": count}
                for name, count in peer_processes[(ip, port, proto)].most_common()
            ],
            "local_addresses": [
                {"address": address, "observations": count}
                for address, count in peer_sources[(ip, port, proto)].most_common()
            ],
            "evidence_type": "observed_socket_snapshot",
            "dependency_confirmed": False,
        })

    packages = []
    package_counts = collections.Counter()
    for row in sw_raw.get("deb_packages") or sw_raw.get("debian_packages") or []:
        status = str(row.get("status") or "unknown")
        package_counts[status] += 1
        if status == "install ok installed":
            packages.append({
                "name": row.get("name"),
                "version": row.get("version"),
                "arch": row.get("arch"),
                "section": row.get("section"),
                "status": status,
            })
    packages.sort(key=lambda x: str(x.get("name") or ""))

    warnings = []
    sys_hostname = str(system.get("hostname") or "")
    computer_name = str(system.get("computer_name") or "")
    normalized_hostname = str(asset_raw.get("hostname") or computer_name or sys_hostname or platform.node())
    if sys_hostname and computer_name and sys_hostname != computer_name:
        warnings.append({
            "code": "HOSTNAME_FIELD_MISMATCH",
            "message": f"system_info.hostname={sys_hostname!r} differs from computer_name={computer_name!r}; CloudMove uses computer_name/asset.hostname={normalized_hostname!r}.",
        })
    if str(asset_raw.get("form_factor") or "").lower() == "laptop" or "ideapad" in str(asset_raw.get("hardware_model") or "").lower():
        warnings.append({
            "code": "NON_SERVER_TEST_ASSET",
            "message": "The current discovery source identifies this asset as a laptop. Treat it as a collector validation sample, not as a rack server workload.",
        })
    if len(peers):
        warnings.append({
            "code": "NETWORK_SNAPSHOT_NOT_DEPENDENCY_PROOF",
            "message": "Remote socket observations are a point-in-time snapshot. They do not by themselves prove an application dependency or capture every short-lived connection.",
        })
    if raw.get("collection", {}).get("errors"):
        warnings.append({
            "code": "COLLECTION_WARNINGS",
            "message": f"The source collector reported {len(raw['collection']['errors'])} query error(s). Review collection.errors in the original input.",
        })

    mem_total = total_mem_bytes
    installed_count = len(packages)
    services = hw_raw.get("systemd_units") or sw_raw.get("systemd_units") or []
    modules = hw_raw.get("kernel_modules") or sw_raw.get("kernel_modules") or []
    all_sockets = net_raw.get("process_open_sockets") or []
    uptime_rows = (rt_raw.get("uptime") or [])

    return {
        "schema_version": "cloudmove.normalized.v1",
        "source": {
            "tool": source.get("tool", "osquery"),
            "tool_version": source.get("tool_version"),
            "collector": source.get("collector"),
            "collector_host": source.get("collector_host"),
            "collected_at": raw.get("collected_at"),
        },
        "asset": {
            "hostname": normalized_hostname,
            "uuid": asset_raw.get("uuid") or system.get("uuid") or None,
            "vendor": asset_raw.get("hardware_vendor") or system.get("hardware_vendor"),
            "model": asset_raw.get("hardware_model") or system.get("hardware_model"),
            "form_factor": asset_raw.get("form_factor") or None,
            "architecture": asset_raw.get("cpu_type") or os_raw.get("arch"),
            "os": {
                "name": os_raw.get("name"),
                "version": os_raw.get("version"),
                "codename": os_raw.get("codename"),
                "architecture": os_raw.get("arch"),
            },
            "cpu": {
                "model": cpu.get("model") or system.get("cpu_brand"),
                "physical_cores": as_int(cpu.get("number_of_cores"), as_int(asset_raw.get("cpu_physical_cores"))),
                "logical_cores": as_int(cpu.get("logical_processors"), as_int(asset_raw.get("cpu_logical_cores"))),
                "max_clock_mhz": as_int(cpu.get("max_clock_speed")),
            },
            "memory": {
                "total_bytes": mem_total,
                "total_gib": gib(mem_total),
                "available_bytes_snapshot": available_mem_bytes,
                "available_gib_snapshot": gib(available_mem_bytes),
            },
        },
        "hardware": {
            "block_devices": block_devices,
            "mounts": mounts,
        },
        "network": {
            "interfaces": interfaces,
            "inferred_subnets": sorted(inferred_subnets),
            "default_gateways": sorted(set(gateways)),
            "routes": routes,
            "listening_services": listeners,
            "observed_remote_endpoints": peers,
        },
        "runtime": {
            "processes": [
                {"pid": as_int(p.get("pid")), "name": p.get("name"), "path": p.get("path"), "uid": as_int(p.get("uid"))}
                for p in processes
            ],
            "process_count": len(processes),
            "socket_observation_count": len(all_sockets),
            "uptime": uptime_rows[0] if uptime_rows else None,
        },
        "software": {
            "installed_debian_packages": packages,
            "package_status_counts": dict(package_counts),
            "installed_package_count": installed_count,
            "systemd_unit_count": len(services),
            "kernel_module_count": len(modules),
        },
        "collection": {
            "query_count": raw.get("collection", {}).get("query_count", 0),
            "successful_query_count": raw.get("collection", {}).get("successful_query_count", 0),
            "error_count": len(raw.get("collection", {}).get("errors") or []),
            "source_errors": raw.get("collection", {}).get("errors") or [],
        },
        "warnings": warnings,
        "limitations": [
            "This is a snapshot of one host, not network-wide discovery.",
            "Current processes and socket observations do not constitute historical performance telemetry.",
            "Observed remote endpoints are not asserted to be confirmed application dependencies.",
            "Disk byte values are estimates and should be checked against lsblk/df before cloud right-sizing.",
        ],
    }


def diagram_summary(inv: dict[str, Any]) -> dict[str, Any]:
    a = inv["asset"]
    network = inv["network"]
    interfaces = network["interfaces"]
    primary = next((i for i in interfaces if i["name"] not in ("lo", "docker0") and i["address"] and not i["address"].startswith("fe80:")), None)
    docker = next((i for i in interfaces if i["name"] == "docker0"), None)
    loopback = next((i for i in interfaces if i["name"] == "lo" and ":" not in i["address"]), None)
    root_mount = next((m for m in inv["hardware"]["mounts"] if m.get("path") == "/"), None)
    disk = next((d for d in inv["hardware"]["block_devices"] if d.get("name", "").startswith("/dev/") and "p" not in Path(d.get("name", "")).name), None)
    public = [p for p in network["observed_remote_endpoints"] if p.get("public_ip")]
    peers_by_proc: collections.Counter[str] = collections.Counter()
    for peer in public:
        for proc in peer.get("processes", []):
            peers_by_proc[proc["name"]] += proc.get("observations", 0)
    return {
        "primary_interface": primary,
        "docker_interface": docker,
        "loopback_interface": loopback,
        "root_mount": root_mount,
        "disk": disk,
        "public_endpoints": public,
        "public_ip_count": len({p["remote_ip"] for p in public}),
        "https_endpoint_count": sum(1 for p in public if p.get("protocol") == "TCP" and p.get("remote_port") == 443),
        "processes_seen_on_public_peers": [name for name, _ in peers_by_proc.most_common(5)],
    }


def write_dot(inv: dict[str, Any], summary: dict[str, Any], path: Path) -> None:
    a = inv["asset"]
    cpu = a["cpu"]
    mem = a["memory"]
    os_info = a["os"]
    disk = summary["disk"] or {}
    root = summary["root_mount"] or {}
    primary = summary["primary_interface"] or {}
    docker = summary["docker_interface"] or {}
    listener_rows = inv["network"]["listening_services"]
    # Keep labels readable: show a few important listeners; full inventory remains in JSON/report.
    preferred_names = {"sshd", "avahi-daemon", "ollama"}
    preferred = [x for x in listener_rows if x["process"] in preferred_names]
    loopback_services = [x for x in listener_rows if x["exposure"] == "loopback_only" and x["process"] not in preferred_names]
    listener_lines = []
    # IPv4 and IPv6 listeners may represent the same service. Collapse those into one diagram line.
    grouped_listeners: dict[tuple[str, int, str, str], set[str]] = collections.defaultdict(set)
    for item in listener_rows:
        if item["process"] not in preferred_names and item["exposure"] != "loopback_only":
            continue
        key = (item["process"], item["port"], item["protocol"], item["exposure"])
        grouped_listeners[key].add(item["address"])
    for key in sorted(grouped_listeners, key=lambda x: (0 if x[0] in preferred_names else 1, x[1], x[0])):
        process_name, port, protocol, exposure = key
        if process_name not in preferred_names and sum(1 for k in grouped_listeners if k[0] not in preferred_names) > 4:
            # Retain only four miscellaneous loopback listeners to keep the diagram legible.
            misc_seen = sum(1 for line in listener_lines if "(loopback)" in line)
            if misc_seen >= 4:
                continue
        suffix = " (loopback)" if exposure == "loopback_only" else " (all interfaces)" if exposure == "all_interfaces_or_unspecified" else ""
        listener_lines.append(f"{process_name} · {protocol}/{port}{suffix}")
    if not listener_lines:
        listener_lines = ["No valid listeners returned"]
    listener_label = "Listening services (snapshot)\n" + "\n".join(listener_lines)

    cpu_label = (
        "Hardware\n"
        f"{a.get('vendor') or 'Vendor unknown'} · {a.get('model') or 'Model unknown'}\n"
        f"CPU: {cpu.get('model') or 'unknown'}\n"
        f"{cpu.get('physical_cores') or '?'} physical / {cpu.get('logical_cores') or '?'} logical cores\n"
        f"RAM: {mem.get('total_gib') or '?'} GiB"
    )
    disk_label = (
        "Storage snapshot\n"
        f"{disk.get('name', 'Disk unknown')}: {disk.get('size_display_estimate') or 'size unknown'} (estimate)\n"
        f"Root /: {root.get('total_display_estimate') or 'unknown'} total; "
        f"{root.get('available_display_estimate') or 'unknown'} available (estimate)"
    )
    sw_label = (
        "Software / runtime inventory\n"
        f"Processes: {inv['runtime']['process_count']}\n"
        f"Installed Debian packages: {inv['software']['installed_package_count']:,}\n"
        f"systemd units: {inv['software']['systemd_unit_count']} · kernel modules: {inv['software']['kernel_module_count']}\n"
        f"Socket records queried: {inv['runtime']['socket_observation_count']}"
    )
    primary_label = (
        f"Primary interface: {primary.get('name', 'unknown')}\n"
        f"{primary.get('cidr') or primary.get('address', 'no address')}\n"
        f"Subnet: {primary.get('subnet') or 'not inferred'}\n"
        f"Default gateway: {', '.join(inv['network']['default_gateways']) or 'not detected'}"
    )
    docker_label = (
        f"Docker bridge: {docker.get('name', 'docker0')}\n"
        f"{docker.get('cidr') or docker.get('address', 'not detected')}"
    ) if docker else "Docker bridge not detected"
    public = summary["public_endpoints"]
    public_names = ", ".join(summary["processes_seen_on_public_peers"]) or "process attribution unavailable"
    public_label = (
        "Remote peers observed (snapshot)\n"
        f"{summary['public_ip_count']} public IP(s); "
        f"{summary['https_endpoint_count']} unique TCP/443 endpoint(s)\n"
        f"Processes seen: {public_names}\n"
        "Not proof of application dependencies"
    )
    dhcp_found = any(
        peer.get("remote_port") == 67 and peer.get("protocol") == "UDP"
        for peer in inv["network"]["observed_remote_endpoints"]
    )
    dhcp_label = "DHCP peer observed\n10.10.36.2:67/UDP" if dhcp_found else "No DHCP peer in socket snapshot"
    host_label = (
        f"{a['hostname']}\n{os_info.get('name', 'OS unknown')} {os_info.get('version', '')} · {os_info.get('architecture', '')}\n"
        f"osquery {inv['source'].get('tool_version', 'version unknown')}\n"
        f"Collected: {inv['source'].get('collected_at', 'timestamp unknown')}\n"
        "Single-host discovery"
    )
    notes_label = (
        "Validation notes\n"
        f"{inv['collection']['successful_query_count']}/{inv['collection']['query_count']} queries successful; "
        f"{inv['collection']['error_count']} query errors\n"
        "This asset is identified as a laptop, not a rack server.\n"
        "Network edges are observed sockets, not confirmed dependencies."
    )

    lines = [
        "digraph CloudMoveDiscovery {",
        '  graph [rankdir=LR, bgcolor="#f7f9fc", pad="0.28", nodesep="0.52", ranksep="0.75", splines=polyline, fontname="DejaVu Sans", labelloc="t", label="CLOUDMOVE · OSQUERY DISCOVERY MAP", fontsize=22, fontcolor="#16243a", compound=true];',
        '  node [shape=box, style="rounded,filled", fontname="DejaVu Sans", fontsize=10, margin="0.17,0.12", color="#c6d0df", fontcolor="#14243a", fillcolor="#ffffff", penwidth=1.2];',
        '  edge [fontname="DejaVu Sans", fontsize=9, color="#64748b", fontcolor="#475569", arrowsize=0.7, penwidth=1.2];',
        '  host [label="' + esc_dot(host_label) + '", fillcolor="#173b67", fontcolor="#ffffff", color="#173b67", penwidth=2.0, fontsize=12];',
        '  hardware [label="' + esc_dot(cpu_label) + '", fillcolor="#e8f2ff", color="#7ba9e5"];',
        '  storage [label="' + esc_dot(disk_label) + '", fillcolor="#e8f2ff", color="#7ba9e5"];',
        '  runtime [label="' + esc_dot(sw_label) + '", fillcolor="#f0eafe", color="#b39be8"];',
        '  services [label="' + esc_dot(listener_label) + '", fillcolor="#fff4dd", color="#e7bd63"];',
        '  network [label="' + esc_dot(primary_label) + '", fillcolor="#e4f7ef", color="#75c7a1"];',
        '  docker [label="' + esc_dot(docker_label) + '", fillcolor="#e4f7ef", color="#75c7a1"];',
        '  loopback [label="Loopback\n127.0.0.1 / ::1\nLocal-only listeners are not LAN services", fillcolor="#e4f7ef", color="#75c7a1"];',
        '  peers [label="' + esc_dot(public_label) + '", fillcolor="#fff0ef", color="#e99b94"];',
        '  dhcp [label="' + esc_dot(dhcp_label) + '", fillcolor="#fff4dd", color="#e7bd63"];',
        '  gateway [label="Default gateway\n' + esc_dot(', '.join(inv['network']['default_gateways']) or 'not detected') + '", fillcolor="#eef2f6", color="#aab6c6"];',
        '  notes [label="' + esc_dot(notes_label) + '", fillcolor="#fff0ef", color="#e99b94"];',
        '  host -> hardware [label="identity / CPU / RAM"];',
        '  host -> storage [label="block devices / mounts"];',
        '  host -> runtime [label="software / processes"];',
        '  host -> network [label="interface / route"];',
        '  host -> services [label="listening sockets"];',
        '  network -> gateway [label="default route"];',
        '  network -> docker [label="local bridge"];',
        '  network -> loopback [label="local interface"];',
        '  network -> peers [label="outbound sockets observed", style=dashed, color="#c45151"];',
        '  network -> dhcp [label="UDP/67 peer", style=dashed];',
        '  runtime -> services [label="PID → process", style=dotted];',
        '  peers -> notes [style=dotted, arrowhead=none, label="interpret cautiously"];',
        '  {rank=same; hardware; storage;}',
        '  {rank=same; runtime; services;}',
        '  {rank=same; peers; dhcp; gateway; docker; loopback;}',
        '}',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mermaid(inv: dict[str, Any], summary: dict[str, Any], path: Path) -> None:
    a = inv["asset"]
    cpu = a["cpu"]
    mem = a["memory"]
    os_info = a["os"]
    primary = summary["primary_interface"] or {}
    disk = summary["disk"] or {}
    root = summary["root_mount"] or {}
    public = summary["public_endpoints"]
    public_proc = ", ".join(summary["processes_seen_on_public_peers"]) or "not attributed"
    gateways = ", ".join(inv["network"]["default_gateways"]) or "not detected"
    lines = [
        "flowchart TB",
        f'  H["{esc_mermaid(a["hostname"])}<br/>{esc_mermaid(os_info.get("name", "OS unknown"))} {esc_mermaid(os_info.get("version", ""))}<br/>{esc_mermaid(a.get("model") or "model unknown")}<br/>CPU {cpu.get("physical_cores") or "?"} physical / {cpu.get("logical_cores") or "?"} logical · RAM {mem.get("total_gib") or "?"} GiB"]',
        f'  HW["Hardware<br/>{esc_mermaid(cpu.get("model") or "CPU unknown")}<br/>{esc_mermaid(disk.get("name", "disk unknown"))}: {esc_mermaid(disk.get("size_display_estimate") or "size unknown")} (estimate)<br/>Root /: {esc_mermaid(root.get("total_display_estimate") or "unknown")} total"]',
        f'  NET["Primary network<br/>{esc_mermaid(primary.get("name", "interface unknown"))}: {esc_mermaid(primary.get("cidr") or primary.get("address", "unknown"))}<br/>Subnet: {esc_mermaid(primary.get("subnet") or "unknown")}<br/>Gateway: {esc_mermaid(gateways)}"]',
        f'  SW["Runtime / software<br/>{inv["runtime"]["process_count"]} processes · {inv["software"]["installed_package_count"]:,} installed Debian packages<br/>{inv["software"]["systemd_unit_count"]} systemd units · {inv["software"]["kernel_module_count"]} kernel modules"]',
        f'  LISTEN["Listening services<br/>{sum(1 for x in inv["network"]["listening_services"] if x["protocol"] == "TCP" and x["port"] == 22)} SSH listener(s) on TCP/22; see report for full list<br/>Socket snapshot: {inv["runtime"]["socket_observation_count"]} records"]',
        f'  PEERS["Remote endpoints observed<br/>{summary["public_ip_count"]} public remote IPs; {summary["https_endpoint_count"]} TCP/443 endpoints<br/>Processes observed: {esc_mermaid(public_proc)}<br/>Not confirmed dependencies"]',
        '  NOTE["Caveat<br/>Single laptop snapshot; not rack-wide discovery<br/>Network edges are observed sockets, not confirmed dependencies"]',
        "  H --> HW",
        "  H --> NET",
        "  H --> SW",
        "  H --> LISTEN",
        "  NET -. observed connections .-> PEERS",
        "  PEERS -. interpret cautiously .-> NOTE",
        "  classDef host fill:#173b67,color:#fff,stroke:#173b67,stroke-width:2px;",
        "  classDef hardware fill:#e8f2ff,stroke:#7ba9e5,color:#14243a;",
        "  classDef network fill:#e4f7ef,stroke:#75c7a1,color:#14243a;",
        "  classDef warn fill:#fff0ef,stroke:#e99b94,color:#14243a;",
        "  class H host;",
        "  class HW,SW hardware;",
        "  class NET,LISTEN network;",
        "  class PEERS,NOTE warn;",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(inv: dict[str, Any], summary: dict[str, Any], path: Path) -> None:
    a = inv["asset"]
    net = inv["network"]
    cpu = a["cpu"]
    mem = a["memory"]
    os_info = a["os"]
    public = summary["public_endpoints"]
    lines = [
        "# CloudMove — informe de discovery osquery",
        "",
        f"- **Activo:** {a['hostname']}",
        f"- **Fecha de recolección (UTC):** {inv['source'].get('collected_at')}",
        f"- **Fuente:** {inv['source'].get('tool')} / {inv['source'].get('tool_version')}",
        f"- **Sistema operativo:** {os_info.get('name')} {os_info.get('version')} ({os_info.get('architecture')})",
        f"- **Modelo:** {a.get('vendor')} {a.get('model')}",
        f"- **CPU:** {cpu.get('model')}; {cpu.get('physical_cores')} núcleos físicos / {cpu.get('logical_cores')} lógicos",
        f"- **RAM total:** {mem.get('total_gib')} GiB; disponible en la instantánea: {mem.get('available_gib_snapshot')} GiB",
        f"- **Consultas osquery:** {inv['collection']['successful_query_count']}/{inv['collection']['query_count']} exitosas; errores: {inv['collection']['error_count']}",
        "",
        "> **Alcance:** este archivo describe una instantánea del portátil donde se ejecutó osquery. No es un inventario de todo el rack ni evidencia por sí sola de qué cargas deben migrarse.",
        "",
        "## Interfaces de red",
        "",
        "| Interfaz | Dirección/CIDR | Subred inferida |",
        "|---|---|---|",
    ]
    for x in net["interfaces"]:
        lines.append(f"| {x.get('name')} | {x.get('cidr') or x.get('address')} | {x.get('subnet') or '—'} |")
    lines.extend(["", f"**Puerta(s) de enlace por defecto:** {', '.join(net['default_gateways']) or 'no detectada'}", "", "## Discos y sistemas de archivos", "", "| Dispositivo | Tamaño estimado | Modelo |", "|---|---:|---|"])
    for d in inv["hardware"]["block_devices"]:
        lines.append(f"| {d.get('name')} | {d.get('size_display_estimate') or 'no calculado'} | {d.get('model') or '—'} |")
    lines.extend(["", "| Punto de montaje | Sistema de archivos | Total estimado | Disponible estimado |", "|---|---|---:|---:|"])
    for m in inv["hardware"]["mounts"]:
        if m.get("path") in ("/", "/boot", "/boot/efi", "/home", "/var", "/var/lib/docker") or (m.get("device") or "").startswith("/dev/"):
            lines.append(f"| {m.get('path')} | {m.get('filesystem')} | {m.get('total_display_estimate') or '—'} | {m.get('available_display_estimate') or '—'} |")
    lines.extend(["", "## Servicios en escucha observados", "", "| Proceso | Dirección | Protocolo/puerto | Exposición |", "|---|---|---|---|"])
    for x in net["listening_services"]:
        lines.append(f"| {x['process']} | {x['address']} | {x['protocol']}/{x['port']} | {x['exposure']} |")
    lines.extend(["", "## Conexiones remotas observadas en esta instantánea", "", "Estas observaciones son evidencia de sockets vistos en el momento de la recolección; no deben etiquetarse automáticamente como dependencias de aplicación confirmadas.", "", "| IP remota | Protocolo/puerto | Observaciones | Procesos asociados | IP pública según parser |", "|---|---|---:|---|---|"])
    for peer in public:
        proc_names = ", ".join(x["name"] for x in peer.get("processes", []))
        lines.append(f"| {peer['remote_ip']} | {peer['protocol']}/{peer['remote_port']} | {peer['observation_count']} | {proc_names} | Sí |")
    for peer in net["observed_remote_endpoints"]:
        if not peer.get("public_ip"):
            proc_names = ", ".join(x["name"] for x in peer.get("processes", []))
            lines.append(f"| {peer['remote_ip']} | {peer['protocol']}/{peer['remote_port']} | {peer['observation_count']} | {proc_names} | No |")
    lines.extend(["", "## Conteos de inventario", "", f"- Procesos: {inv['runtime']['process_count']}", f"- Registros de sockets consultados: {inv['runtime']['socket_observation_count']}", f"- Paquetes Debian instalados: {inv['software']['installed_package_count']}", f"- Unidades systemd: {inv['software']['systemd_unit_count']}", f"- Módulos del kernel: {inv['software']['kernel_module_count']}", f"- Interfaces: {len(net['interfaces'])}", f"- Rutas: {len(net['routes'])}", f"- Servicios en escucha: {len(net['listening_services'])}", f"- Endpoints remotos únicos: {len(net['observed_remote_endpoints'])}", "", "## Advertencias e interpretación", ""])
    for warning in inv["warnings"]:
        lines.append(f"- **{warning['code']}** — {warning['message']}")
    for limitation in inv["limitations"]:
        lines.append(f"- {limitation}")
    lines.extend(["", "## Siguiente paso para CloudMove", "", "1. Importar el JSON normalizado y conservar fuente/fecha de cada observación.", "2. En los servidores reales autorizados, ejecutar osquery en cada host o desplegar un gestor de flota.", "3. Recolectar métricas históricas de CPU, memoria y disco para dimensionamiento; esta instantánea no las ofrece.", "4. Confirmar dependencias con recolección repetida/telemetría y validación por los responsables de la aplicación.", "5. Añadir metadatos de motores de base de datos con consultas de catálogo de solo lectura.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def render_graph(dot_path: Path, output_dir: Path) -> list[str]:
    dot = shutil.which("dot")
    generated = []
    if not dot:
        return generated
    for fmt in ("svg", "png"):
        out = output_dir / f"cloudmove-discovery-diagram.{fmt}"
        try:
            subprocess.run([dot, f"-T{fmt}", str(dot_path), "-o", str(out)], check=True, capture_output=True, text=True, timeout=30)
            generated.append(str(out))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            print(f"WARNING: Graphviz {fmt} rendering failed: {detail[:400]}", file=sys.stderr)
    return generated


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="Path to cloudmove-osquery-inventory.json")
    ap.add_argument("--output-dir", default="cloudmove-parsed", help="Output directory")
    args = ap.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not input_path.is_file():
        print(f"ERROR: input file does not exist: {input_path}", file=sys.stderr)
        return 2
    try:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
        normalized = parse_inventory(raw)
        summary = diagram_summary(normalized)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        print(f"ERROR: could not parse inventory: {exc}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = output_dir / "cloudmove-normalized-inventory.json"
    dot_path = output_dir / "cloudmove-discovery-diagram.dot"
    mmd_path = output_dir / "cloudmove-discovery-diagram.mmd"
    report_path = output_dir / "cloudmove-discovery-report.md"
    normalized_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_dot(normalized, summary, dot_path)
    write_mermaid(normalized, summary, mmd_path)
    write_report(normalized, summary, report_path)
    generated = render_graph(dot_path, output_dir)

    print("CloudMove parser completed.")
    print(f"Input:      {input_path}")
    print(f"Output dir: {output_dir}")
    print(f"Normalized: {normalized_path}")
    print(f"DOT:        {dot_path}")
    print(f"Mermaid:    {mmd_path}")
    print(f"Report:     {report_path}")
    for item in generated:
        print(f"Diagram:    {item}")
    print(f"Asset:      {normalized['asset']['hostname']} ({normalized['asset']['os'].get('name')} {normalized['asset']['os'].get('version')})")
    print(f"Queries:    {normalized['collection']['successful_query_count']}/{normalized['collection']['query_count']} successful")
    print(f"Processes:  {normalized['runtime']['process_count']}; listeners: {len(normalized['network']['listening_services'])}; endpoints: {len(normalized['network']['observed_remote_endpoints'])}")
    if not generated:
        print("Graphviz not found; .dot and .mmd sources were generated. Install graphviz to render SVG/PNG.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
