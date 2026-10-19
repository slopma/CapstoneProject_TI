import pytest
from app.cmir.models import CMIRNode, CMIRRelationship, CMIR
from app.adapters.aws_adapter import AWSAdapter
from app.adapters.azure_adapter import AzureAdapter
from app.adapters.k8s_adapter import KubernetesAdapter


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


def test_azure_adapter_translation(sample_cmir):
    adapter = AzureAdapter()
    translated = adapter.translate_cmir(sample_cmir)
    assert len(translated) == 7

    type_map = {res["id"]: res["type"] for res in translated}
    assert type_map["vpc-1"] == "azurerm_virtual_network"
    assert type_map["subnet-1"] == "azurerm_subnet"
    assert type_map["vm-1"] == "azurerm_linux_virtual_machine"
    assert type_map["db-1"] == "azurerm_postgresql_server"
    assert type_map["redis-1"] == "azurerm_redis_cache"
    assert type_map["bucket-1"] == "azurerm_storage_account"
    assert type_map["secret-1"] == "azurerm_key_vault_secret"


def test_k8s_adapter_translation(sample_cmir):
    adapter = KubernetesAdapter()
    translated = adapter.translate_cmir(sample_cmir)
    assert len(translated) == 7

    kind_map = {res["id"]: res["kind"] for res in translated}
    assert kind_map["vm-1"] == "Deployment"
    assert kind_map["db-1"] == "StatefulSet"
    assert kind_map["redis-1"] == "StatefulSet"
    assert kind_map["secret-1"] == "Secret"
    assert kind_map["bucket-1"] == "PersistentVolumeClaim"
