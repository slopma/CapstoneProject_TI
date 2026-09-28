import json
from app.cmir.normalizer import normalize_inventory
from app.graph.builder import build_graph
from app.dependencies.resolver import resolve_dependencies


def test_dependency_engine_classification():
    with open("inventory/enterprise-multicloud-example.json") as file:
        inventory = json.load(file)

    cmir = normalize_inventory(inventory)
    graph = build_graph(cmir)

    # Select payment-api
    res = resolve_dependencies(graph, ["payment-api"])

    assert "payment-api" in res["selected"]
    assert "auth-service" in res["required_direct"]
    assert "payment-db" in res["required_direct"]
    assert "auth-redis" in res["required_direct"]
    assert "s3-payment-vault" in res["required_direct"]
    # Shared dependency check
    assert "payment-db" in res["shared_dependencies"]
