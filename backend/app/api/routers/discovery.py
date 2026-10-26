from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field

from app.config import AWS_OUTPUT_PATH, GCP_OUTPUT_PATH, PROJECT_ROOT
from app.discovery.cloud_live_discovery import (
    AWSLiveDiscoveryConnector,
    GCPLiveDiscoveryConnector,
    CloudInventoryReconciler,
)
from app.discovery.connectors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorTimeoutError,
)
from app.discovery.exporters import generate_markdown_report, generate_mermaid_diagram
from app.discovery.models import DATABASE_COLLECTOR_SPECS, OpenAudITCollectorAdapter
from app.discovery.osquery_parser import SUPPORTED_SCHEMAS
from app.discovery.storage import DEFAULT_OSQUERY_JSON_PATH, discovery_store
from app.discovery.terraform_bridge import (
    generate_discovery_aws_terraform,
    generate_discovery_gcp_terraform,
    generate_discovery_terraform,
)
from app.persistence.transactional_db import get_transactional_db

router = APIRouter(prefix="/api/v1/discovery", tags=["Discovery Analyzer"])

COLLECTOR_SCRIPT_PATH = PROJECT_ROOT / "cloudmove_osquery_export.py"

MAX_IMPORT_BYTES = 25 * 1024 * 1024  # 25 MiB limit


def _extract_json_from_multipart(body: bytes, content_type: str) -> tuple[bytes, str]:
    """Extract uploaded file bytes and filename from multipart/form-data without external C deps."""
    boundary_token = "boundary="
    if boundary_token not in content_type:
        raise ValueError("Encabezado multipart/form-data inválido: falta boundary.")
    boundary = content_type.split(boundary_token, 1)[1].split(";", 1)[0].strip().strip('"')
    delimiter = f"--{boundary}".encode("utf-8")
    parts = body.split(delimiter)

    for part in parts:
        if b"Content-Disposition:" not in part:
            continue
        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            continue
        raw_headers = part[:header_end].decode("utf-8", errors="replace")
        content = part[header_end + 4 :]
        if content.endswith(b"\r\n"):
            content = content[:-2]

        filename = "uploaded-osquery.json"
        if 'filename="' in raw_headers:
            filename = raw_headers.split('filename="', 1)[1].split('"', 1)[0] or filename

        # Check MIME inside part headers if present
        if "Content-Type:" in raw_headers:
            part_mime = raw_headers.split("Content-Type:", 1)[1].split("\r\n", 1)[0].strip().lower()
            if part_mime not in ("application/json", "text/json", "text/plain", "application/octet-stream"):
                raise PermissionError(f"Tipo MIME de archivo no permitido: '{part_mime}'. Use application/json.")

        return content.strip(), filename

    raise ValueError("No se encontró ningún archivo adjunto dentro del cuerpo multipart/form-data.")


def _build_session_response(session_record: Dict[str, Any], include_all_packages: bool = False) -> Dict[str, Any]:
    """Prepare the session response payload (avoiding redundant multi-megabyte duplication)."""
    norm = session_record["normalized_inventory"]
    sections = norm["sections"]
    sw = sections["software"]

    # Provide first 250 packages inline for instant rendering; full 4,320+ packages are queryable via /packages or export
    packages_inline = sw["packages"] if include_all_packages else sw["packages"][:250]

    tf_context = {
        "session_id": session_record["session_id"],
        "filename": session_record["filename"],
        "hostname": session_record["hostname"],
        "collected_at": session_record["collected_at"],
        "summary": norm["summary"],
        "sections": sections,
        "cmir": session_record.get("cmir"),
    }

    return {
        "session_id": session_record["session_id"],
        "filename": session_record["filename"],
        "imported_at": session_record["imported_at"],
        "hostname": session_record["hostname"],
        "collected_at": session_record["collected_at"],
        "schema_version": norm["schema_version"],
        "reimported": norm.get("reimported", False),
        "source": norm["source"],
        "summary": norm["summary"],
        "sections": {
            "hardware": sections["hardware"],
            "software": {
                **sw,
                "packages": packages_inline,
                "packages_inline_count": len(packages_inline),
                "packages_total_count": sw["package_count"],
            },
            "network": sections["network"],
            "runtime": sections["runtime"],
            "databases": sections["databases"],
            "assessment": sections["assessment"],
        },
        "issues": norm["issues"],
        "graph": session_record["graph"],
        "cmir_validation": session_record["cmir_validation"],
        "terraform": {
            "replatform": generate_discovery_aws_terraform(tf_context, strategy="replatform"),
            "rehost": generate_discovery_aws_terraform(tf_context, strategy="rehost"),
        },
    }


