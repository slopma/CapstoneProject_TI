import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.cmir.normalizer import normalize_inventory
from app.graph.builder import build_graph
from app.graph.hierarchy import filter_graph_view, get_breadcrumbs, get_children
from app.config import INVENTORY_PATH
from app.migration.target_architecture import build_target_cloud_cmir
from app.migration.orchestrator import migration_orchestrator

router = APIRouter(prefix="/api/v1/architecture", tags=["Architecture"])


def _load_cmir():
    if not INVENTORY_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Inventory file not found at {INVENTORY_PATH}")
    with open(INVENTORY_PATH, "r") as file:
        inventory = json.load(file)
    return normalize_inventory(inventory)


def _load_target_cmir(migration_id: Optional[str] = None, provider: Optional[str] = None):
    """Load or generate the authoritative Target Cloud Architecture CMIR."""
    from app.cmir.models import CMIR
    target_prov = (provider or "aws").lower().strip()
    job = None
    if migration_id:
        try:
            job = migration_orchestrator.get_migration(migration_id)
        except Exception:
            pass

    if not job:
        # Pick the most relevant active migration job
        jobs = migration_orchestrator.list_migrations()
        app_jobs = [j for j in jobs if j.get("use_case") == "app_source"]
        job = app_jobs[0] if app_jobs else (jobs[0] if jobs else None)

    if job and job.get("source_environment"):
        src = job["source_environment"]
        prov = job.get("target_provider") or target_prov
        decisions = (
            (job.get("source_config") or {}).get("user_decisions")
            or job.get("user_decisions")
            or job.get("decisions")
        )
        return build_target_cloud_cmir(
            app_discovery=src,
            target_provider=prov,
            deployment_mode=src.get("deployment_mode", "vm_rehost"),
            user_decisions=decisions,
            terraform_artifacts=job.get("generated_artifacts"),
        )

    # NO DEFAULT HARDCODED FALLBACK:
    # If no active migration plan exists, return an empty CMIR indicating no active workload is being migrated.
    return CMIR(
        name="Sin plan de migración activo",
        provider=target_prov,
        resources=[],
        relationships=[],
        metadata={
            "empty": True,
            "message": "No hay un plan de migración activo. Analiza un artefacto para generar la arquitectura objetivo.",
        },
    )


@app_cmir_get := router.get("/cmir")
def get_cmir(view_mode: Optional[str] = Query("target", description="View mode: 'target' (Nube) or 'source' (On-Prem)")):
    if view_mode == "source":
        cmir = _load_cmir()
    else:
        cmir = _load_target_cmir()
    return cmir.model_dump()


@router.get("/graph")
def get_graph(
    parent_id: Optional[str] = Query(None, description="Drill down into a parent container node ID"),
    level: Optional[int] = Query(None, description="Filter nodes by hierarchy level (0 to 8)"),
    focus: Optional[str] = Query(None, description="Focus mode on a specific node ID"),
    provider: Optional[str] = Query(None, description="Filter by cloud provider (aws, azure, etc)"),
    view_mode: Optional[str] = Query("target", description="View mode: 'target' (Arquitectura Objetivo Cloud) o 'source' (Topología de Origen)"),
    migration_id: Optional[str] = Query(None, description="ID del plan de migración para representar su arquitectura objetivo"),
):
    if view_mode == "source":
        cmir = _load_cmir()
    else:
        cmir = _load_target_cmir(migration_id=migration_id, provider=provider)

    graph = build_graph(cmir)

    view = filter_graph_view(
        graph,
        parent_id=parent_id,
        level=level,
        focus_node_id=focus,
        provider_filter=provider if view_mode == "source" else None,
    )

    breadcrumbs = []
    if focus and focus in graph:
        breadcrumbs = get_breadcrumbs(graph, focus)
    elif parent_id and parent_id in graph:
        breadcrumbs = get_breadcrumbs(graph, parent_id)

    return {
        "architecture_name": cmir.name,
        "provider": cmir.provider,
        "view_mode": view_mode,
        "is_target_architecture": view_mode != "source",
        "nodes": view["nodes"],
        "edges": view["edges"],
        "total_nodes": view["total_nodes"],
        "visible_count": view["visible_count"],
        "breadcrumbs": breadcrumbs,
        "active_parent": parent_id,
        "focus_node": focus,
    }


@router.get("/breadcrumbs/{node_id}")
def get_node_breadcrumbs(node_id: str):
    cmir = _load_cmir()
    graph = build_graph(cmir)
    if node_id not in graph:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found in architecture graph.")
    return {"breadcrumbs": get_breadcrumbs(graph, node_id)}


@router.get("/children/{node_id}")
def get_node_children(node_id: str):
    cmir = _load_cmir()
    graph = build_graph(cmir)
    if node_id not in graph:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found in architecture graph.")
    return {"parent_id": node_id, "children": get_children(graph, node_id)}
