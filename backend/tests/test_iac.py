import json
from app.cmir.normalizer import normalize_inventory
from app.adapters.aws_adapter import AWSAdapter
from app.adapters.azure_adapter import AzureAdapter
from app.generators.terraform import generate_aws_terraform, generate_azure_terraform


def test_iac_generation_aws_and_azure():
    with open("inventory/enterprise-multicloud-example.json") as file:
        inventory = json.load(file)

    cmir = normalize_inventory(inventory)

    # AWS
    aws_adapter = AWSAdapter()
    aws_specs = aws_adapter.translate_cmir(cmir)
    aws_tf = generate_aws_terraform(aws_specs)

    assert "resource \"aws_vpc\"" in aws_tf
    assert "resource \"aws_db_instance\"" in aws_tf
    assert "resource \"aws_elasticache_cluster\"" in aws_tf
    assert "resource \"aws_s3_bucket\"" in aws_tf

    # Azure
    azure_adapter = AzureAdapter()
    azure_specs = azure_adapter.translate_cmir(cmir)
    azure_tf = generate_azure_terraform(azure_specs)

    assert "resource \"azurerm_resource_group\"" in azure_tf
    assert "resource \"azurerm_linux_virtual_machine\"" in azure_tf