@router.get("/collectors")
def get_discovery_collectors():
    """Return available and architecturally prepared discovery collectors."""
    open_audit = OpenAudITCollectorAdapter()
    return {
        "active_collectors": [
            {
                "id": "osquery",
                "name": "osquery Host Discovery Collector",
                "status": "active",
                "supported_schemas": sorted(SUPPORTED_SCHEMAS),
            },
            {
                "id": "aws_live_discovery",
                "name": "AWS Live Cloud Discovery Connector (boto3 STS/EC2/RDS/S3/IAM)",
                "status": "active",
                "supported_schemas": ["cmir-2.1"],
            },
            {
                "id": "gcp_live_discovery",
                "name": "GCP Live Cloud Discovery Connector (Cloud Asset API / Compute / SQL / GCS / IAM)",
                "status": "active",
                "supported_schemas": ["cmir-2.1"],
            },
        ],
        "prepared_collectors": [
            {
                "id": open_audit.collector_id,
                "name": open_audit.collector_name,
                "status": "prepared_interface",
                "supported_schemas": open_audit.supported_schemas,
            },
            *[spec.model_dump() for spec in DATABASE_COLLECTOR_SPECS.values()],
        ],
        "default_local_inventory_available": DEFAULT_OSQUERY_JSON_PATH.is_file(),
        "default_local_inventory_name": DEFAULT_OSQUERY_JSON_PATH.name,
    }


@router.get("/sessions")
def list_discovery_sessions():
    """List all imported discovery sessions."""
    return {
        "sessions": discovery_store.list_sessions(),
        "default_local_available": DEFAULT_OSQUERY_JSON_PATH.is_file(),
    }


@router.get("/latest")
def get_latest_discovery_session(include_all_packages: bool = Query(False)):
    """Return the latest imported discovery session, or auto-load the local osquery inventory if present."""
    try:
        session = discovery_store.get_latest_or_default()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not session:
        raise HTTPException(
            status_code=404,
            detail="No hay ningún análisis de discovery cargado actualmente. Importe un archivo JSON de osquery.",
        )
    return _build_session_response(session, include_all_packages=include_all_packages)


@router.post("/import-local")
def import_local_osquery_inventory(include_all_packages: bool = Query(False)):
    """Load and analyze the real osquery inventory located at docs/cloudmove-osquery-inventory.json."""
    if not DEFAULT_OSQUERY_JSON_PATH.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró el archivo local en {DEFAULT_OSQUERY_JSON_PATH}.",
        )
    try:
        session = discovery_store.import_from_path(DEFAULT_OSQUERY_JSON_PATH)
        return _build_session_response(session, include_all_packages=include_all_packages)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/import")
