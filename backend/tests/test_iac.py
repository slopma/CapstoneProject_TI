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


def test_ha_containerized_multi_tier_supabase_and_ai_translator(tmp_path):
    from app.migration.app_migrator import (
        inspect_application_source,
        build_application_cmir,
        generate_app_migration_artifacts,
    )
    from app.generators.ai_translator import (
        prepare_ai_payload,
        generate_cheap_infrastructure,
        write_terraform_artifacts,
    )

    inline_cocoa = {
        "docker-compose.prod.yml": (
            "version: '3.8'\n"
            "services:\n"
            "  backend:\n"
            "    build: ./backend\n"
            "    ports:\n"
            "      - '8000:8000'\n"
            "  frontend:\n"
            "    build: ./frontend-vite\n"
            "    ports:\n"
            "      - '3000:80'\n"
        ),
        "backend/Dockerfile": "FROM python:3.11-slim\nEXPOSE 8000\nCMD [\"uvicorn\", \"src.db.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n",
        "backend/requirements.txt": "fastapi==0.104.1\nuvicorn==0.24.0\nsupabase==2.4.0\ngeopandas==0.14.3\nscikit-learn==1.5.0\n",
        "frontend-vite/Dockerfile": "FROM nginx:alpine\nEXPOSE 80\nCMD [\"nginx\", \"-g\", \"daemon off;\"]\n",
        "frontend-vite/package.json": json.dumps({
            "name": "cocoa-frontend",
            "dependencies": {"react": "^18.2.0", "@supabase/supabase-js": "^2.57.4"},
        }),
        "frontend-vite/.env": (
            "VITE_SUPABASE_URL=https://zlkdxzfxkhohlpswdmap.supabase.co\n"
            "VITE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSJ9.sig\n"
            "VITE_API_URL=http://127.0.0.1:8000\n"
        ),
    }

    disc = inspect_application_source(inline_files=inline_cocoa, app_name_override="CocoaApp")
    cmir = build_application_cmir(disc, target_provider="aws", deployment_mode="container")
    bundle = generate_app_migration_artifacts(disc, cmir, target_provider="aws")

    assert bundle["validation"]["valid"] is True
    main_tf = bundle["files"]["main.tf"]

    # 1. Must include High Availability ALB, Target Group, Listener, Launch Template, and Auto Scaling Group
    assert 'data "aws_ami" "ubuntu"' in main_tf
    assert 'resource "aws_lb" "app_alb"' in main_tf
    assert 'resource "aws_lb_target_group" "app_tg"' in main_tf
    assert 'resource "aws_lb_listener" "http_listener"' in main_tf
    assert 'resource "aws_launch_template" "compute_cocoaapp_host_lt"' in main_tf
    assert 'resource "aws_autoscaling_group" "compute_cocoaapp_host_asg"' in main_tf

    # 2. Must NOT create phantom EC2 instances for child apps, identity, or service_mesh_link
    assert 'resource "aws_instance" "app_cocoaapp"' not in main_tf
    assert 'resource "aws_instance" "identity_cocoaapp_sa"' not in main_tf
    assert 'resource "aws_instance" "dep_cocoaapp_mesh_frontend_to_backend"' not in main_tf
    assert 'resource "aws_iam_role" "identity_cocoaapp_sa"' in main_tf
    assert 'resource "aws_iam_instance_profile" "identity_cocoaapp_sa_profile"' in main_tf

    # 3. Must NOT provision a redundant RDS instance when Supabase BaaS is used
    assert 'resource "aws_db_instance"' not in main_tf
    assert "External BaaS Preserved" in main_tf

    # 4. Must include containerized user_data.sh with 2GB swap and docker compose
    assert "user_data.sh" in bundle["files"]
    assert "/swapfile" in bundle["files"]["user_data.sh"]
    assert "docker compose" in bundle["files"]["user_data.sh"]

    # 5. Test AI Orchestrator payload & synthesis
    ai_payload = prepare_ai_payload(disc, repo_url="https://github.com/slopma/CocoaApp")
    assert ai_payload["repository_url"] == "https://github.com/slopma/CocoaApp"
    assert "eyJhbGci" not in json.dumps(ai_payload)
    tf_out = generate_cheap_infrastructure(ai_payload, api_key="")
    assert tf_out["validation"]["valid"] is True
    written = write_terraform_artifacts(tf_out, str(tmp_path / "ai_out"))
    assert "main.tf" in written
    assert "user_data.sh" in written


