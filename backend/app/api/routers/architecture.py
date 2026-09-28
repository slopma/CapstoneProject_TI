import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.cmir.normalizer import normalize_inventory
from app.graph.builder import build_graph
from app.graph.hierarchy import filter_graph_view, get_breadcrumbs, get_children
from app.config import INVENTORY_PATH

router = APIRouter(prefix="/api/v1/architecture", tags=["Architecture"])


def _load_cmir():
    if not INVENTORY_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Inventory file not found at {INVENTORY_PATH}")
    with open(INVENTORY_PATH, "r") as file:
        inventory = json.load(file)
    return normalize_inventory(inventory)


@app_cmir_get := router.get("/cmir")
def get_cmir():
    cmir = _load_cmir()
    return cmir.model_dump()


@router.get("/graph")
def get_graph(
    parent_id: Optional[str] = Query(None, description="Drill down into a parent container node ID"),
    level: Optional[int] = Query(None, description="Filter nodes by hierarchy level (0 to 8)"),
    focus: Optional[str] = Query(None, description="Focus mode on a specific node ID"),
    provider: Optional[str] = Query(None, description="Filter by cloud provider (aws, azure, etc)"),
):
    cmir = _load_cmir()
    graph = build_graph(cmir)

    view = filter_graph_view(
        graph,
        parent_id=parent_id,
        level=level,
        focus_node_id=focus,
        provider_filter=provider,
    )

    breadcrumbs = []
    if focus and focus in graph:
        breadcrumbs = get_breadcrumbs(graph, focus)
    elif parent_id and parent_id in graph:
        breadcrumbs = get_breadcrumbs(graph, parent_id)

    return {
        "architecture_name": cmir.name,
        "provider": cmir.provider,
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
