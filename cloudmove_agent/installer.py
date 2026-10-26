"""
CloudMove Agent — CLI Installer & Systemd Configuration Utility (`installer.py`).

Provides reproducible automated installation, enrollment, and systemd service setup.
Can be executed as:
    python3 -m cloudmove_agent.installer --server http://<host>:8000 --token <ENROLLMENT_TOKEN>
"""

from __future__ import annotations

import argparse
import configparser
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import urllib.error
import urllib.request


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SYSTEMD_UNIT_TEMPLATE = """[Unit]
Description=CloudMove Discovery & Migration Agent
After=network.target

[Service]
Type=simple
User=root
ExecStart={python_bin} -m cloudmove_agent.agent_daemon
WorkingDirectory={working_dir}
Restart=always
RestartSec=10
StandardOutput=append:/var/log/cloudmove/agent.log
StandardError=append:/var/log/cloudmove/agent.log
NoNewPrivileges=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
"""


def check_server_connectivity(server_url: str) -> Dict[str, Any]:
    url = f"{server_url.rstrip('/')}/health"
    req = urllib.request.Request(url, headers={"User-Agent": "CloudMove-Installer/2.1"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8")) if data else {"status": "ok"}
    except Exception as exc:
        raise RuntimeError(f"No se pudo conectar con el servidor CloudMove en '{url}': {exc}") from exc


def enroll_with_token(
    server_url: str,
    enrollment_token: str,
    hostname: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> Dict[str, Any]:
    host = hostname or socket.gethostname()
    ip = ip_address or "127.0.0.1"
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        pass

    machine_id = None
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        f = Path(p)
        if f.is_file():
            machine_id = f.read_text(encoding="utf-8").strip()
            break

    payload = {
        "enrollment_token": enrollment_token.strip(),
        "hostname": host,
        "ip_address": ip,
        "os_family": "linux" if platform.system().lower() == "linux" else platform.system().lower(),
        "os_name": platform.system(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "machine_id": machine_id,
        "version": "2.1.0",
        "capabilities": [
            "discovery",
            "advanced_inspection",
            "disk_snapshot",
            "native_tool_install",
            "config_modification",
            "service_control",
            "cutover_revert",
        ],
    }

    url = f"{server_url.rstrip('/')}/api/v1/agents/enroll"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "CloudMove-Installer/2.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Error de enrolamiento en '{url}' (HTTP {exc.code}): {err}") from exc
    except Exception as exc:
        raise RuntimeError(f"Error de conexión durante el enrolamiento: {exc}") from exc


def write_agent_config(
    conf_path: Path,
    server_url: str,
    agent_id: str,
    api_key: str,
    heartbeat_interval: int = 20,
) -> None:
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    parser = configparser.ConfigParser()
    parser["agent"] = {
        "server_url": server_url.rstrip("/"),
        "agent_id": agent_id,
        "api_key": api_key,
        "heartbeat_interval": str(heartbeat_interval),
        "enrolled_at": _utc_now(),
    }
    with open(conf_path, "w", encoding="utf-8") as f:
        parser.write(f)
    try:
        os.chmod(str(conf_path), 0o600)
    except Exception:
        pass


def install_systemd_service(python_bin: str, working_dir: Path) -> bool:
    if os.name != "posix" or platform.system().lower() != "linux":
        print("[!] No se configura systemd en entornos no Linux.")
        return False

    service_file = Path("/etc/systemd/system/cloudmove-agent.service")
    try:
        unit_content = SYSTEMD_UNIT_TEMPLATE.format(
            python_bin=python_bin,
            working_dir=str(working_dir),
        )
        service_file.write_text(unit_content, encoding="utf-8")
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "cloudmove-agent.service"], check=True)
        subprocess.run(["systemctl", "restart", "cloudmove-agent.service"], check=True)
        print("[✓] Servicio systemd 'cloudmove-agent' instalado y activo.")
        return True
    except PermissionError:
        print("[!] Se requieren permisos de superusuario (root/sudo) para instalar el servicio systemd.")
        print(f"[!] Puede copiar la plantilla a '{service_file}' manualmente.")
        return False
    except Exception as exc:
        print(f"[!] Error configurando systemd: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Instalador y configurador oficial del agente CloudMove")
    parser.add_argument("--server", default="http://localhost:8000", help="URL base del servidor CloudMove")
    parser.add_argument("--token", required=True, help="Token de inscripción emitido desde la plataforma web")
    parser.add_argument("--config", default="/etc/cloudmove/agent.conf", help="Ruta de guardado de la configuración")
    parser.add_argument("--no-service", action="store_true", help="No intentar registrar el servicio systemd")
    args = parser.parse_args()

    print(f"==> 1. Verificando conectividad hacia el servidor '{args.server}'...")
    check_server_connectivity(args.server)
    print("    [✓] Conectividad HTTP confirmada.")

    print(f"==> 2. Enrolando agente con el token de inscripción...")
    enrollment = enroll_with_token(args.server, args.token)
    agent_id = enrollment["agent_id"]
    api_key = enrollment["agent_api_key"]
    print(f"    [✓] Agente autenticado exitosamente. Agent ID: {agent_id}")

    conf_path = Path(args.config)
    if not os.access(conf_path.parent, os.W_OK) and not Path("/etc").exists():
        conf_path = Path.home() / ".cloudmove" / "agent.conf"

    print(f"==> 3. Guardando configuración protegida en '{conf_path}'...")
    write_agent_config(conf_path, args.server, agent_id, api_key)
    print("    [✓] Configuración guardada (permisos 0600).")

    if not args.no_service and os.geteuid() == 0:
        print("==> 4. Configurando servicio systemd 'cloudmove-agent'...")
        install_systemd_service(sys.executable, Path(__file__).resolve().parent.parent)

    print("\n[✓] Instalación del Agente CloudMove completada exitosamente.")
    print(f"    Agent ID: {agent_id}")
    print(f"    Configuración: {conf_path}")


if __name__ == "__main__":
    main()
