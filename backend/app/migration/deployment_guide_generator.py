"""
CloudMove Deployment Guide Generator.
Generates comprehensive, step-by-step production runbooks (in Markdown)
for deploying collected workloads to AWS and GCP across all three use cases:
- Case 1: GitHub / Application Source Code (app_source)
- Case 2: Live Operating System & VM Image (vm_image)
- Case 3: Datacenter Migration Campaign (datacenter_campaign)
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

DEFAULT_API_URL = os.getenv("CLOUDMOVE_API_URL", "http://localhost:8000").rstrip("/")


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "-", str(text).strip())
    return re.sub(r"-+", "-", cleaned).strip("-").lower() or "workload"


def generate_deployment_guide(
    use_case: str,
    target_provider: str,
    job_name: str,
    migration_id: str,
    source_environment: Dict[str, Any],
    artifacts_files: Dict[str, str],
    target_config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate production-ready, step-by-step markdown deployment instructions tailored
    to the specific use case and cloud target provider (AWS or GCP).
    """
    provider_clean = str(target_provider or "aws").lower().strip()
    uc_clean = str(use_case or "app_source").lower().strip()
    cfg = target_config or {}
    src = source_environment or {}
    slug_name = _slug(job_name)

    default_region = "us-east-1" if provider_clean == "aws" else "us-central1"
    region = cfg.get("region") or cfg.get("aws_region") or cfg.get("gcp_region") or default_region
    gcp_project = cfg.get("gcp_project_id") or cfg.get("project_id") or "cloudmove-production"

    if uc_clean == "app_source":
        return _build_case_1_guide(
            provider_clean=provider_clean,
            job_name=job_name,
            slug_name=slug_name,
            migration_id=migration_id,
            region=region,
            gcp_project=gcp_project,
            src=src,
            files=artifacts_files,
        )
    elif uc_clean == "vm_image":
        return _build_case_2_guide(
            provider_clean=provider_clean,
            job_name=job_name,
            slug_name=slug_name,
            migration_id=migration_id,
            region=region,
            gcp_project=gcp_project,
            src=src,
            files=artifacts_files,
        )
    else:
        return _build_case_3_guide(
            provider_clean=provider_clean,
            job_name=job_name,
            slug_name=slug_name,
            migration_id=migration_id,
            region=region,
            gcp_project=gcp_project,
            src=src,
            files=artifacts_files,
        )


