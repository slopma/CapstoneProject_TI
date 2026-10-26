from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.discovery.campaigns import (
    ApproveCampaignRequest,
    CreateCampaignRequest,
    campaign_store,
)
from app.discovery.connectors import SecurityPolicyViolationError

router = APIRouter(prefix="/api/v1", tags=["Data Center Campaigns"])


def _require_operator_role(role: Optional[str], required_for: str) -> None:
    if role and role.lower() in ("viewer", "readonly_guest", "anonymous"):
        raise HTTPException(
            status_code=403,
            detail=f"Permiso denegado: el rol '{role}' no está autorizado para '{required_for}'.",
        )


@router.post("/campaigns")
def create_campaign(
    payload: Optional[CreateCampaignRequest] = None,
    x_cloudmove_role: Optional[str] = Header(default=None),
):
    """Crear una nueva campaña de descubrimiento masivo del data center."""
    _require_operator_role(x_cloudmove_role, "campaigns.create")
    req = payload or CreateCampaignRequest()
    try:
        return campaign_store.create_campaign(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/campaigns")
def list_campaigns():
    """Listar campañas de descubrimiento y sus estados."""
    campaigns = campaign_store.list_campaigns()
    return {
        "count": len(campaigns),
        "campaigns": campaigns,
    }


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str):
    """Consultar el resumen, métricas, sitios, activos y progreso de una campaña."""
    try:
        return campaign_store.get_campaign_detail(campaign_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/plan")
def plan_campaign(
    campaign_id: str,
    x_cloudmove_role: Optional[str] = Header(default=None),
):
    """Generar o recalcular el plan por nodo (Fases A–E y evaluación de los 8 controles)."""
    _require_operator_role(x_cloudmove_role, "campaigns.plan")
    try:
        return campaign_store.generate_plan(campaign_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/approve")
def approve_campaign_policy(
    campaign_id: str,
    payload: Optional[ApproveCampaignRequest] = None,
    x_cloudmove_role: Optional[str] = Header(default=None),
):
    """Registrar aprobación de la política de despliegue para una campaña."""
    _require_operator_role(x_cloudmove_role, "campaigns.approve")
    req = payload or ApproveCampaignRequest()
    try:
        return campaign_store.approve_campaign(campaign_id, req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/execute")
def execute_campaign(
    campaign_id: str,
    force_install: bool = Query(
        False,
        description="Si es true, intenta forzar instalación de agentes (bloqueado en discover_only y discover_plan).",
    ),
    x_cloudmove_role: Optional[str] = Header(default=None),
):
    """Iniciar la ejecución autorizada de la campaña (Descubrir -> Identificar -> Instalar -> Verificar)."""
    _require_operator_role(x_cloudmove_role, "campaigns.execute")
    try:
        return campaign_store.execute_campaign(campaign_id, force_install_agents=force_install)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/cancel")
def cancel_campaign(
    campaign_id: str,
    x_cloudmove_role: Optional[str] = Header(default=None),
):
    """Solicitar la cancelación de una campaña y sus tareas pendientes."""
    _require_operator_role(x_cloudmove_role, "campaigns.cancel")
    try:
        return campaign_store.cancel_campaign(campaign_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(
    campaign_id: str,
    reason: str = Query("Pausa solicitada por el operador"),
    x_cloudmove_role: Optional[str] = Header(default=None),
):
    """Pausar una campaña conservando todos los descubrimientos parciales y puntos de control."""
    _require_operator_role(x_cloudmove_role, "campaigns.pause")
    try:
        return campaign_store.pause_campaign(campaign_id, reason=reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/resume")
def resume_campaign(
    campaign_id: str,
    x_cloudmove_role: Optional[str] = Header(default=None),
):
    """Reanudar una campaña pausada o interrumpida sin perder ni duplicar activos descubiertos."""
    _require_operator_role(x_cloudmove_role, "campaigns.resume")
    try:
        return campaign_store.resume_campaign(campaign_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/assets/{asset_id}/retry")
def retry_campaign_host(
    campaign_id: str,
    asset_id: str,
    x_cloudmove_role: Optional[str] = Header(default=None),
):
    """Reintentar descubrimiento sobre un host específico conservando resultados parciales."""
    _require_operator_role(x_cloudmove_role, "campaigns.retry_host")
    try:
        return campaign_store.retry_host_discovery(campaign_id, asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/campaigns/{campaign_id}/cmir")
def get_campaign_cmir(
    campaign_id: str,
    target_provider: str = Query("aws", description="Proveedor destino: aws | gcp"),
):
    """
    Construir y devolver el modelo jerárquico CMIR v2.1 completo del datacenter:
    DATACENTER -> PHYSICAL HOST -> HYPERVISOR -> VM -> OS -> PROCESSES/SERVICES -> APPLICATIONS -> DEPENDENCIES.
    """
    if target_provider.lower().strip() not in ("aws", "gcp"):
        raise HTTPException(status_code=400, detail="Proveedor destino no admitido. Use 'aws' o 'gcp'.")
    try:
        return campaign_store.build_campaign_cmir(campaign_id, target_provider=target_provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/migrate")
def plan_campaign_migration(
    campaign_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    x_cloudmove_role: Optional[str] = Header(default=None),
):
    """
    Caso de Uso 3: Seleccionar un subgrafo de activos descubiertos en la campaña,
    validar dependencias compartidas (sin migrarlas automáticamente sin confirmación)
    y crear un plan de migración orquestado hacia AWS o GCP.
    """
    _require_operator_role(x_cloudmove_role, "campaigns.migrate")
    body = payload or {}
    target_provider = str(body.get("target_provider") or "aws").lower().strip()
    if target_provider not in ("aws", "gcp"):
        raise HTTPException(
            status_code=400,
            detail=f"Proveedor '{target_provider}' no admitido. Proveedores admitidos: 'aws', 'gcp'.",
        )
    selected_resources = body.get("selected_resources")
    validated_shared = body.get("validated_shared_resources")

    try:
        from app.migration.orchestrator import migration_orchestrator

        plan_bundle = campaign_store.plan_campaign_workload_migration(
            campaign_id,
            selected_resources=selected_resources,
            target_provider=target_provider,
            validated_shared_resources=validated_shared,
        )
        job = migration_orchestrator.create_migration(
            name=body.get("name") or f"Campaña {campaign_id} -> {target_provider.upper()}",
            use_case="datacenter_campaign",
            target_provider=target_provider,
            source_config={
                "campaign_id": campaign_id,
                "selected_resources": selected_resources,
                "validated_shared_resources": validated_shared,
            },
            auto_assess_and_plan=True,
        )
        return {
            **plan_bundle,
            "migration_job": job,
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/campaigns/{campaign_id}/assets")
def get_campaign_assets(campaign_id: str):
    """Consultar los nodos descubiertos, reconciliados y evaluados en la campaña."""
    try:
        assets = campaign_store.get_campaign_assets(campaign_id)
        return {"campaign_id": campaign_id, "count": len(assets), "assets": assets}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/campaigns/{campaign_id}/tasks")
def get_campaign_tasks(campaign_id: str):
    """Consultar las tareas individuales e idempotentes por cola y por nodo."""
    try:
        tasks = campaign_store.get_campaign_tasks(campaign_id)
        return {"campaign_id": campaign_id, "count": len(tasks), "tasks": tasks}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/campaigns/{campaign_id}/report")
def get_campaign_report(
    campaign_id: str,
    format: str = Query("json", description="Formato de reporte: json | md"),
):
    """Obtener el informe global consolidado de la campaña."""
    try:
        report = campaign_store.get_campaign_report(campaign_id)
        if format.lower() in ("md", "markdown"):
            return PlainTextResponse(
                content=report["markdown_report"],
                media_type="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="campaign-report-{campaign_id}.md"'
                },
            )
        return report
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ==============================================================================
# Catálogo Unificado de Activos, Observaciones, Relaciones y Preparación
# ==============================================================================


@router.get("/assets")
def list_assets(
    asset_type: Optional[str] = Query(None, description="Filtrar por tipo de activo (virtual_machine, physical_server, cloud_instance)"),
    site_id: Optional[str] = Query(None, description="Filtrar por sitio (site-dc-a, site-dc-b)"),
    os_family: Optional[str] = Query(None, description="Filtrar por familia de SO (linux, windows, unsupported)"),
    state: Optional[str] = Query(None, description="Filtrar por estado del ciclo de vida"),
    environment_id: Optional[str] = Query(None, description="Filtrar por entorno autorizado"),
    x_cloudmove_env: Optional[str] = Header(default=None),
):
    """Listar activos descubiertos con filtros por tipo, sitio, familia de SO y estado."""
    effective_env = environment_id or x_cloudmove_env
    assets = campaign_store.list_assets(
        asset_type=asset_type,
        site_id=site_id,
        os_family=os_family,
        state=state,
        environment_id=effective_env,
    )
    return {
        "count": len(assets),
        "filters": {
            "asset_type": asset_type,
            "site_id": site_id,
            "os_family": os_family,
            "state": state,
            "environment_id": effective_env,
        },
        "assets": assets,
    }


@router.get("/assets/{asset_id}")
def get_asset_detail(
    asset_id: str,
    x_cloudmove_env: Optional[str] = Header(default=None),
):
    """Consultar detalle canónico de un activo, sus volúmenes, bases de datos y metadatos."""
    try:
        return campaign_store.get_asset_detail(asset_id, environment_id=x_cloudmove_env)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/observations")
def get_asset_observations(
    asset_id: str,
    x_cloudmove_env: Optional[str] = Header(default=None),
):
    """Consultar historial de observaciones y procedencia por fuente de descubrimiento."""
    try:
        obs = campaign_store.get_asset_observations(asset_id, environment_id=x_cloudmove_env)
        return {"asset_id": asset_id, "count": len(obs), "observations": obs}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/relationships")
def get_asset_relationships(
    asset_id: str,
    x_cloudmove_env: Optional[str] = Header(default=None),
):
    """Consultar relaciones tipadas (host->VM, VM->DB, VM->datastore, servicio->servicio)."""
    try:
        rels = campaign_store.get_asset_relationships(asset_id, environment_id=x_cloudmove_env)
        return {"asset_id": asset_id, "count": len(rels), "relationships": rels}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/migration-readiness")
def get_asset_migration_readiness(
    asset_id: str,
    x_cloudmove_env: Optional[str] = Header(default=None),
):
    """Consultar preparación de migración, ola sugerida, estrategia 6R, bloqueos e información faltante."""
    try:
        return campaign_store.get_asset_migration_readiness(asset_id, environment_id=x_cloudmove_env)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/health")
def get_asset_health(asset_id: str):
    """Consultar la salud de un nodo, sus 4 niveles de verificación y el estado de su agente."""
    try:
        return campaign_store.get_asset_health(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ==============================================================================
# Conectores de Infraestructura Autorizados (Proxmox VE / vSphere / DNS / Cloud)
# ==============================================================================


@router.get("/connectors")
def list_connectors(
    environment_id: Optional[str] = Query(None),
    x_cloudmove_env: Optional[str] = Header(default=None),
):
    """Listar conectores de descubrimiento registrados."""
    effective_env = environment_id or x_cloudmove_env
    connectors = campaign_store.list_connectors(environment_id=effective_env)
    return {"count": len(connectors), "connectors": connectors}


@router.post("/connectors")
def register_connector(
    payload: Dict[str, Any] = Body(...),
    x_cloudmove_role: Optional[str] = Header(default=None),
):
    """Registrar un nuevo conector autorizado con validación anti-SSRF."""
    _require_operator_role(x_cloudmove_role, "connectors.register")
    try:
        return campaign_store.register_connector(payload)
    except SecurityPolicyViolationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/connectors/{connector_id}/test")
def test_connector(
    connector_id: str,
    x_cloudmove_role: Optional[str] = Header(default=None),
):
    """Probar conectividad y permisos de un conector registrado."""
    _require_operator_role(x_cloudmove_role, "connectors.test")
    try:
        return campaign_store.test_connector(connector_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
