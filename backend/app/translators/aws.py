AWS_MAPPING = {
    "compute": "aws_instance",
    "database": "aws_db_instance",
    "cache": "aws_elasticache_cluster"
}


def translate_resource(resource):

    return {
        "cmir_type": resource.type,
        "target_type": AWS_MAPPING.get(
            resource.type
        ),
        "name": resource.name
    }