def test_interactive_github_to_cloud_transformation_decisions():
    from app.migration.app_migrator import (
        inspect_application_source,
        build_application_cmir,
        generate_app_migration_artifacts,
    )

    inline_cocoa = {
        "docker-compose.yml": (
            "version: '3.8'\n"
            "services:\n"
            "  backend:\n"
            "    build: ./backend\n"
            "    ports:\n"
            "      - '8000:8000'\n"
            "  frontend:\n"
            "    build: ./frontend-vite\n"
            "    ports:\n"
            "      - '3000:80'\n"
        ),
        "backend/Dockerfile": "FROM python:3.11-slim\nEXPOSE 8000\n",
        "backend/requirements.txt": "fastapi==0.104.1\nsupabase==2.4.0\n",
        "frontend-vite/Dockerfile": "FROM nginx:alpine\nEXPOSE 80\n",
        "frontend-vite/package.json": json.dumps({
            "name": "cocoa-frontend",
            "dependencies": {"react": "^18.2.0", "@supabase/supabase-js": "^2.57.4"},
        }),
        "frontend-vite/.env": "VITE_SUPABASE_URL=https://example.supabase.co\n",
    }

    disc = inspect_application_source(inline_files=inline_cocoa, app_name_override="CocoaApp")
    catalog = disc["transformation_catalog"]
    assert len(catalog["items"]) >= 5
    assert len(catalog["planned_resources_summary"]) >= 4

    item_ids = {item["id"] for item in catalog["items"]}
    assert "compute_architecture" in item_ids
    assert "dep:dep-cocoaapp-supabase-baas" in item_ids
    assert "secrets_and_env" in item_ids
    assert "workload_identity" in item_ids

    # Case A: User overrides Supabase to transform to cloud-managed RDS, chooses single EC2 instance,
    # chooses S3 Static Hosting for frontend, AWS Secrets Manager, and skips IAM Role (for AWS Academy)
    custom_decisions = {
        "compute_architecture": "single_instance_containerized",
        "dep:dep-cocoaapp-supabase-baas": "transform_to_cloud_managed",
        "component:frontend": "cloud_static_storage",
        "secrets_and_env": "cloud_secrets_manager",
        "workload_identity": "skip_custom_iam",
    }
    cmir_custom = build_application_cmir(
        disc,
        target_provider="aws",
        deployment_mode="container",
        user_decisions=custom_decisions,
    )
    bundle_custom = generate_app_migration_artifacts(disc, cmir_custom, target_provider="aws")
    assert bundle_custom["validation"]["valid"] is True
    main_tf_custom = bundle_custom["files"]["main.tf"]

    # Should provision RDS because user explicitly chose transform_to_cloud_managed for Supabase
    assert 'resource "aws_db_instance"' in main_tf_custom
    # Should provision a single aws_instance instead of ALB + Auto Scaling Group
    assert 'resource "aws_instance" "compute_cocoaapp_host"' in main_tf_custom
    assert 'resource "aws_lb" "app_alb"' not in main_tf_custom
    assert 'resource "aws_autoscaling_group"' not in main_tf_custom
    # Should provision S3 Static Website Hosting for frontend
    assert 'resource "aws_s3_bucket"' in main_tf_custom
    assert 'resource "aws_s3_bucket_website_configuration"' in main_tf_custom
    # Should provision AWS Secrets Manager secret
    assert 'resource "aws_secretsmanager_secret"' in main_tf_custom
    # Should skip IAM Role creation when skip_custom_iam is selected
    assert 'resource "aws_iam_role"' not in main_tf_custom


