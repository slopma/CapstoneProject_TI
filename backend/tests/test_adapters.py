import pytest
from app.cmir.models import CMIRNode, CMIRRelationship, CMIR
from app.adapters.aws_adapter import AWSAdapter


@pytest.fixture
def sample_cmir():
    resources = [
        CMIRNode(id="vpc-1", name="Main Network", type="vpc", provider="on-premise", level=3),
        CMIRNode(id="subnet-1", name="App Subnet", type="subnet", parent_id="vpc-1", level=3),
        CMIRNode(id="vm-1", name="Web Server", type="workload", parent_id="subnet-1", level=7, engine="nginx"),
        CMIRNode(id="db-1", name="PostgreSQL Primary", type="database", parent_id="subnet-1", level=8, engine="postgres"),
        CMIRNode(id="redis-1", name="Cache Redis", type="cache", parent_id="subnet-1", level=8, engine="redis"),
        CMIRNode(id="bucket-1", name="Static Attachments", type="storage", level=8),
        CMIRNode(id="secret-1", name="DB Password", type="secret", level=8),
    ]
    relationships = [
        CMIRRelationship(source="vm-1", target="db-1", type="depends_on"),
        CMIRRelationship(source="vm-1", target="redis-1", type="uses"),
        CMIRRelationship(source="vm-1", target="secret-1", type="uses"),
    ]
    return CMIR(name="test-architecture", provider="on-premise", resources=resources, relationships=relationships)


def test_aws_adapter_translation(sample_cmir):
    adapter = AWSAdapter()
    translated = adapter.translate_cmir(sample_cmir)
    assert len(translated) == 7

    type_map = {res["id"]: res["type"] for res in translated}
    assert type_map["vpc-1"] == "aws_vpc"
    assert type_map["subnet-1"] == "aws_subnet"
    assert type_map["vm-1"] == "aws_instance"
    assert type_map["db-1"] == "aws_db_instance"
    assert type_map["redis-1"] == "aws_elasticache_cluster"
    assert type_map["bucket-1"] == "aws_s3_bucket"
    assert type_map["secret-1"] == "aws_secretsmanager_secret"
