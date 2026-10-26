# CloudMove v2.1 — Informe de Auditoría Técnica, Arquitectura Evolucionada y Guía de Validación (On-Premise → AWS / GCP)

**Fecha:** 2026-10-25  
**Versión de esquema CMIR:** `2.1`  
**Proveedores destino soportados:** Exclusivamente **AWS** y **Google Cloud Platform (GCP)** (`Azure` fuera del alcance funcional activo; ver `docs/ADR/ADR-001-aws-gcp-exclusive-target-providers.md`).

---

## 1. Fase Inicial: Tabla de Auditoría Técnica del Repositorio

Antes de implementar las nuevas capacidades, se auditó el código fuente existente de CloudMove, comparando documentación, endpoints, modelos, servicios, interfaz y pruebas:

| Componente | Ubicación | Estado Inicial Demostrado | Evidencia Concreta | Funcionalidad Reutilizada | Cambios Implementados para los 3 Casos de Uso |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Modelo e Infraestructura CMIR** | `backend/app/cmir/models.py`, `builder.py`, `normalizer.py`, `validator.py` | **Funcional (Parcial para los 3 casos de uso)** | Soportaba 8 niveles jerárquicos básicos y atributos de descubrimiento osquery, pero carecía de versionado de esquema, metadatos estructurados de evidencia (`observed` / `inferred` / `unknown`, fuente, fecha, confianza), mapeo al recurso destino y entidades explícitas para `datacenter`, `physical_host`, `hypervisor`, `vm_image`, `disk_image`, `application`, `process`, `system_service`. | `CMIR`, `CMIRNode`, `CMIRRelationship`, `normalize_inventory`, `validate_cmir`. | Extendido a **CMIR v2.1** con `EvidenceItem`, `TargetResourceMapping`, 23 tipos canónicos de entidad, 13 tipos de relación (`runs_on`, `hosts`, `depends_on`, `communicates_with`, `connects_to`, `reads_from`, `writes_to`, `mounts`, `exposes`, `requires_identity`, `migrates_to`), IDs determinísticos (`deterministic_node_id`) y migración automática de esquemas (`migrate_cmir_schema`). |
| **Motor de Grafos y Selección** | `backend/app/graph/builder.py`, `hierarchy.py`, `selection.py` | **Funcional (Parcial)** | `builder.py` construía grafos Cytoscape de 8 niveles; `selection.py` no existía como extractor de subgrafos CMIR con protección de dependencias compartidas. | `build_graph`, niveles jerárquicos y estilos Cytoscape. | Añadidos tipos e iconos CMIR v2.1 en `builder.py` y creado `extract_subgraph_cmir` en `selection.py` para extraer subgrafos de cargas seleccionadas preservando su jerarquía y relaciones. |
| **Motor de Dependencias** | `backend/app/dependencies/resolver.py`, `validator.py` | **Parcial** | Clasificaba dependencias directas, inversas y compartidas (`shared`), pero no distinguía dependencias observadas (`confirmed`) de inferidas (`inferred`) o desconocidas (`unknown`), ni bloqueaba la migración automática de recursos compartidos. | `analyze_dependencies`, `validate_migration_selection`. | Extendido para separar `confirmed_dependencies`, `inferred_dependencies` y `unknown_dependencies`, añadir `shared_dependency_policies` (`auto_migrate=False, requires_validation=True`) y calcular `auto_migratable_resources`. |
| **Adaptadores y Traductores (AWS, GCP, Azure, K8s)** | `backend/app/adapters/`, `backend/app/translators/aws.py`, `gcp.py` | **AWS Funcional / GCP Desconectado / Azure Legacy** | `AWSAdapter` funcionaba y estaba conectado a `/api/migration/generate`. `translators/gcp.py` existía pero **no existía `GCPAdapter`**, ni generador HCL para GCP en `generators/terraform.py`, ni soporte GCP en el router o la UI. Azure y K8s seguían expuestos en UI y API. | `CloudAdapter`, `AWSAdapter`, `translate_to_aws`, `translate_to_gcp`. | Creado `GCPAdapter` (`gcp_adapter.py`), ampliado `CloudAdapter` con validación de configuración, prerrequisitos, artefactos y estado, restringido el alcance activo exclusivamente a `aws` y `gcp` (con rechazo HTTP 400 para `azure`), manteniendo `AzureAdapter` solo para compatibilidad con tests unitarios históricos. |
| **Generador de Terraform / IaC** | `backend/app/generators/terraform.py`, `backend/app/discovery/terraform_bridge.py` | **Parcial (Solo AWS/Azure/K8s)** | `terraform.py` solo generaba HCL para AWS y Azure, más manifiestos K8s. `terraform_bridge.py` solo generaba Terraform AWS (`generate_discovery_aws_terraform`). | `generate_aws_terraform_files`, `format_terraform_code`, `recommend_ec2_instance_type`. | Añadidos `generate_gcp_terraform_files` y `generate_gcp_terraform` en `terraform.py` (`google_compute_network`, `google_compute_subnetwork`, `google_compute_firewall`, `google_compute_instance`, `google_compute_image`, `google_compute_disk`, `google_sql_database_instance`, `google_redis_instance`, `google_storage_bucket`, `google_secret_manager_secret`), soporte `aws_ami` / `aws_ebs_snapshot_import`, y soporte GCP completo en `terraform_bridge.py`. |
| **Router de Migración y Orquestación** | `backend/app/api/routers/migration.py` | **Parcial (Sin máquina de estados ni Casos de Uso 1 y 2)** | `/api/migration/generate` generaba HCL en un solo paso sin persistencia de planes, sin máquina de estados, sin etapas ordenadas, sin aprobación previa al cutover, y sin flujos para migración desde código/app ni desde imágenes de VM/disco. | Endpoint `/api/migration/generate` para el lienzo interactivo. | Creado el paquete `backend/app/migration/` (`orchestrator.py`, `app_migrator.py`, `image_migrator.py`) con máquina de estados explícita (`DRAFT → DISCOVERING → ASSESSED → PLAN_READY → APPROVED → PREPARING → TESTING → READY_FOR_CUTOVER → COMPLETED` + `FAILED`, `CANCELLED`, `ROLLED_BACK`) y endpoints REST para los 3 casos de uso. |
| **Descubrimiento Osquery y Agente Local** | `backend/app/discovery/`, `cloudmove_agent/`, `cloudmove_osquery_export.py` | **Funcional** | `parser.py`, `cmir_bridge.py`, `readiness.py` y los tests de `test_discovery.py` funcionaban sólidamente con inventarios reales y exportaciones multi-OS. | Parser osquery, `SecretRedactor`, `IdentityReconciler`, `ArchitectureScanner`, `ProxmoxAPIConnector`. | Integrado con el selector `aws`/`gcp` en `/api/discovery/sessions/{id}/terraform` y reutilizado `SecretRedactor` e `IdentityReconciler` en los Casos de Uso 1 y 3. |
| **Campañas de Datacenter (Caso de Uso 3)** | `backend/app/discovery/campaigns.py`, `backend/app/api/routers/campaigns.py` | **Funcional (Parcial para Caso de Uso 3)** | Soportaba creación, preflight, escaneo SSH/osquery/Proxmox/fixtures y reconciliación de identidades, pero carecía de pausa/reanudación, reintentos por host fallido, exportación a CMIR v2.1 jerárquico de 7 niveles y planificación de migración de subgrafos con protección de recursos compartidos. | `DataCenterCampaignStore`, conectores SSH/Proxmox, `SecretRedactor`, reconciliación de activos. | Añadidos `pause_campaign`, `resume_campaign`, `retry_host_discovery`, `build_campaign_cmir` (jerarquía completa `Datacenter → Host → Hypervisor → VM → OS → Procesos/Servicios → App → Dependencias`) y `plan_campaign_workload_migration` conectado a `MigrationOrchestrator`. |
| **Frontend React / Vite** | `frontend/src/` | **Parcial** | Tenía vistas para Grafo (`App.jsx`), Osquery (`CloudMoveDiscoveryWorkspace.jsx`) y Campañas (`DataCenterCampaignWorkspace.jsx`), pero exponía Azure/K8s en selectores de migración y carecía de interfaz para Caso de Uso 1, Caso de Uso 2 y Orquestador de Migraciones por etapas. | `App.jsx`, `Sidebar.jsx`, `DataCenterCampaignWorkspace.jsx`, `CloudMoveDiscoveryWorkspace.jsx`, `MigrationPreviewModal.jsx`. | Creado `MigrationOrchestratorWorkspace.jsx` para los 3 casos de uso y control del ciclo de vida de planes; actualizados selectores en `DetailPanel.jsx`, `MigrationPanel.jsx`, `MigrationPreviewModal.jsx` y `Sidebar.jsx` para operar exclusivamente con **AWS** y **GCP**. |

