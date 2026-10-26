#!/usr/bin/env python3
"""
Instalador y verificador multiplataforma desacoplado de osquery para CloudMove.

 Capacidades:
1. Consulta dinámicamente el catálogo oficial de lanzamientos de osquery en la web
   (GitHub Releases API + fallback determinista con digests SHA-256 oficiales).
2. Detecta el sistema operativo (Linux, Windows, macOS) y la arquitectura del PC
   (x86_64/amd64, aarch64/arm64).
3. Selecciona el paquete adecuado para el equipo actual priorizando paquetes
   portables en espacio de usuario (.tar.gz / .zip) que no requieren root/admin.
4. Verifica el hash SHA-256 del archivo descargado, valida rutas contra Path Traversal
   e instala en el directorio local del usuario.
5. Ejecuta una prueba funcional (smoke test SQL) con `osqueryi` para certificar
   que el binario funciona correctamente antes de iniciar el escaneo completo.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION = "5.23.1"
BASE_URL = f"https://github.com/osquery/osquery/releases/download/{VERSION}"
GITHUB_RELEASE_API = f"https://api.github.com/repos/osquery/osquery/releases/tags/{VERSION}"
GITHUB_LATEST_API = "https://api.github.com/repos/osquery/osquery/releases/latest"

# Directorios locales en espacio de usuario (sin requerir root/administrador)
if platform.system() == "Windows":
    _LOCAL_BASE = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "CloudMove"
    INSTALL_DIR = _LOCAL_BASE / "osquery"
    BIN_DIR = _LOCAL_BASE / "bin"
    BINARY_NAME = "osqueryi.exe"
else:
    INSTALL_DIR = Path.home() / ".local" / "share" / "cloudmove" / "osquery"
    BIN_DIR = Path.home() / ".local" / "bin"
    BINARY_NAME = "osqueryi"

# Catálogo oficial de respaldo (v5.23.1) con sus hashes SHA-256 verificados
FALLBACK_RELEASE_ASSETS: List[Dict[str, Any]] = [
    {
        "name": f"osquery-{VERSION}_1.linux_x86_64.tar.gz",
        "os": "linux",
        "arch": "x86_64",
        "format": "tar.gz",
        "portable": True,
        "url": f"{BASE_URL}/osquery-{VERSION}_1.linux_x86_64.tar.gz",
        "sha256": "0f37a478a1dbda24b67c81551e32d734b392c5a2f5deb156bf1c41ca204cfa67",
    },
    {
        "name": f"osquery-{VERSION}_1.linux_aarch64.tar.gz",
        "os": "linux",
        "arch": "aarch64",
        "format": "tar.gz",
        "portable": True,
        "url": f"{BASE_URL}/osquery-{VERSION}_1.linux_aarch64.tar.gz",
        "sha256": "9ae763820166f75f19970b5147b1930a308865a923ab127f4b8bbaea7b69962a",
    },
    {
        "name": f"osquery_{VERSION}-1.linux_amd64.deb",
        "os": "linux",
        "arch": "x86_64",
        "format": "deb",
        "portable": False,
        "url": f"{BASE_URL}/osquery_{VERSION}-1.linux_amd64.deb",
        "sha256": "1431a9a6394657eba3cdd3476a462a6fe9721fc3664a70f23efcf7e37816787a",
    },
    {
        "name": f"osquery_{VERSION}-1.linux_arm64.deb",
        "os": "linux",
        "arch": "aarch64",
        "format": "deb",
        "portable": False,
        "url": f"{BASE_URL}/osquery_{VERSION}-1.linux_arm64.deb",
        "sha256": "062df9b6432ca1b374e80b24b54f027e224f1300d8bf6338182ec40f41b7975d",
    },
    {
        "name": f"osquery-{VERSION}-1.linux.x86_64.rpm",
        "os": "linux",
        "arch": "x86_64",
        "format": "rpm",
        "portable": False,
        "url": f"{BASE_URL}/osquery-{VERSION}-1.linux.x86_64.rpm",
        "sha256": "500e3ba0eb0f2087002acbb82481320f7c131e217f5b525df1c5b4490c43bf4f",
    },
    {
        "name": f"osquery-{VERSION}-1.linux.aarch64.rpm",
        "os": "linux",
        "arch": "aarch64",
        "format": "rpm",
        "portable": False,
        "url": f"{BASE_URL}/osquery-{VERSION}-1.linux.aarch64.rpm",
        "sha256": "499d3009647c42013c42043ac08bad6cc2aa0fe2f8da53b45a3fa601563b9df0",
    },
    {
        "name": f"osquery-{VERSION}.windows_x86_64.zip",
        "os": "windows",
        "arch": "x86_64",
        "format": "zip",
        "portable": True,
        "url": f"{BASE_URL}/osquery-{VERSION}.windows_x86_64.zip",
        "sha256": "7bd411050ef6b5aae1b23956aec0dc5ce6e800c5656f0cd463ac70a6e1bdf30b",
    },
    {
        "name": f"osquery-{VERSION}.windows_arm64.zip",
        "os": "windows",
        "arch": "aarch64",
        "format": "zip",
        "portable": True,
        "url": f"{BASE_URL}/osquery-{VERSION}.windows_arm64.zip",
        "sha256": "0913d05cc3fc92dd9253c945caacde10a776408f267cc1cc853a05de24dba900",
    },
    {
        "name": f"osquery-{VERSION}.msi",
        "os": "windows",
        "arch": "x86_64",
        "format": "msi",
        "portable": False,
        "url": f"{BASE_URL}/osquery-{VERSION}.msi",
        "sha256": "bb3adc9f32f257147855404d24bceebcd8baf6e65f4d4ca43e186f4a85fa6ed3",
    },
    {
        "name": f"osquery-{VERSION}_1.macos_arm64.tar.gz",
        "os": "darwin",
        "arch": "aarch64",
        "format": "tar.gz",
        "portable": True,
        "url": f"{BASE_URL}/osquery-{VERSION}_1.macos_arm64.tar.gz",
        "sha256": "5484f0b62e05a7b2fa9d6e43f038915ea2b7ce063d59bd671ede0cf8dd0552da",
    },
    {
        "name": f"osqueryd-macos-bare-{VERSION}.tar.gz",
        "os": "darwin",
        "arch": "x86_64",
        "format": "tar.gz",
        "portable": True,
        "url": f"{BASE_URL}/osqueryd-macos-bare-{VERSION}.tar.gz",
        "sha256": "8c10f293def8cda9734a4d8e734fac8d271032868f14c7bc4fcef789832602b6",
    },
    {
        "name": f"osquery-{VERSION}.pkg",
        "os": "darwin",
        "arch": "universal",
        "format": "pkg",
        "portable": False,
        "url": f"{BASE_URL}/osquery-{VERSION}.pkg",
        "sha256": "9f40cea0358759ab2ee871c577055657e3cc2c7cbe5c1247f764245941178aa6",
    },
]


def detect_pc_platform() -> Dict[str, str]:
    """Detecta y normaliza el sistema operativo y arquitectura del equipo actual."""
    raw_sys = platform.system().lower()
    if raw_sys.startswith("linux"):
        norm_os = "linux"
        os_label = "Linux"
    elif raw_sys.startswith("win"):
        norm_os = "windows"
        os_label = "Windows"
    elif raw_sys.startswith("darwin") or raw_sys.startswith("mac"):
        norm_os = "darwin"
        os_label = "macOS"
    else:
        norm_os = raw_sys
        os_label = platform.system()

    raw_arch = platform.machine().lower()
    if raw_arch in ("x86_64", "amd64", "x64"):
        norm_arch = "x86_64"
    elif raw_arch in ("aarch64", "arm64", "armv8b", "armv8l"):
        norm_arch = "aarch64"
    else:
        norm_arch = raw_arch

    return {
        "os": norm_os,
        "os_label": os_label,
        "raw_system": platform.system(),
        "arch": norm_arch,
        "raw_machine": platform.machine(),
        "release": platform.release(),
        "hostname": platform.node(),
    }


def _classify_asset_name(name: str, url: str, digest_str: Optional[str] = None, size: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Clasifica un archivo publicado en la web de descargas de osquery según OS, arquitectura y formato."""
    lower = name.lower()
    if "dbgsym" in lower or "debuginfo" in lower:
        return None

    # Sistema operativo
    if "linux" in lower or lower.endswith(".deb") or lower.endswith(".rpm"):
        asset_os = "linux"
    elif "windows" in lower or lower.endswith(".msi") or lower.endswith(".nupkg"):
        asset_os = "windows"
    elif "macos" in lower or "darwin" in lower or lower.endswith(".pkg"):
        asset_os = "darwin"
    else:
        return None

    # Arquitectura
    if any(tok in lower for tok in ("x86_64", "amd64", "x64")):
        asset_arch = "x86_64"
    elif any(tok in lower for tok in ("aarch64", "arm64")):
        asset_arch = "aarch64"
    elif lower.endswith(".msi"):
        asset_arch = "x86_64"
    elif lower.endswith(".pkg") or "macos-bare" in lower:
        asset_arch = "universal"
    else:
        asset_arch = "unknown"

    # Formato y si es extraíble en espacio de usuario (portable)
    if lower.endswith(".tar.gz"):
        fmt = "tar.gz"
        portable = True
    elif lower.endswith(".zip"):
        fmt = "zip"
        portable = True
    elif lower.endswith(".deb"):
        fmt = "deb"
        portable = False
    elif lower.endswith(".rpm"):
        fmt = "rpm"
        portable = False
    elif lower.endswith(".msi"):
        fmt = "msi"
        portable = False
    elif lower.endswith(".pkg"):
        fmt = "pkg"
        portable = False
    elif lower.endswith(".nupkg"):
        fmt = "nupkg"
        portable = False
    else:
        fmt = "binary"
        portable = False

    sha256 = None
    if digest_str and digest_str.startswith("sha256:"):
        sha256 = digest_str.split("sha256:", 1)[1].strip()

    return {
        "name": name,
        "os": asset_os,
        "arch": asset_arch,
        "format": fmt,
        "portable": portable,
        "url": url,
        "sha256": sha256,
        "size_bytes": size,
    }


