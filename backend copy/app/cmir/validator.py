from .models import CMIR


def validate_cmir(cmir: CMIR) -> bool:

    resource_ids = {
        resource.id
        for resource in cmir.resources
    }

    for relationship in cmir.relationships:

        if relationship.source not in resource_ids:
            return False

        if relationship.target not in resource_ids:
            return False

    return True