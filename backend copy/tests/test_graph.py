import json

from app.cmir.normalizer import normalize_inventory
from app.graph.builder import build_graph


def test_graph():

    with open("inventory/onprem-example.json") as file:
        inventory = json.load(file)

    cmir = normalize_inventory(inventory)

    graph = build_graph(cmir)

    assert graph.number_of_nodes() == 3
    assert graph.number_of_edges() == 2

    assert graph.has_edge(
        "backend",
        "postgres"
    )

    assert graph.has_edge(
        "backend",
        "redis"
    )