#!/usr/bin/env python3
"""
Recolector de inventario osquery para CloudMove.

Modos de uso:
1. Interfaz visual interactiva (abre un panel local en el navegador para escanear y enviar a CloudMove):
     python3 cloudmove_osquery_export.py --ui
2. Escaneo directo + envío automático al analizador CloudMove:
     python3 cloudmove_osquery_export.py --analyze
3. Exportación clásica a archivo JSON (con o sin sudo):
     python3 cloudmove_osquery_export.py --output cloudmove-osquery-inventory.json
"""

import argparse
import datetime
import http.server
import json
import os
import platform
import shutil
import socketserver
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

QUERIES = {
    "system_info": "SELECT * FROM system_info LIMIT 1;",
    "os_version": "SELECT * FROM os_version LIMIT 1;",
    "platform_info": "SELECT * FROM platform_info LIMIT 1;",
    "cpu_info": "SELECT * FROM cpu_info LIMIT 64;",
    "memory_info": "SELECT * FROM memory_info LIMIT 10;",
    "uptime": "SELECT * FROM uptime LIMIT 1;",
    "interface_addresses": "SELECT * FROM interface_addresses LIMIT 256;",
    "routes": "SELECT * FROM routes LIMIT 512;",
    "mounts": "SELECT * FROM mounts LIMIT 512;",
    "block_devices": "SELECT * FROM block_devices LIMIT 512;",
    "listening_ports": (
        "SELECT pid, port, protocol, address FROM listening_ports "
        "WHERE CAST(port AS INTEGER) > 0 AND address != '' LIMIT 2000;"
    ),
    "processes": "SELECT pid, name, path, uid FROM processes LIMIT 2000;",
    "process_open_sockets": (
        "SELECT pid, fd, family, protocol, local_address, remote_address, "
        "local_port, remote_port FROM process_open_sockets LIMIT 4000;"
    ),
    "deb_packages": "SELECT * FROM deb_packages LIMIT 5000;",
    "systemd_units": "SELECT * FROM systemd_units LIMIT 1000;",
    "kernel_modules": "SELECT * FROM kernel_modules LIMIT 1000;",
}


