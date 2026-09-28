import json
from app.cmir.normalizer import normalize_inventory
from app.cmir.validator import validate_cmir


def test_cmir_loading():
    with open("inventory/enterprise-multicloud-example.json") as file:
        inventory = json.load(file)

    cmir = normalize_inventory(inventory)

    assert cmir.name == "enterprise-multicloud-platform"
    assert len(cmir.resources) == 19
    assert len(cmir.relationships) == 11

    res = validate_cmir(cmir)
    assert res["valid"] is True
    assert len(res["errors"]) == 0
    # Should flag payment-db as shared
    assert len(res["warnings"]) > 0


def test_cmir_node_hierarchy():
    with open("inventory/enterprise-multicloud-example.json") as file:
        inventory = json.load(file)

    cmir = normalize_inventory(inventory)
    node_map = {n.id: n for n in cmir.resources}

    assert node_map["vpc-main"].level == 3
    assert node_map["vpc-main"].parent_id == "us-east-1"
    assert "subnet-public" in node_map["vpc-main"].children_ids
    assert node_map["payment-db"].is_shared is True