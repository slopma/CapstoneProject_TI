GCP_MAPPING = {
    "compute": "google_compute_instance",
    "database": "google_sql_database_instance",
    "cache": "google_redis_instance"
}


def translate_resource(resource):

    return {
        "cmir_type": resource.type,
        "target_type": GCP_MAPPING.get(
            resource.type
        ),
        "name": resource.name
    }