def test_native_compose_yaml_env_interpolation_and_probe_endpoints(tmp_path, monkeypatch):
    import base64
    import gzip
    import re
    import subprocess
    from fastapi.testclient import TestClient
    from app.api.routers import migration as migration_router
    from app.main import app
    from app.migration.app_migrator import (
        inspect_application_source,
        build_application_cmir,
        generate_app_migration_artifacts,
    )

    repo_dir = tmp_path / "bookstore-repo"
    (repo_dir / "backend").mkdir(parents=True)
    (repo_dir / "frontend").mkdir(parents=True)
    (repo_dir / "database").mkdir(parents=True)

    (repo_dir / "compose.yaml").write_text(
        "services:\n"
        "  postgres:\n"
        "    image: ${POSTGRES_IMAGE:?POSTGRES_IMAGE is required}\n"
        "    ports:\n"
        "      - \"${POSTGRES_HOST_PORT:?POSTGRES_HOST_PORT is required}:5432\"\n"
        "  bootstrap:\n"
        "    image: ${BOOTSTRAP_IMAGE:?BOOTSTRAP_IMAGE is required}\n"
        "    depends_on:\n"
        "      postgres:\n"
        "        condition: service_healthy\n"
        "  backend:\n"
        "    build:\n"
        "      context: ./backend\n"
        "    ports:\n"
        "      - \"${BACKEND_HOST_PORT:?BACKEND_HOST_PORT is required}:${PORT:?PORT is required}\"\n"
        "    depends_on:\n"
        "      bootstrap:\n"
        "        condition: service_completed_successfully\n"
        "    healthcheck:\n"
        "      test: [\"CMD-SHELL\", \"wget -q --spider http://localhost:$$PORT/health\"]\n"
        "  frontend:\n"
        "    build:\n"
        "      context: ./frontend\n"
        "    ports:\n"
        "      - \"${FRONTEND_HOST_PORT:?FRONTEND_HOST_PORT is required}:${NGINX_PORT:?NGINX_PORT is required}\"\n"
        "    depends_on:\n"
        "      backend:\n"
        "        condition: service_healthy\n",
        encoding="utf-8",
    )
    (repo_dir / ".env.example").write_text(
        "POSTGRES_IMAGE=postgres:17-alpine\n"
        "BOOTSTRAP_IMAGE=postgres:17\n"
        "FRONTEND_HOST_PORT=8080\n"
        "BACKEND_HOST_PORT=5001\n"
        "POSTGRES_HOST_PORT=5432\n"
        "NGINX_PORT=80\n"
        "PORT=5001\n"
        "CORS_ORIGINS=http://localhost:3000,http://localhost:8080\n"
        "DB_HOST=postgres\n"
        "DB_NAME=bookstore\n"
        "DB_ADMIN_USER=bookstore_admin\n"
        "APP_DB_USER=bookstore_app\n",
        encoding="utf-8",
    )
    (repo_dir / "backend" / "Dockerfile").write_text("FROM node:24-alpine\nCMD [\"npm\", \"start\"]\n", encoding="utf-8")
    (repo_dir / "backend" / "package.json").write_text(
        json.dumps({"name": "bookstore-backend", "dependencies": {"express": "5.1.0", "pg": "8.16.3"}}),
        encoding="utf-8",
    )
    (repo_dir / "frontend" / "Dockerfile").write_text("FROM nginx:1.27-alpine\nCMD [\"nginx\", \"-g\", \"daemon off;\"]\n", encoding="utf-8")
    (repo_dir / "frontend" / "package.json").write_text(
        json.dumps({"name": "bookstore-frontend", "dependencies": {"react": "19.0.0", "vite": "6.0.0"}}),
        encoding="utf-8",
    )
    (repo_dir / "database" / "schema.sql").write_text(
        "CREATE TABLE public.books (book_id UUID PRIMARY KEY, title VARCHAR(255));\n",
        encoding="utf-8",
    )

    disc = inspect_application_source(source_path=str(repo_dir), app_name_override="bookstore")
    comp_names = [c["name"] for c in disc["components"]]
    assert comp_names == ["backend", "frontend"]
    assert 8080 in disc["exposed_ports"]
    assert 5001 in disc["exposed_ports"]
    assert disc["exposed_ports"][0] == 8080
    assert disc["service_endpoints"] == {
        "frontend_port": 8080,
        "backend_port": 5001,
        "health_endpoint": "/health",
    }

    cmir = build_application_cmir(
        disc,
        target_provider="aws",
        deployment_mode="container",
        user_decisions={
            "compute_architecture": "single_instance_containerized",
            "dep:dep-bookstore-postgresql": "self_hosted_container",
        },
    )
    bundle = generate_app_migration_artifacts(disc, cmir, target_provider="aws")
    assert bundle["validation"]["valid"] is True

    main_tf = bundle["files"]["main.tf"]
    sg_ports = set(re.findall(r"from_port\s*=\s*(\d+)", main_tf))
    assert {"22", "80", "443", "5001", "5432", "8080"}.issubset(sg_ports)

    raw_ud = bundle["files"]["user_data.sh"]
    if "CLOUDMOVE HIGH-EFFICIENCY SELF-EXTRACTING BOOTSTRAP" in raw_ud:
        m = re.search(r'echo "([A-Za-z0-9+/=]+)" \| base64 -d', raw_ud)
        decoded_ud = gzip.decompress(base64.b64decode(m.group(1))).decode("utf-8")
    else:
        decoded_ud = raw_ud
    assert "./postgres" not in decoded_ud
    assert "./bootstrap" not in decoded_ud
    assert 'COMPOSE_FILE="compose.yaml"' in decoded_ud
    assert 'PRESERVE_REPO_DB="true"' in decoded_ud
    assert "export COMPOSE_BAKE=false" in decoded_ud
    assert "append_cors_origins" in decoded_ud

    sh_file = tmp_path / "user_data_check.sh"
    sh_file.write_text(decoded_ud, encoding="utf-8")
    subprocess.run(["bash", "-n", str(sh_file)], check=True)

    # Verify probe-instance-status accepts dynamic frontend/backend ports and preserves 3000/8000 defaults
    monkeypatch.setattr(migration_router, "_probe_tcp_port", lambda host, port, timeout=2.0: True)
    monkeypatch.setattr(
        migration_router,
        "_probe_http_endpoint",
        lambda url, timeout=2.5: {"online": True, "status": 200, "message": "OK"},
    )
    client = TestClient(app)
    res_custom = client.get(
        "/api/v1/migration/probe-instance-status",
        params={"ip": "54.160.10.20", "frontend_port": 8080, "backend_port": 5001, "health_path": "/health"},
    )
    assert res_custom.status_code == 200
    body_custom = res_custom.json()
    assert body_custom["frontend"]["port"] == 8080
    assert body_custom["backend"]["port"] == 5001
    assert body_custom["backend"]["url"] == "http://54.160.10.20:5001/health"
    assert body_custom["all_ready"] is True

    res_default = client.get("/api/v1/migration/probe-instance-status", params={"ip": "54.160.10.20"})
    assert res_default.status_code == 200
    assert res_default.json()["frontend"]["port"] == 3000
    assert res_default.json()["backend"]["port"] == 8000