---

## 2. Arquitectura Evolucionada Implementada

El flujo extremo a extremo implementado en CloudMove v2.1 sigue la secuencia:

```
ENTORNO DE ORIGEN (App Source / Imagen VM / Campaña Datacenter)
  → DESCUBRIMIENTO E INVENTARIO (Conectores + SecretRedactor)
  → RECOLECCIÓN DE EVIDENCIAS (observed / inferred / unknown + timestamp + confidence)
  → NORMALIZACIÓN CMIR v2.1 (IDs determinísticos + 23 tipos de entidad + 13 relaciones)
  → GRAFO DE ARQUITECTURA Y DEPENDENCIAS (Separación confirmadas vs inferidas + protección shared)
  → SELECCIÓN DE LA CARGA (Extracción de subgrafo + políticas auto_migrate=False en compartidos)
  → EVALUACIÓN DE COMPATIBILIDAD Y FIDELIDAD (Readiness + 5 dimensiones en imágenes VM)
  → PLAN DE MIGRACIÓN (MigrationOrchestrator: etapas ordenadas, prerrequisitos, bloqueos, rollback)
  → GENERACIÓN DE ARTEFACTOS (Terraform modular AWS/GCP, scripts de importación, manifiestos, diff report)
  → PRUEBAS EN DESTINO Y VALIDACIÓN (Simulación controlada dry-run o ejecución autorizada)
  → CUTOVER CONTROLADO (Requiere estado APPROVED y ausencia de bloqueos críticos)
```