async def import_discovery_inventory(request: Request, include_all_packages: bool = Query(False)):
    """Import, validate, parse, and normalize an osquery inventory JSON (via multipart upload or JSON body)."""
    content_type = (request.headers.get("content-type") or "application/json").lower()

    allowed_prefixes = (
        "application/json",
        "text/json",
        "text/plain",
        "multipart/form-data",
    )
    if not any(content_type.startswith(p) for p in allowed_prefixes):
        raise HTTPException(
            status_code=415,
            detail={
                "code": "UNSUPPORTED_MEDIA_TYPE",
                "message": f"Tipo MIME '{content_type}' no soportado. Envíe un archivo JSON (application/json o multipart/form-data).",
            },
        )

    raw_body = await request.body()
    if not raw_body:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EMPTY_PAYLOAD",
                "message": "El archivo o cuerpo de la petición está vacío.",
            },
        )

    if len(raw_body) > MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": f"El archivo excede el tamaño máximo permitido de {MAX_IMPORT_BYTES // (1024 * 1024)} MiB.",
            },
        )

    filename = request.headers.get("x-filename", "uploaded-inventory.json")
    json_bytes = raw_body

    if content_type.startswith("multipart/form-data"):
        try:
            json_bytes, filename = _extract_json_from_multipart(raw_body, request.headers.get("content-type", ""))
        except PermissionError as exc:
            raise HTTPException(
                status_code=415,
                detail={"code": "INVALID_FILE_MIME", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "MALFORMED_MULTIPART", "message": str(exc)},
            ) from exc

    if not json_bytes:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_JSON_FILE", "message": "El archivo JSON enviado está vacío."},
        )

    try:
        decoded_text = json_bytes.decode("utf-8")
        parsed_payload = json.loads(decoded_text)
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_ENCODING", "message": "El archivo debe estar codificado en UTF-8 válido."},
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_JSON_SYNTAX",
                "message": f"El archivo no es un JSON válido (línea {exc.lineno}, columna {exc.colno}): {exc.msg}",
            },
        ) from exc

    # Unwrap optional {"filename": "...", "inventory": {...}} envelope if sent by JSON client
    if isinstance(parsed_payload, dict) and "inventory" in parsed_payload and "schema_version" not in parsed_payload:
        filename = str(parsed_payload.get("filename") or filename)
        parsed_payload = parsed_payload["inventory"]

    digest = hashlib.sha256(json_bytes).hexdigest()

    try:
        session = discovery_store.import_raw_inventory(
            raw_data=parsed_payload,
            filename=filename,
            deduplicate_by_hash=False,
            raw_bytes_digest=digest,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SCHEMA_VALIDATION_ERROR",
                "message": str(exc),
            },
        ) from exc

    return _build_session_response(session, include_all_packages=include_all_packages)


@router.get("/sessions/{session_id}")
def get_discovery_session(session_id: str, include_all_packages: bool = Query(False)):
    """Retrieve a previously imported discovery session by ID."""
    session = discovery_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sesión de discovery '{session_id}' no encontrada.")
    return _build_session_response(session, include_all_packages=include_all_packages)


