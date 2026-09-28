import json
from app.cmir.normalizer import normalize_inventory
from app.graph.builder import build_graph
from app.graph.hierarchy import get_breadcrumbs, filter_graph_view


def test_graph_building_and_hierarchy():
    with open("inventory/enterprise-multicloud-example.json") as file:
        inventory = json.load(file)

    cmir = normalize_inventory(inventory)
    graph = build_graph(cmir)

    assert graph.number_of_nodes() == 19
    # Check parent-child hierarchy edge
    assert graph.has_edge("us-east-1", "vpc-main")
    # Check dependency edge
    assert graph.has_edge("frontend-ui", "payment-api")

    # Test Breadcrumbs calculation
    breadcrumbs = get_breadcrumbs(graph, "payment-api")
    node_ids = [b["id"] for b in breadcrumbs]
    assert "aws-cloud" in node_ids
    assert "us-east-1" in node_ids
    assert "vpc-main" in node_ids
    assert "eks-prod-cluster" in node_ids
    assert "ns-backend" in node_ids
    assert "payment-platform" in node_ids
    assert "payment-api" in node_ids

    # Test Focus mode filtering
    focus_view = filter_graph_view(graph, focus_node_id="payment-api")
    assert focus_view["visible_count"] < graph.number_of_nodes()