def _build_case_1_guide(
    provider_clean: str,
    job_name: str,
    slug_name: str,
    migration_id: str,
    region: str,
    gcp_project: str,
    src: Dict[str, Any],
    files: Dict[str, str],
) -> str:
    env_vars = src.get("environment_variables", [])
    rt = src.get("runtime")
    if isinstance(rt, dict):
        runtime = rt.get("language") or "Aplicacion Web"
        framework = rt.get("framework") or src.get("framework") or "Framework Contenerizado"
    else:
        runtime = str(rt) if rt else "Aplicacion Web"
        framework = src.get("framework") or "Framework Contenerizado"

    detected_port = src.get("port") or 8000
    if isinstance(detected_port, list) and detected_port:
        detected_port = detected_port[0]

    detected_db = src.get("database") or "PostgreSQL"
    if isinstance(detected_db, dict):
        detected_db = detected_db.get("engine") or "PostgreSQL"

    env_example_lines = [
        f"PORT={detected_port}",
        "NODE_ENV=production",
        "DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}",
        "SECRET_KEY=generate-a-secure-random-token-here",
        "ALLOWED_ORIGINS=*",
    ]
    if env_vars:
        for ev in env_vars[:6]:
            var_name = ev.get("name") if isinstance(ev, dict) else str(ev)
            if var_name not in ("PORT", "DATABASE_URL", "NODE_ENV", "SECRET_KEY", "ALLOWED_ORIGINS"):
                env_example_lines.append(f"{var_name}=production-value-here")

    env_block = "\n".join(env_example_lines)

    if provider_clean == "aws":
        return f"""# Guia Paso a Paso: Despliegue y Configuracion de Aplicacion en AWS (ECS Fargate / RDS)
**Carga de Trabajo:** {job_name} | **ID de Migracion:** {migration_id}
**Entorno de Ejecucion:** {runtime} ({framework}) | **Region Destino:** AWS `{region}`
**Modo Arquitectonico:** Contenedores en AWS Fargate con Red Aislada VPC y Base de Datos Gestionada ({detected_db})

---

### Paso 1: Descargar el Paquete de Despliegue (.ZIP)
Descarga el paquete completo generado desde CloudMove o utiliza `curl`:
```bash
# Descarga directa del paquete zip generado
CLOUDMOVE_API_URL="${{CLOUDMOVE_API_URL:-{DEFAULT_API_URL}}}"
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/bundle.zip"
unzip bundle.zip -d ./cloudmove_app_deploy
cd ./cloudmove_app_deploy
```
Archivos incluidos en el paquete:
- `main.tf`, `variables.tf`, `outputs.tf`, `provider.tf`: Modulos de Terraform para aprovisionar VPC, Subredes publicas/privadas, Security Groups, Cluster ECS Fargate y Base de Datos RDS.
- `Dockerfile` y `docker-compose.yml`: Definicion de contenedor optimizada para {runtime}.
- `DEPLOYMENT_INSTRUCTIONS.md`: Este manual operativo de despliegue.

### Paso 2: Autenticacion en AWS y Configuracion del CLI
Verifica que tu cuenta de AWS este activa y configurada:
```bash
aws configure set default.region {region}
aws sts get-caller-identity
```

### Paso 3: Compilacion y Publicacion de la Imagen en Amazon ECR
1. Crear el repositorio en Amazon ECR (si no existe):
```bash
aws ecr create-repository --repository-name {slug_name} --region {region} || true
```
2. Autenticar Docker local con el registro privado de ECR:
```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region {region} | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.{region}.amazonaws.com
```
3. Compilar la imagen Docker local y subirla al repositorio:
```bash
docker build -t {slug_name}:latest .
docker tag {slug_name}:latest $AWS_ACCOUNT_ID.dkr.ecr.{region}.amazonaws.com/{slug_name}:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.{region}.amazonaws.com/{slug_name}:latest
```

### Paso 4: Aprovisionamiento de Infraestructura con Terraform
Aprovisiona la red VPC, los grupos de seguridad, el balanceador ALB, la base de datos gestionada y la tarea ECS:
```bash
terraform init
terraform plan
terraform apply -auto-approve
```

### Paso 5: Despliegue Efectivo del Servicio en la Nube (ECS Fargate)
Fuerza la actualizacion del servicio ECS para que descargue la imagen publicada en ECR y levante las tareas:
```bash
CLUSTER_NAME=$(terraform output -raw ecs_cluster_name 2>/dev/null || echo "{slug_name}-cluster")
SERVICE_NAME=$(terraform output -raw ecs_service_name 2>/dev/null || echo "{slug_name}-service")

aws ecs update-service \\
    --cluster "$CLUSTER_NAME" \\
    --service "$SERVICE_NAME" \\
    --force-new-deployment \\
    --region {region}

echo "Esperando a que las tareas de ECS alcancen estado RUNNING y salud estable..."
aws ecs wait services-stable --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" --region {region}
```

### Paso 6: Configuraciones Necesarias para Usar la Aplicacion

#### 6.1 Variables de Entorno y Almacenamiento de Secretos
Almacena las credenciales sensibles y de conexion en AWS Secrets Manager:
```bash
cat << 'EOF' > .env.production
{env_block}
EOF

aws secretsmanager create-secret \\
    --name "{slug_name}/production" \\
    --description "Variables de entorno y secretos para {job_name}" \\
    --secret-string file://.env.production \\
    --region {region} || \\
aws secretsmanager update-secret \\
    --secret-id "{slug_name}/production" \\
    --secret-string file://.env.production \\
    --region {region}
```

#### 6.2 Inicializacion y Ejecucion de Migraciones de Base de Datos
Obten los datos de conexion de la base de datos RDS creada por Terraform:
```bash
DB_ENDPOINT=$(terraform output -raw db_endpoint 2>/dev/null || echo "rds-host:5432")
echo "Base de datos disponible en: $DB_ENDPOINT"

# Opcion A: Ejecutar migraciones mediante una tarea efimera en ECS Fargate (Recomendado)
aws ecs run-task \\
    --cluster "$CLUSTER_NAME" \\
    --task-definition "{slug_name}-task" \\
    --launch-type FARGATE \\
    --network-configuration "awsvpcConfiguration={{subnets=[$(terraform output -raw private_subnet_id 2>/dev/null)],securityGroups=[$(terraform output -raw ecs_security_group_id 2>/dev/null)],assignPublicIp=ENABLED}}" \\
    --overrides '{{"containerOverrides": [{{"name": "{slug_name}", "command": ["npm", "run", "migrate"]}}]}}'

# Opcion B: Ejecutar migraciones directamente con herramientas locales si tienes acceso por VPN o Bastion
# python manage.py migrate  /  alembic upgrade head  /  npx prisma migrate deploy
```

#### 6.3 Configuracion de Red, CORS y Grupos de Seguridad
- **Trafico Web:** El balanceador Application Load Balancer (ALB) permite trafico de entrada en el puerto 80 (HTTP) y 443 (HTTPS) desde `0.0.0.0/0`.
- **Base de Datos:** El grupo de seguridad de RDS restringe las conexiones en el puerto 5432/3306 admitiendo unicamente paquetes provenientes del Security Group de ECS Fargate.
- **CORS:** Si la aplicacion atiende peticiones de una aplicacion web externa, verifica que la variable `ALLOWED_ORIGINS` contenga el dominio del cliente.

#### 6.4 Enlace Frontend <-> Backend
Si cuentas con una aplicacion web separada (React, Vue, Angular o Mobile), configura la variable de entorno del cliente con el endpoint asignado:
```bash
SERVICE_ENDPOINT=$(terraform output -raw app_endpoint 2>/dev/null || terraform output -raw alb_dns_name)
echo "Configurar en cliente frontend: VITE_API_BASE_URL=http://$SERVICE_ENDPOINT"
```

### Paso 7: Acceso Publico, Verificacion y Como Usar la Aplicacion
1. **Consultar URL Publica:**
```bash
APP_URL=$(terraform output -raw app_endpoint 2>/dev/null || echo "http://$(terraform output -raw alb_dns_name)")
echo "URL publica de la aplicacion: $APP_URL"
```
2. **Prueba de Salud del Servicio:**
```bash
curl -Iv "$APP_URL/health" || curl -Iv "$APP_URL/"
```
3. **Uso y Pruebas Operativas:**
- Abre `$APP_URL` en tu navegador web.
- Si es una API REST o FastAPI/Node, accede a la documentacion Swagger interactiva en `$APP_URL/docs` o `$APP_URL/swagger`.
- Realiza una peticion de prueba de login o consulta de registros de prueba contra la base de datos migrada.
"""
    else:
        return f"""# Guia Paso a Paso: Despliegue y Configuracion de Aplicacion en Google Cloud (Cloud Run / Cloud SQL)
**Carga de Trabajo:** {job_name} | **ID de Migracion:** {migration_id}
**Entorno de Ejecucion:** {runtime} ({framework}) | **Region Destino:** GCP `{region}`
**Proyecto GCP:** `{gcp_project}` | **Base de Datos:** Cloud SQL ({detected_db})

---

### Paso 1: Descargar el Paquete de Despliegue (.ZIP)
Descarga el paquete completo generado por CloudMove:
```bash
CLOUDMOVE_API_URL="${{CLOUDMOVE_API_URL:-{DEFAULT_API_URL}}}"
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/bundle.zip"
unzip bundle.zip -d ./cloudmove_app_deploy
cd ./cloudmove_app_deploy
```
Archivos incluidos:
- `main.tf`, `variables.tf`, `outputs.tf`, `provider.tf`: Codigo Terraform para Google Cloud (VPC, Cloud SQL, Cloud Run / GKE, Secret Manager).
- `Dockerfile`: Definicion de contenedor optimizada para {runtime}.
- `DEPLOYMENT_INSTRUCTIONS.md`: Este manual tecnico de referencia.

### Paso 2: Autenticacion y Seleccion de Proyecto en GCP
```bash
gcloud auth login
gcloud config set project {gcp_project}
gcloud services enable compute.googleapis.com artifactregistry.googleapis.com run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com
```

### Paso 3: Compilacion y Registro en Google Artifact Registry
1. Crear el repositorio de artefactos:
```bash
gcloud artifacts repositories create {slug_name}-repo \\
    --repository-format=docker \\
    --location={region} \\
    --description="Repositorio de contenedores para {job_name}" || true
```
2. Autenticar Docker con Artifact Registry:
```bash
gcloud auth configure-docker {region}-docker.pkg.dev
```
3. Compilar y subir la imagen:
```bash
IMAGE_TAG="{region}-docker.pkg.dev/{gcp_project}/{slug_name}-repo/{slug_name}:latest"
docker build -t "$IMAGE_TAG" .
docker push "$IMAGE_TAG"
```

### Paso 4: Aprovisionamiento de Infraestructura con Terraform
```bash
terraform init
terraform plan
terraform apply -auto-approve -var="gcp_project_id={gcp_project}" -var="gcp_region={region}"
```

### Paso 5: Despliegue Efectivo del Servicio en Google Cloud Run
Despliega o actualiza el servicio con la imagen compilada y acceso publico:
```bash
IMAGE_TAG="{region}-docker.pkg.dev/{gcp_project}/{slug_name}-repo/{slug_name}:latest"

gcloud run deploy {slug_name} \\
    --image="$IMAGE_TAG" \\
    --platform=managed \\
    --region={region} \\
    --allow-unauthenticated \\
    --port={detected_port} \\
    --set-env-vars="NODE_ENV=production,PORT={detected_port}"
```

### Paso 6: Configuraciones Necesarias para Usar la Aplicacion

#### 6.1 Variables de Entorno y Secretos en Google Secret Manager
Almacena las credenciales sensibles:
```bash
cat << 'EOF' > .env.production
{env_block}
EOF

gcloud secrets create {slug_name}-env --data-file=.env.production || \\
gcloud secrets versions add {slug_name}-env --data-file=.env.production
```

#### 6.2 Conexion a Cloud SQL e Inicializacion de Migraciones
1. Otorga permisos a la cuenta de servicio de Cloud Run para conectar a Cloud SQL:
```bash
CLOUDRUN_SA=$(gcloud run services describe {slug_name} --region={region} --format="value(spec.template.spec.serviceAccountName)")
gcloud projects add-iam-policy-binding {gcp_project} \\
    --member="serviceAccount:$CLOUDRUN_SA" \\
    --role="roles/cloudsql.client"
```
2. Ejecuta un Cloud Run Job para correr las migraciones de esquema:
```bash
gcloud run jobs create {slug_name}-migrate \\
    --image="$IMAGE_TAG" \\
    --region={region} \\
    --command="npm,run,migrate" || true
gcloud run jobs execute {slug_name}-migrate --region={region} --wait
```

#### 6.3 Enlace Frontend <-> Backend
Configura la URL de Cloud Run en tu aplicacion cliente:
```bash
SERVICE_URL=$(gcloud run services describe {slug_name} --region={region} --format="value(status.url)")
echo "Configurar en cliente frontend: VITE_API_BASE_URL=$SERVICE_URL"
```

### Paso 7: Acceso Publico, Verificacion y Como Usar la Aplicacion
1. **Consultar URL de Cloud Run:**
```bash
SERVICE_URL=$(gcloud run services describe {slug_name} --region={region} --format="value(status.url)")
echo "Servicio disponible en: $SERVICE_URL"
```
2. **Prueba de Salud:**
```bash
curl -Iv "$SERVICE_URL"
```
3. **Uso de la Aplicacion:**
- Abre la URL en el navegador web para verificar la interfaz de usuario.
- Accede a la documentacion de endpoints (`$SERVICE_URL/docs`).
- Asocia un dominio corporativo personalizado si lo requieres mediante `gcloud beta run domain-mappings create --service={slug_name} --domain=tu-dominio.com`.
"""


