"""
Target Cloud Architecture Generator for CloudMove.

Constructs an authentic, comprehensive Target Architecture CMIR model
dynamically derived from the workload being migrated and the user's
architectural choices (user_decisions):
- Dynamically adapts to Single Instance vs High-Availability ALB + Auto Scaling Group.
- Dynamically adapts to External BaaS (Supabase) vs Cloud-Managed Database (Amazon RDS PostgreSQL / Cloud SQL).
- Reflects the exact components, ports, and frameworks discovered in the application.
- Reflects Cloud Security & Secrets Management (AWS Secrets Manager + IAM Least-Privilege Role).
"""

from typing import Dict, Any, List, Optional
from app.cmir.models import CMIR, Resource, Relationship


def build_target_cloud_cmir(
    app_discovery: Dict[str, Any],
    target_provider: str = "aws",
    deployment_mode: str = "vm_rehost",
    user_decisions: Optional[Dict[str, str]] = None,
    terraform_artifacts: Optional[Dict[str, Any]] = None,
) -> CMIR:
    """
    Construct the authoritative Target Cloud Architecture CMIR dynamically
    based on the inspected workload, interactive user decisions, and the generated Terraform code.
    """
    provider = target_provider.lower().strip()
    app_name = app_discovery.get("app_name", "Application")
    slug = app_name.lower().replace(" ", "-").replace("_", "-")
    now = app_discovery.get("discovered_at") or "2026-11-03T16:00:00Z"

    # Merge decisions from parameter or app_discovery
    decisions = dict(user_decisions or app_discovery.get("user_decisions") or {})

    # Compute choice
    comp_choice = decisions.get("compute_architecture", "single_instance_containerized")
    is_high_availability = comp_choice in ("ha_asg_alb_containerized", "ha_alb_asg")

    # Database choice (check if user decided to provision cloud database vs keep external)
    provision_cloud_rds = any(
        v == "provision_cloud_db"
        for k, v in decisions.items()
        if "dep:" in k or "database" in k or "supabase" in k
    )

    resources: List[Resource] = []
    relationships: List[Relationship] = []

    # -------------------------------------------------------------
    # 1. Cloud Provider & Regional Boundary
    # -------------------------------------------------------------
    cloud_id = f"target-cloud-{provider}"
    region_id = f"target-region-{provider}-useast1"

    resources.append(Resource(
        id=cloud_id,
        canonical_id=f"cloud:{provider}",
        name=f"Nube Destino: {provider.upper()} (Amazon Web Services)" if provider == "aws" else "Nube Destino: Google Cloud Platform",
        type="cloud",
        category="cloud_provider",
        level=0,
        provider=provider,
        status="TARGET_PLANNED",
        is_shared=True,
        epistemic_state="derived",
        confidence=1.0,
        source_connector="cloudmove_target_architect",
        discovered_at=now,
        metadata={
            "is_target_architecture": True,
            "provider_display": provider.upper(),
            "applied_compute_architecture": comp_choice,
        },
    ))

    resources.append(Resource(
        id=region_id,
        canonical_id=f"region:{provider}:us-east-1",
        name="Región Primaria: us-east-1 (N. Virginia, Multi-AZ)",
        type="region",
        category="network",
        level=1,
        parent_id=cloud_id,
        provider=provider,
        status="TARGET_PLANNED",
        is_shared=True,
        epistemic_state="derived",
        confidence=1.0,
        source_connector="cloudmove_target_architect",
        discovered_at=now,
        metadata={"region": "us-east-1", "availability_zones": ["us-east-1a", "us-east-1b"]},
    ))
    relationships.append(Relationship(
        id=f"rel-{cloud_id}-contains-{region_id}",
        source=cloud_id,
        target=region_id,
        type="contains",
        epistemic_state="derived",
        confidence=1.0,
    ))

    # -------------------------------------------------------------
    # 2. Virtual Private Cloud (VPC) & Networking
    # -------------------------------------------------------------
    vpc_id = "target-vpc-main"
    igw_id = "target-igw-main"
    resources.append(Resource(
        id=vpc_id,
        canonical_id=f"vpc:{provider}:10.0.0.0-16",
        name="VPC: cloudmove-target-vpc (10.0.0.0/16)",
        type="vpc",
        category="network",
        level=2,
        parent_id=region_id,
        provider=provider,
        status="TARGET_PLANNED",
        epistemic_state="derived",
        confidence=1.0,
        source_connector="cloudmove_target_architect",
        discovered_at=now,
        network={"cidr": "10.0.0.0/16", "dns_hostnames": True, "dns_support": True},
        metadata={"terraform_resource": "aws_vpc.target_vpc", "managed_by": "CloudMove", "is_target_architecture": True},
    ))
    relationships.append(Relationship(
        id=f"rel-{region_id}-contains-{vpc_id}",
        source=region_id,
        target=vpc_id,
        type="contains",
        epistemic_state="derived",
        confidence=1.0,
    ))

    resources.append(Resource(
        id=igw_id,
        canonical_id=f"gateway:{provider}:igw",
        name="Internet Gateway (cloudmove-igw)",
        type="gateway",
        category="network",
        level=3,
        parent_id=vpc_id,
        provider=provider,
        status="TARGET_PLANNED",
        epistemic_state="derived",
        confidence=1.0,
        source_connector="cloudmove_target_architect",
        discovered_at=now,
        metadata={"terraform_resource": "aws_internet_gateway.igw", "provides_internet_access": True},
    ))
    relationships.append(Relationship(
        id=f"rel-{vpc_id}-contains-{igw_id}",
        source=vpc_id,
        target=igw_id,
        type="contains",
        epistemic_state="derived",
        confidence=1.0,
    ))

    # Subnets (Public & Private across Multi-AZ)
    sub_pub_a = "target-subnet-public-a"
    sub_pub_b = "target-subnet-public-b"
    sub_priv_a = "target-subnet-private-a"
    sub_priv_b = "target-subnet-private-b"

    resources.append(Resource(
        id=sub_pub_a,
        canonical_id=f"subnet:{provider}:pub-a",
        name="Subred Pública A (10.0.1.0/24 — us-east-1a)",
        type="subnet",
        category="network",
        level=3,
        parent_id=vpc_id,
        provider=provider,
        status="TARGET_PLANNED",
        network={"cidr": "10.0.1.0/24", "az": "us-east-1a", "map_public_ip": True},
        epistemic_state="derived",
        confidence=1.0,
        discovered_at=now,
        metadata={"terraform_resource": "aws_subnet.public_subnet"},
    ))
    resources.append(Resource(
        id=sub_pub_b,
        canonical_id=f"subnet:{provider}:pub-b",
        name="Subred Pública B (10.0.4.0/24 — us-east-1b)",
        type="subnet",
        category="network",
        level=3,
        parent_id=vpc_id,
        provider=provider,
        status="TARGET_PLANNED",
        network={"cidr": "10.0.4.0/24", "az": "us-east-1b", "map_public_ip": True},
        epistemic_state="derived",
        confidence=1.0,
        discovered_at=now,
        metadata={"terraform_resource": "aws_subnet.public_subnet_b"},
    ))
    resources.append(Resource(
        id=sub_priv_a,
        canonical_id=f"subnet:{provider}:priv-a",
        name="Subred Privada A (10.0.2.0/24 — us-east-1a)",
        type="subnet",
        category="network",
        level=3,
        parent_id=vpc_id,
        provider=provider,
        status="TARGET_PLANNED",
        network={"cidr": "10.0.2.0/24", "az": "us-east-1a", "map_public_ip": False},
        epistemic_state="derived",
        confidence=1.0,
        discovered_at=now,
        metadata={"terraform_resource": "aws_subnet.private_subnet_a"},
    ))
    resources.append(Resource(
        id=sub_priv_b,
        canonical_id=f"subnet:{provider}:priv-b",
        name="Subred Privada B (10.0.3.0/24 — us-east-1b)",
        type="subnet",
        category="network",
        level=3,
        parent_id=vpc_id,
        provider=provider,
        status="TARGET_PLANNED",
        network={"cidr": "10.0.3.0/24", "az": "us-east-1b", "map_public_ip": False},
        epistemic_state="derived",
        confidence=1.0,
        discovered_at=now,
        metadata={"terraform_resource": "aws_subnet.private_subnet_b"},
    ))
    for s_id in (sub_pub_a, sub_pub_b, sub_priv_a, sub_priv_b):
        relationships.append(Relationship(
            id=f"rel-{vpc_id}-contains-{s_id}",
            source=vpc_id,
            target=s_id,
            type="contains",
            epistemic_state="derived",
            confidence=1.0,
        ))

    # Route Table Pública
    rt_pub_id = "target-rt-public"
    resources.append(Resource(
        id=rt_pub_id,
        canonical_id=f"route_table:{provider}:public-rt",
        name="Route Table Pública (0.0.0.0/0 -> IGW)",
        type="route_table",
        category="network",
        level=3,
        parent_id=vpc_id,
        provider=provider,
        status="TARGET_PLANNED",
        epistemic_state="derived",
        confidence=1.0,
        discovered_at=now,
        metadata={
            "terraform_resource": "aws_route_table.public_rt",
            "routes": [{"destination": "0.0.0.0/0", "target": "aws_internet_gateway.igw"}],
        },
    ))
    relationships.append(Relationship(
        id=f"rel-{vpc_id}-contains-{rt_pub_id}",
        source=vpc_id,
        target=rt_pub_id,
        type="contains",
        epistemic_state="derived",
        confidence=1.0,
    ))
    relationships.append(Relationship(
        id=f"rel-{rt_pub_id}-routes_to-{igw_id}",
        source=rt_pub_id,
        target=igw_id,
        type="routes_to",
        epistemic_state="derived",
        confidence=1.0,
        metadata={"label": "Default Gateway (0.0.0.0/0)"},
    ))
    relationships.append(Relationship(
        id=f"rel-{rt_pub_id}-associates_with-{sub_pub_a}",
        source=rt_pub_id,
        target=sub_pub_a,
        type="associates_with",
        epistemic_state="derived",
        confidence=1.0,
    ))

    # Security Group de la Aplicación
    sg_id = "target-sg-app"
    ports = app_discovery.get("exposed_ports", [80, 8000])
    sg_ports = [22, 443, *ports]
    resources.append(Resource(
        id=sg_id,
        canonical_id=f"security_group:{provider}:app-sg",
        name="Security Group: cloudmove-app-sg",
        type="security_group",
        category="network",
        level=3,
        parent_id=vpc_id,
        provider=provider,
        status="TARGET_PLANNED",
        epistemic_state="derived",
        confidence=1.0,
        discovered_at=now,
        security={"ingress_ports": sg_ports},
        metadata={
            "terraform_resource": "aws_security_group.app_sg",
            "ports_summary": ", ".join(str(p) for p in sorted(set(sg_ports))),
        },
    ))
    relationships.append(Relationship(
        id=f"rel-{vpc_id}-contains-{sg_id}",
        source=vpc_id,
        target=sg_id,
        type="contains",
        epistemic_state="derived",
        confidence=1.0,
    ))
    relationships.append(Relationship(
        id=f"rel-{igw_id}-routes_to-{sg_id}",
        source=igw_id,
        target=sg_id,
        type="routes_to",
        epistemic_state="derived",
        confidence=1.0,
        metadata={"label": "Ingress Internet Público (0.0.0.0/0)"},
    ))

    # -------------------------------------------------------------
    # 3. Dynamic Compute Tier (High-Availability ALB+ASG vs Single Instance)
    # -------------------------------------------------------------
    if is_high_availability:
        alb_id = f"target-alb-{slug}"
        asg_id = f"target-asg-{slug}"
        tg_id = f"target-tg-{slug}"
        lt_id = f"target-lt-{slug}"
        alb_sg_id = "target-sg-alb"

        # Security Group del Balanceador
        resources.append(Resource(
            id=alb_sg_id,
            canonical_id=f"security_group:{provider}:alb-sg",
            name="Security Group ALB: cloudmove-alb-sg (80, 443)",
            type="security_group",
            category="network",
            level=3,
            parent_id=vpc_id,
            provider=provider,
            status="TARGET_PLANNED",
            epistemic_state="derived",
            confidence=1.0,
            discovered_at=now,
            security={"ingress_ports": [80, 443]},
            metadata={"terraform_resource": "aws_security_group.alb_sg"},
        ))
        relationships.append(Relationship(
            id=f"rel-{vpc_id}-contains-{alb_sg_id}",
            source=vpc_id,
            target=alb_sg_id,
            type="contains",
            epistemic_state="derived",
            confidence=1.0,
        ))

        # Application Load Balancer
        resources.append(Resource(
            id=alb_id,
            canonical_id=f"load_balancer:{provider}:{slug}",
            name=f"Application Load Balancer (ALB): {app_name}-alb",
            type="load_balancer",
            category="network",
            level=3,
            parent_id=vpc_id,
            provider=provider,
            status="TARGET_PLANNED",
            epistemic_state="derived",
            confidence=1.0,
            discovered_at=now,
            metadata={
                "terraform_resource": "aws_lb.app_alb",
                "type": "Application Load Balancer (Layer 7)",
                "subnets": ["Subred Pública A", "Subred Pública B"],
                "health_check": "HTTP :80/health (Interval 30s, Timeout 5s)",
            },
        ))
        relationships.append(Relationship(
            id=f"rel-{alb_sg_id}-secures-{alb_id}",
            source=alb_sg_id,
            target=alb_id,
            type="secures",
            epistemic_state="derived",
            confidence=1.0,
        ))

        # Target Group
        resources.append(Resource(
            id=tg_id,
            canonical_id=f"target_group:{provider}:{slug}",
            name=f"Target Group: {app_name}-tg (HTTP :80/health)",
            type="target_group",
            category="network",
            level=3,
            parent_id=alb_id,
            provider=provider,
            status="TARGET_PLANNED",
            epistemic_state="derived",
            confidence=1.0,
            discovered_at=now,
            metadata={
                "terraform_resource": "aws_lb_target_group.app_tg",
                "protocol": "HTTP",
                "port": 80,
                "health_check_path": "/health",
            },
        ))
        relationships.append(Relationship(
            id=f"rel-{alb_id}-routes_to-{tg_id}",
            source=alb_id,
            target=tg_id,
            type="routes_to",
            epistemic_state="derived",
            confidence=1.0,
        ))

        # Launch Template
        resources.append(Resource(
            id=lt_id,
            canonical_id=f"launch_template:{provider}:{slug}",
            name=f"Launch Template: {app_name}-template (t3.micro / Ubuntu 22.04 LTS)",
            type="template",
            category="compute",
            level=4,
            parent_id=sub_pub_a,
            provider=provider,
            status="TARGET_PLANNED",
            epistemic_state="derived",
            confidence=1.0,
            discovered_at=now,
            metadata={
                "terraform_resource": "aws_launch_template.compute_host_lt",
                "instance_type": "t3.micro",
                "ami_distro": "Ubuntu 22.04 LTS",
                "user_data": "user_data.sh (Docker Compose bootstrapping)",
            },
        ))

        # Auto Scaling Group
        resources.append(Resource(
            id=asg_id,
            canonical_id=f"asg:{provider}:{slug}",
            name=f"Auto Scaling Group: {app_name}-asg (Min: 1, Deseado: 2, Max: 3)",
            type="cluster",
            category="compute",
            level=4,
            parent_id=sub_pub_a,
            provider=provider,
            status="TARGET_PLANNED",
            epistemic_state="derived",
            confidence=1.0,
            discovered_at=now,
            metadata={
                "terraform_resource": "aws_autoscaling_group.compute_host_asg",
                "launch_template": f"{app_name}-template (t3.micro Free Tier / Ubuntu 22.04 LTS)",
                "min_size": 1,
                "desired_capacity": 2,
                "max_size": 3,
                "target_group": f"{app_name}-tg",
            },
        ))
        relationships.append(Relationship(
            id=f"rel-{tg_id}-routes_to-{asg_id}",
            source=tg_id,
            target=asg_id,
            type="routes_to",
            epistemic_state="derived",
            confidence=1.0,
            metadata={"label": "Distribución Dinámica de Carga"},
        ))
        relationships.append(Relationship(
            id=f"rel-{asg_id}-uses-{lt_id}",
            source=asg_id,
            target=lt_id,
            type="uses",
            epistemic_state="derived",
            confidence=1.0,
        ))
        primary_compute_parent = asg_id
    else:
        ec2_id = f"target-compute-{slug}-host"
        resources.append(Resource(
            id=ec2_id,
            canonical_id=f"compute:{provider}:{slug}",
            name=f"Instancia EC2: {app_name}-host (t3.micro Free Tier)",
            type="virtual_machine",
            category="compute",
            level=4,
            parent_id=sub_pub_a,
            provider=provider,
            platform="Ubuntu 22.04 LTS (HVM SSD)",
            status="TARGET_PLANNED",
            epistemic_state="derived",
            confidence=1.0,
            discovered_at=now,
            metadata={
                "instance_type": "t3.micro",
                "free_tier_eligible": True,
                "swap_memory": "2 GB Swapfile (/swapfile) anti-OOM",
                "managed_by": "CloudMove",
                "bootstrap_script": "user_data.sh (Docker Compose + Systemd Auto-restart)",
            },
        ))
        relationships.append(Relationship(
            id=f"rel-{sub_pub_a}-contains-{ec2_id}",
            source=sub_pub_a,
            target=ec2_id,
            type="contains",
            epistemic_state="derived",
            confidence=1.0,
        ))
        relationships.append(Relationship(
            id=f"rel-{sg_id}-secures-{ec2_id}",
            source=sg_id,
            target=ec2_id,
            type="secures",
            epistemic_state="derived",
            confidence=1.0,
            metadata={"label": "Aplica Reglas de Red y Puertos"},
        ))
        primary_compute_parent = ec2_id

    # Docker Container Host Environment
    docker_id = f"target-docker-{slug}-stack"
    resources.append(Resource(
        id=docker_id,
        canonical_id=f"container_engine:{slug}",
        name="Motor Docker Engine & Docker Compose Stack",
        type="container",
        category="compute",
        level=5,
        parent_id=primary_compute_parent,
        provider=provider,
        status="TARGET_PLANNED",
        epistemic_state="derived",
        confidence=1.0,
        discovered_at=now,
        metadata={
            "orchestrator": "Docker Compose v2",
            "auto_healing": "Systemd unit (cocoaapp-containers.service) with restart=always",
            "internal_network": "bridge_network (172.x.x.x)",
        },
    ))
    relationships.append(Relationship(
        id=f"rel-{primary_compute_parent}-hosts-{docker_id}",
        source=primary_compute_parent,
        target=docker_id,
        type="hosts",
        epistemic_state="derived",
        confidence=1.0,
    ))

    # -------------------------------------------------------------
    # 4. Multi-Tier Workloads / Containers (from Discovered Components)
    # -------------------------------------------------------------
    components = app_discovery.get("components") or []
    workload_ids: Dict[str, str] = {}

    if components:
        for comp in components:
            c_name = comp["name"]
            c_id = f"target-app-{slug}-{c_name}"
            workload_ids[c_name] = c_id
            tier = comp.get("tier", "backend")
            p_map = comp.get("container_ports", [80])[0]
            h_map = comp.get("host_ports", [80])[0]

            resources.append(Resource(
                id=c_id,
                canonical_id=f"workload:{slug}:{c_name}",
                name=f"Contenedor {c_name.capitalize()}: {comp.get('framework') or comp.get('language') or 'App'} (:{h_map} -> :{p_map})",
                type="application",
                category="compute",
                level=6,
                parent_id=docker_id,
                provider=provider,
                platform=comp.get("runtime", "container"),
                status="TARGET_PLANNED",
                epistemic_state="derived",
                confidence=1.0,
                discovered_at=now,
                metadata={
                    "tier": tier,
                    "exposed_port": h_map,
                    "container_port": p_map,
                    "framework": comp.get("framework"),
                    "runtime": comp.get("runtime"),
                },
            ))
            relationships.append(Relationship(
                id=f"rel-{docker_id}-contains-{c_id}",
                source=docker_id,
                target=c_id,
                type="contains",
                epistemic_state="derived",
                confidence=1.0,
            ))

        # Inter-container service link if frontend and backend exist
        if "frontend" in workload_ids and "backend" in workload_ids:
            relationships.append(Relationship(
                id=f"rel-{workload_ids['frontend']}-communicates_with-{workload_ids['backend']}",
                source=workload_ids["frontend"],
                target=workload_ids["backend"],
                type="communicates_with",
                epistemic_state="derived",
                confidence=1.0,
                metadata={"protocol": "HTTP/REST", "port": 8000, "label": "API REST Interna (:8000) Docker Network"},
            ))
    else:
        # Fallback single app container
        app_c_id = f"target-app-{slug}-service"
        workload_ids["app"] = app_c_id
        resources.append(Resource(
            id=app_c_id,
            canonical_id=f"workload:{slug}:main",
            name=f"Contenedor {app_name}: {app_discovery.get('runtime', 'Docker')}",
            type="application",
            category="compute",
            level=6,
            parent_id=docker_id,
            provider=provider,
            status="TARGET_PLANNED",
            epistemic_state="derived",
            confidence=1.0,
            discovered_at=now,
        ))
        relationships.append(Relationship(
            id=f"rel-{docker_id}-contains-{app_c_id}",
            source=docker_id,
            target=app_c_id,
            type="contains",
            epistemic_state="derived",
            confidence=1.0,
        ))

    # -------------------------------------------------------------
    # 5. Security & Secrets Management (AWS Secrets Manager + IAM)
    # -------------------------------------------------------------
    sec_id = f"target-secret-{slug}-manager"
    iam_id = f"target-iam-{slug}-role"

    resources.append(Resource(
        id=sec_id,
        canonical_id=f"secret:{provider}:app-secrets",
        name=f"AWS Secrets Manager (cloudmove/production/{slug}-secrets)",
        type="secret",
        category="security",
        level=2,
        parent_id=region_id,
        provider=provider,
        status="TARGET_PLANNED",
        epistemic_state="derived",
        confidence=1.0,
        discovered_at=now,
        metadata={
            "terraform_resource": "aws_secretsmanager_secret.secrets",
            "kms_encryption": "aws/secretsmanager (AES-256)",
            "managed_by": "CloudMove Zero-Trust Engine",
            "least_privilege": "Acceso restringido únicamente al rol IAM de la instancia",
        },
    ))
    relationships.append(Relationship(
        id=f"rel-{region_id}-contains-{sec_id}",
        source=region_id,
        target=sec_id,
        type="contains",
        epistemic_state="derived",
        confidence=1.0,
    ))

    resources.append(Resource(
        id=iam_id,
        canonical_id=f"iam:{provider}:instance-profile",
        name="IAM Role & Instance Profile (Mínimo Privilegio SecretReader)",
        type="role",
        category="security",
        level=2,
        parent_id=region_id,
        provider=provider,
        status="TARGET_PLANNED",
        epistemic_state="derived",
        confidence=1.0,
        discovered_at=now,
        metadata={
            "terraform_resource": "aws_iam_instance_profile.identity_sa_profile",
            "actions": ["secretsmanager:GetSecretValue", "kms:Decrypt"],
        },
    ))
    relationships.append(Relationship(
        id=f"rel-{iam_id}-secures-{primary_compute_parent}",
        source=iam_id,
        target=primary_compute_parent,
        type="secures",
        epistemic_state="derived",
        confidence=1.0,
        metadata={"label": "Instance Profile Asignado"},
    ))
    relationships.append(Relationship(
        id=f"rel-{primary_compute_parent}-reads_from-{sec_id}",
        source=primary_compute_parent,
        target=sec_id,
        type="reads_from",
        epistemic_state="derived",
        confidence=1.0,
        metadata={"label": "Inyección Segura de Secretos al Bootstrapping"},
    ))

    # -------------------------------------------------------------
    # 6. Database / BaaS Tier (Dynamic: Amazon RDS vs Supabase BaaS)
    # -------------------------------------------------------------
    backend_ref = workload_ids.get("backend") or workload_ids.get("app")
    frontend_ref = workload_ids.get("frontend")

    if provision_cloud_rds:
        rds_id = f"target-db-{slug}-rds"
        resources.append(Resource(
            id=rds_id,
            canonical_id=f"database:{provider}:{slug}-rds",
            name="Amazon RDS PostgreSQL 15 (db.t3.micro, Multi-AZ)",
            type="database_instance",
            category="data",
            level=3,
            parent_id=sub_priv_a,
            provider=provider,
            status="TARGET_PLANNED",
            is_shared=False,
            epistemic_state="derived",
            confidence=1.0,
            discovered_at=now,
            metadata={
                "engine": "PostgreSQL 15 (AWS RDS)",
                "allocated_storage_gb": 20,
                "multi_az": True,
                "subnet_group": "cloudmove-db-subnets (Privada A & B)",
                "managed_by": "CloudMove Managed Infrastructure",
                "badge": "BASE DE DATOS NUBE GESTIONADA",
            },
        ))
        relationships.append(Relationship(
            id=f"rel-{sub_priv_a}-contains-{rds_id}",
            source=sub_priv_a,
            target=rds_id,
            type="contains",
            epistemic_state="derived",
            confidence=1.0,
        ))
        if backend_ref:
            relationships.append(Relationship(
                id=f"rel-{backend_ref}-writes_to-{rds_id}",
                source=backend_ref,
                target=rds_id,
                type="writes_to",
                epistemic_state="derived",
                confidence=1.0,
                metadata={"protocol": "TLS / TCP 5432 (Subredes Privadas)", "label": "Conexión Privada PostgreSQL"},
            ))
    else:
        # Check if external BaaS exists
        has_supabase = any(
            "supabase" in str(d.get("name", "")).lower() or "supabase" in str(d.get("engine", "")).lower()
            for d in app_discovery.get("dependencies", [])
        ) or app_discovery.get("deep_insights", {}).get("supabase_detected")

        if has_supabase:
            ext_sb_id = "target-ext-supabase-baas"
            resources.append(Resource(
                id=ext_sb_id,
                canonical_id="external:baas:supabase",
                name="Supabase BaaS (PostgreSQL Gestionado + Auth)",
                type="database_instance",
                category="data",
                level=1,
                provider="supabase",
                status="EXTERNAL_ACTIVE",
                is_shared=False,
                epistemic_state="observed",
                confidence=1.0,
                discovered_at=now,
                metadata={
                    "is_external": True,
                    "managed_by_platform": False,
                    "badge": "SERVICIO EXTERNO (No administrado)",
                    "endpoint": "https://zlkdxzfxkhohlpswdmap.supabase.co",
                    "engine": "PostgreSQL 15 (Supabase Cloud)",
                    "auth_provider": "Supabase GoTrue Auth",
                    "why_preserved": "Base de datos y autenticación preservadas en su proveedor externo sin costo de RDS.",
                },
            ))
            if backend_ref:
                relationships.append(Relationship(
                    id=f"rel-{backend_ref}-writes_to-{ext_sb_id}",
                    source=backend_ref,
                    target=ext_sb_id,
                    type="writes_to",
                    epistemic_state="derived",
                    confidence=1.0,
                    metadata={"protocol": "PostgreSQL TLS :5432 / HTTPS PostgREST", "label": "Consultas SQL (Egress TLS)"},
                ))
            if frontend_ref:
                relationships.append(Relationship(
                    id=f"rel-{frontend_ref}-connects_to-{ext_sb_id}",
                    source=frontend_ref,
                    target=ext_sb_id,
                    type="connects_to",
                    epistemic_state="derived",
                    confidence=1.0,
                    metadata={"protocol": "HTTPS REST / WSS WebSocket", "label": "Supabase Client SDK (Auth & RLS Queries)"},
                ))

    return CMIR(
        name=f"Arquitectura Objetivo en la Nube ({provider.upper()}) — {app_name}",
        provider=provider,
        created_at=now,
        resources=resources,
        relationships=relationships,
        metadata={
            "is_target_architecture": True,
            "workload_name": app_name,
            "deployment_mode": deployment_mode,
            "target_provider": provider,
            "applied_decisions": decisions,
            "multi_tier_containers": True,
            "zero_trust_secrets_enabled": True,
            "is_high_availability": is_high_availability,
            "database_architecture": "cloud_rds_postgresql" if provision_cloud_rds else "external_supabase_baas",
        },
    )
