import json

from app.cmir.normalizer import normalize_inventory
from app.graph.builder import build_graph
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    allow_methods=["GET"],
    allow_headers=["*"],
)


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

    with open(
        "inventory/onprem-example.json",
        "r"
    ) as file:

        inventory = json.load(file)

    return inventory

@app.get("/cmir")
def get_cmir():

    with open(
        "inventory/onprem-example.json",
        "r"
    ) as file:

        inventory = json.load(file)

    cmir = normalize_inventory(inventory)

    return cmir.model_dump()

@app.get("/graph")
def get_graph():

    with open(
        "inventory/onprem-example.json",
        "r"
    ) as file:

        inventory = json.load(file)

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