def _build_case_2_guide(
    provider_clean: str,
    job_name: str,
    slug_name: str,
    migration_id: str,
    region: str,
    gcp_project: str,
    src: Dict[str, Any],
    files: Dict[str, str],
) -> str:
    os_info = src.get("os", {})
    distro = os_info.get("distro", "Linux")
    kernel = os_info.get("kernel", "Linux Kernel")
    arch = os_info.get("architecture", "x86_64")
    boot_mode = src.get("boot_mode", "UEFI")
    part_scheme = src.get("partition_scheme", "GPT")
    users = ", ".join(src.get("local_users", ["root"]))
    pkgs_count = src.get("installed_packages_summary", {}).get("total_count", 0)
    disks = src.get("disks", [{}])
    primary_disk = disks[0].get("device", "/dev/nvme0n1")
    disk_size = disks[0].get("size_gib", 50)
    used_gib = src.get("total_used_gib", 15)

    if provider_clean == "aws":
        return f"""# Guia Paso a Paso: Despliegue y Montaje de Sistema Operativo e Imagen de VM en AWS EC2
**Servidor Origen:** {job_name} | **ID de Migracion:** {migration_id}
**Sistema Operativo:** {distro} (Kernel: `{kernel}`, `{arch}`)
**Arranque / Particionado:** `{boot_mode}` (`{part_scheme}`) | **Disco Principal:** `{primary_disk}` ({disk_size} GiB prov, {used_gib} GiB usados)
**Usuarios Descubiertos:** {users} | **Paquetes Inventariados:** {pkgs_count}
**Region Destino:** AWS `{region}`

---

### Paso 1: Descargar la Copia del SO y los Artefactos de Migracion
Tienes a tu disposicion descargas directas desde la interfaz de CloudMove o mediante la API:
1. **Descargar Paquete Completo de Despliegue (.ZIP):**
   Incluye Terraform (`main.tf`, `variables.tf`), `deploy_to_aws.sh`, `create_full_raw_disk_clone.sh`, `restore_system_image.sh`, manifiestos de paquetes/usuarios y la copia comprimida del SO.
   ```bash
   CLOUDMOVE_API_URL="${{CLOUDMOVE_API_URL:-{DEFAULT_API_URL}}}"
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/bundle.zip"
   unzip bundle.zip -d ./cloudmove_os_migration
   cd ./cloudmove_os_migration
   ```
2. **Descargar Copia del Sistema Operativo Directamente (.tar.gz):**
   Contiene todos los ficheros de `/etc`, tabla de particiones, cuentas de usuarios locales, servicios de systemd y script de restauracion in-guest:
   ```bash
   curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/system-image"
   ```
3. **Descargar Imagen de Disco QCOW2 (si fue generada en Staging):**
   ```bash
   curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/disk-image"
   ```

### Paso 2: Subida de la Imagen / Transmision de Bloques hacia Amazon S3
Para subir la imagen del disco hacia AWS dispones de dos modalidades segun tus recursos locales:
- **Opcion A: Streaming directo bit a bit a S3 en caliente (Sin agotar almacenamiento local)**
  Transmite la particion del sistema operativo en vivo directamente hacia tu bucket S3:
  ```bash
  sudo chmod +x create_full_raw_disk_clone.sh
  sudo ./create_full_raw_disk_clone.sh s3
  ```
- **Opcion B: Subir la imagen de disco (.qcow2 / .raw / .vmdk) descargada**
  ```bash
  S3_BUCKET="cloudmove-vm-import-{slug_name}-{region}"
  aws s3 mb "s3://$S3_BUCKET" --region {region} || true
  aws s3 cp {slug_name}.qcow2 "s3://$S3_BUCKET/{slug_name}.qcow2"
  ```

### Paso 3: Registro e Importacion de la Imagen en el Hipervisor AWS (Creacion de AMI)
1. Configurar el rol IAM requerido por el servicio de importacion (`vmimport`):
```bash
cat << 'EOF' > /tmp/vmimport-trust.json
{{
  "Version": "2012-10-17",
  "Statement": [
    {{
      "Effect": "Allow",
      "Principal": {{ "Service": "vmie.amazonaws.com" }},
      "Action": "sts:AssumeRole",
      "Condition": {{ "StringEquals": {{ "sts:Externalid": "vmimport" }} }}
    }}
  ]
}}
EOF
aws iam create-role --role-name vmimport --assume-role-policy-document file:///tmp/vmimport-trust.json || true
```
2. Lanzar la tarea de conversion a AMI en AWS:
```bash
cat << EOF > /tmp/containers.json
[
  {{
    "Description": "Copia de SO {job_name}",
    "Format": "qcow2",
    "UserBucket": {{
      "S3Bucket": "$S3_BUCKET",
      "S3Key": "{slug_name}.qcow2"
    }}
  }}
]
EOF

IMPORT_TASK_ID=$(aws ec2 import-image \\
    --description "{job_name} OS Migration" \\
    --disk-containers file:///tmp/containers.json \\
    --boot-mode {boot_mode.lower()} \\
    --region {region} \\
    --query "ImportTaskId" --output text)

echo "Tarea de importacion iniciada: $IMPORT_TASK_ID. Esperando finalizacion..."
while true; do
    STATUS=$(aws ec2 describe-import-image-tasks --import-task-ids "$IMPORT_TASK_ID" --region {region} --query "ImportImageTasks[0].Status" --output text)
    PROGRESS=$(aws ec2 describe-import-image-tasks --import-task-ids "$IMPORT_TASK_ID" --region {region} --query "ImportImageTasks[0].Progress" --output text 2>/dev/null || echo "0")
    echo "  Progreso de importacion AMI: $STATUS ($PROGRESS%)"
    if [ "$STATUS" = "completed" ]; then
        AMI_ID=$(aws ec2 describe-import-image-tasks --import-task-ids "$IMPORT_TASK_ID" --region {region} --query "ImportImageTasks[0].ImageId" --output text)
        echo "AMI registrada satisfactoriamente: $AMI_ID"
        break
    elif [ "$STATUS" = "deleted" ]; then
        echo "Error en la importacion de la imagen en AWS."
        exit 1
    fi
    sleep 20
done
```
*(Nota: Si ejecutas `./deploy_to_aws.sh` del paquete, todo este paso se ejecuta automaticamente).*

### Paso 4: Montaje y Aprovisionamiento de la Instancia EC2 con Terraform
Con la AMI generada (`$AMI_ID`), ejecuta Terraform para crear la VPC, subred publica, Security Groups e instanciar la maquina virtual:
```bash
terraform init
terraform plan -var="ami_id=$AMI_ID"
terraform apply -auto-approve -var="ami_id=$AMI_ID"
```
Esto aprovisiona:
- Una instancia EC2 Nitro con el disco montado como volumen raiz `/dev/sda1` o `/dev/nvme0n1`.
- IP Elastica publica vinculada.
- Security Group con acceso SSH (puerto 22), puertos web (80/443) y puertos de las aplicaciones inventariadas.

### Paso 5: Conexion Remota y Verificacion del Disco Montado
1. Obten la IP publica asignada por Terraform:
```bash
INSTANCE_IP=$(terraform output -raw instance_public_ip 2>/dev/null || aws ec2 describe-instances --filters "Name=image-id,Values=$AMI_ID" --query "Reservations[0].Instances[0].PublicIpAddress" --output text)
echo "Servidor en la nube disponible en: $INSTANCE_IP"
```
2. Inicia sesion por SSH (utilizando el usuario configurado en cloud-init o el usuario del sistema migrado):
```bash
SSH_USER="${{SSH_USER:-admin}}"
ssh -i ~/.ssh/id_rsa "$SSH_USER@$INSTANCE_IP"
```
3. Verifica la estructura del disco montado y expande la particion si el volumen EBS es mayor al tamano de origen:
```bash
lsblk -f
sudo growpart /dev/nvme0n1 1 || sudo growpart /dev/xvda 1 || true
sudo resize2fs /dev/nvme0n1p1 2>/dev/null || sudo xfs_growfs / 2>/dev/null || true
```

### Paso 6: Restauracion de Configuraciones del SO In-Guest (Usuarios y Servicios)
Transfiere la copia del sistema operativo (`system_image_snapshot_*.tar.gz`) a la nueva maquina virtual y ejecuta la restauracion:
```bash
# Desde tu estacion local:
SSH_USER="${{SSH_USER:-admin}}"
scp -i ~/.ssh/id_rsa system_image_snapshot_*.tar.gz "$SSH_USER@$INSTANCE_IP:~/"

# En la sesion SSH de la maquina virtual:
tar -xzf system_image_snapshot_*.tar.gz
sudo chmod +x restore_system_image.sh
sudo ./restore_system_image.sh
```
¿Que realiza `restore_system_image.sh`?
- Restaura los archivos de `/etc` preservando certificados, `/etc/hosts` y configuraciones personalizadas.
- Recrea las cuentas de usuario locales descubiertas ({users}) con sus mismos UID y shells.
- Recarga demonios de systemd y activa los servicios criticos.

### Paso 7: Validacion Operativa y Puesta en Marcha
Verifica que los servicios del sistema operativo se encuentren activos:
```bash
# Validar servicios principales
sudo systemctl status ssh
sudo ss -tulpn

# Validar cuentas de usuario restauradas
cat /etc/passwd | grep -E "${{SSH_USER:-admin}}|root|postgres"
```
El servidor en la nube esta montado, activo y operando con la misma configuracion del entorno original.
"""
    else:
        return f"""# Guia Paso a Paso: Despliegue y Montaje de Sistema Operativo e Imagen de VM en Google Compute Engine
**Servidor Origen:** {job_name} | **ID de Migracion:** {migration_id}
**Sistema Operativo:** {distro} (Kernel: `{kernel}`, `{arch}`)
**Arranque / Particionado:** `{boot_mode}` (`{part_scheme}`) | **Disco Principal:** `{primary_disk}` ({disk_size} GiB prov, {used_gib} GiB usados)
**Usuarios Descubiertos:** {users} | **Paquetes Inventariados:** {pkgs_count}
**Region Destino:** GCP `{region}` | **Proyecto:** `{gcp_project}`

---

### Paso 1: Descargar la Copia del SO y los Artefactos de Migracion
Descarga los artefactos desde la plataforma CloudMove:
1. **Descargar Paquete Completo de Despliegue (.ZIP):**
   ```bash
   CLOUDMOVE_API_URL="${{CLOUDMOVE_API_URL:-{DEFAULT_API_URL}}}"
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/bundle.zip"
   unzip bundle.zip -d ./cloudmove_os_migration
   cd ./cloudmove_os_migration
   ```
2. **Descargar Copia del Sistema Operativo (.tar.gz):**
   ```bash
   curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/system-image"
   ```
3. **Descargar Imagen de Disco QCOW2:**
   ```bash
   curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/disk-image"
   ```

### Paso 2: Subida de la Imagen a Google Cloud Storage
- **Opcion A: Streaming directo con el script adjunto:**
  ```bash
  sudo chmod +x create_full_raw_disk_clone.sh
  sudo ./create_full_raw_disk_clone.sh gcs
  ```
- **Opcion B: Subir la imagen de disco QCOW2 generada:**
  ```bash
  GCS_BUCKET="cloudmove-vm-images-{gcp_project}"
  gcloud storage buckets create "gs://$GCS_BUCKET" --project="{gcp_project}" || true
  gcloud storage cp {slug_name}.qcow2 "gs://$GCS_BUCKET/{slug_name}.qcow2"
  ```

### Paso 3: Registro e Importacion de la Imagen en Google Compute Engine
Importa la imagen en el catalogo de Compute Engine habilitando controladores VirtIO y compatibilidad UEFI:
```bash
gcloud compute images import {slug_name}-cloudmove \\
    --project="{gcp_project}" \\
    --source-file="gs://$GCS_BUCKET/{slug_name}.qcow2" \\
    --guest-os-features=UEFI_COMPATIBLE,GVNIC,VIRTIO_SCSI_MULTIQUEUE
```

### Paso 4: Montaje y Aprovisionamiento de la VM con Terraform
Ejecuta Terraform pasando el nombre de la imagen importada:
```bash
terraform init
terraform plan -var="custom_image_name={slug_name}-cloudmove"
terraform apply -auto-approve -var="custom_image_name={slug_name}-cloudmove"
```

### Paso 5: Conexion Remota y Verificacion del Disco Montado
1. Conectate a la maquina virtual mediante Google Cloud IAP o SSH:
```bash
gcloud compute ssh {slug_name}-vm --zone={region}-a --project={gcp_project}
```
2. Inspecciona el disco y expande el sistema de archivos:
```bash
lsblk
sudo growpart /dev/sda 1 || true
sudo resize2fs /dev/sda1 2>/dev/null || sudo xfs_growfs / 2>/dev/null || true
```

### Paso 6: Restauracion de Configuraciones del SO In-Guest (Usuarios y Servicios)
Transfiere y ejecuta el paquete de restauracion:
```bash
# Copiar paquete al servidor
gcloud compute scp system_image_snapshot_*.tar.gz {slug_name}-vm:~/ --zone={region}-a

# En el servidor Compute Engine:
tar -xzf system_image_snapshot_*.tar.gz
sudo chmod +x restore_system_image.sh
sudo ./restore_system_image.sh
```

### Paso 7: Validacion Operativa
Comprueba el estado de salud de la maquina virtual y servicios en escucha:
```bash
systemctl list-units --type=service --state=running
sudo ss -tulpn
```
"""


