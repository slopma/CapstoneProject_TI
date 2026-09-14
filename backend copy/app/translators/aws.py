from app.cmir.models import CMIR


AWS_TYPE_MAPPING = {
    "compute": "aws_instance",
    "database": "aws_db_instance",
    "cache": "aws_elasticache_cluster",
}


def translate_resource(resource):
    terraform_type = AWS_TYPE_MAPPING.get(resource.type)

    if not terraform_type:
        raise ValueError(
            f"Tipo de recurso no soportado por AWS: {resource.type}"
        )

    return {
        "id": resource.id,
        "name": resource.name,
        "type": terraform_type,
        "engine": resource.engine,
    }


def translate_cmir_to_aws(cmir: CMIR):
    return [
        translate_resource(resource)
        for resource in cmir.resources
    ]