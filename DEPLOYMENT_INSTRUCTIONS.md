# Guia Paso a Paso: Despliegue y Configuracion de Aplicacion en AWS (ECS Fargate / RDS)
**Carga de Trabajo:** Migración CocoaApp → AWS | **ID de Migracion:** mig-app-aws-f0b1f6
**Repositorio GitHub:** `https://github.com/empresa/migraci-n-cocoaapp-aws` (Rama: `main`, Commit: `latest`)
**Entorno de Ejecucion:** Python (backend) + TypeScript/React (frontend) (FastAPI (Backend API) + React (Vite SPA) (Frontend)) | **Puerto:** `80` | **Region Destino:** AWS `us-east-1`
**Modo Arquitectonico:** Contenedores en AWS Fargate con Red Aislada VPC y Base de Datos Gestionada (PostgreSQL 15)

---

### Paso 1: Descargar el Paquete de Despliegue y Clonar el Repositorio
Para desplegar el codigo analizado de forma identica:
1. Clonar el repositorio y posicionarse en el commit analizado:
```bash
git clone https://github.com/empresa/migraci-n-cocoaapp-aws migraci-n-cocoaapp-aws
cd migraci-n-cocoaapp-aws
git checkout HEAD
```
2. Descargar los artefactos generados por CloudMove (Terraform, Dockerfile optimizado y configuraciones):
```bash
CLOUDMOVE_API_URL="${CLOUDMOVE_API_URL:-http://localhost:8000}"
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/mig-app-aws-f0b1f6/bundle.zip"
unzip -o bundle.zip
```
Archivos incluidos en el paquete:
- `main.tf`, `variables.tf`, `outputs.tf`, `provider.tf`: Modulos de Terraform para aprovisionar VPC, Subredes publicas/privadas, Security Groups, Cluster ECS Fargate y Base de Datos RDS (PostgreSQL).
- `Dockerfile` y `docker-compose.yml`: Definicion de contenedor optimizada para Python (backend) + TypeScript/React (frontend) (FastAPI (Backend API) + React (Vite SPA) (Frontend)) ejecutando `["nginx", "-g", "daemon off;"]`.
- `DEPLOYMENT_INSTRUCTIONS.md`: Este manual tecnico de referencia.

### Paso 2: Instalacion de Dependencias y Validacion Local del Proyecto
Instala las dependencias detectadas para verificar la integridad del codigo fuente antes de la construccion del contenedor:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Paso 3: Autenticacion en AWS y Configuracion del CLI
Verifica que tu cuenta de AWS este activa y configurada:
```bash
aws configure set default.region us-east-1
aws sts get-caller-identity
```

### Paso 4: Compilacion y Publicacion de la Imagen en Amazon ECR
1. Crear el repositorio en Amazon ECR (si no existe):
```bash
aws ecr create-repository --repository-name migraci-n-cocoaapp-aws --region us-east-1 || true
```
2. Autenticar Docker local con el registro privado de ECR:
```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com
```
3. Compilar la imagen Docker local con el tag exacto del commit y subirla al repositorio:
```bash
docker build -t migraci-n-cocoaapp-aws:latest .
docker tag migraci-n-cocoaapp-aws:latest $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/migraci-n-cocoaapp-aws:latest
docker tag migraci-n-cocoaapp-aws:latest $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/migraci-n-cocoaapp-aws:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/migraci-n-cocoaapp-aws:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/migraci-n-cocoaapp-aws:latest
```

### Paso 5: Aprovisionamiento de Infraestructura con Terraform
Aprovisiona la red VPC, los grupos de seguridad, el balanceador ALB, la base de datos gestionada (PostgreSQL) y la tarea ECS:
```bash
terraform init
terraform plan
terraform apply -auto-approve
```

### Paso 6: Despliegue Efectivo del Servicio en la Nube (ECS Fargate)
Fuerza la actualizacion del servicio ECS para que descargue la imagen publicada en ECR y levante las tareas:
```bash
CLUSTER_NAME=$(terraform output -raw ecs_cluster_name 2>/dev/null || echo "migraci-n-cocoaapp-aws-cluster")
SERVICE_NAME=$(terraform output -raw ecs_service_name 2>/dev/null || echo "migraci-n-cocoaapp-aws-service")

aws ecs update-service \
    --cluster "$CLUSTER_NAME" \
    --service "$SERVICE_NAME" \
    --force-new-deployment \
    --region us-east-1

echo "Esperando a que las tareas de ECS alcancen estado RUNNING y salud estable..."
aws ecs wait services-stable --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" --region us-east-1
```