def _build_case_3_guide(
    provider_clean: str,
    job_name: str,
    slug_name: str,
    migration_id: str,
    region: str,
    gcp_project: str,
    src: Dict[str, Any],
    files: Dict[str, str],
) -> str:
    servers_count = len(src.get("servers", [])) or 12
    waves_count = 4

    return f"""# Guia Paso a Paso: Ejecucion de Campana de Migracion de Datacenter ({provider_clean.upper()})
**Campana:** {job_name} | **ID de Migracion:** {migration_id}
**Total de Servidores:** {servers_count} servidores inventariados | **Fases:** {waves_count} Oleadas (Waves)
**Nube Destino:** {provider_clean.upper()} (`{region}`)
**Estrategia:** Replicacion Continua a Nivel de Bloques con Replicacion de Datos CDC y Cero Tiempo de Inactividad

---

### Paso 1: Descargar el Paquete de Campana de Datacenter
Descarga el archivo ZIP generado por CloudMove:
```bash
CLOUDMOVE_API_URL="${{CLOUDMOVE_API_URL:-{DEFAULT_API_URL}}}"
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/{migration_id}/bundle.zip"
unzip bundle.zip -d ./cloudmove_datacenter
cd ./cloudmove_datacenter
```
Archivos incluidos:
- `main.tf`, `variables.tf`: Landing Zone completa (VPC central, Subredes de BD/App/Web, Transit Gateway, Cloud NAT).
- `migration_waves.json`: Matriz de dependencias y asignacion de servidores por oleada.
- `deploy_waves_{provider_clean}.sh`: Script para orquestar la migracion secuencial por fases.
- `DEPLOYMENT_INSTRUCTIONS.md`: Este manual de operaciones.

### Paso 2: Despliegue de la Landing Zone y Red Compartida (Wave 0)
Antes de migrar servidores individuales, despliega los cimientos de red y seguridad:
```bash
cd landing_zone
terraform init
terraform apply -auto-approve
```
Esto aprovisiona:
1. VPC central con enrutamiento entre subredes publicas, de aplicacion y de bases de datos.
2. Conexion hibrida hacia el datacenter local ({provider_clean.upper() == "AWS" and "AWS Site-to-Site VPN / Direct Connect" or "Google Cloud Interconnect / Cloud VPN"}).
3. Roles de servicio IAM, politicas de firewall y perimetros de seguridad.

### Paso 3: Migracion Continua de Bases de Datos (Wave 1 - Data Tier)
1. Aprovisionar instancias administradas de base de datos ({provider_clean.upper() == "AWS" and "Amazon RDS / Aurora Multi-AZ" or "Google Cloud SQL"}).
2. Configurar replicacion continua de datos con Change Data Capture (CDC):
{provider_clean == "aws" and """```bash
# Iniciar tarea de replicacion con AWS Database Migration Service (DMS)
aws dms start-replication-task --replication-task-arn $DMS_TASK_ARN --start-replication-task-type start-replication
```""" or """```bash
# Iniciar replicacion continua con Database Migration Service de GCP
gcloud database-migration migration-jobs start $GCP_MIGRATION_JOB_ID
```"""}
3. Mantener la replicacion activa mientras se migran las capas de aplicacion.

### Paso 4: Migracion de Servidores de Aplicacion por Bloques (Wave 2 - App Tier)
Instalar los agentes de replicacion continua a nivel de bloques en los servidores fisicos o hipervisores VMware/Proxmox:
{provider_clean == "aws" and f"""```bash
# Instalar agente de AWS Application Migration Service (AWS MGN) en los servidores origen
sudo ./aws-replication-installer-init.py --region {region}
```""" or """```bash
# Configurar Google Cloud Migrate to Virtual Machines
gcloud migration vms connectors create ...
```"""}
Los discos se sincronizan de forma continua y transparente en segundo plano.

### Paso 5: Despliegue de Balanceadores y Capa Web (Wave 3 - Web Tier)
Aprovisionar balanceadores de carga ({provider_clean.upper() == "AWS" and "Application Load Balancer" or "Google Cloud Load Balancing"}) apuntando a los servidores replicados en la Wave 2.

### Paso 6: Ventana de Conmutacion Final (Cutover) y Rollback
1. Activar modo solo-lectura temporal en base de datos origen.
2. Esperar a que el retraso (lag) de replicacion en CDC llegue a 0 segundos.
3. Promover la base de datos en la nube a Primaria.
4. Conmutar registros DNS con TTL bajo (60 segundos).
5. Mantener canal de replicacion inversa activo durante la ventana de observabilidad (48 horas).
"""
