#!/usr/bin/env python3
"""
Agente local desacoplado de CloudMove (`cloudmove_agent/app.py`).

Actúa como puente local autorizado entre el navegador web y el sistema operativo del usuario:
1. Consulta la web de lanzamientos de osquery para detectar los sistemas operativos disponibles.
2. Prepara o instala automáticamente el paquete de osquery adecuado para la arquitectura del PC.
3. Ejecuta una prueba funcional (smoke test) sobre `osqueryi`.
4. Ejecuta `cloudmove_osquery_export.py --allow-non-root` para escanear el equipo y generar el JSON.
5. Expone `/inventory` y sincroniza automáticamente el JSON con el backend de CloudMove.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Permitir importación tanto si se ejecuta desde `cloudmove_agent/` como desde la raíz del proyecto
AGENT_DIR = Path(__file__).resolve().parent
PROJECT = AGENT_DIR.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from osquery_installer import (  # noqa: E402
    detect_pc_platform,
    find_existing_osquery,
    get_installer_status_report,
    install_osquery,
    verify_osquery_binary,
)

COLLECTOR = PROJECT / "cloudmove_osquery_export.py"
# Guardamos el inventario generado por el agente en docs/cloudmove-osquery-agent-inventory.json
# para no sobrescribir nunca el archivo de muestra original del repositorio.
INVENTORY = PROJECT / "docs" / "cloudmove-osquery-agent-inventory.json"

app = FastAPI(
    title="CloudMove Local Discovery Agent",
    version="1.0.0",
    description="Puente local multiplataforma para instalar osquery, probar el binario y escanear el equipo.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class DiscoveryResult(BaseModel):
    status: str
    message: str
    inventory: str
    osquery_path: Optional[str] = None
    pc_platform: Optional[Dict[str, Any]] = None
    recommended_asset: Optional[Dict[str, Any]] = None
    smoke_test: Optional[Dict[str, Any]] = None
    hostname: Optional[str] = None
    cloudmove_session_id: Optional[str] = None


@app.get("/health")
def health_check():
    """Comprueba el estado del agente local, del recolector y de osquery en este PC."""
    report = get_installer_status_report()
    return {
        "status": "ok",
        "agent": "cloudmove_agent",
        "collector_exists": COLLECTOR.is_file(),
        "collector_path": str(COLLECTOR),
        "osquery_installed": report["osquery_installed"],
        "osquery_binary_path": report["osquery_binary_path"],
        "pc_platform": report["pc_platform"],
        "recommended_asset_for_pc": report["recommended_asset_for_pc"],
        "available_web_assets_count": report["available_web_assets_count"],
        "catalog_source": report["catalog_source"],
        "smoke_test": report["smoke_test"],
    }


@app.get("/catalog")
def get_osquery_web_catalog():
    """
    Devuelve la lista completa de paquetes disponibles en la web oficial de descargas
    de osquery y cuál corresponde al sistema operativo y arquitectura de este PC.
    """
    return get_installer_status_report()


@app.post("/discover", response_model=DiscoveryResult)
def run_discovery(force_reinstall: bool = Query(False, description="Forzar descarga e instalación local de osquery")):
    """
    Ejecuta las dos etapas del descubrimiento:
    1. Preparar/instalar osquery para el PC actual y ejecutar la prueba funcional.
    2. Ejecutar `cloudmove_osquery_export.py --allow-non-root` y generar el inventario JSON.
    """
    try:
        if not COLLECTOR.is_file():
            raise HTTPException(
                status_code=500,
                detail=f"No se encontró el recolector en '{COLLECTOR}'.",
            )

        # Etapa 1: comprobar o preparar osquery + prueba funcional (smoke test).
        osquery_path = install_osquery(force_download=force_reinstall)
        smoke = verify_osquery_binary(osquery_path)
        report = get_installer_status_report()

        # Etapa 2: ejecutar el recolector sin privilegios de administrador.
        INVENTORY.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["PATH"] = (
            str(Path(osquery_path).parent)
            + os.pathsep
            + str(Path.home() / ".local" / "bin")
            + os.pathsep
            + env.get("PATH", "")
        )

        command = [
            sys.executable,
            str(COLLECTOR),
            "--output",
            str(INVENTORY),
            "--allow-non-root",
            "--osquery-bin",
            str(osquery_path),
        ]

        result = subprocess.run(
            command,
            cwd=str(PROJECT),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Error desconocido")[-4000:]
            raise HTTPException(
                status_code=500,
                detail=f"El recolector falló:\n{detail}",
            )

        if not INVENTORY.is_file():
            raise HTTPException(
                status_code=500,
                detail="El recolector terminó, pero no generó el JSON esperado.",
            )

        # Leer hostname y sincronizar automáticamente con el backend de CloudMove si está activo
        doc = json.loads(INVENTORY.read_text(encoding="utf-8"))
        hostname = (doc.get("asset") or {}).get("hostname") or detect_pc_platform().get("hostname")
        session_id = None
        try:
            from cloudmove_osquery_export import upload_to_cloudmove
            uploaded = upload_to_cloudmove(doc)
            session_id = uploaded.get("session_id")
        except Exception:
            session_id = None

        return DiscoveryResult(
            status="completed",
            message=(
                f"osquery ({smoke.get('osquery_info', {}).get('version', '5.23.1')}) está preparado, "
                f"superó la prueba funcional y el escaneo de '{hostname}' terminó correctamente."
            ),
            inventory="/inventory",
            osquery_path=osquery_path,
            pc_platform=report.get("pc_platform"),
            recommended_asset=report.get("recommended_asset_for_pc"),
            smoke_test=smoke,
            hostname=hostname,
            cloudmove_session_id=session_id,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/inventory")
def download_inventory():
    """Permite descargar el JSON generado por el descubrimiento."""
    if not INVENTORY.is_file():
        raise HTTPException(
            status_code=404,
            detail="Todavía no hay un inventario generado.",
        )

    return FileResponse(
        path=INVENTORY,
        media_type="application/json",
        filename="cloudmove-osquery-inventory.json",
    )
