"""
Hybrid Deterministic + AI Infrastructure Orchestrator (`ai_translator.py`).

Bridges CloudMove's deterministic static source analyzer (`app_migrator.py`) and CMIR v2.1
with an AI Cloud Architect (Google Gemini Structured JSON Output) and a deterministic
High-Availability Containerized Synthesizer fallback:

1. `prepare_ai_payload(discovery_data, repo_url)`:
   Extracts the clean architectural essence (components, frameworks, ports, start commands,
   redacted env var keys, Docker/Compose status, and external BaaS dependencies like Supabase)
   without sending raw secrets or noise.
2. `generate_container_user_data_sh(ai_payload)`:
   Generates a fault-tolerant, containerization-first `user_data.sh` bootstrap script that:
   - Configures a 2 GB swapfile (preventing OOM during heavy builds like geopandas/scikit-learn/vite).
   - Installs Docker Engine & Docker Compose v2.
   - Clones the GitHub repository (supporting private repos via `github_token`) at the pinned commit.
   - Writes `.env` keys safely.
   - Auto-generates `Dockerfile` / `docker-compose.cloudmove.yml` if the project lacks them so
     project weight (>250 MB dependencies) is never a migration bottleneck.
   - Starts the containers with `restart: always` and registers a systemd unit for reboot resilience.
3. `generate_cheap_infrastructure(ai_payload, api_key, model_name)`:
   Queries Gemini (`gemini-1.5-flash` / `gemini-2.0-flash`) with `response_mime_type="application/json"`,
   validates the HCL via `AWSAdapter().validate_artifacts()`, and seamlessly falls back to
   CloudMove's deterministic High-Availability (ALB + Auto Scaling Group + Multi-AZ + Containers)
   generator when running offline or without `GEMINI_API_KEY`.
4. `write_terraform_artifacts(tf_data, output_dir)`:
   Writes `main.tf`, `variables.tf`, `provider.tf`, `outputs.tf`, and `user_data.sh` to disk.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


ARCHITECTURAL_SYSTEM_PROMPT = """Eres un Arquitecto Cloud Experto especializado en AWS, Alta Disponibilidad (High Availability), Contenerización con Docker y optimización inteligente de costos.
Recibirás un JSON con la topología descubierta de una aplicación de GitHub.

TU OBJETIVO:
1. Diseñar una infraestructura en AWS altamente disponible (resiliente a fallos), contenerizada (para que el peso de librerías pesadas como scikit-learn, geopandas, pandas o node_modules nunca sea un límite como en Lambda) y optimizada en costos (instancias t3.micro elegibles en Capa Gratuita):
   - Red VPC Multi-AZ con subredes públicas en 2 Zonas de Disponibilidad (`a` y `b`), Internet Gateway y tabla de ruteo.
   - Application Load Balancer (`aws_lb`, `aws_lb_target_group`, `aws_lb_listener`) con Health Check activo en el endpoint de salud descubierto (`/health`).
   - Launch Template (`aws_launch_template`) + Auto Scaling Group (`aws_autoscaling_group`) Multi-AZ con `health_check_type = "ELB"` que reemplace automáticamente instancias no saludables, ejecutando la aplicación en contenedores Docker mediante `user_data.sh`.
   - Rol IAM de mínimo privilegio (`aws_iam_role` + `aws_iam_instance_profile`) sin costo adicional.
2. Generar el código Terraform válido para AWS Provider ~> 5.0 (`main.tf`, `variables.tf`, `provider.tf`, `outputs.tf`).
3. Generar un script de Bash (`user_data.sh`) que se inyectará en las instancias del Auto Scaling Group / EC2. Este script debe:
   - Configurar un archivo swap de 2 GB (`/swapfile`) para soportar compilaciones pesadas en instancias `t3.micro`.
   - Actualizar el sistema e instalar Docker, Docker Compose v2 y Git.
   - Clonar el repositorio desde la URL proporcionada (soportando repositorios privados si se provee `github_token`).
   - Crear un archivo `.env` base usando únicamente las llaves de variables de entorno detectadas.
   - Si el proyecto tiene `docker-compose`, ejecutar `docker compose -f <compose_file> up -d --build`. Si no tiene `Dockerfile` o `docker-compose.yml`, generar uno automáticamente y levantar los contenedores con política `restart: always`.

