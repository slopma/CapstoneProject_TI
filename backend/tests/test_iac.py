import json
from app.cmir.normalizer import normalize_inventory
from app.adapters.aws_adapter import AWSAdapter
from app.adapters.gcp_adapter import GCPAdapter
from app.adapters.azure_adapter import AzureAdapter
from app.adapters.k8s_adapter import KubernetesAdapter
from app.generators.terraform import (
    generate_aws_terraform,
    generate_gcp_terraform,
    generate_azure_terraform,
    generate_k8s_manifests,
    generate_aws_terraform_files,
    generate_gcp_terraform_files,
    generate_azure_terraform_files,
    generate_k8s_manifest_files,
    format_terraform_code,
)


def test_iac_generation_all_targets():
    with open("inventory/enterprise-multicloud-example.json") as file:
        inventory = json.load(file)

    cmir = normalize_inventory(inventory)

    # AWS HCL Generation
    aws_adapter = AWSAdapter()
    aws_specs = aws_adapter.translate_cmir(cmir)
    aws_tf = generate_aws_terraform(aws_specs)

    assert "resource \"aws_vpc\"" in aws_tf
    assert "resource \"aws_db_instance\"" in aws_tf
    assert "resource \"aws_elasticache_cluster\"" in aws_tf
    assert "resource \"aws_s3_bucket\"" in aws_tf

    # GCP HCL Generation
    gcp_adapter = GCPAdapter()
    gcp_specs = gcp_adapter.translate_cmir(cmir)
    gcp_tf = generate_gcp_terraform(gcp_specs)

    assert "resource \"google_compute_network\"" in gcp_tf
    assert "resource \"google_sql_database_instance\"" in gcp_tf
    assert "resource \"google_redis_instance\"" in gcp_tf
    assert "resource \"google_storage_bucket\"" in gcp_tf

    # Azure HCL Generation
    azure_adapter = AzureAdapter()
    azure_specs = azure_adapter.translate_cmir(cmir)
    azure_tf = generate_azure_terraform(azure_specs)

    assert "resource \"azurerm_resource_group\"" in azure_tf
    assert "resource \"azurerm_linux_virtual_machine\"" in azure_tf
    assert "resource \"azurerm_postgresql_server\"" in azure_tf
    assert "resource \"azurerm_redis_cache\"" in azure_tf

    # Kubernetes YAML Generation
    k8s_adapter = KubernetesAdapter()
    k8s_specs = k8s_adapter.translate_cmir(cmir)
    k8s_yaml = generate_k8s_manifests(k8s_specs)

    assert "kind: Deployment" in k8s_yaml
    assert "kind: Service" in k8s_yaml
    assert "kind: StatefulSet" in k8s_yaml


def test_modular_iac_files_generation():
    with open("inventory/enterprise-multicloud-example.json") as file:
        inventory = json.load(file)

    cmir = normalize_inventory(inventory)

    # Test AWS modular files
    aws_adapter = AWSAdapter()
    aws_specs = aws_adapter.translate_cmir(cmir)
    aws_files = generate_aws_terraform_files(aws_specs)

    assert "main.tf" in aws_files
    assert "variables.tf" in aws_files
    assert "outputs.tf" in aws_files
    assert "provider.tf" in aws_files
    assert "resource \"aws_vpc\"" in aws_files["main.tf"]
    assert "variable \"aws_region\"" in aws_files["variables.tf"]

    # Test GCP modular files
    gcp_adapter = GCPAdapter()
    gcp_specs = gcp_adapter.translate_cmir(cmir)
    gcp_files = generate_gcp_terraform_files(gcp_specs)

    assert "main.tf" in gcp_files
    assert "variables.tf" in gcp_files
    assert "outputs.tf" in gcp_files
    assert "provider.tf" in gcp_files
    assert "resource \"google_compute_network\"" in gcp_files["main.tf"]
    assert "variable \"gcp_project_id\"" in gcp_files["variables.tf"]
    assert "variable \"gcp_region\"" in gcp_files["variables.tf"]

    # Test Azure modular files
    azure_adapter = AzureAdapter()
    azure_specs = azure_adapter.translate_cmir(cmir)
    azure_files = generate_azure_terraform_files(azure_specs)

    assert "main.tf" in azure_files
    assert "variables.tf" in azure_files
    assert "outputs.tf" in azure_files
    assert "provider.tf" in azure_files
    assert "resource \"azurerm_resource_group\"" in azure_files["main.tf"]
    assert "variable \"azure_location\"" in azure_files["variables.tf"]

    # Test K8s modular files
    k8s_adapter = KubernetesAdapter()
    k8s_specs = k8s_adapter.translate_cmir(cmir)
    k8s_files = generate_k8s_manifest_files(k8s_specs)

    assert "k8s-manifests.yaml" in k8s_files
    assert "kind: Deployment" in k8s_files["k8s-manifests.yaml"]


def test_format_terraform_code():
    raw_code = "resource \"aws_vpc\" \"main\" {\n  cidr_block = \"10.0.0.0/16\" \n}\n"
    formatted = format_terraform_code(raw_code)
    assert isinstance(formatted, str)
    assert "resource \"aws_vpc\" \"main\"" in formatted