def run_query(binary: str, sql: str) -> Tuple[Optional[ list ], Optional[str]]:
    """Ejecuta una consulta de solo lectura y devuelve filas o error."""
    try:
        result = subprocess.run(
            [binary, "--json", sql],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    try:
        rows = json.loads(stdout) if stdout else []
    except json.JSONDecodeError:
        return None, f"Respuesta JSON inválida: {(stderr or stdout)[:400]}"

    if result.returncode != 0:
        return None, f"Código {result.returncode}: {(stderr or stdout)[:400]}"

    if "no such table" in stderr.lower() or "error:" in stderr.lower():
        return None, stderr[:400]

    if not isinstance(rows, list):
        return None, "La consulta no devolvió una lista JSON."

    return rows, None


def collect_osquery_inventory(
    require_root: bool = False,
    on_progress: Optional[Callable[[str, int, int], None]] = None,
) -> Dict[str, Any]:
    """
    Ejecuta las 16 consultas de osquery en el dispositivo local y devuelve el
    documento JSON con esquema `cloudmove.discovery.v1`.
    """
    binary = shutil.which("osqueryi")
    if not binary:
        raise RuntimeError(
            "No se encontró 'osqueryi' en el PATH del sistema. Instala osquery (https://osquery.io/downloads) para escanear este dispositivo."
        )

    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    if require_root and not is_root:
        raise PermissionError("Ejecuta este recolector con sudo (--require-root activo).")

    tables: Dict[str, list] = {}
    errors: list = []
    total_queries = len(QUERIES)

    for idx, (name, sql) in enumerate(QUERIES.items(), start=1):
        if on_progress:
            on_progress(name, idx, total_queries)
        rows, error = run_query(binary, sql)
        if error:
            tables[name] = []
            errors.append({"query": name, "error": error})
        else:
            tables[name] = rows or []

    system = (tables.get("system_info") or [{}])[0]
    os_version = (tables.get("os_version") or [{}])[0]
    platform_info = (tables.get("platform_info") or [{}])[0]

    raw_hostname = (
        system.get("computer_name")
        or system.get("hostname")
        or platform.node()
        or "local-device"
    )
    hostname = platform.node() if raw_hostname == "localhost" and platform.node() else raw_hostname

    version_result = subprocess.run(
        [binary, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    osquery_version = (version_result.stdout or version_result.stderr).strip()

    privilege_note = (
        "Ejecutado con privilegios root (visibilidad completa de sockets y procesos)."
        if is_root
        else "Ejecutado en modo usuario sin sudo (algunos sockets de otros usuarios pueden omitirse)."
    )

    document = {
        "schema_version": "cloudmove.discovery.v1",
        "source": {
            "tool": "osquery",
            "tool_version": osquery_version,
            "collector": "cloudmove_osquery_export.py",
            "collector_host": platform.node(),
            "privilege_mode": "root" if is_root else "user",
        },
        "collected_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(timespec="seconds"),
        "asset": {
            "hostname": hostname,
            "uuid": system.get("uuid"),
            "hardware_vendor": system.get("hardware_vendor"),
            "hardware_model": system.get("hardware_model"),
            "cpu_type": system.get("cpu_type"),
            "cpu_logical_cores": system.get("cpu_logical_cores"),
            "cpu_physical_cores": system.get("cpu_physical_cores"),
            "physical_memory_bytes": system.get("physical_memory"),
            "os": os_version,
            "platform": platform_info,
            "system_info": system,
        },
        "hardware": {
            "cpu_info": tables["cpu_info"],
            "memory_info": tables["memory_info"],
            "block_devices": tables["block_devices"],
            "mounts": tables["mounts"],
        },
        "network": {
            "interfaces": tables["interface_addresses"],
            "routes": tables["routes"],
            "listening_ports": tables["listening_ports"],
            "process_open_sockets": tables["process_open_sockets"],
        },
        "software": {
            "deb_packages": tables["deb_packages"],
            "systemd_units": tables["systemd_units"],
            "kernel_modules": tables["kernel_modules"],
        },
        "runtime": {
            "processes": tables["processes"],
            "uptime": tables["uptime"],
        },
        "collection": {
            "query_count": len(QUERIES),
            "successful_query_count": len(QUERIES) - len(errors),
            "errors": errors,
            "note": (
                f"Instantánea de solo lectura ({privilege_note}). "
                "Una observación puntual no descubre todas las dependencias de red."
            ),
        },
    }
    return document


def upload_to_cloudmove(
    document: Dict[str, Any],
    api_base_candidates: Optional[list] = None,
) -> Dict[str, Any]:
    """Envía el inventario recolectado al backend de CloudMove y devuelve la sesión creada."""
    candidates = api_base_candidates or [
        "http://localhost:8001",
        "http://localhost:8000",
    ]
    payload_bytes = json.dumps(document, ensure_ascii=False).encode("utf-8")
    hostname = document.get("asset", {}).get("hostname") or "device"
    filename = f"live-osquery-{hostname}.json"

    last_err = None
    for base in candidates:
        url = f"{base.rstrip('/')}/api/v1/discovery/import"
        req = urllib.request.Request(
            url,
            data=payload_bytes,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Filename": filename,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                data["_uploaded_to"] = base
                return data
        except Exception as exc:
            last_err = exc

    raise RuntimeError(f"No se pudo conectar con el backend de CloudMove ({last_err}).")


LOCAL_UI_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CloudMove — Agente Recolector Osquery Local</title>
  <style>
    :root {
      --bg: #0f172a;
      --card: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --success: #10b981;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 32px 20px;
    }
    .container {
      max-width: 820px;
      margin: 0 auto;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 28px;
      box-shadow: 0 20px 40px rgba(0,0,0,0.35);
    }
    h1 { margin: 0 0 8px; font-size: 22px; }
    p { margin: 0 0 18px; color: var(--muted); line-height: 1.5; font-size: 14px; }
    .actions {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 20px;
    }
    button, a.btn {
      padding: 11px 18px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: #0284c7;
      color: #fff;
      font-weight: 600;
      font-size: 14px;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    button.secondary, a.btn.secondary {
      background: #334155;
    }
    button:disabled { opacity: 0.6; cursor: wait; }
    .status-box {
      padding: 16px;
      background: #0b1120;
      border: 1px solid var(--border);
      border-radius: 10px;
      font-family: ui-monospace, monospace;
      font-size: 13px;
      line-height: 1.6;
      white-space: pre-wrap;
      margin-bottom: 16px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }
    .metric {
      background: #0b1120;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
    }
    .metric span { display: block; font-size: 11px; color: var(--muted); text-transform: uppercase; }
    .metric strong { font-size: 16px; color: var(--accent); }
  </style>
</head>
<body>
  <div class="container">
    <h1>CloudMove — Recolector Osquery de Dispositivo Local</h1>
    <p>
      Esta interfaz ejecuta <code>cloudmove_osquery_export.py</code> directamente en tu equipo, recopila
      CPU, memoria, discos, red, puertos en escucha, servicios y paquetes mediante <code>osqueryi</code>,
      y envía el resultado automáticamente al analizador CloudMove.
    </p>
    <div class="actions">
      <button id="btnScan" onclick="runScanAndAnalyze()">
        1. Escanear Mi Dispositivo y Analizar en CloudMove
      </button>
      <button id="btnDownload" class="secondary" onclick="downloadJson()" style="display:none;">
        Descargar JSON Recolectado
      </button>
      <a id="btnOpenCloudMove" class="btn secondary" href="http://localhost:5173" target="_blank" style="display:none;">
        Abrir Interfaz Principal CloudMove ↗
      </a>
    </div>
    <div id="status" class="status-box">Listo para escanear este dispositivo con osqueryi...</div>
    <div id="metrics" class="grid" style="display:none;"></div>
  </div>

  <script>
    let lastInventory = null;
    async function runScanAndAnalyze() {
      const btn = document.getElementById('btnScan');
      const status = document.getElementById('status');
      const metrics = document.getElementById('metrics');
      btn.disabled = true;
      status.textContent = "⏳ Ejecutando las 16 consultas de osqueryi en este dispositivo y enviando a CloudMove...";
      try {
        const res = await fetch('/api/scan-and-upload', { method: 'POST' });
        const data = await res.json();
        if (!res.ok || data.error) {
          throw new Error(data.error || 'Error durante la recolección');
        }
        lastInventory = data.inventory;
        document.getElementById('btnDownload').style.display = 'inline-flex';
        document.getElementById('btnOpenCloudMove').style.display = 'inline-flex';
        status.textContent =
          "✅ ¡Escaneo y análisis completados con éxito!\\n" +
          "• Host detectado: " + data.hostname + "\\n" +
          "• Archivo local guardado: " + data.saved_path + "\\n" +
          "• Sesión en CloudMove: " + (data.session_id || "Importado") + "\\n" +
          "• Haz clic en 'Abrir Interfaz Principal CloudMove' para ver el Diagrama Interactivo y el código Terraform AWS.";
        metrics.style.display = 'grid';
        metrics.innerHTML = [
          ['Host', data.hostname],
          ['Sistema Operativo', data.os_name],
          ['Consultas Exitosas', data.queries_ok + '/' + data.queries_total],
          ['Paquetes / Procesos', data.packages_count + ' / ' + data.processes_count],
        ].map(([k, v]) => `<div class="metric"><span>${k}</span><strong>${v}</strong></div>`).join('');
      } catch (err) {
        status.textContent = "❌ Error: " + err.message;
      } finally {
        btn.disabled = false;
      }
    }

    function downloadJson() {
      if (!lastInventory) return;
      const blob = new Blob([JSON.stringify(lastInventory, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'cloudmove-osquery-inventory.json';
      a.click();
    }
  </script>
</body>
</html>
"""


def launch_local_ui(output_path: str, port: int = 8765) -> int:
    """Levanta una interfaz web local para ejecutar el recolector con un clic."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(LOCAL_UI_HTML.encode("utf-8"))

        def do_POST(self) -> None:
            if self.path == "/api/scan-and-upload":
                try:
                    doc = collect_osquery_inventory(require_root=False)
                    out = Path(output_path).expanduser().resolve()
                    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

                    session_id = None
                    try:
                        uploaded = upload_to_cloudmove(doc)
                        session_id = uploaded.get("session_id")
                    except Exception:
                        session_id = "Guardado localmente (Backend offline)"

                    payload = {
                        "hostname": doc["asset"]["hostname"],
                        "os_name": f"{doc['asset']['os'].get('name', 'Linux')} {doc['asset']['os'].get('version', '')}".strip(),
                        "queries_ok": doc["collection"]["successful_query_count"],
                        "queries_total": doc["collection"]["query_count"],
                        "packages_count": len(doc["software"]["deb_packages"]),
                        "processes_count": len(doc["runtime"]["processes"]),
                        "saved_path": str(out),
                        "session_id": session_id,
                        "inventory": doc,
                    }
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                except Exception as exc:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        url = f"http://127.0.0.1:{port}"
        print(f"Interfaz de recolección CloudMove activa en: {url}")
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nCerrando interfaz local.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="cloudmove-osquery-inventory.json",
        help="Ruta del archivo JSON de salida",
    )
    parser.add_argument(
        "--require-root",
        action="store_true",
        help="Exigir ejecución con sudo/root",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Enviar automáticamente el inventario recolectado al backend de CloudMove y abrir el navegador",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Abrir interfaz visual interactiva en el navegador para escanear este dispositivo",
    )
    args = parser.parse_args()

    if args.ui:
        return launch_local_ui(args.output)

    try:
        document = collect_osquery_inventory(
            require_root=args.require_root,
            on_progress=lambda name, idx, total: print(f"[{idx}/{total}] Consultando tabla osquery: {name}..."),
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        output.chmod(0o600)
    except OSError:
        pass

    print(f"Inventario guardado en: {output}")
    print(f"Equipo: {document['asset']['hostname']}")
    print(
        f"Consultas exitosas: "
        f"{document['collection']['successful_query_count']}/{document['collection']['query_count']}"
    )
    print(f"Consultas con errores: {len(document['collection']['errors'])}")

    if args.analyze:
        try:
            res = upload_to_cloudmove(document)
            print(f"Analizado en CloudMove (Sesión: {res.get('session_id')})")
            webbrowser.open("http://localhost:5173")
        except Exception as exc:
            print(f"AVISO: No se pudo subir automáticamente a CloudMove: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