@router.get("/sessions/{session_id}/packages")
def query_session_packages(
    session_id: str,
    q: Optional[str] = Query(None, description="Search by package name or version"),
    section: Optional[str] = Query(None, description="Filter by Debian package section"),
    arch: Optional[str] = Query(None, description="Filter by architecture (amd64, all, etc.)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Search and paginate through all installed packages in a discovery session."""
    session = discovery_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sesión '{session_id}' no encontrada.")

    pkgs = session["normalized_inventory"]["sections"]["software"]["packages"]
    filtered = pkgs

    if section and section != "all":
        filtered = [p for p in filtered if p.get("section") == section]
    if arch and arch != "all":
        filtered = [p for p in filtered if p.get("arch") == arch]
    if q and q.strip():
        needle = q.strip().lower()
        filtered = [
            p for p in filtered
            if needle in (p.get("name") or "").lower()
            or needle in (p.get("version") or "").lower()
            or needle in (p.get("section") or "").lower()
        ]

    total = len(filtered)
    sliced = filtered[offset : offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": sliced,
    }


@router.get("/sessions/{session_id}/processes")
def query_session_processes(
    session_id: str,
    q: Optional[str] = Query(None, description="Search by PID, name or executable path"),
    only_network: bool = Query(False, description="Only processes with listening ports or open sockets"),
    exclude_kernel: bool = Query(False, description="Exclude kernel threads without binary path"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Search and filter runtime processes in a discovery session."""
    session = discovery_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sesión '{session_id}' no encontrada.")

    procs = session["normalized_inventory"]["sections"]["runtime"]["processes"]
    filtered = procs

    if only_network:
        filtered = [p for p in filtered if p.get("listening_ports") or p.get("open_socket_count", 0) > 0]
    if exclude_kernel:
        filtered = [p for p in filtered if not p.get("is_kernel_thread")]
    if q and q.strip():
        needle = q.strip().lower()
        filtered = [
            p for p in filtered
            if needle in str(p.get("pid") or "").lower()
            or needle in (p.get("name") or "").lower()
            or needle in (p.get("path") or "").lower()
        ]

    return {
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "items": filtered[offset : offset + limit],
    }


@router.get("/sessions/{session_id}/services")
def query_session_services(
    session_id: str,
    q: Optional[str] = Query(None, description="Search by unit ID or description"),
    active_state: Optional[str] = Query(None, description="Filter by active_state (active, inactive, failed)"),
    unit_type: Optional[str] = Query(None, description="Filter by unit type (service, socket, timer, target)"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Search and filter systemd units in a discovery session."""
    session = discovery_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sesión '{session_id}' no encontrada.")

    services = session["normalized_inventory"]["sections"]["software"]["services"]
    filtered = services

    if active_state and active_state != "all":
        filtered = [s for s in filtered if s.get("active_state") == active_state]
    if unit_type and unit_type != "all":
        filtered = [s for s in filtered if s.get("unit_type") == unit_type]
    if q and q.strip():
        needle = q.strip().lower()
        filtered = [
            s for s in filtered
            if needle in (s.get("id") or "").lower()
            or needle in (s.get("description") or "").lower()
            or needle in (s.get("fragment_path") or "").lower()
        ]

    return {
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "items": filtered[offset : offset + limit],
    }


@router.get("/sessions/{session_id}/export")
def export_discovery_session(
    session_id: str,
    format: str = Query("json", description="Export format: json | md | mmd | cmir | tf"),
    target_provider: str = Query("aws", description="Target provider when format=tf: aws | gcp"),
):
    """Export the normalized discovery inventory, Markdown report, Mermaid diagram, or CMIR model."""
    session = discovery_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sesión '{session_id}' no encontrada.")

    fmt = format.lower().strip()
    hostname = session.get("hostname") or "host"
    norm = session["normalized_inventory"]

    if fmt == "json":
        return JSONResponse(
            content=norm,
            headers={
                "Content-Disposition": f'attachment; filename="cloudmove-normalized-{hostname}.json"'
            },
        )
    if fmt == "cmir":
        return JSONResponse(
            content=session["cmir"],
            headers={
                "Content-Disposition": f'attachment; filename="cloudmove-cmir-{hostname}.json"'
            },
        )
    if fmt == "md":
        md_text = generate_markdown_report(norm)
        return PlainTextResponse(
            content=md_text,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="cloudmove-discovery-report-{hostname}.md"'
            },
        )
    if fmt == "mmd":
        mmd_text = generate_mermaid_diagram(norm)
        return PlainTextResponse(
            content=mmd_text,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="cloudmove-discovery-diagram-{hostname}.mmd"'
            },
        )
    if fmt == "tf":
        provider_clean = target_provider.lower().strip()
        if provider_clean not in ("aws", "gcp"):
            raise HTTPException(status_code=400, detail="Proveedor no soportado. Use 'aws' o 'gcp'.")
        tf_context = {
            "session_id": session["session_id"],
            "filename": session["filename"],
            "hostname": hostname,
            "collected_at": session["collected_at"],
            "summary": norm["summary"],
            "sections": norm["sections"],
            "cmir": session.get("cmir"),
        }
        tf_bundle = generate_discovery_terraform(tf_context, strategy="replatform", target_provider=provider_clean)
        return PlainTextResponse(
            content=tf_bundle["iac_code"],
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="cloudmove-{provider_clean}-{hostname}.tf"'
            },
        )

    raise HTTPException(
        status_code=400,
        detail=f"Formato de exportación '{format}' no soportado. Use json, cmir, md, mmd o tf.",
    )


@router.get("/sessions/{session_id}/terraform")
@router.post("/sessions/{session_id}/terraform")
def generate_session_terraform(
    session_id: str,
    strategy: str = Query("replatform", description="Migration strategy: replatform | rehost"),
    target_provider: str = Query("aws", description="Target cloud provider: aws | gcp"),
    write_files: bool = Query(False, description="Persist modular .tf files into generated/aws/ or generated/gcp/"),
):
    """
    Generate modular AWS or GCP Terraform (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`)
    and step-by-step JSON->CMIR->Provider traceability for a discovery session.
    """
    provider_clean = target_provider.lower().strip()
    if provider_clean not in ("aws", "gcp"):
        raise HTTPException(
            status_code=400,
            detail=f"Proveedor '{target_provider}' no admitido. Proveedores destino admitidos: aws, gcp.",
        )

    session = discovery_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sesión '{session_id}' no encontrada.")

    norm = session["normalized_inventory"]
    tf_context = {
        "session_id": session["session_id"],
        "filename": session["filename"],
        "hostname": session["hostname"],
        "collected_at": session["collected_at"],
        "summary": norm["summary"],
        "sections": norm["sections"],
        "cmir": session.get("cmir"),
    }

    result = generate_discovery_terraform(tf_context, strategy=strategy, target_provider=provider_clean)

    if write_files:
        out_dir = GCP_OUTPUT_PATH.parent if provider_clean == "gcp" else AWS_OUTPUT_PATH.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        for fname, fcontent in result["files"].items():
            (out_dir / fname).write_text(fcontent, encoding="utf-8")
        result["written_to_dir"] = str(out_dir)

    return result


def _load_osquery_installer_module():
    installer_path = PROJECT_ROOT / "cloudmove_agent" / "osquery_installer.py"
    if not installer_path.is_file():
        raise RuntimeError(f"No se encontró el instalador en '{installer_path}'.")
    spec = importlib.util.spec_from_file_location("cloudmove_osquery_installer", installer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("No se pudo cargar cloudmove_agent/osquery_installer.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@router.get("/osquery-catalog")
def get_osquery_installer_catalog():
    """
    Inspect the official osquery web release assets, detect the current PC's OS and
    architecture, and return the recommended package and smoke-test status.
    """
    try:
        installer_mod = _load_osquery_installer_module()
        return installer_mod.get_installer_status_report()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error al consultar el catálogo de instaladores osquery: {exc}",
        ) from exc


@router.get("/collector-script")
def download_collector_script():
    """
    Download `cloudmove_osquery_export.py` so any user can execute it on their
    device (`python3 cloudmove_osquery_export.py --ui` or `--analyze`).
    """
    if not COLLECTOR_SCRIPT_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró el recolector en '{COLLECTOR_SCRIPT_PATH}'.",
        )
    content = COLLECTOR_SCRIPT_PATH.read_text(encoding="utf-8")
    return PlainTextResponse(
        content=content,
        media_type="text/x-python; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="cloudmove_osquery_export.py"'
        },
    )