### 2.1. Decisiones de Arquitectura (ADRs)
Se documentaron cuatro ADRs en `docs/ADR/`:
- [`ADR-001-aws-gcp-exclusive-target-providers.md`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/docs/ADR/ADR-001-aws-gcp-exclusive-target-providers.md): Alcance exclusivo AWS y GCP para todas las migraciones activas.
- [`ADR-002-extended-cmir-v2_1-and-evidence-provenance.md`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/docs/ADR/ADR-002-extended-cmir-v2_1-and-evidence-provenance.md): Modelo CMIR v2.1, trazabilidad de evidencias (`observed`, `inferred`, `unknown`) e IDs determinísticos.
- [`ADR-003-unified-migration-orchestrator-and-three-use-cases.md`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/docs/ADR/ADR-003-unified-migration-orchestrator-and-three-use-cases.md): Orquestador unificado con máquina de estados explícita y los 3 casos de uso integrados.
- [`ADR-004-vm-image-migration-fidelity-and-limitations.md`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/docs/ADR/ADR-004-vm-image-migration-fidelity-and-limitations.md): Modelo de 5 dimensiones de fidelidad en migración de imágenes de VM y separación estricta entre estado persistente en disco y estado volátil en RAM.

---

## 3. Detalle de los Tres Casos de Uso Implementados