### Paso 7: Configuraciones Necesarias para Usar la Aplicacion

#### 7.1 Variables de Entorno y Almacenamiento de Secretos
Almacena las credenciales sensibles y de conexion en AWS Secrets Manager:
```bash
cat << 'EOF' > .env.production
PORT=80
NODE_ENV=production
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/migraci-n-cocoaapp-aws_db
SECRET_KEY=generate-a-secure-random-token-here
ALLOWED_ORIGINS=*
VITE_SUPABASE_URL=production-value-here
VITE_SUPABASE_ANON_KEY=production-value-here
VITE_SUPABASE_SERVICE_ROLE_KEY=production-value-here
VITE_API_URL=production-value-here
EOF

aws secretsmanager create-secret \
    --name "migraci-n-cocoaapp-aws/production" \
    --description "Variables de entorno y secretos para Migración CocoaApp → AWS" \
    --secret-string file://.env.production \
    --region us-east-1 || \
aws secretsmanager update-secret \
    --secret-id "migraci-n-cocoaapp-aws/production" \
    --secret-string file://.env.production \
    --region us-east-1
```

#### 7.2 Inicializacion y Ejecucion de Migraciones de Base de Datos
Obten los datos de conexion de la base de datos RDS creada por Terraform:
```bash
DB_ENDPOINT=$(terraform output -raw db_endpoint 2>/dev/null || echo "rds-host:5432")
echo "Base de datos disponible en: $DB_ENDPOINT"

# Opcion A: Ejecutar migraciones mediante una tarea efimera en ECS Fargate (Recomendado)
aws ecs run-task \
    --cluster "$CLUSTER_NAME" \
    --task-definition "migraci-n-cocoaapp-aws-task" \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$(terraform output -raw private_subnet_id 2>/dev/null)],securityGroups=[$(terraform output -raw ecs_security_group_id 2>/dev/null)],assignPublicIp=ENABLED}" \
    --overrides '{"containerOverrides": [{"name": "migraci-n-cocoaapp-aws", "command": ["alembic", "upgrade", "head"]}]}'

# Opcion B: Ejecutar migraciones directamente con herramientas locales si tienes acceso por VPN o Bastion
# alembic upgrade head
```

#### 7.3 Configuracion de Red, CORS y Grupos de Seguridad
- **Trafico Web:** El balanceador Application Load Balancer (ALB) permite trafico de entrada en el puerto 80 (HTTP) y 443 (HTTPS) desde `0.0.0.0/0`, enrutando al puerto `80` del contenedor.
- **Base de Datos:** El grupo de seguridad de RDS restringe las conexiones admitiendo unicamente paquetes provenientes del Security Group de ECS Fargate.
- **CORS:** Si la aplicacion atiende peticiones de una aplicacion web externa, verifica que la variable `ALLOWED_ORIGINS` contenga el dominio del cliente.

#### 7.4 Enlace Frontend <-> Backend
Si cuentas con una aplicacion web separada (React, Vue, Angular o Mobile), configura la variable de entorno del cliente con el endpoint asignado:
```bash
SERVICE_ENDPOINT=$(terraform output -raw app_endpoint 2>/dev/null || terraform output -raw alb_dns_name)
echo "Configurar en cliente frontend: VITE_API_BASE_URL=http://$SERVICE_ENDPOINT"
```

### Paso 8: Acceso Publico, Verificacion y Como Usar la Aplicacion
1. **Consultar URL Publica:**
```bash
APP_URL=$(terraform output -raw app_endpoint 2>/dev/null || echo "http://$(terraform output -raw alb_dns_name)")
echo "URL publica de la aplicacion: $APP_URL"
```
2. **Prueba de Salud del Servicio (Sonda en `/health`):**
```bash
curl -Iv "$APP_URL/health" || curl -Iv "$APP_URL/"
```
3. **Uso y Pruebas Operativas:**
- Abre `$APP_URL` en tu navegador web.
- Si expone una API REST (FastAPI/Express), accede a la documentacion interactiva en `$APP_URL/docs` o `$APP_URL/swagger`.
- Realiza una peticion de prueba de login o consulta de registros de prueba contra la base de datos migrada.
