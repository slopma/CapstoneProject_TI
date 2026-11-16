import React from "react";

export default function CloudRunbookGuidePanel({
  currentJob,
  showDeploymentGuide,
  setShowDeploymentGuide,
  handleDownloadZipBundle,
  handleDownloadDiskImage,
  handleDownloadSystemImage,
  handleDownloadHypervisorScript,
  handleDownloadFile,
}) {
  if (!currentJob?.generated_artifacts?.files) return null;

  return (
              <div className="cm-card">
                <div className="cm-card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                  <div>
                    <span style={{ fontSize: 15, fontWeight: 700 }}>
                      Guía Paso a Paso: Cómo Montar lo Recogido en la Nube ({currentJob.target_provider?.toUpperCase()})
                    </span>
                    <div className="cm-hint" style={{ marginTop: 4 }}>
                      {currentJob.use_case === "app_source" && "Caso 1: Aplicación desde Código Fuente / GitHub — Despliegue en Contenedores Gestionados y Bases de Datos"}
                      {currentJob.use_case === "vm_image" && "Caso 2: Sistema Operativo / Máquina Virtual — Ingesta de Disco, Importación de Hipervisor y Restauración In-Guest"}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <button
                      type="button"
                      className="cm-btn primary sm"
                      onClick={handleDownloadZipBundle}
                    >
                      Descargar Paquete Completo (.ZIP)
                    </button>
                    {currentJob.use_case === "vm_image" && (
                      <details className="cm-export-menu">
                        <summary aria-label="Descargar formatos de imagen de disco y scripts de hipervisor">
                          Formatos de Disco e Imagen ▾
                        </summary>
                        <div className="cm-export-dropdown-list" role="menu">
                          <button
                            type="button"
                            role="menuitem"
                            className="cm-export-dropdown-item"
                            onClick={() => handleDownloadDiskImage("vdi")}
                            title="Descargar disco virtual listo para VirtualBox (.VDI)"
                          >
                            <span>Descargar VirtualBox (.VDI)</span>
                            <code>.vdi</code>
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            className="cm-export-dropdown-item"
                            onClick={() => handleDownloadDiskImage("vmdk")}
                            title="Descargar disco virtual listo para VMware (.VMDK)"
                          >
                            <span>Descargar VMware (.VMDK)</span>
                            <code>.vmdk</code>
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            className="cm-export-dropdown-item"
                            onClick={() => handleDownloadDiskImage("qcow2")}
                            title="Descargar disco virtual para QEMU / KVM / Proxmox (.QCOW2)"
                          >
                            <span>Descargar QCOW2</span>
                            <code>.qcow2</code>
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            className="cm-export-dropdown-item"
                            onClick={handleDownloadSystemImage}
                            title="Descargar copia del sistema operativo (/etc, usuarios, systemd)"
                          >
                            <span>Descargar Copia SO (.tar.gz)</span>
                            <code>.tar.gz</code>
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            className="cm-export-dropdown-item"
                            onClick={() => handleDownloadHypervisorScript("virtualbox")}
                            title="Descargar script para crear y encender la VM automáticamente en VirtualBox con 1 comando"
                          >
                            <span>Script VirtualBox</span>
                            <code>.sh</code>
                          </button>
                        </div>
                      </details>
                    )}
                    {currentJob.generated_artifacts?.files?.["DEPLOYMENT_INSTRUCTIONS.md"] && (
                      <button
                        type="button"
                        className="cm-btn sm"
                        onClick={() => handleDownloadFile("DEPLOYMENT_INSTRUCTIONS.md", currentJob.generated_artifacts.files["DEPLOYMENT_INSTRUCTIONS.md"])}
                      >
                        Descargar Manual (.md)
                      </button>
                    )}
                    <button
                      type="button"
                      className="cm-btn sm"
                      aria-expanded={showDeploymentGuide}
                      onClick={() => setShowDeploymentGuide((prev) => !prev)}
                    >
                      {showDeploymentGuide ? "Ocultar Pasos (−)" : "Ver Pasos (+)"}
                    </button>
                  </div>
                </div>

                {/* Barra de Descargas de Archivos Individuales */}
                <div style={{ marginBottom: 18, padding: "10px 14px", backgroundColor: "#f8fafc", borderRadius: 6, border: "1px solid #e2e8f0" }}>
                  <div style={{ fontSize: 13.5, fontWeight: 700, color: "#334155", marginBottom: 6 }}>
                    Archivos listos para descargar e inspeccionar individualmente:
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {Object.keys(currentJob.generated_artifacts.files).map((fName) => (
                      <button
                        key={fName}
                        type="button"
                        className="cm-btn sm"
                        style={{ fontSize: 13, padding: "3px 8px", backgroundColor: "#ffffff" }}
                        onClick={() => handleDownloadFile(fName, currentJob.generated_artifacts.files[fName])}
                        title={`Descargar ${fName}`}
                      >
                        {fName}
                      </button>
                    ))}
                  </div>
                </div>

                {showDeploymentGuide && (
                  <>
                {/* CASO 1: APLICACIÓN DESDE GITHUB / CÓDIGO FUENTE */}
                {currentJob.use_case === "app_source" && (() => {
                  const srcEnv = currentJob.source_environment || {};
                  const gitMeta = srcEnv.git_meta || {};
                  const appRepoUrl = gitMeta.repository_url || srcEnv.github_url || `https://github.com/empresa/${currentJob.name || "app"}`;
                  const appCommitSha = gitMeta.commit_sha || gitMeta.short_sha || "HEAD";
                  const appShortSha = gitMeta.short_sha || (appCommitSha !== "HEAD" ? appCommitSha.substring(0, 8) : "latest");
                  const appRuntime = srcEnv.language || (srcEnv.runtime && typeof srcEnv.runtime === "object" ? srcEnv.runtime.language : srcEnv.runtime) || "Aplicación Web";
                  const appFramework = srcEnv.framework || (srcEnv.runtime && typeof srcEnv.runtime === "object" ? srcEnv.runtime.framework : "") || "Framework Contenerizado";
                  const appPorts = srcEnv.exposed_ports || srcEnv.ports || [srcEnv.port || 8000];
                  const appPrimaryPort = Array.isArray(appPorts) ? appPorts[0] : appPorts;
                  const appStartCmds = srcEnv.start_commands || [appRuntime.toLowerCase().includes("python") ? `uvicorn main:app --port ${appPrimaryPort}` : "npm start"];
                  const appPrimaryStartCmd = appStartCmds[0];
                  const appHealthEps = srcEnv.health_endpoints || ["/health"];
                  const appPrimaryHealthEp = appHealthEps[0];
                  const appDb = srcEnv.database_requirements || srcEnv.database || {};
                  const appDbEngine = (typeof appDb === "object" ? appDb.engine : appDb) || "PostgreSQL";
                  const appDbVersion = (typeof appDb === "object" ? appDb.version : "") || "15";
                  const appSlug = (currentJob.name || "app").toLowerCase().replace(/[^a-z0-9_-]/g, "-");

                  const rtLower = appRuntime.toLowerCase();
                  const isPython = rtLower.includes("python") || rtLower.includes("py");
                  const isNode = rtLower.includes("node") || rtLower.includes("javascript") || rtLower.includes("typescript");
                  const isJava = rtLower.includes("java") || rtLower.includes("spring");
                  const isGo = rtLower.includes("go") || rtLower.includes("golang");

                  const depInstallCmd = isPython
                    ? "python3 -m venv .venv && source .venv/bin/activate\npip install -r requirements.txt"
                    : isNode
                    ? "npm ci --production || npm install"
                    : isJava
                    ? "./mvnw clean package -DskipTests || gradle build"
                    : isGo
                    ? "go mod download && go build -o app ."
                    : "docker build -t app:local .";

                  const migrateCmd = isPython
                    ? (appFramework.toLowerCase().includes("django") ? "python manage.py migrate" : "alembic upgrade head")
                    : isNode
                    ? "npx prisma migrate deploy || npm run migrate"
                    : isJava
                    ? "java -jar target/*.jar --migrate"
                    : isGo
                    ? "./app --migrate"
                    : "npm run migrate || alembic upgrade head";

                  return (
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 1: Clonar Repositorio en Commit Analizado y Descargar Paquete
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Clona el repositorio <strong>{appRepoUrl}</strong> en el commit exacto analizado (<code>{appShortSha}</code>) y extrae los artefactos generados por CloudMove:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`git clone ${appRepoUrl} ${appSlug}
cd ${appSlug}
git checkout ${appCommitSha}

CLOUDMOVE_API_URL="\${CLOUDMOVE_API_URL:-${typeof window !== "undefined" ? window.location.origin : ""}}"
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/bundle.zip"
unzip -o bundle.zip`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 2: Instalación de Dependencias y Validación Local ({appRuntime})
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Instala las dependencias detectadas para asegurar que el entorno de ejecución es reproducible:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{depInstallCmd}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 3: Compilación y Publicación del Contenedor (Amazon ECR)
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Compila la imagen Docker etiquetada con el commit analizado (<code>{appShortSha}</code>) y súbela al registro de contenedores de AWS:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`# 1. Autenticar Docker con Amazon ECR:
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr create-repository --repository-name ${appSlug} --region us-east-1 || true
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

# 2. Compilar imagen y subir a ECR:
docker build -t ${appSlug}:${appShortSha} .
docker tag ${appSlug}:${appShortSha} $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/${appSlug}:${appShortSha}
docker tag ${appSlug}:${appShortSha} $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/${appSlug}:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/${appSlug}:${appShortSha}
docker push $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/${appSlug}:latest`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 4: Aprovisionamiento de Infraestructura con Terraform (AWS)
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Despliega la red VPC, subredes, balanceador ALB, clúster ECS Fargate y base de datos {appDbEngine} {appDbVersion}:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`terraform init
terraform plan
terraform apply -auto-approve`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 5: Despliegue Efectivo de la Aplicación en AWS
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Fuerza la ejecución del contenedor en el servicio de cómputo en AWS configurando el comando de arranque (<code>{appPrimaryStartCmd}</code>):
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`aws ecs update-service \\
    --cluster $(terraform output -raw ecs_cluster_name 2>/dev/null || echo "${appSlug}-cluster") \\
    --service $(terraform output -raw ecs_service_name 2>/dev/null || echo "${appSlug}-service") \\
    --force-new-deployment --region us-east-1

aws ecs wait services-stable \\
    --cluster $(terraform output -raw ecs_cluster_name 2>/dev/null || echo "${appSlug}-cluster") \\
    --services $(terraform output -raw ecs_service_name 2>/dev/null || echo "${appSlug}-service") --region us-east-1`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 6: Configuración de Variables de Entorno y Migraciones ({appDbEngine})
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Configura las variables de entorno detectadas y ejecuta las migraciones de base de datos en AWS:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`# 1. Registrar secretos en AWS Secrets Manager:
aws secretsmanager create-secret --name "${appSlug}/production" \\
    --secret-string "{\\"DATABASE_URL\\":\\"$(terraform output -raw db_endpoint 2>/dev/null)\\",\\"PORT\\":\\"${appPrimaryPort}\\",\\"ALLOWED_ORIGINS\\":\\"*\\"}" \\
    --region us-east-1 || true

# 2. Ejecutar migraciones en ECS Fargate:
aws ecs run-task --cluster "${appSlug}-cluster" --task-definition "${appSlug}-task" --launch-type FARGATE \\
    --network-configuration "awsvpcConfiguration={{subnets=[$(terraform output -raw private_subnet_id 2>/dev/null)],securityGroups=[$(terraform output -raw ecs_security_group_id 2>/dev/null)],assignPublicIp=ENABLED}}" \\
    --overrides '{"containerOverrides": [{"name": "${appSlug}", "command": ["sh", "-c", "${migrateCmd}"]}]}'`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 7: Enlace Frontend y Verificación Operativa (Sonda en {appPrimaryHealthEp})
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Comprueba la respuesta HTTP en la sonda de salud <code>{appPrimaryHealthEp}</code> y conecta la URL pública al cliente web:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`APP_URL=$(terraform output -raw app_endpoint 2>/dev/null || terraform output -raw service_url 2>/dev/null || echo "http://localhost:${appPrimaryPort}")
echo "Aplicación activa en la nube: $APP_URL"

# Verificar sonda de salud detectada:
curl -Iv "$APP_URL${appPrimaryHealthEp}" || curl -Iv "$APP_URL/"

# Configuración para clientes frontend:
echo "Configurar en cliente web: VITE_API_BASE_URL=$APP_URL"`}
                        </pre>
                      </div>
                    </div>
                  );
                })()}

                {/* CASO 2: IMAGEN DE SISTEMA OPERATIVO / VM */}
                {currentJob.use_case === "vm_image" && (() => {
                  const vmSrc = currentJob.source_environment || {};
                  const vmOs = vmSrc.os || {};
                  const vmDistro = vmOs.distro || "Linux";
                  const vmKernel = vmOs.kernel || "Linux Kernel";
                  const vmArch = vmOs.architecture || "x86_64";
                  const vmBootMode = (vmSrc.boot_mode || "UEFI").toLowerCase();
                  const vmUsers = Array.isArray(vmSrc.local_users) ? vmSrc.local_users.join(", ") : (vmSrc.local_users || "root, ubuntu");
                  const vmDisks = vmSrc.disks || [{}];
                  const vmPrimaryDisk = vmDisks[0]?.device || "/dev/nvme0n1";
                  const vmDiskSize = vmDisks[0]?.size_gib || 50;
                  const vmPkgs = vmSrc.installed_packages_summary?.total_count || 4324;
                  const vmServicesList = vmSrc.services || ["ssh.service", "systemd-journald.service"];
                  const vmServicesStr = Array.isArray(vmServicesList)
                    ? (typeof vmServicesList[0] === "object" ? vmServicesList.slice(0, 5).map(s => s.name).join(", ") : vmServicesList.slice(0, 5).join(", "))
                    : "ssh.service, systemd-journald.service";
                  const vmSlug = (currentJob.name || "host").toLowerCase().replace(/[^a-z0-9_-]/g, "-");

                  return (
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 1: Descargar la Copia del SO y Disco Listo para tu Hipervisor
                        </div>
                        <p style={{ margin: "0 0 8px 0", fontSize: 14, color: "#475569" }}>
                          Servidor analizado: <strong>{currentJob.name}</strong> ({vmDistro}, Kernel: <code>{vmKernel}</code>, <code>{vmArch}</code>, Disco: <code>{vmPrimaryDisk}</code> de {vmDiskSize} GiB, {vmPkgs} paquetes).
                          Descarga el formato exacto que necesites para tu virtualizador o para la nube:
                        </p>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                          <button
                            type="button"
                            className="cm-btn sm"
                            onClick={() => handleDownloadDiskImage("vdi")}
                            title="Descargar disco virtual listo para VirtualBox (.VDI)"
                          >
                            Descargar para VirtualBox (.VDI)
                          </button>
                          <button
                            type="button"
                            className="cm-btn sm"
                            onClick={() => handleDownloadDiskImage("vmdk")}
                            title="Descargar disco virtual listo para VMware (.VMDK)"
                          >
                            Descargar para VMware (.VMDK)
                          </button>
                          <button
                            type="button"
                            className="cm-btn sm"
                            onClick={() => handleDownloadDiskImage("qcow2")}
                            title="Descargar disco virtual para QEMU / KVM / Proxmox (.QCOW2)"
                          >
                            Descargar QCOW2 (.qcow2)
                          </button>
                          <button
                            type="button"
                            className="cm-btn sm"
                            onClick={handleDownloadSystemImage}
                            title="Descargar copia del sistema operativo (/etc, usuarios, systemd)"
                          >
                            Descargar Copia SO (.tar.gz)
                          </button>
                          <button
                            type="button"
                            className="cm-btn primary sm"
                            onClick={handleDownloadZipBundle}
                          >
                            Descargar Paquete Completo (.ZIP)
                          </button>
                        </div>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`# Descargas directas vía curl:
CLOUDMOVE_API_URL="\${CLOUDMOVE_API_URL:-${typeof window !== "undefined" ? window.location.origin : ""}}"

# Para VirtualBox:
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/disk-image?format=vdi"
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/hypervisor-script?hypervisor=virtualbox"

# Para VMware:
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/disk-image?format=vmdk"

# Copia de archivos y configuraciones del SO:
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/system-image"`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 2: Transmitir / Subir la Copia del SO hacia el Almacenamiento Cloud
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Sube la imagen a la nube utilizando streaming directo sin saturar el almacenamiento local o sube la imagen descargada:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`# Opción A: Streaming directo bit a bit a Amazon S3 en caliente (Recomendado):
sudo chmod +x create_full_raw_disk_clone.sh
sudo ./create_full_raw_disk_clone.sh s3

# Opción B: Subir la imagen virtual descargada:
aws s3 mb "s3://cloudmove-vm-import-${vmSlug}-us-east-1" || true
aws s3 cp *.qcow2 "s3://cloudmove-vm-import-${vmSlug}-us-east-1/"`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 3: Registro e Importación de la Imagen en Amazon EC2 (Creación de AMI)
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Importa el disco en Amazon EC2 respetando el modo de arranque detectado (<code>{vmBootMode}</code>):
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`# Ejecutar importación de AMI en AWS con modo de arranque ${vmBootMode}:
aws ec2 import-image --description "Migrated ${vmDistro}" --disk-containers file:///tmp/containers.json --boot-mode ${vmBootMode} --region us-east-1

# O ejecuta el script automatizado que realiza el proceso completo:
chmod +x deploy_to_aws.sh
./deploy_to_aws.sh`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 4: Montaje y Aprovisionamiento de la VM con Terraform
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Con el identificador de la AMI, provisiona la instancia de cómputo EC2, VPC, subredes e IP pública:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`terraform init
terraform plan -var="ami_id=$AMI_ID"
terraform apply -auto-approve -var="ami_id=$AMI_ID"`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 5: Conexión Remota SSH y Verificación/Expansión del Disco Montado
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Inicia sesión por SSH en la nueva máquina virtual, verifica los puntos de montaje y expande la partición en caliente:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`# 1. Conectar a la instancia en la nube:
ssh -i ~/.ssh/id_rsa admin@$INSTANCE_PUBLIC_IP

# 2. Verificar discos y expandir partición raíz si el volumen cloud es mayor:
lsblk -f
sudo growpart /dev/nvme0n1 1 || sudo growpart /dev/xvda 1 || sudo growpart /dev/sda 1 || true
sudo resize2fs /dev/nvme0n1p1 2>/dev/null || sudo xfs_growfs / 2>/dev/null || true`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 6: Restauración de Configuraciones del SO In-Guest (Usuarios y Servicios)
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Transfiere la copia descargada <code>system_image_snapshot_*.tar.gz</code> al servidor y restaura los usuarios identificados (<code>{vmUsers}</code>) y servicios (<code>{vmServicesStr}</code>):
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`# 1. Copiar snapshot del SO hacia la VM (desde tu estación de trabajo):
scp -i ~/.ssh/id_rsa system_image_snapshot_*.tar.gz admin@$INSTANCE_PUBLIC_IP:~/

# 2. En la sesión SSH de la VM remota, ejecutar la restauración:
tar -xzf system_image_snapshot_*.tar.gz
sudo chmod +x restore_system_image.sh
sudo ./restore_system_image.sh`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 7: Validación Operativa y Puesta en Marcha en la Nube
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Comprueba que los servicios del sistema, bases de datos y demonios se encuentren activos y respondiendo:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`# 1. Validar servicios activos y puertos en escucha:
sudo systemctl status ssh
sudo ss -tulpn

# 2. Verificar cuentas de usuario locales restauradas:
cat /etc/passwd | grep -E "admin|root|postgres|ubuntu|rabbitmq"`}
                        </pre>
                      </div>

                      <div className="cm-step-card">
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Paso 8: Automatización y Prueba Local en Hipervisores (VirtualBox / VMware)
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 14, color: "#475569" }}>
                          Si deseas validar el sistema operativo o ejecutarlo como máquina virtual local con 1 comando:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 13.5 }}>
{`# Opción A: VirtualBox (Automático)
# Descarga el lanzador y ejecútalo (crea la VM, asigna 4GB RAM, UEFI y conecta el disco VDI):
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/hypervisor-script?hypervisor=virtualbox"
chmod +x launch_virtualbox_*.sh
./launch_virtualbox_*.sh

# Opción B: VMware Workstation / Player
# Descarga el disco VMDK y abre el archivo VMX generado en el paquete ZIP:
vmplayer ${vmSlug}.vmx`}
                        </pre>
                      </div>
                    </div>
                  );
                })()}
                  </>
                )}
              </div>
  );
}