### Caso de Uso 1: Migración Guiada desde Aplicación (`app_source`)
- **Módulo principal:** [`backend/app/migration/app_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py)
- **Capacidades:**
  - Inspecciona directorios de código fuente y manifiestos (`app_manifest.yaml`, `requirements.txt`, `package.json`, `pom.xml`, `go.mod`, `Dockerfile`, `docker-compose.yml`, `.env.example`) además de descriptores de procesos y endpoints en ejecución.
  - Detecta lenguaje, framework, runtime, comandos de arranque (`entrypoint`/`cmd`), puertos expuestos, rutas de almacenamiento y servicios externos (PostgreSQL, Redis, S3/GCS, colas).
  - **Redacción estricta de secretos:** Extrae los nombres de variables de entorno requeridas y redacta cualquier valor sensible (`[REDACTED_BY_CLOUDMOVE_SECRET_POLICY]`), generando una plantilla `.env.template` segura.
  - **Clasificación de evidencias:** Distingue dependencias confirmadas (`observed`, p. ej. servicios declarados en `docker-compose.yml` o manifiesto con endpoint verificado) de dependencias inferidas (`inferred`, p. ej. librerías `redis` o `boto3` en `requirements.txt` sin host confirmado).
  - **Opciones de destino recomendadas sin forzar refactorización:** Evalúa y propone en AWS (`EC2VM`, `ECS Fargate / App Runner`, `EKS`) y en GCP (`Compute Engine VM`, `Cloud Run`, `GKE`), recomendando la opción de menor fricción según el estado y las dependencias.
  - **Plan guiado de 12 etapas:** Desde inventario de aplicación hasta cutover controlado, incluyendo checklist de validación funcional y procedimiento de rollback.

### Caso de Uso 2: Migración de Imagen Completa de SO / VM (`vm_image`)
- **Módulo principal:** [`backend/app/migration/image_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py)
- **Capacidades:**
  - Soporta formatos `VMDK`, `VHD`, `VHDX`, `QCOW2`, `RAW`, `OVA` y `OVF`.
  - **Integridad de origen:** Calcula el hash criptográfico `SHA-256` en modo solo lectura sin modificar jamás la imagen original.
  - **Compatibilidad y conversión de formato:** Detecta cuando un formato requiere conversión (p. ej. `QCOW2` no es importable directamente por AWS VM Import/Export y requiere conversión previa en copia de staging a `RAW` o `VMDK` mediante `qemu-img convert`), verifica el modo de arranque (`BIOS` vs `UEFI`), particiones, fstab por UUID y controladores paravirtuales (`ena`/`nvme` para AWS Nitro; `virtio_scsi`/`virtio_net`/`gvnic` para GCP).
  - **Evaluación explícita de las 5 dimensiones de fidelidad:**
    1. *Fidelidad de Disco y Sistema de Archivos* (`Preservada` a nivel de bloque en el snapshot tomada la imagen).
    2. *Fidelidad de Sistema Operativo, Paquetes y Binarios* (`Preservada`, registrando en el log de auditoría cualquier inyección de drivers en la copia de staging).
    3. *Fidelidad de Identidad de Red, IP/MAC y Licencias ligadas a Hardware* (`Cambia en la nube`: MAC, UUID de placa/SMBIOS e IP pública cambian; requiere reconfiguración DNS/DHCP).
    4. *Fidelidad de Procesos en Ejecución y Estado Volátil en Memoria RAM* (`No transferible mediante imagen de disco`: ni AWS VM Import/Export ni GCP Image Import transfieren memoria RAM activa ni sockets TCP abiertos; se modela como **bloqueador explícito** si el usuario exige preservar RAM activa sin reinicio).
    5. *Fidelidad de Servicios del Sistema al Arranque* (`Preservada en unidades habilitadas en systemd/init`, sujeta a alcanzabilidad de dependencias).
  - **Artefactos generados:** Terraform modular (`aws_ami` + `aws_instance` + `aws_ebs_volume` o `google_compute_image` + `google_compute_instance` + `google_compute_disk`), script CLI de importación (`aws ec2 import-image` / `gcloud compute images import`) e **Informe Comparativo Origen vs Destino (`diff_report`)**.

### Caso de Uso 3: Descubrimiento de Datacenter Completo y Planificación de Migración (`datacenter_campaign`)
- **Módulos principales:** [`backend/app/discovery/campaigns.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/campaigns.py) y [`backend/app/migration/orchestrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/orchestrator.py)
- **Capacidades:**
  - **Gestión avanzada de campañas:** Creación de campañas multi-rango/multi-host, `preflight`, ejecución con progreso por host, **pausa (`pause`)**, **reanudación (`resume`)**, **reintento individual de hosts fallidos (`retry-host`)** y preservación de resultados parciales cuando existen equipos inalcanzables.
  - **Reconciliación de identidad determinística:** Evita duplicar activos cuando un mismo servidor o VM aparece por IP, hostname, UUID o interfaz de hipervisor.
  - **Jerarquía CMIR v2.1 completa:** Construye el grafo `DATACENTER → HOST FÍSICO → HIPERVISOR → MÁQUINA VIRTUAL → SISTEMA OPERATIVO → PROCESOS / SERVICIOS → APLICACIONES / BASES DE DATOS → DEPENDENCIAS`.
  - **Selección de cargas y protección de dependencias compartidas:** Permite seleccionar un subconjunto de activos para migrar a AWS o GCP; el motor de dependencias identifica recursos compartidos (como bases de datos o almacenamientos consumidos por otras cargas no seleccionadas) y los marca con `auto_migrate=False` y `requires_validation=True`.

---

## 4. Guía Paso a Paso para Ejecutar las Pruebas y Validar los 3 Casos de Uso

### 4.1. Ejecución de la Suite Automatizada de Pruebas (Backend)
Desde la raíz del proyecto (`/home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI`):

```bash
PYTHONPATH=backend .venv/bin/python3 -m pytest -v
```

