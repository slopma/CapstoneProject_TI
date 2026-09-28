import json
import logging
import uuid
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.cmir.normalizer import normalize_inventory
from app.graph.builder import build_graph
from app.dependencies.resolver import resolve_dependencies
from app.translators.aws import translate_cmir_to_aws
from app.generators.terraform import generate_aws_terraform
from app.config import AWS_OUTPUT_PATH, CORS_ORIGINS, INVENTORY_PATH, LOG_LEVEL
from app.api.routers import architecture, migration

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] [ReqID: %(correlation_id)s] %(message)s",
)
logger = logging.getLogger("cloudmove")

app = FastAPI(
    title="CloudMove Enterprise API",
    description="Plataforma de abstracción de arquitectura, migración selectiva jerárquica y generación IaC multicloud",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    req_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = req_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = req_id
    return response


# Include Routers
app.include_router(architecture.router)
app.include_router(migration.router)


def load_inventory():
    if not INVENTORY_PATH.exists():
        return {"architecture": {"name": "empty", "provider": "none"}, "resources": [], "relationships": []}
    with open(INVENTORY_PATH, "r") as file:
        return json.load(file)


@app.get("/")
def root():
    return {
        "project": "CloudMove",
        "version": "2.0.0",
        "status": "running",
        "architecture_engine": "Hierarchical Graph Level 0-8",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "inventory_loaded": INVENTORY_PATH.exists(),
        "inventory_path": str(INVENTORY_PATH),
    }


# Legacy / Backward Compatibility Endpoints
@app.get("/inventory")
def get_inventory():
    return load_inventory()


@app.get("/cmir")
def get_cmir():
    inventory = load_inventory()
    cmir = normalize_inventory(inventory)
    return cmir.model_dump()


@app.get("/graph")
def get_graph():
    inventory = load_inventory()
    cmir = normalize_inventory(inventory)
    graph = build_graph(cmir)

    return {
        "nodes": [
            {"id": node, **graph.nodes[node]}
            for node in graph.nodes
        ],
        "edges": [
            {"source": source, "target": target, **graph.edges[source, target]}
            for source, target in graph.edges
        ],
    }


class SelectionRequest(BaseModel):
    resources: list[str]


@app.post("/dependencies")
def get_dependencies(request: SelectionRequest):
    inventory = load_inventory()
    cmir = normalize_inventory(inventory)
    graph = build_graph(cmir)
    result = resolve_dependencies(graph, request.resources)

    return {
        "selected": request.resources,
        "dependencies": result["dependencies"],
        "details": result,
    }


@app.post("/generate")
def generate_terraform(request: SelectionRequest):
    if not request.resources:
        return {
            "error": {
                "code": "NO_RESOURCES",
                "message": "Debe seleccionar al menos un recurso.",
            }
        }

    inventory = load_inventory()
    cmir = normalize_inventory(inventory)
    graph = build_graph(cmir)

    dep_analysis = resolve_dependencies(graph, request.resources)
    all_ids = dep_analysis["all_included"]

    selected_resources = [res for res in cmir.resources if res.id in all_ids]
    selected_cmir = cmir.model_copy(
        update={
            "resources": selected_resources,
            "relationships": [
                rel for rel in cmir.relationships
                if rel.source in all_ids and rel.target in all_ids
            ]
        }
    )

    aws_resources = translate_cmir_to_aws(selected_cmir)
    terraform = generate_aws_terraform(aws_resources)

    AWS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AWS_OUTPUT_PATH, "w") as file:
        file.write(terraform)

    return {
        "status": "generated",
        "target": "aws",
        "selected": request.resources,
        "dependencies": dep_analysis["dependencies"],
        "resources_generated": [resource.id for resource in selected_resources],
        "output": str(AWS_OUTPUT_PATH),
        "terraform": terraform,
    }
