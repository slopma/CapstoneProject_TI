from .models import CMIR


def normalize_inventory(inventory: dict) -> CMIR:
    architecture = inventory["architecture"]

    return CMIR(
        name=architecture["name"],
        provider=architecture["provider"],
        resources=inventory["resources"],
        relationships=inventory["relationships"]
    )