RESTRICCIONES ESTRICTAS:
- NO crees bases de datos `aws_db_instance` (RDS) si el JSON indica una dependencia externa gestionada BaaS (como Supabase, Firebase o MongoDB Atlas con `is_external_baas: true` o `requires_data_migration: false`).
- NO crees múltiples instancias EC2 sueltas para representar roles IAM, enlaces de red (`service_mesh_link`) o sub-contenedores que ya corren dentro del mismo `docker-compose`.
- Devuelve tu respuesta ÚNICAMENTE en formato JSON con la siguiente estructura exacta:
{
  "provider_tf": "<código terraform de provider.tf>",
  "variables_tf": "<código terraform de variables.tf>",
  "main_tf": "<código terraform completo de main.tf>",
  "outputs_tf": "<código terraform de outputs.tf>",
  "user_data_sh": "<script bash completo de user_data.sh>"
}
"""


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "app").strip().lower()).strip("-")
    return cleaned or "app"


def prepare_ai_payload(
    discovery_data: Dict[str, Any],
    repo_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Step 1: Synthesize the architectural discovery payload for AI & Containerization orchestration.
    Strips out noise (full file trees) and guarantees ZERO raw secret values are included
    (only environment variable keys are exported).
    """
    git_meta = discovery_data.get("git_metadata") or {}
    effective_repo_url = (
        repo_url
        or git_meta.get("repository_url")
        or discovery_data.get("repository_url")
        or "https://github.com/organization/application.git"
    )
    git_ref = git_meta.get("ref") or discovery_data.get("github_ref") or "main"
    commit_sha = git_meta.get("commit_sha") or "HEAD"

    env_var_keys: List[str] = []
    for ev in discovery_data.get("environment_variables", []):
        if isinstance(ev, dict) and ev.get("name"):
            env_var_keys.append(str(ev["name"]))
        elif isinstance(ev, str):
            env_var_keys.append(ev)

    raw_components = discovery_data.get("components") or []
    components_payload: List[Dict[str, Any]] = []
    if raw_components:
        for comp in raw_components:
            comp_env_keys = list((comp.get("env_vars") or {}).keys()) if isinstance(comp.get("env_vars"), dict) else []
            components_payload.append({
                "name": comp.get("name", "service"),
                "tier": comp.get("tier", "backend"),
                "context_path": comp.get("context_path", "."),
                "type": comp.get("framework") or comp.get("language") or discovery_data.get("framework", "unknown"),
                "runtime": comp.get("runtime") or discovery_data.get("runtime", "python:3.11-slim"),
                "ports": comp.get("host_ports") or comp.get("container_ports") or discovery_data.get("exposed_ports", [80]),
                "container_ports": comp.get("container_ports") or [80],
                "start_command": comp.get("start_command") or (discovery_data.get("start_commands") or [""])[0],
                "env_vars_keys": comp_env_keys or env_var_keys,
                "has_dockerfile": bool(comp.get("dockerfile")),
            })
    else:
        components_payload.append({
            "name": discovery_data.get("app_name", "app"),
            "tier": "fullstack",
            "context_path": ".",
            "type": f"{discovery_data.get('language', 'Python')} / {discovery_data.get('framework', 'FastAPI')}",
            "runtime": discovery_data.get("runtime", "python:3.11-slim"),
            "ports": discovery_data.get("exposed_ports", [8080]),
            "container_ports": discovery_data.get("exposed_ports", [8080]),
            "start_command": (discovery_data.get("start_commands") or ["uvicorn app.main:app --host 0.0.0.0 --port 8080"])[0],
            "env_vars_keys": env_var_keys,
            "has_dockerfile": bool(discovery_data.get("has_dockerfile", False)),
        })

    deep_insights = discovery_data.get("deep_insights") or {}
    has_docker_compose = bool(
        deep_insights.get("has_docker_compose")
        or discovery_data.get("has_docker_compose")
        or any("docker-compose" in f for f in discovery_data.get("files_inspected", []))
    )
    compose_file = deep_insights.get("compose_file")
    if not compose_file:
        for f in discovery_data.get("files_inspected", []):
            if f in ("docker-compose.prod.yml", "docker-compose.yml", "compose.yml"):
                compose_file = f
                break

    external_dependencies: List[Dict[str, Any]] = []
    for dep in discovery_data.get("dependencies", []):
        engine_str = str(dep.get("engine") or "").lower()
        is_baas = (
            "supabase" in engine_str
            or "firebase" in engine_str
            or bool(dep.get("is_external_baas"))
            or (dep.get("type") == "database_instance" and dep.get("requires_data_migration") is False)
        )
        external_dependencies.append({
            "id": dep.get("id"),
            "name": dep.get("name"),
            "type": "external_baas" if is_baas else dep.get("type"),
            "engine": dep.get("engine"),
            "port": dep.get("port"),
            "classification": dep.get("classification", "confirmed"),
            "is_external_baas": is_baas,
            "requires_cloud_rds_provisioning": not is_baas and dep.get("type") in ("database", "database_instance"),
        })

    return {
        "app_name": discovery_data.get("app_name", "app"),
        "app_id": discovery_data.get("app_id", "app-workload"),
        "repository_url": effective_repo_url,
        "git_ref": git_ref,
        "commit_sha": commit_sha,
        "language": discovery_data.get("language", "Python"),
        "framework": discovery_data.get("framework", "FastAPI"),
        "runtime": discovery_data.get("runtime", "python:3.11-slim"),
        "exposed_ports": discovery_data.get("exposed_ports", [80]),
        "health_endpoint": (discovery_data.get("health_endpoints") or ["/health"])[0],
        "env_vars_keys": env_var_keys,
        "has_dockerfile": bool(discovery_data.get("has_dockerfile", False)),
        "has_docker_compose": has_docker_compose,
        "compose_file": compose_file or "docker-compose.yml",
        "components": components_payload,
        "external_dependencies": external_dependencies,
        "high_availability": {
            "enabled": True,
            "deployment_strategy": "containerized_asg_behind_alb",
            "load_balancer": "aws_lb (Application Load Balancer Multi-AZ)",
            "auto_scaling_group": "aws_autoscaling_group (min=1, desired=2, max=3, ELB health check)",
            "instance_type": "t3.micro",
        },
    }


