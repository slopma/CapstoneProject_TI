import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.cmir.normalizer import normalize_inventory
from app.graph.builder import build_graph
from app.dependencies.resolver import resolve_dependencies
from app.translators.aws import translate_cmir_to_aws
from app.generators.terraform import generate_aws_terraform


app = FastAPI(
    title="CloudMove API",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


INVENTORY_PATH = Path("inventory/onprem-example.json")
AWS_OUTPUT_PATH = Path("generated/aws/main.tf")


def load_inventory():
    with open(INVENTORY_PATH, "r") as file:
        return json.load(file)


@app.get("/")
def root():
    return {
        "project": "CloudMove",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


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
            {
                "id": node,
                **graph.nodes[node]
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "source": source,
                "target": target,
                **graph.edges[source, target]
            }
            for source, target in graph.edges
        ]
    }


class SelectionRequest(BaseModel):
    resources: list[str]


@app.post("/dependencies")
def get_dependencies(request: SelectionRequest):

    inventory = load_inventory()

    cmir = normalize_inventory(inventory)

    graph = build_graph(cmir)

    dependencies = resolve_dependencies(
        graph,
        request.resources
    )

    return {
        "selected": request.resources,
        "dependencies": dependencies
    }


@app.post("/generate")
def generate_terraform(request: SelectionRequest):

    if not request.resources:
        return {
            "error": {
                "code": "NO_RESOURCES",
                "message": "Debe seleccionar al menos un recurso."
            }
        }

    inventory = load_inventory()

    cmir = normalize_inventory(inventory)

    graph = build_graph(cmir)

    # Resolver dependencias automáticamente
    dependencies = resolve_dependencies(
        graph,
        request.resources
    )

    # Recursos que realmente serán migrados
    selected_resources = [
        resource
        for resource in cmir.resources
        if resource.id in dependencies
    ]

    # Crear CMIR reducido para la migración seleccionada
    selected_cmir = cmir.model_copy(
        update={
            "resources": selected_resources,
            "relationships": [
                relationship
                for relationship in cmir.relationships
                if relationship.source in dependencies
                and relationship.target in dependencies
            ]
        }
    )

    # Traducir CMIR → AWS
    aws_resources = translate_cmir_to_aws(selected_cmir)

    # Generar Terraform
    terraform = generate_aws_terraform(aws_resources)

    AWS_OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(AWS_OUTPUT_PATH, "w") as file:
        file.write(terraform)

    return {
        "status": "generated",
        "target": "aws",
        "selected": request.resources,
        "dependencies": dependencies,
        "resources_generated": [
            resource.id
            for resource in selected_resources
        ],
        "output": str(AWS_OUTPUT_PATH),
        "terraform": terraform
    }
