import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.cmir.normalizer import normalize_inventory
from app.graph.builder import build_graph
from app.dependencies.resolver import resolve_dependencies
from app.dependencies.validator import validate_migration_subgraph
from app.adapters.aws_adapter import AWSAdapter
from app.adapters.azure_adapter import AzureAdapter
from app.adapters.k8s_adapter import KubernetesAdapter
from app.generators.terraform import generate_aws_terraform, generate_azure_terraform, generate_k8s_manifests
from app.config import INVENTORY_PATH, AWS_OUTPUT_PATH, AZURE_OUTPUT_PATH, K8S_OUTPUT_PATH

router = APIRouter(prefix="/api/v1/migration", tags=["Migration Engine"])


class SelectionRequest(BaseModel):
    resources: List[str] = Field(..., description="IDs of nodes selected for migration")
    target_provider: Optional[str] = Field("aws", description="Target cloud provider: aws, azure, kubernetes")


def _load_cmir():
    if not INVENTORY_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Inventory file not found at {INVENTORY_PATH}")
    with open(INVENTORY_PATH, "r") as file:
        inventory = json.load(file)
    return normalize_inventory(inventory)


@router.post("/dependencies")
def get_migration_dependencies(request: SelectionRequest):
    if not request.resources:
        raise HTTPException(status_code=400, detail="Debe seleccionar al menos un recurso o nivel jerárquico.")

    cmir = _load_cmir()
    graph = build_graph(cmir)

    dep_analysis = resolve_dependencies(graph, request.resources)
    return dep_analysis


@router.post("/validate")
def validate_migration(request: SelectionRequest):
    if not request.resources:
        raise HTTPException(status_code=400, detail="Debe seleccionar al menos un recurso para validar.")

    cmir = _load_cmir()
    graph = build_graph(cmir)
    dep_analysis = resolve_dependencies(graph, request.resources)

    selected_ids = dep_analysis["all_included"]
    selected_nodes = [res for res in cmir.resources if res.id in selected_ids]

    sub_cmir = cmir.model_copy(
        update={
            "resources": selected_nodes,
            "relationships": [
                rel for rel in cmir.relationships
                if rel.source in selected_ids and rel.target in selected_ids
            ]
        }
    )

    validation_result = validate_migration_subgraph(
        sub_cmir,
        dep_analysis,
        target_provider=request.target_provider or "aws"
    )

    return validation_result


@router.post("/generate")
def generate_migration_iac(request: SelectionRequest):
    if not request.resources:
        raise HTTPException(status_code=400, detail="Debe seleccionar al menos un recurso para migrar.")

    target = (request.target_provider or "aws").lower()
    cmir = _load_cmir()
    graph = build_graph(cmir)

    dep_analysis = resolve_dependencies(graph, request.resources)
    all_included_ids = dep_analysis["all_included"]

    selected_nodes = [res for res in cmir.resources if res.id in all_included_ids]
    sub_cmir = cmir.model_copy(
        update={
            "resources": selected_nodes,
            "relationships": [
                rel for rel in cmir.relationships
                if rel.source in all_included_ids and rel.target in all_included_ids
            ]
        }
    )

    validation = validate_migration_subgraph(sub_cmir, dep_analysis, target_provider=target)
    if not validation["can_generate"]:
        return {
            "error": {
                "code": "VALIDATION_FAILED",
                "message": "La validación previa a la migración falló.",
                "details": validation["errors"],
            }
        }

    if target == "aws":
        adapter = AWSAdapter()
        translated_resources = adapter.translate_cmir(sub_cmir)
        code = generate_aws_terraform(translated_resources)
        output_path = AWS_OUTPUT_PATH
    elif target == "azure":
        adapter = AzureAdapter()
        translated_resources = adapter.translate_cmir(sub_cmir)
        code = generate_azure_terraform(translated_resources)
        output_path = AZURE_OUTPUT_PATH
    elif target in ("k8s", "kubernetes"):
        adapter = KubernetesAdapter()
        translated_resources = adapter.translate_cmir(sub_cmir)
        code = generate_k8s_manifests(translated_resources)
        output_path = K8S_OUTPUT_PATH
    else:
        raise HTTPException(status_code=400, detail=f"Proveedor de destino '{target}' no soportado.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(code)

    return {
        "status": "generated",
        "target": target,
        "selected_requested": request.resources,
        "dependency_summary": {
            "required_direct": dep_analysis["required_direct"],
            "required_transitive": dep_analysis["required_transitive"],
            "shared": dep_analysis["shared_dependencies"],
            "optional": dep_analysis["optional_dependencies"],
            "total_migrated_nodes": len(selected_nodes),
        },
        "resources_generated": [res.id for res in selected_nodes],
        "output_path": str(output_path),
        "validation": validation,
        "iac_code": code,
    }