- **Resultado verificado:** `44 passed` (incluyendo las 35 pruebas anteriores más 9 pruebas integrales E2E en [`backend/tests/test_production_completion_e2e.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/tests/test_production_completion_e2e.py) que cubren persistencia transaccional ACID SQLite WAL, control de concurrencia optimista, bloqueo exclusivo de etapa, idempotencia, descubrimiento cloud en vivo AWS/GCP con propagación honesta de errores, matriz oficial de replicación/importación MGN vs VM Import y Migrate to VMs vs Image Import, inspección binaria real con `qemu-img info` y `qemu-img convert`, detección de código Python/Node/Java/Go/Docker, protección de dependencias compartidas en campañas con hosts inalcanzables y validación sintáctica real con `/usr/bin/terraform fmt -check`).

### 4.2. Verificación de Compilación del Frontend
```bash
npm --prefix frontend run build
```
- **Resultado verificado:** Compilación limpia (`✓ 194 modules transformed`, código de salida `0`).

### 4.3. Validación Interactiva de los 3 Casos de Uso (API y UI)
Para iniciar el backend y el frontend localmente:
```bash
# Terminal 1 - Backend FastAPI (puerto 8000)
PYTHONPATH=backend .venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 - Frontend Vite (puerto 5173)
npm --prefix frontend run dev
```

En el navegador (`http://localhost:5173`), abre la vista **"Orquestador AWS/GCP"** en la barra lateral izquierda:

1. **Validar Caso de Uso 1 (`Migración desde Aplicación`):**
   - Selecciona el proveedor destino (**AWS** o **GCP**).
   - Ingresa la URL de un repositorio GitHub o la ruta local de la aplicación y pulsa **"Descubrir App y Generar Plan Guiado"**.
   - Verifica las variables de entorno con secretos redactados, la separación entre dependencias confirmadas (`observed`) e inferidas (`inferred`), las opciones de despliegue recomendadas y el código Terraform generado.
2. **Validar Caso de Uso 2 (`Migración de Imagen VM/SO`):**
   - Selecciona la pestaña **"Caso 2: Migración de Imagen VM/SO"**.
   - Usa la imagen de muestra `inventory/sample_images/debian12-erp-prod.vmdk` y su manifiesto `inventory/sample_images/debian12-erp-prod.manifest.json`.
   - Pulsa **"Inspeccionar Imagen VM y Crear Plan"** y revisa el checksum SHA-256 calculado en modo solo lectura, las **5 dimensiones de fidelidad**, el **Informe Comparativo Origen vs Destino (`diff_report`)** y los archivos Terraform + script de importación AWS/GCP.
3. **Validar Caso de Uso 3 (`Campaña Datacenter → Cloud`):**
   - Selecciona la pestaña **"Caso 3: Campaña Datacenter → Cloud"** (o la vista **"Campañas Datacenter"**).
   - Inspecciona la jerarquía CMIR v2.1 de la campaña, prueba los controles de **Pausar**, **Reanudar** y **Reintentar Host**, selecciona las cargas a migrar y genera el plan de migración verificando que los recursos compartidos quedan protegidos (`auto_migrate=False`).
4. **Validar la Máquina de Estados del Orquestador:**
   - En el panel inferior de ejecución por etapas, avanza las etapas en modo `Dry-Run`.
   - Comprueba que la etapa de `cutover` está bloqueada hasta que pulses **"Aprobar Plan (`APPROVED`)"**, y que puedes simular fallos, reintentar etapas con punto de recuperación (`recovery_point`) o ejecutar **Rollback**.

---

## 5. Qué Funciona Localmente vs. Qué Requiere Credenciales/Entorno Real, Limitaciones y Trabajo Futuro

### 5.1. Capacidades 100% Funcionales y Verificadas Localmente (Sin Credenciales Externas)
- Descubrimiento e inspección real de repositorios/manifiestos de aplicaciones locales (`Dockerfile`, `docker-compose.yml`, `requirements.txt`, `package.json`, `app_manifest.yaml`, `.env.example`) con redacción automática de secretos.
- Cálculo real de checksums `SHA-256` en modo solo lectura sobre archivos de imagen de disco, validación de formato/bootloader/controladores, evaluación de las 5 dimensiones de fidelidad e informe comparativo origen vs destino.
- Parser de inventarios reales de `osquery`, campañas de datacenter con persistencia JSON, pausa/reanudación, reintentos por host y reconciliación determinística de identidades.
- Normalización y validación de **CMIR v2.1** con migración desde esquemas anteriores (`1.0`/`2.0` → `2.1`), trazabilidad de evidencias y extracción de subgrafos con protección de dependencias compartidas.
- Máquina de estados completa del `MigrationOrchestrator` (`DRAFT` → `COMPLETED` / `FAILED` / `CANCELLED` / `ROLLED_BACK`) con simulación honesta (`completed_in_real_cloud: False` en modo `dry_run`).
- Generación de código **Terraform modular (`main.tf`, `variables.tf`, `outputs.tf`, `provider.tf`)** tanto para **AWS** como para **GCP**.

### 5.2. Capacidades que Requieren Credenciales Cloud Reales o Acceso de Red Autorizado
- **Ejecución real en AWS / GCP (`dry_run=False`):** Requiere credenciales válidas configuradas en el entorno (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` + bucket S3 de staging para `aws ec2 import-image`, o `GOOGLE_APPLICATION_CREDENTIALS` + bucket GCS para `gcloud compute images import`) y el binario `terraform` para ejecutar `terraform apply` contra la cuenta destino.
- **Descubrimiento en vivo de servidores remotos e hipervisores:** El conector SSH (`SSHDeviceConnector`) requiere conectividad TCP/22 y llaves/credenciales autorizadas hacia los hosts objetivo; el conector Proxmox (`ProxmoxAPIConnector`) requiere un endpoint HTTPS alcanzable y un API Token válido.
- **Inyección física de drivers en imágenes (`virt-v2v` / `qemu-img`):** Cuando se ejecuta en modo de remediación real sobre una copia de staging, requiere las utilidades del sistema (`qemu-img`, `libguestfs-tools`) instaladas en el host de conversión.

### 5.3. Cierre de las 3 Brechas Históricas y Requisitos de Ejecución Cloud en Vivo
1. **Persistencia transaccional ACID y concurrencia multi-operador (IMPLEMENTADO):** El almacén de migraciones, campañas, etapas, evidencias, artefactos, snapshots cloud y auditoría opera sobre [`TransactionalPersistenceDB`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py) (`SQLite WAL` / `PostgreSQL` con migraciones de esquema versionadas `1.0.0`, `2.0.0`, `2.1.0`), control de concurrencia optimista (`version` / HTTP 409), bloqueo atómico exclusivo por etapa (`acquire_stage_lock` / HTTP 409), idempotencia (`idempotency_key`), supervivencia ante reinicios del proceso y migración automática controlada desde archivos JSON legados con respaldo `.bak`.
2. **Descubrimiento directo de cuentas AWS/GCP existentes (IMPLEMENTADO):** El módulo [`cloud_live_discovery.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/cloud_live_discovery.py) implementa descubrimiento cloud en vivo mediante `boto3` (`sts`, `ec2`, `rds`, `s3`, `iam` con paginadores) y APIs REST de Google Cloud (`cloudasset.googleapis.com` / Compute / Cloud SQL / Storage / IAM con `pageToken`), backoff exponencial ante `Throttling`/`429`, propagación estricta de errores de autenticación/permisos (nunca convierte un fallo de API en inventario vacío exitoso), normalización determinística a CMIR v2.1 y reconciliación contra snapshots previos (`added`, `modified`, `removed`, `read_errors`).
3. **Migración de máquinas con matriz oficial de replicación continua vs importación de imagen (IMPLEMENTADO):** El módulo [`replication_and_import.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/replication_and_import.py) modela y ejecuta la matriz oficial de compatibilidad entre **AWS Application Migration Service (`aws_mgn`)**, **AWS VM Import/Export (`aws_vm_import`)**, **Google Cloud Migrate to Virtual Machines (`gcp_vmmigration`)** y **Google Compute Engine Image Import (`gcp_image_import`)**, junto con inspección binaria real de cabeceras de disco (`qemu-img info -U --output=json`, `KDMV`, `QFI\xfb`, GPT) y conversión física en copia de staging (`qemu-img convert`).
4. **Comprobación externa que requiere credenciales cloud reales:** La ejecución de `terraform apply`, `aws ec2 import-image`, `mgn:StartReplication` o `gcloud compute images import` contra una cuenta real de AWS o un proyecto real de GCP requiere credenciales válidas en el entorno; cuando no están presentes, CloudMove opera honestamente en modo `simulated_dry_run` (`completed_in_real_cloud = False`) y marca el estado operativo como `SIMULATED` / `PLANNED` / `VALIDATED` sin fingir jamás un despliegue real.
