# Guia Paso a Paso: Despliegue y Montaje de Sistema Operativo e Imagen de VM en AWS EC2
**Servidor Origen:** Migración SO Host en Vivo (rabbitmq-kali-live-os) → AWS | **ID de Migracion:** mig-vm_-aws-93b6b2
**Sistema Operativo:** Kali GNU/Linux Rolling (Kernel: `7.1.5+kali-amd64`, `x86_64`)
**Arranque / Particionado:** `UEFI` (`GPT`) | **Disco Principal:** `/dev/nvme0n1` (476.94 GiB prov, 233.66 GiB usados)
**Usuarios Descubiertos:** root, www-data, mysql, redis, postgres, lacastrilp, rabbitmq | **Paquetes Inventariados:** 4324
**Region Destino:** AWS `us-east-1`

---

### Paso 1: Descargar la Copia del SO y los Artefactos de Migracion
Tienes a tu disposicion descargas directas desde la interfaz de CloudMove o mediante la API:
1. **Descargar Paquete Completo de Despliegue (.ZIP):**
   Incluye Terraform (`main.tf`, `variables.tf`), `deploy_to_aws.sh`, `create_full_raw_disk_clone.sh`, `restore_system_image.sh`, manifiestos de paquetes/usuarios y la copia comprimida del SO.
   ```bash
   CLOUDMOVE_API_URL="${CLOUDMOVE_API_URL:-http://localhost:8000}"
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/mig-vm_-aws-93b6b2/bundle.zip"
   unzip bundle.zip -d ./cloudmove_os_migration
   cd ./cloudmove_os_migration
   ```
2. **Descargar Copia del Sistema Operativo Directamente (.tar.gz):**
   Contiene todos los ficheros de `/etc`, tabla de particiones, cuentas de usuarios locales, servicios de systemd y script de restauracion in-guest:
   ```bash
   curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/mig-vm_-aws-93b6b2/system-image"
   ```
3. **Descargar Imagen de Disco QCOW2 (si fue generada en Staging):**
   ```bash
   curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/mig-vm_-aws-93b6b2/disk-image"
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
  S3_BUCKET="cloudmove-vm-import-migraci-n-so-host-en-vivo-rabbitmq-kali-live-os-aws-us-east-1"
  aws s3 mb "s3://$S3_BUCKET" --region us-east-1 || true
  aws s3 cp migraci-n-so-host-en-vivo-rabbitmq-kali-live-os-aws.qcow2 "s3://$S3_BUCKET/migraci-n-so-host-en-vivo-rabbitmq-kali-live-os-aws.qcow2"
  ```

### Paso 3: Registro e Importacion de la Imagen en el Hipervisor AWS (Creacion de AMI)
1. Configurar el rol IAM requerido por el servicio de importacion (`vmimport`):
```bash
cat << 'EOF' > /tmp/vmimport-trust.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "vmie.amazonaws.com" },
      "Action": "sts:AssumeRole",
      "Condition": { "StringEquals": { "sts:Externalid": "vmimport" } }
    }
  ]
}
EOF
aws iam create-role --role-name vmimport --assume-role-policy-document file:///tmp/vmimport-trust.json || true
```
2. Lanzar la tarea de conversion a AMI en AWS:
```bash
cat << EOF > /tmp/containers.json
[
  {
    "Description": "Copia de SO Migración SO Host en Vivo (rabbitmq-kali-live-os) → AWS",
    "Format": "qcow2",
    "UserBucket": {
      "S3Bucket": "$S3_BUCKET",
      "S3Key": "migraci-n-so-host-en-vivo-rabbitmq-kali-live-os-aws.qcow2"
    }
  }
]
EOF

IMPORT_TASK_ID=$(aws ec2 import-image \
    --description "Migración SO Host en Vivo (rabbitmq-kali-live-os) → AWS OS Migration" \
    --disk-containers file:///tmp/containers.json \
    --boot-mode uefi \
    --region us-east-1 \
    --query "ImportTaskId" --output text)

echo "Tarea de importacion iniciada: $IMPORT_TASK_ID. Esperando finalizacion..."
while true; do
    STATUS=$(aws ec2 describe-import-image-tasks --import-task-ids "$IMPORT_TASK_ID" --region us-east-1 --query "ImportImageTasks[0].Status" --output text)
    PROGRESS=$(aws ec2 describe-import-image-tasks --import-task-ids "$IMPORT_TASK_ID" --region us-east-1 --query "ImportImageTasks[0].Progress" --output text 2>/dev/null || echo "0")
    echo "  Progreso de importacion AMI: $STATUS ($PROGRESS%)"
    if [ "$STATUS" = "completed" ]; then
        AMI_ID=$(aws ec2 describe-import-image-tasks --import-task-ids "$IMPORT_TASK_ID" --region us-east-1 --query "ImportImageTasks[0].ImageId" --output text)
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
SSH_USER="${SSH_USER:-admin}"
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
SSH_USER="${SSH_USER:-admin}"
scp -i ~/.ssh/id_rsa system_image_snapshot_*.tar.gz "$SSH_USER@$INSTANCE_IP:~/"

# En la sesion SSH de la maquina virtual:
tar -xzf system_image_snapshot_*.tar.gz
sudo chmod +x restore_system_image.sh
sudo ./restore_system_image.sh
```
¿Que realiza `restore_system_image.sh`?
- Restaura los archivos de `/etc` preservando certificados, `/etc/hosts` y configuraciones personalizadas.
- Recrea las cuentas de usuario locales descubiertas (root, www-data, mysql, redis, postgres, lacastrilp, rabbitmq) con sus mismos UID y shells.
- Recarga demonios de systemd y activa los servicios criticos.

### Paso 7: Validacion Operativa y Puesta en Marcha
Verifica que los servicios del sistema operativo se encuentren activos:
```bash
# Validar servicios principales
sudo systemctl status ssh
sudo ss -tulpn

# Validar cuentas de usuario restauradas
cat /etc/passwd | grep -E "${SSH_USER:-admin}|root|postgres"
```
El servidor en la nube esta montado, activo y operando con la misma configuracion del entorno original.
