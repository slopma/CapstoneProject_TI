import json

from app.cmir.normalizer import normalize_inventory
from app.cmir.validator import validate_cmir


def test_cmir():

    with open("inventory/onprem-example.json") as file:
        inventory = json.load(file)

    cmir = normalize_inventory(inventory)

    assert cmir.name == "onprem-reference"
    assert len(cmir.resources) == 3
    assert len(cmir.relationships) == 2

    assert validate_cmir(cmir)