@router.post("/collect-device")
def collect_live_device_inventory(
    persist_json: bool = Query(True, description="Persist collected JSON snapshot in backend/data/discovery_sessions"),
):
    """
    Two-stage automated discovery:
    1. Prepare/install osquery for the current PC's OS & architecture and run smoke test.
    2. Execute `cloudmove_osquery_export.py` via `osqueryi`, parse and normalize into CloudMove.
    """
    if not COLLECTOR_SCRIPT_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró el script recolector en '{COLLECTOR_SCRIPT_PATH}'.",
        )

    try:
        installer_mod = _load_osquery_installer_module()
        osquery_bin = installer_mod.install_osquery(force_download=False)
        smoke_test = installer_mod.verify_osquery_binary(osquery_bin)

        spec = importlib.util.spec_from_file_location("cloudmove_osquery_export", COLLECTOR_SCRIPT_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("No se pudo cargar el módulo cloudmove_osquery_export.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        document = mod.collect_osquery_inventory(require_root=False, osquery_bin=osquery_bin)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "OSQUERY_COLLECTION_FAILED",
                "message": str(exc),
                "remediation": (
                    "Verifique la conexión para descargar osquery o inicie cloudmove_agent "
                    "en el equipo objetivo."
                ),
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "DEVICE_SCAN_ERROR",
                "message": f"Error al preparar osquery o escanear el dispositivo: {exc}",
            },
        ) from exc

    hostname = (document.get("asset") or {}).get("hostname") or "local-device"
    raw_bytes = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    digest = hashlib.sha256(raw_bytes).hexdigest()
    filename = f"live-osquery-{hostname}.json"

    try:
        session = discovery_store.import_raw_inventory(
            raw_data=document,
            filename=filename,
            deduplicate_by_hash=False,
            raw_bytes_digest=digest,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "DISCOVERY_PARSE_ERROR",
                "message": f"Error al analizar el inventario recolectado del dispositivo: {exc}",
            },
        ) from exc

    resp = _build_session_response(session)
    resp["agent_smoke_test"] = smoke_test
    return resp


