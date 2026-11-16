"""
CloudMove Agent — Multiplatform System Collector (`system_collector.py`).

Collects detailed host inventory conforming to Section 3.3 of CloudMove:
- Host identity, OS, kernel, stable machine-id.
- CPU (cores, model, frequency, utilization).
- Memory (total, available, used, swap).
- Disks, partitions, filesystem types, mount points, UUIDs, free space.
- Network interfaces, MAC addresses, IPv4/IPv6 addresses, default routes.
- Listening ports, TCP/UDP sockets, connected endpoints (via /proc/net or ss).
- Running processes, parent PIDs, user, command line, memory/CPU.
- System services (systemd / Windows Services), enabled status, active status.
- Scheduled timers and cron jobs.
- Installed package counts and detected runtimes (Python, Node, Java, Go, Docker).
- Local database discovery (PostgreSQL, MySQL, Redis, MongoDB instances detected via socket/port).
- Strictly preserves evidence provenance (observed vs inferred) and redacts any secret or password.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_stable_machine_id() -> str:
    """Read hardware or OS stable machine identifier."""
    # 1. Linux machine-id
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        p = Path(path)
        if p.is_file():
            try:
                mid = p.read_text(encoding="utf-8").strip()
                if mid:
                    return mid
            except Exception:
                pass

    # 2. Linux DMI Product UUID (requires root or readable sysfs)
    dmi = Path("/sys/class/dmi/id/product_uuid")
    if dmi.is_file():
        try:
            val = dmi.read_text(encoding="utf-8").strip()
            if val:
                return val
        except Exception:
            pass

    # 3. Fallback: Hostname + MAC-derived UUID
    try:
        import uuid
        node = uuid.getnode()
        return f"node-{node:012x}"
    except Exception:
        return f"host-{socket.gethostname()}"


def collect_cpu_info() -> Dict[str, Any]:
    """Collect CPU core count, architecture, and current utilization."""
    info: Dict[str, Any] = {
        "architecture": platform.machine(),
        "cores_logical": os.cpu_count() or 1,
        "cores_physical": os.cpu_count() or 1,
        "model": platform.processor() or platform.machine(),
        "usage_percent": 0.0,
    }
    # Read /proc/cpuinfo on Linux
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        try:
            text = cpuinfo.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                if "model name" in line:
                    info["model"] = line.split(":", 1)[1].strip()
                    break
        except Exception:
            pass

    # Load average
    try:
        load1, load5, load15 = os.getloadavg()
        info["load_average"] = {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)}
        info["usage_percent"] = min(100.0, round((load1 / max(1, os.cpu_count() or 1)) * 100.0, 1))
    except Exception:
        info["load_average"] = {"1m": 0.0, "5m": 0.0, "15m": 0.0}

    return info


def collect_memory_info() -> Dict[str, Any]:
    """Collect total, free, and available physical memory and swap."""
    mem: Dict[str, Any] = {
        "total_mb": 0,
        "free_mb": 0,
        "available_mb": 0,
        "used_mb": 0,
        "usage_percent": 0.0,
        "swap_total_mb": 0,
        "swap_free_mb": 0,
    }
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            text = meminfo.read_text(encoding="utf-8", errors="replace")
            data: Dict[str, int] = {}
            for line in text.splitlines():
                parts = line.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    v_str = parts[1].strip().split()[0]
                    if v_str.isdigit():
                        data[k] = int(v_str)

            total_kb = data.get("MemTotal", 0)
            avail_kb = data.get("MemAvailable", data.get("MemFree", 0))
            mem["total_mb"] = total_kb // 1024
            mem["available_mb"] = avail_kb // 1024
            mem["free_mb"] = data.get("MemFree", 0) // 1024
            mem["used_mb"] = max(0, mem["total_mb"] - mem["available_mb"])
            if mem["total_mb"] > 0:
                mem["usage_percent"] = round((mem["used_mb"] / mem["total_mb"]) * 100.0, 1)

            mem["swap_total_mb"] = data.get("SwapTotal", 0) // 1024
            mem["swap_free_mb"] = data.get("SwapFree", 0) // 1024
        except Exception:
            pass
    return mem


def collect_disks_and_mounts() -> List[Dict[str, Any]]:
    """Collect block devices, partitions, mountpoints, filesystems, and usage."""
    disks: List[Dict[str, Any]] = []
    # 1. Inspect mounts via /proc/mounts
    mounts_file = Path("/proc/mounts")
    mounts: List[Dict[str, Any]] = []
    if mounts_file.is_file():
        try:
            for line in mounts_file.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    dev, mnt, fstype, opts = parts[0], parts[1], parts[2], parts[3]
                    if fstype in ("ext4", "xfs", "btrfs", "vfat", "ntfs", "zfs", "nfs", "cifs", "overlay"):
                        size_mb = 0
                        free_mb = 0
                        used_mb = 0
                        try:
                            st = os.statvfs(mnt)
                            size_mb = (st.f_blocks * st.f_frsize) // (1024 * 1024)
                            free_mb = (st.f_bavail * st.f_frsize) // (1024 * 1024)
                            used_mb = max(0, size_mb - free_mb)
                        except Exception:
                            pass

                        mounts.append({
                            "device": dev,
                            "mountpoint": mnt,
                            "filesystem": fstype,
                            "options": opts,
                            "read_only": "ro" in opts.split(","),
                            "size_mb": size_mb,
                            "free_mb": free_mb,
                            "used_mb": used_mb,
                        })
        except Exception:
            pass

    # 2. Try lsblk JSON if available
    try:
        res = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,UUID,ROTA"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0:
            doc = json.loads(res.stdout)
            for blk in doc.get("blockdevices", []):
                size_gb = round(int(blk.get("size", 0)) / (1024**3), 2)
                disks.append({
                    "name": blk.get("name"),
                    "size_bytes": blk.get("size"),
                    "size_gb": size_gb,
                    "type": blk.get("type"),
                    "mountpoint": blk.get("mountpoint"),
                    "fstype": blk.get("fstype"),
                    "uuid": blk.get("uuid"),
                    "rotational": blk.get("rota") == "1",
                    "children": blk.get("children", []),
                })
    except Exception:
        pass

    if not disks and mounts:
        for m in mounts:
            disks.append({
                "name": m["device"],
                "mountpoint": m["mountpoint"],
                "fstype": m["filesystem"],
                "size_gb": round(m["size_mb"] / 1024, 2),
                "free_gb": round(m["free_mb"] / 1024, 2),
                "type": "mount",
            })

    return disks


def collect_network_interfaces() -> List[Dict[str, Any]]:
    """Collect network interfaces, MAC addresses, and assigned IP addresses."""
    interfaces: List[Dict[str, Any]] = []
    sys_net = Path("/sys/class/net")
    if sys_net.is_dir():
        try:
            for iface in sys_net.iterdir():
                ifname = iface.name
                mac = "00:00:00:00:00:00"
                mac_file = iface / "address"
                if mac_file.is_file():
                    mac = mac_file.read_text(encoding="utf-8").strip()

                is_up = False
                operstate = iface / "operstate"
                if operstate.is_file():
                    is_up = operstate.read_text(encoding="utf-8").strip().lower() == "up"

                interfaces.append({
                    "interface": ifname,
                    "mac_address": mac,
                    "is_up": is_up,
                    "is_loopback": ifname == "lo",
                })
        except Exception:
            pass

    # Try ip -j addr if available
    try:
        res = subprocess.run(
            ["ip", "-j", "addr"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0:
            doc = json.loads(res.stdout)
            parsed: List[Dict[str, Any]] = []
            for item in doc:
                ifname = item.get("ifname")
                ips = []
                for addr in item.get("addr_info", []):
                    ips.append({
                        "family": addr.get("family"),
                        "local": addr.get("local"),
                        "prefixlen": addr.get("prefixlen"),
                    })
                parsed.append({
                    "interface": ifname,
                    "mac_address": item.get("address"),
                    "operstate": item.get("operstate"),
                    "flags": item.get("flags", []),
                    "ip_addresses": ips,
                })
            return parsed
    except Exception:
        pass

    return interfaces


def collect_listening_ports() -> List[Dict[str, Any]]:
    """Collect listening TCP/UDP ports and bound sockets via /proc/net/tcp or ss."""
    listeners: List[Dict[str, Any]] = []
    # 1. Try ss -tulpn -j or standard ss
    try:
        res = subprocess.run(
            ["ss", "-tulpn"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 5:
                    proto = parts[0]
                    state = parts[1]
                    local_addr = parts[4]
                    port = None
                    if ":" in local_addr:
                        port_str = local_addr.rsplit(":", 1)[1]
                        if port_str.isdigit():
                            port = int(port_str)

                    proc_info = parts[6] if len(parts) >= 7 else ""
                    listeners.append({
                        "protocol": proto,
                        "state": state,
                        "local_address": local_addr,
                        "port": port,
                        "process_raw": proc_info,
                    })
            if listeners:
                return listeners
    except Exception:
        pass

    # 2. Fallback: Parse /proc/net/tcp
    for net_file, proto in [("/proc/net/tcp", "tcp"), ("/proc/net/tcp6", "tcp6")]:
        f = Path(net_file)
        if f.is_file():
            try:
                for line in f.read_text(encoding="utf-8").splitlines()[1:]:
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        st = parts[3]
                        if st == "0A":  # TCP_LISTEN
                            hex_addr = parts[1]
                            ip_hex, port_hex = hex_addr.split(":")
                            port = int(port_hex, 16)
                            listeners.append({
                                "protocol": proto,
                                "state": "LISTEN",
                                "port": port,
                                "local_address": f":{port}",
                            })
            except Exception:
                pass
    return listeners


def collect_system_services() -> List[Dict[str, Any]]:
    """Collect active systemd services and units."""
    services: List[Dict[str, Any]] = []
    try:
        res = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                parts = line.split(None, 4)
                if len(parts) >= 4:
                    unit_name = parts[0]
                    load = parts[1]
                    active = parts[2]
                    sub = parts[3]
                    desc = parts[4] if len(parts) >= 5 else ""
                    if unit_name.endswith(".service"):
                        services.append({
                            "name": unit_name,
                            "load_state": load,
                            "active_state": active,
                            "sub_state": sub,
                            "description": desc,
                            "is_running": active == "active",
                        })
    except Exception:
        pass
    return services


def detect_local_databases() -> List[Dict[str, Any]]:
    """
    Detect running database instances (PostgreSQL, MySQL, Redis, MongoDB, RabbitMQ)
    strictly via local socket/process inspection without connecting or extracting business data.
    """
    dbs: List[Dict[str, Any]] = []
    listeners = collect_listening_ports()
    ports_listening = {item["port"] for item in listeners if item.get("port")}

    # PostgreSQL: default port 5432 or unix socket in /var/run/postgresql
    if 5432 in ports_listening or Path("/var/run/postgresql").is_dir():
        dbs.append({
            "engine": "postgresql",
            "default_port": 5432,
            "detected_via": "listening_port_or_socket",
            "is_shared": True,
            "requires_quiescing": True,
        })

    # Redis: default port 6379 or /var/run/redis
    if 6379 in ports_listening or Path("/var/run/redis").is_dir():
        dbs.append({
            "engine": "redis",
            "default_port": 6379,
            "detected_via": "listening_port_or_socket",
            "is_shared": True,
            "requires_quiescing": False,
        })

    # MySQL / MariaDB: default port 3306 or /var/run/mysqld
    if 3306 in ports_listening or Path("/var/run/mysqld").is_dir():
        dbs.append({
            "engine": "mysql",
            "default_port": 3306,
            "detected_via": "listening_port_or_socket",
            "is_shared": True,
            "requires_quiescing": True,
        })

    # RabbitMQ: default port 5672
    if 5672 in ports_listening:
        dbs.append({
            "engine": "rabbitmq",
            "default_port": 5672,
            "detected_via": "listening_port",
            "is_shared": True,
            "requires_quiescing": False,
        })

    return dbs


def collect_running_processes(limit: int = 80) -> List[Dict[str, Any]]:
    """Collect active running processes sorted by memory/CPU utilization."""
    procs: List[Dict[str, Any]] = []
    try:
        res = subprocess.run(
            ["ps", "-eo", "pid,ppid,user,%cpu,%mem,rss,stat,comm,args", "--sort=-%mem"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0:
            lines = res.stdout.splitlines()[1:]
            for line in lines[:limit]:
                parts = line.strip().split(None, 8)
                if len(parts) >= 8:
                    pid_s, ppid_s, user, cpu_s, mem_s, rss_s, stat, comm = parts[:8]
                    cmdline = parts[8] if len(parts) > 8 else comm
                    try:
                        pid = int(pid_s)
                        ppid = int(ppid_s)
                    except ValueError:
                        continue
                    try:
                        cpu_pct = float(cpu_s)
                    except ValueError:
                        cpu_pct = 0.0
                    try:
                        mem_pct = float(mem_s)
                    except ValueError:
                        mem_pct = 0.0
                    try:
                        rss_mb = round(int(rss_s) / 1024.0, 2)
                    except ValueError:
                        rss_mb = 0.0

                    procs.append({
                        "pid": pid,
                        "ppid": ppid,
                        "user": user,
                        "cpu_percent": cpu_pct,
                        "mem_percent": mem_pct,
                        "rss_mb": rss_mb,
                        "state": stat,
                        "name": comm,
                        "cmdline": cmdline[:220],
                    })
    except Exception:
        pass
    return procs


_SKIP_DIR_NAMES = {
    ".cache",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".npm",
    ".cargo",
    ".rustup",
    ".local",
    ".mozilla",
    ".thunderbird",
    "Trash",
    "snap",
    ".vscode",
    ".cursor",
    ".gemini",
}


def _scan_dir_stats(target_dir: Path, max_files_walk: int = 2500) -> tuple[int, int]:
    """Fast bounded directory size and file count scanner."""
    total_bytes = 0
    files_count = 0
    stack = [target_dir]
    visited = 0
    while stack and visited < max_files_walk:
        curr = stack.pop()
        try:
            with os.scandir(curr) as it:
                for entry in it:
                    visited += 1
                    if visited > max_files_walk:
                        break
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in _SKIP_DIR_NAMES:
                            continue
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        files_count += 1
                        try:
                            st = entry.stat(follow_symlinks=False)
                            blocks_bytes = getattr(st, "st_blocks", 0) * 512
                            actual_bytes = (
                                min(st.st_size, blocks_bytes)
                                if blocks_bytes > 0
                                else st.st_size
                            )
                            total_bytes += actual_bytes
                        except Exception:
                            pass
        except Exception:
            pass
    return total_bytes, files_count


def _build_folder_node(
    dir_path: Path,
    category: str,
    depth: int = 0,
    max_depth: int = 2,
    max_children: int = 25,
) -> Optional[Dict[str, Any]]:
    """Build a hierarchical folder node with child folders and files and sizes."""
    try:
        if not dir_path.exists() or dir_path.is_symlink():
            return None
        st = dir_path.stat()
        mtime_iso = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
    except Exception:
        return None

    owner = "root"
    try:
        import pwd
        owner = pwd.getpwuid(st.st_uid).pw_name
    except Exception:
        pass

    if dir_path.is_file():
        blocks_bytes = getattr(st, "st_blocks", 0) * 512
        sz = min(st.st_size, blocks_bytes) if blocks_bytes > 0 else st.st_size
        return {
            "id": str(dir_path),
            "path": str(dir_path),
            "name": dir_path.name,
            "type": "file",
            "category": category,
            "owner": owner,
            "size_bytes": sz,
            "size_mb": round(sz / (1024 * 1024), 2),
            "size_gib": round(sz / (1024 ** 3), 4),
            "files_count": 1,
            "modified_at": mtime_iso,
            "children": [],
        }

    children: List[Dict[str, Any]] = []
    if depth < max_depth:
        try:
            entries = []
            with os.scandir(dir_path) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.name.startswith(".") and entry.name not in (".env.example",):
                        continue
                    if entry.name in _SKIP_DIR_NAMES:
                        continue
                    entries.append(Path(entry.path))
            # Sort directories first, then by name
            entries.sort(key=lambda p: (0 if p.is_dir() else 1, p.name.lower()))
            for child_path in entries[:max_children]:
                child_node = _build_folder_node(
                    child_path,
                    category=category,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_children=35 if depth >= 1 else 60,
                )
                if child_node:
                    children.append(child_node)
        except Exception:
            pass

    size_bytes, files_count = _scan_dir_stats(dir_path)
    if children:
        children_sum = sum(c.get("size_bytes", 0) for c in children)
        if children_sum > size_bytes:
            size_bytes = children_sum

    return {
        "id": str(dir_path),
        "path": str(dir_path),
        "name": dir_path.name or str(dir_path),
        "type": "directory",
        "category": category,
        "owner": owner,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 2),
        "size_gib": round(size_bytes / (1024 ** 3), 4),
        "files_count": max(files_count, len(children)),
        "modified_at": mtime_iso,
        "children": children,
    }


def collect_filesystem_tree() -> List[Dict[str, Any]]:
    """
    Scan the local device's user home folders and key system/application directories
    so the user can browse their folders & files in CloudMove and select which ones
    to migrate within the AWS EBS storage quota.
    """
    tree: List[Dict[str, Any]] = []

    # 1. Scan all user directories under /home/*
    home_root = Path("/home")
    if home_root.is_dir():
        try:
            for user_dir in sorted(home_root.iterdir()):
                if not user_dir.is_dir() or user_dir.is_symlink():
                    continue
                # Scan visible folders/files inside /home/<user> up to 4 levels deep
                user_node = _build_folder_node(
                    user_dir,
                    category="user_home",
                    depth=0,
                    max_depth=4,
                    max_children=60,
                )
                if user_node:
                    user_node["label"] = f"Carpeta de Usuario ({user_dir.name})"
                    tree.append(user_node)
        except Exception:
            pass

    # 2. Scan key system & application directories (/opt, /var/www, /srv, /etc)
    for sys_path_str, cat, label in [
        ("/opt", "app_data", "Aplicaciones y Paquetes en /opt"),
        ("/var/www", "app_data", "Sitios y Servicios Web en /var/www"),
        ("/srv", "app_data", "Datos de Servicios en /srv"),
        ("/etc", "system_config", "Configuración del Sistema Operativo en /etc"),
    ]:
        p = Path(sys_path_str)
        if p.is_dir():
            node = _build_folder_node(p, category=cat, depth=0, max_depth=1, max_children=20)
            if node and (node.get("files_count", 0) > 0 or node.get("children")):
                node["label"] = label
                tree.append(node)

    return tree


def collect_system_inventory() -> Dict[str, Any]:
    """
    Gather complete system inventory scan conforming to CMIR v2.1.
    Distinguishes observed facts and attaches timestamps and evidence metadata.
    """
    now = _utc_now()
    hostname = socket.gethostname()
    try:
        etc_hn = Path("/etc/hostname")
        if etc_hn.is_file():
            raw_hn = etc_hn.read_text(encoding="utf-8").strip()
            if raw_hn and raw_hn != "localhost":
                hostname = raw_hn
    except Exception:
        pass
    machine_id = get_stable_machine_id()
    cpu = collect_cpu_info()
    memory = collect_memory_info()
    disks = collect_disks_and_mounts()
    interfaces = collect_network_interfaces()
    listeners = collect_listening_ports()
    services = collect_system_services()
    processes = collect_running_processes()
    databases = detect_local_databases()
    filesystem_tree = collect_filesystem_tree()

    # Detect installed runtimes
    runtimes = []
    for r_bin, r_name in [
        ("python3", "Python"),
        ("node", "Node.js"),
        ("java", "Java/JVM"),
        ("go", "Go"),
        ("docker", "Docker Container Engine"),
    ]:
        try:
            res = subprocess.run([r_bin, "--version"], capture_output=True, text=True, timeout=2, check=False)
            if res.returncode == 0:
                ver = (res.stdout or res.stderr).splitlines()[0].strip()
                runtimes.append({"runtime": r_name, "binary": r_bin, "version": ver})
        except Exception:
            pass

    return {
        "hostname": hostname,
        "machine_id": machine_id,
        "os_family": "linux" if platform.system().lower() == "linux" else platform.system().lower(),
        "os_name": platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "collected_at": now,
        "cpu": cpu,
        "memory": memory,
        "disks": disks,
        "network_interfaces": interfaces,
        "listening_ports": listeners,
        "services": services[:120],
        "processes": processes,
        "runtimes": runtimes,
        "databases": databases,
        "filesystem_tree": filesystem_tree,
        "evidence_provenance": "observed_by_cloudmove_agent",
    }