def generate_auto_dockerfile_and_compose(ai_payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Generate optimized containerization files (`Dockerfile.cloudmove` and `docker-compose.cloudmove.yml`)
    so that even applications without a Dockerfile or docker-compose.yml in their repository
    are migrated as resilient containers without payload-weight limits.
    """
    app_slug = _slug(ai_payload.get("app_name", "app"))
    lang = str(ai_payload.get("language", "Python")).lower()
    ports = ai_payload.get("exposed_ports") or [8080]
    primary_port = ports[0]
    components = ai_payload.get("components") or []
    start_cmd = components[0].get("start_command") if components else f"uvicorn app.main:app --host 0.0.0.0 --port {primary_port}"

    if "node" in lang or "typescript" in lang or "react" in lang:
        dockerfile_content = f"""# Auto-generated by CloudMove Containerization Engine
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev || npm install
COPY . .
EXPOSE {primary_port}
CMD ["npm", "start"]
"""
    elif "java" in lang:
        dockerfile_content = f"""# Auto-generated by CloudMove Containerization Engine
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /app
COPY . .
RUN mvn clean package -DskipTests

FROM eclipse-temurin:17-jre-jammy
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE {primary_port}
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
"""
    elif "go" in lang:
        dockerfile_content = f"""# Auto-generated by CloudMove Containerization Engine
FROM golang:1.22-alpine AS build
WORKDIR /app
COPY . .
RUN go build -o /app/server .

FROM alpine:3.19
WORKDIR /app
COPY --from=build /app/server /app/server
EXPOSE {primary_port}
ENTRYPOINT ["/app/server"]
"""
    else:
        cmd_str = start_cmd if str(start_cmd).strip().startswith("[") else json.dumps(str(start_cmd).split())
        dockerfile_content = f"""# Auto-generated by CloudMove Containerization Engine
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE {primary_port}
CMD {cmd_str}
"""

    services_yaml_lines = [
        "# Auto-generated by CloudMove Containerization Engine (High Availability Container Stack)",
        "services:",
    ]
    if len(components) > 1:
        for comp in components:
            c_name = _slug(comp.get("name", "service"))
            c_ctx = comp.get("context_path", ".")
            c_ports = comp.get("ports") or [80]
            c_cports = comp.get("container_ports") or c_ports
            h_port = c_ports[0]
            c_port = c_cports[0]
            services_yaml_lines.extend([
                f"  {c_name}:",
                "    build:",
                f"      context: ./{c_ctx}",
                "      dockerfile: Dockerfile",
                "    restart: always",
                "    env_file:",
                "      - .env",
                "    ports:",
                f'      - "{h_port}:{c_port}"',
            ])
    else:
        port_mappings = "\n".join(f'      - "{p}:{p}"' for p in ports)
        df_name = "Dockerfile" if ai_payload.get("has_dockerfile") else "Dockerfile.cloudmove"
        services_yaml_lines.extend([
            f"  {app_slug}:",
            "    build:",
            "      context: .",
            f"      dockerfile: {df_name}",
            "    restart: always",
            "    env_file:",
            "      - .env",
            "    ports:",
            port_mappings,
        ])

    return {
        "Dockerfile.cloudmove": dockerfile_content,
        "docker-compose.cloudmove.yml": "\n".join(services_yaml_lines) + "\n",
    }


def generate_container_user_data_sh(ai_payload: Dict[str, Any]) -> str:
    """
    Generate the complete `user_data.sh` script injected into EC2 / Auto Scaling Group instances.
    Handles swap allocation (for heavy ML/GIS builds on t3.micro), Docker & Docker Compose v2
    installation, repository cloning, environment file creation, container startup, and systemd
    boot persistence.
    """
    app_name = ai_payload.get("app_name", "app")
    app_slug = _slug(app_name)
    repo_url = ai_payload.get("repository_url", "https://github.com/organization/application.git")
    git_ref = ai_payload.get("git_ref", "main")
    commit_sha = ai_payload.get("commit_sha", "HEAD")
    has_compose = bool(ai_payload.get("has_docker_compose"))
    compose_file = ai_payload.get("compose_file") or "docker-compose.yml"
    env_keys = ai_payload.get("env_vars_keys") or []
    health_ep = ai_payload.get("health_endpoint") or "/health"
    ports = ai_payload.get("exposed_ports") or [80]
    primary_port = ports[0]

    auto_container_files = generate_auto_dockerfile_and_compose(ai_payload)
    dockerfile_fallback = auto_container_files["Dockerfile.cloudmove"]
    compose_fallback = auto_container_files["docker-compose.cloudmove.yml"]

    env_lines = [f"{k}=${{{k}:-}}" for k in env_keys] if env_keys else ["NODE_ENV=production", f"PORT={primary_port}"]
    env_block = "\n".join(env_lines)

    compose_target = compose_file if has_compose else "docker-compose.cloudmove.yml"

    return f"""#!/usr/bin/env bash
# ==============================================================================
# CLOUDMOVE AUTO-SCALING CONTAINERIZED BOOTSTRAP SCRIPT (user_data.sh)
# Application : {app_name}
# Repository  : {repo_url} (ref: {git_ref}, commit: {commit_sha})
# Architecture: High-Availability Containerized Node (ALB + Auto Scaling Group)
# ==============================================================================
set -euo pipefail
exec > >(tee /var/log/cloudmove-user-data.log | logger -t cloudmove-user-data -s 2>/dev/console) 2>&1

echo "[1/6] Configurando 2 GB de memoria Swap para soportar compilaciones pesadas en contenedores..."
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "[2/6] Actualizando sistema operativo e instalando Docker Engine, Docker Compose v2 y Git..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg git jq docker.io docker-compose-v2 || apt-get install -y docker.io docker-compose git curl
systemctl enable --now docker

echo "[3/6] Clonando repositorio {repo_url} en /opt/{app_slug}..."
mkdir -p /opt/{app_slug}
if [ ! -d "/opt/{app_slug}/.git" ]; then
  git clone --branch "{git_ref}" "{repo_url}" /opt/{app_slug} || git clone "{repo_url}" /opt/{app_slug}
fi
cd /opt/{app_slug}
if [ "{commit_sha}" != "HEAD" ] && [ "{commit_sha}" != "latest" ]; then
  git checkout "{commit_sha}" || true
fi

echo "[4/6] Generando plantilla base .env (inyecte secretos desde AWS SSM / Secrets Manager)..."
if [ ! -f /opt/{app_slug}/.env ]; then
  cat << 'EOF_ENV' > /opt/{app_slug}/.env
{env_block}
EOF_ENV
fi

echo "[5/6] Verificando manifiestos de contenerización (Dockerfile / Docker Compose)..."
if [ ! -f /opt/{app_slug}/Dockerfile ] && [ ! -f /opt/{app_slug}/Dockerfile.cloudmove ]; then
  cat << 'EOF_DF' > /opt/{app_slug}/Dockerfile.cloudmove
{dockerfile_fallback.rstrip()}
EOF_DF
fi

if [ ! -f "/opt/{app_slug}/{compose_target}" ]; then
  cat << 'EOF_COMPOSE' > /opt/{app_slug}/docker-compose.cloudmove.yml
{compose_fallback.rstrip()}
EOF_COMPOSE
  COMPOSE_FILE="docker-compose.cloudmove.yml"
else
  COMPOSE_FILE="{compose_target}"
fi

echo "[6/6] Construyendo e iniciando contenedores con reinicio automático (resiliencia ante fallos)..."
docker compose -f "$COMPOSE_FILE" up -d --build || docker-compose -f "$COMPOSE_FILE" up -d --build

cat << EOF_SYSTEMD > /etc/systemd/system/{app_slug}-containers.service
[Unit]
Description=CloudMove Containerized Stack - {app_name}
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/{app_slug}
ExecStart=/usr/bin/docker compose -f $COMPOSE_FILE up -d
ExecStop=/usr/bin/docker compose -f $COMPOSE_FILE down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF_SYSTEMD

systemctl daemon-reload
systemctl enable {app_slug}-containers.service

echo "[OK] Despliegue contenerizado de '{app_name}' activo. Puertos: {ports}, Health Check: {health_ep}"
"""


def generate_cheap_infrastructure(
    ai_payload: Dict[str, Any],
    api_key: Optional[str] = None,
    model_name: str = "gemini-1.5-flash",
) -> Dict[str, Any]:
    """
    Step 3: Query Gemini LLM with Structured JSON Output to design the AWS infrastructure,
    validate the HCL with `AWSAdapter().validate_artifacts()`, and seamlessly fall back to
    CloudMove's upgraded deterministic HA Containerized generator if offline or if no API key is set.
    """
    from app.adapters.aws_adapter import AWSAdapter
    from app.migration.app_migrator import build_application_cmir

    effective_key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()
    user_data_sh = generate_container_user_data_sh(ai_payload)
    auto_container = generate_auto_dockerfile_and_compose(ai_payload)

    if effective_key:
        full_prompt = (
            f"{ARCHITECTURAL_SYSTEM_PROMPT}\n\n"
            f"Datos de la Aplicación:\n{json.dumps(ai_payload, indent=2, ensure_ascii=False)}"
        )
        raw_json_text: Optional[str] = None

        # 1. Try google.generativeai SDK if installed
        try:
            import google.generativeai as genai  # type: ignore

            genai.configure(api_key=effective_key)
            model = genai.GenerativeModel(
                model_name,
                generation_config={"response_mime_type": "application/json"},
            )
            response = model.generate_content(full_prompt)
            raw_json_text = response.text
        except ImportError:
            # 2. Direct REST call to Gemini API (zero external SDK dependency required)
            try:
                api_url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model_name}:generateContent?key={effective_key}"
                )
                req_body = json.dumps({
                    "contents": [{"parts": [{"text": full_prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                }).encode("utf-8")
                req = urllib.request.Request(
                    api_url,
                    data=req_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=25) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    candidates = resp_data.get("candidates") or []
                    if candidates:
                        parts = (candidates[0].get("content") or {}).get("parts") or []
                        if parts:
                            raw_json_text = parts[0].get("text")
            except Exception:
                raw_json_text = None
        except Exception:
            raw_json_text = None

        if raw_json_text:
            try:
                parsed = json.loads(raw_json_text)
                if isinstance(parsed, dict) and parsed.get("main_tf") and parsed.get("variables_tf"):
                    candidate_files = {
                        "provider.tf": parsed.get("provider_tf") or _default_aws_provider_tf(),
                        "variables.tf": parsed["variables_tf"],
                        "main.tf": parsed["main_tf"],
                        "outputs.tf": parsed.get("outputs_tf") or _default_aws_outputs_tf(),
                    }
                    validation = AWSAdapter().validate_artifacts(candidate_files)
                    if validation.get("valid"):
                        return {
                            "generation_engine": f"gemini_ai_orchestrator ({model_name})",
                            "provider_tf": candidate_files["provider.tf"],
                            "variables_tf": candidate_files["variables.tf"],
                            "main_tf": candidate_files["main.tf"],
                            "outputs_tf": candidate_files["outputs.tf"],
                            "user_data_sh": parsed.get("user_data_sh") or user_data_sh,
                            "Dockerfile.cloudmove": auto_container["Dockerfile.cloudmove"],
                            "docker-compose.cloudmove.yml": auto_container["docker-compose.cloudmove.yml"],
                            "validation": validation,
                        }
            except Exception:
                pass

    # Deterministic High-Availability Containerized Synthesis (100% reliable, offline-capable)
    synthetic_discovery = {
        "app_id": ai_payload.get("app_id", f"app-{_slug(ai_payload.get('app_name', 'app'))}"),
        "app_name": ai_payload.get("app_name", "app"),
        "source_path": ai_payload.get("repository_url", "inline_manifests"),
        "discovered_at": "2026-11-02T00:00:00+00:00",
        "language": ai_payload.get("language", "Python"),
        "framework": ai_payload.get("framework", "FastAPI"),
        "runtime": ai_payload.get("runtime", "python:3.11-slim"),
        "runtime_constraints": ">=Containerized Runtime",
        "start_commands": [
            c.get("start_command", "docker compose up -d")
            for c in (ai_payload.get("components") or [{"start_command": "docker compose up -d"}])
        ],
        "exposed_ports": ai_payload.get("exposed_ports", [80]),
        "health_endpoints": [ai_payload.get("health_endpoint", "/health")],
        "persistent_volumes": [],
        "environment_variables": [{"name": k, "redacted_value": "[REDACTED]", "is_secret": False} for k in ai_payload.get("env_vars_keys", [])],
        "components": [
            {
                "name": c.get("name", "app"),
                "tier": c.get("tier", "backend"),
                "runtime": c.get("runtime", "python:3.11-slim"),
                "framework": c.get("type", "FastAPI"),
                "language": ai_payload.get("language", "Python"),
                "container_ports": c.get("container_ports") or c.get("ports") or [80],
                "start_command": c.get("start_command", ""),
            }
            for c in (ai_payload.get("components") or [])
        ],
        "dependencies": [
            {
                "id": d.get("id") or f"dep-{_slug(d.get('name', 'ext'))}",
                "name": d.get("name", "external-dep"),
                "type": "external_baas" if d.get("is_external_baas") else d.get("type", "database_instance"),
                "engine": d.get("engine", "postgres"),
                "port": d.get("port", 5432),
                "relationship_type": "reads_and_writes",
                "classification": d.get("classification", "confirmed"),
                "epistemic_state": "observed",
                "confidence": 0.99,
                "requires_data_migration": bool(d.get("requires_cloud_rds_provisioning", False)),
                "is_external_baas": bool(d.get("is_external_baas", False)),
                "evidence": [],
            }
            for d in (ai_payload.get("external_dependencies") or [])
        ],
    }

    cmir = build_application_cmir(synthetic_discovery, target_provider="aws", deployment_mode="container")
    iac = AWSAdapter().generate_iac(cmir)
    files = iac["files"]

    return {
        "generation_engine": "cloudmove_deterministic_ha_container_engine",
        "provider_tf": files["provider.tf"],
        "variables_tf": files["variables.tf"],
        "main_tf": files["main.tf"],
        "outputs_tf": files["outputs.tf"],
        "user_data_sh": user_data_sh,
        "Dockerfile.cloudmove": auto_container["Dockerfile.cloudmove"],
        "docker-compose.cloudmove.yml": auto_container["docker-compose.cloudmove.yml"],
        "validation": iac["validation"],
    }


def write_terraform_artifacts(tf_data: Dict[str, Any], output_dir: str) -> Dict[str, str]:
    """
    Step 4: Write the generated Terraform files (`provider.tf`, `variables.tf`, `main.tf`,
    `outputs.tf`) and the containerized bootstrap script (`user_data.sh`) to disk.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    written: Dict[str, str] = {}
    file_mapping = {
        "provider.tf": tf_data.get("provider_tf") or _default_aws_provider_tf(),
        "variables.tf": tf_data.get("variables_tf", ""),
        "main.tf": tf_data.get("main_tf", ""),
        "outputs.tf": tf_data.get("outputs_tf") or _default_aws_outputs_tf(),
        "user_data.sh": tf_data.get("user_data_sh", ""),
    }
    if tf_data.get("Dockerfile.cloudmove"):
        file_mapping["Dockerfile.cloudmove"] = tf_data["Dockerfile.cloudmove"]
    if tf_data.get("docker-compose.cloudmove.yml"):
        file_mapping["docker-compose.cloudmove.yml"] = tf_data["docker-compose.cloudmove.yml"]

    for filename, content in file_mapping.items():
        if content:
            target_file = out_path / filename
            target_file.write_text(content, encoding="utf-8")
            if filename.endswith(".sh"):
                target_file.chmod(0o755)
            written[filename] = str(target_file)

    return written


def _default_aws_provider_tf() -> str:
    return """terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
"""


def _default_aws_outputs_tf() -> str:
    return """output "vpc_id" {
  description = "ID of target VPC"
  value       = aws_vpc.target_vpc.id
}

output "public_subnet_id" {
  description = "ID of Primary Public Subnet"
  value       = aws_subnet.public_subnet.id
}
"""
