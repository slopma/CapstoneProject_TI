from app.cmir.models import CMIR
from app.adapters.aws_adapter import AWSAdapter


def translate_cmir_to_aws(cmir: CMIR):
    adapter = AWSAdapter()
    return adapter.translate_cmir(cmir)


def translate_resource(resource):
    adapter = AWSAdapter()
    return adapter.translate_node(resource)