# ==============================================================================
# Live Cloud Infrastructure Discovery (AWS & GCP) with Reconciliation
# ==============================================================================


class AWSLiveDiscoveryRequest(BaseModel):
    regions: Optional[List[str]] = Field(default_factory=lambda: ["us-east-1"])
    profile_name: Optional[str] = Field(None)
    aws_access_key_id: Optional[str] = Field(None)
    aws_secret_access_key: Optional[str] = Field(None)
    aws_session_token: Optional[str] = Field(None)
    role_arn: Optional[str] = Field(None)


class GCPLiveDiscoveryRequest(BaseModel):
    project_id: Optional[str] = Field(None)
    zone: str = Field("us-central1-a")
    service_account_json: Optional[str] = Field(None)
    access_token: Optional[str] = Field(None)


@router.post("/cloud/aws")
def discover_live_aws_infrastructure(request: Optional[AWSLiveDiscoveryRequest] = None):
    """
    Execute real AWS live cloud discovery via boto3 (`sts`, `ec2`, `rds`, `s3`, `iam` with pagination),
    normalize into CMIR v2.1, reconcile against any previous snapshot for the same account/region,
    and persist in the ACID transactional database.
    Never converts an API/auth error into an empty inventory.
    """
    req = request or AWSLiveDiscoveryRequest()
    primary_region = (req.regions or ["us-east-1"])[0]
    connector = AWSLiveDiscoveryConnector(
        region=primary_region,
        profile_name=req.profile_name,
        role_arn=req.role_arn,
    )
    try:
        return connector.discover_live_account()
    except ConnectorAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AWS_AUTH_OR_PERMISSION_ERROR",
                "provider": "aws",
                "message": str(exc),
            },
        ) from exc
    except ConnectorTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "error_code": "AWS_API_TIMEOUT",
                "provider": "aws",
                "message": str(exc),
            },
        ) from exc
    except ConnectorError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "AWS_DISCOVERY_ERROR",
                "provider": "aws",
                "message": str(exc),
            },
        ) from exc


@router.post("/cloud/gcp")
def discover_live_gcp_infrastructure(request: Optional[GCPLiveDiscoveryRequest] = None):
    """
    Execute real GCP live cloud discovery via Google Cloud Asset API (`searchAllResources` with pagination),
    normalize into CMIR v2.1, reconcile against any previous snapshot for the same project,
    and persist in the ACID transactional database.
    Never converts an API/auth error into an empty inventory.
    """
    req = request or GCPLiveDiscoveryRequest()
    connector = GCPLiveDiscoveryConnector(
        project_id=req.project_id,
        region=req.zone,
        credentials_path=req.service_account_json,
    )
    try:
        return connector.discover_live_project()
    except ConnectorAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "GCP_AUTH_OR_PERMISSION_ERROR",
                "provider": "gcp",
                "message": str(exc),
            },
        ) from exc
    except ConnectorTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "error_code": "GCP_API_TIMEOUT",
                "provider": "gcp",
                "message": str(exc),
            },
        ) from exc
    except ConnectorError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "GCP_DISCOVERY_ERROR",
                "provider": "gcp",
                "message": str(exc),
            },
        ) from exc


@router.get("/cloud/snapshots")
def list_cloud_discovery_snapshots(provider: Optional[str] = Query(None, description="aws | gcp")):
    """Return persisted live cloud discovery snapshots and reconciliation diffs."""
    if provider and provider.lower().strip() not in ("aws", "gcp"):
        raise HTTPException(status_code=400, detail="Proveedor no soportado. Use 'aws' o 'gcp'.")
    snapshots = get_transactional_db().list_cloud_discovery_snapshots(
        provider=provider.lower().strip() if provider else None
    )
    return {
        "count": len(snapshots),
        "snapshots": snapshots,
    }