def fetch_available_release_assets(timeout: int = 10) -> Tuple[List[Dict[str, Any]], str]:
    """
    Consulta en vivo la web de descargas oficial de osquery (GitHub Releases API)
    para obtener todos los sistemas operativos y paquetes disponibles.
    Si no hay salida a la API o hay límite de tasa, usa el catálogo verificado local.
    """
    for api_url in (GITHUB_RELEASE_API, GITHUB_LATEST_API):
        try:
            req = urllib.request.Request(
                api_url,
                headers={
                    "User-Agent": "CloudMove-Discovery-Agent/1.0",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            raw_assets = payload.get("assets") or []
            classified: List[Dict[str, Any]] = []
            for item in raw_assets:
                parsed = _classify_asset_name(
                    name=item.get("name", ""),
                    url=item.get("browser_download_url", ""),
                    digest_str=item.get("digest"),
                    size=item.get("size"),
                )
                if parsed:
                    classified.append(parsed)
            if classified:
                return classified, f"live_web_catalog ({api_url})"
        except Exception:
            continue

    return list(FALLBACK_RELEASE_ASSETS), f"fallback_verified_catalog (v{VERSION})"


def select_asset_for_current_pc(
    assets: Optional[List[Dict[str, Any]]] = None,
    pc_info: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Selecciona el archivo instalador/portable óptimo para el PC actual a partir
    de los paquetes disponibles en la web de descarga.
    """
    pc = pc_info or detect_pc_platform()
    if assets is None:
        assets, _ = fetch_available_release_assets()

    target_os = pc["os"]
    target_arch = pc["arch"]

    # 1. Priorizar paquete portable (.tar.gz / .zip) exacto para OS + Arch (no requiere sudo/admin)
    for asset in assets:
        if asset["os"] == target_os and asset["arch"] == target_arch and asset["portable"]:
            return asset

    # 2. En macOS Intel o universal, permitir paquete universal/bare
    if target_os == "darwin":
        for asset in assets:
            if asset["os"] == "darwin" and asset["portable"]:
                return asset

    # 3. Alternativa: cualquier paquete coincidente con OS y Arch (.deb, .rpm, .msi, .pkg)
    for asset in assets:
        if asset["os"] == target_os and asset["arch"] in (target_arch, "universal"):
            return asset

    raise RuntimeError(
        f"No se encontró un paquete de osquery compatible con este PC "
        f"(OS={pc['raw_system']}, Arch={pc['raw_machine']})."
    )


def find_existing_osquery() -> Optional[str]:
    """
    Busca si osqueryi ya está instalado en el sistema o en el directorio local del agente.
    Nota importante: NO usar `.resolve()` sobre el enlace simbólico `osqueryi`, ya que en
    Linux/macOS `osqueryi` es un symlink hacia `osqueryd` y el binario inspecciona `argv[0]`
    para ejecutarse en modo interactivo sin exigir pidfile de demonio.
    """
    # 1. Binario en el PATH del sistema
    system_bin = shutil.which("osqueryi") or shutil.which("osqueryi.exe")
    if system_bin and Path(system_bin).exists():
        return str(Path(system_bin).absolute())

    # 2. Binario en rutas habituales del sistema operativo
    common_paths = [
        BIN_DIR / BINARY_NAME,
        Path("/usr/bin/osqueryi"),
        Path("/usr/local/bin/osqueryi"),
        Path("/opt/osquery/bin/osqueryi"),
        Path("C:/Program Files/osquery/osqueryi.exe"),
    ]
    for candidate in common_paths:
        if candidate.exists():
            return str(candidate.absolute())

    # 3. Binario previamente extraído en INSTALL_DIR
    if INSTALL_DIR.exists():
        found = next(
            (p for p in INSTALL_DIR.rglob(BINARY_NAME) if p.exists()),
            None,
        )
        if found:
            return str(found.absolute())

    return None


def verify_osquery_binary(binary_path: str) -> Dict[str, Any]:
    """
    Ejecuta una prueba real (smoke test) sobre el binario `osqueryi` para confirmar
    que responde en el PC actual y puede consultar tablas del sistema.
    """
    version_proc = subprocess.run(
        [binary_path, "--version"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    version_text = (version_proc.stdout or version_proc.stderr).strip()

    test_sql = "SELECT version, build_platform, build_distro FROM osquery_info LIMIT 1;"
    query_proc = subprocess.run(
        [binary_path, "--json", test_sql],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if query_proc.returncode != 0:
        raise RuntimeError(
            f"La prueba funcional de osqueryi falló (código {query_proc.returncode}): "
            f"{(query_proc.stderr or query_proc.stdout)[:300]}"
        )

    rows = json.loads(query_proc.stdout.strip() or "[]")
    info_row = rows[0] if rows and isinstance(rows, list) else {}

    return {
        "verified": True,
        "binary_path": binary_path,
        "version_output": version_text,
        "osquery_info": info_row,
    }


def _compute_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_archive_safely(archive_path: Path, archive_format: str, dest_dir: Path) -> None:
    """
    Extrae archivos .tar.gz o .zip validando que ninguna ruta escape del directorio destino.
    Convierte enlaces simbólicos absolutos internos del paquete (ej. `usr/bin/osqueryi -> /opt/osquery/bin/osqueryd`)
    en enlaces relativos seguros dentro de `dest_dir` para evitar `AbsoluteLinkError` en Python 3.12+
    y permitir la ejecución en espacio de usuario sin depender de `/opt/osquery` del sistema.
    """
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    if archive_format == "tar.gz":
        with tarfile.open(archive_path, "r:gz") as tar:
            safe_members: List[tarfile.TarInfo] = []
            for member in tar.getmembers():
                rel_member_str = member.name.lstrip("/").lstrip("./")
                if not rel_member_str:
                    continue
                path = Path(rel_member_str)
                if path.is_absolute() or ".." in path.parts:
                    raise RuntimeError(
                        f"El paquete contiene una ruta insegura ('{member.name}'); se canceló la extracción."
                    )
                member.name = rel_member_str

                if member.issym() or member.islnk():
                    raw_link = member.linkname
                    if Path(raw_link).is_absolute() or raw_link.startswith("/"):
                        # Enlace absoluto dentro del árbol del paquete (ej. /opt/osquery/bin/osqueryd)
                        link_rel_parts = Path(raw_link.lstrip("/")).parts
                        if ".." in link_rel_parts:
                            raise RuntimeError(
                                f"El paquete contiene un enlace simbólico inseguro ('{raw_link}'); se canceló la extracción."
                            )
                        target_inside_dest = (dest_dir / Path(*link_rel_parts)).resolve()
                        if not str(target_inside_dest).startswith(str(dest_dir)):
                            raise RuntimeError(
                                f"El enlace simbólico '{raw_link}' apunta fuera del directorio de instalación."
                            )
                        link_parent = (dest_dir / path).parent.resolve()
                        member.linkname = os.path.relpath(target_inside_dest, link_parent)
                    else:
                        # Verificar que el enlace relativo no escape de dest_dir
                        link_parent = (dest_dir / path).parent.resolve()
                        resolved_target = (link_parent / raw_link).resolve()
                        if not str(resolved_target).startswith(str(dest_dir)):
                            raise RuntimeError(
                                f"El enlace simbólico relativo '{raw_link}' escapa del directorio de instalación."
                            )

                safe_members.append(member)

            try:
                tar.extractall(dest_dir, members=safe_members, filter="data")
            except TypeError:
                # Compatibilidad con versiones de Python anteriores a 3.12 sin parámetro filter
                tar.extractall(dest_dir, members=safe_members)
    elif archive_format == "zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member_name in zf.namelist():
                path = Path(member_name)
                if path.is_absolute() or ".." in path.parts:
                    raise RuntimeError(
                        "El paquete ZIP contiene una ruta insegura; se canceló la extracción."
                    )
            zf.extractall(dest_dir)
    else:
        raise RuntimeError(f"Formato de archivo no soportado para extracción directa: {archive_format}")


def install_osquery(force_download: bool = False) -> str:
    """
    Comprueba si osquery está disponible en el PC; si no lo está (o si se solicita
    `force_download`), consulta el catálogo web de descargas de osquery, descarga el
    paquete correspondiente al OS y arquitectura del PC, verifica su SHA-256, lo
    instala en espacio de usuario y ejecuta una prueba de funcionamiento.
    """
    if not force_download:
        existing = find_existing_osquery()
        if existing:
            verify_osquery_binary(existing)
            return existing

    pc_info = detect_pc_platform()
    assets, catalog_source = fetch_available_release_assets()
    selected = select_asset_for_current_pc(assets, pc_info)

    if not selected.get("portable"):
        raise RuntimeError(
            f"Se detectó el paquete '{selected['name']}' ({selected['url']}), "
            "que requiere instalador del sistema."
        )

    url = selected["url"]
    expected_sha256 = selected.get("sha256")
    archive_format = selected["format"]

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    INSTALL_DIR.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cloudmove-osquery-") as temp:
        archive = Path(temp) / selected["name"]
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "CloudMove-Discovery/1.0"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            with archive.open("wb") as output:
                shutil.copyfileobj(response, output)

        # Verificar integridad SHA-256 si el catálogo oficial provee digest
        actual_sha256 = _compute_sha256(archive)
        if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
            raise RuntimeError(
                f"Verificación SHA-256 fallida para '{selected['name']}'. "
                f"Esperado: {expected_sha256}, Obtenido: {actual_sha256}."
            )

        extracted = Path(temp) / "extracted"
        _extract_archive_safely(archive, archive_format, extracted)

        binaries = [
            path
            for path in extracted.rglob("osqueryi*")
            if path.is_file() and path.name in ("osqueryi", "osqueryi.exe")
        ]
        if not binaries:
            # En paquetes como osqueryd, el binario puede llamarse osqueryd y actuar como osqueryi
            binaries = [
                path
                for path in extracted.rglob("osqueryd*")
                if path.is_file() and path.name in ("osqueryd", "osqueryd.exe")
            ]

        if not binaries:
            raise RuntimeError(
                "El paquete se descargó, pero no contiene un ejecutable "
                "osqueryi reconocible. No se instaló."
            )

        # Conservar la estructura completa del paquete (incluyendo symlinks relativos)
        shutil.copytree(
            extracted,
            INSTALL_DIR,
            symlinks=True,
            dirs_exist_ok=True,
        )

    # Buscar primero el binario real (osqueryd u osqueryi archivo regular) para asignarle permisos +x
    real_binary = next(
        (
            p
            for p in INSTALL_DIR.rglob("osquery*")
            if p.is_file() and not p.is_symlink() and p.name in ("osqueryi", "osqueryi.exe", "osqueryd", "osqueryd.exe")
        ),
        None,
    )
    installed = next(
        (
            p
            for p in INSTALL_DIR.rglob("osqueryi*")
            if (p.exists() or p.is_symlink()) and p.name in ("osqueryi", "osqueryi.exe")
        ),
        None,
    ) or real_binary

    if installed is None and real_binary is None:
        raise RuntimeError("No se encontró osqueryi tras la extracción.")

    target_executable = installed or real_binary
    # Asegurar permisos de ejecución en sistemas POSIX y enlazar como `osqueryi` en ~/.local/bin
    if platform.system() != "Windows":
        bin_to_chmod = real_binary or target_executable
        if bin_to_chmod and bin_to_chmod.exists():
            current_mode = bin_to_chmod.stat().st_mode
            bin_to_chmod.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        link_path = BIN_DIR / BINARY_NAME
        link_target = real_binary or target_executable
        try:
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            link_path.symlink_to(link_target.resolve())
            target_executable = link_path
        except OSError:
            shutil.copy2(link_target.resolve(), link_path)
            target_executable = link_path

    # Ejecutar prueba funcional (smoke test) antes de dar por buena la instalación
    verify_osquery_binary(str(target_executable.absolute()))
    return str(target_executable.absolute())


def get_installer_status_report() -> Dict[str, Any]:
    """
    Devuelve el diagnóstico completo del PC actual, los paquetes disponibles en
    la web de osquery, el paquete seleccionado para este PC y el estado del binario.
    """
    pc_info = detect_pc_platform()
    assets, catalog_source = fetch_available_release_assets(timeout=6)
    selected_asset = None
    selection_error = None
    try:
        selected_asset = select_asset_for_current_pc(assets, pc_info)
    except Exception as exc:
        selection_error = str(exc)

    existing_bin = find_existing_osquery()
    smoke_test = None
    if existing_bin:
        try:
            smoke_test = verify_osquery_binary(existing_bin)
        except Exception as exc:
            smoke_test = {"verified": False, "error": str(exc)}

    return {
        "osquery_version_target": VERSION,
        "pc_platform": pc_info,
        "catalog_source": catalog_source,
        "available_web_assets_count": len(assets),
        "available_web_assets": assets,
        "recommended_asset_for_pc": selected_asset,
        "selection_error": selection_error,
        "osquery_installed": existing_bin is not None,
        "osquery_binary_path": existing_bin,
        "smoke_test": smoke_test,
    }
