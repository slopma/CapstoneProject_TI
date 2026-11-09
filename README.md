# CloudMove — Informe Técnico de Arquitectura y Funcionamiento Interno

**CloudMove** es una plataforma de ingeniería para el descubrimiento automatizado, modelado semántico intermedio (**CMIR v2.1**), validación epistémica de dependencias, síntesis determinista de Infraestructura como Código (**Terraform HCL**) y orquestación transaccional de migraciones hacia **Amazon Web Services (AWS)** y **Google Cloud Platform (GCP)**.

Este documento constituye un **informe técnico exhaustivo** sobre cómo funciona CloudMove por detrás, cómo está diseñado su motor interno de 7 capas y cómo operan paso a paso desde cero sus flujos de migración, con énfasis profundo en el **Caso de Uso 1 (Migración desde GitHub / Código Fuente)** y el **Caso de Uso 2 (Migración de Imágenes de Disco, ISO, VM y Captura de Sistema Operativo en Vivo)**.

---

## Tabla de Contenidos

1. [Visión General y los 3 Casos de Uso de CloudMove](#1-visión-general-y-los-3-casos-de-uso-de-cloudmove)
2. [¿Cómo Funciona CloudMove por Detrás? (Arquitectura Interna de 7 Capas)](#2-cómo-funciona-cloudmove-por-detrás-arquitectura-interna-de-7-capas)
   - [2.1 Capa 1: Motores de Descubrimiento Multi-Fuente](#21-capa-1-motores-de-descubrimiento-multi-fuente)
   - [2.2 Capa 2: Representación Intermedia Neutral (CMIR v2.1)](#22-capa-2-representación-intermedia-neutral-cmir-v21)
   - [2.3 Capa 3: Motor de Grafos (`networkx.DiGraph`) y Resolución Epistémica de Dependencias (BFS)](#23-capa-3-motor-de-grafos-networkxdigraph-y-resolución-epistémica-de-dependencias-bfs)
   - [2.4 Capa 4: Adaptadores de Proveedor (`AWSAdapter` y `GCPAdapter`)](#24-capa-4-adaptadores-de-proveedor-awsadapter-y-gcpadapter)
   - [2.5 Capa 5: Generador Modular de Terraform HCL y Validador en 4 Niveles](#25-capa-5-generador-modular-de-terraform-hcl-y-validador-en-4-niveles)
   - [2.6 Capa 6: Orquestador de Máquina de Estados y Persistencia Transaccional ACID (`SQLite WAL`)](#26-capa-6-orquestador-de-máquina-de-estados-y-persistencia-transaccional-acid-sqlite-wal)
   - [2.7 Capa 7: Consola de Despliegue Interactivo en la Nube Real (`CloudDeploymentRunner`)](#27-capa-7-consola-de-despliegue-interactivo-en-la-nube-real-clouddeploymentrunner)
3. [Caso de Uso 1 (`app_source`): Migración desde GitHub / Código Fuente Paso a Paso desde Cero](#3-caso-de-uso-1-app_source-migración-desde-github--código-fuente-paso-a-paso-desde-cero)
   - [3.1 Visión End-to-End del Caso 1](#31-visión-end-to-end-del-caso-1)
   - [3.2 Paso 1: Ingesta desde GitHub, Pinning de Commit SHA y Sandbox Efímero Anti-Zip-Slip](#32-paso-1-ingesta-desde-github-pinning-de-commit-sha-y-sandbox-efímero-anti-zip-slip)
   - [3.3 Paso 2: Escaneo del Árbol de Archivos, Poda de Ruido y Lectura de Manifiestos](#33-paso-2-escaneo-del-árbol-de-archivos-poda-de-ruido-y-lectura-de-manifiestos)
   - [3.4 Paso 3: Análisis Estático Profundo Multi-Componente (AST / Regex de Código)](#34-paso-3-análisis-estático-profundo-multi-componente-ast--regex-de-código)
   - [3.5 Paso 4: Inspección Forense de Backups de Bases de Datos (`PGDMP` / `.sql`) y Semillas](#35-paso-4-inspección-forense-de-backups-de-bases-de-datos-pgdmp--sql-y-semillas)
   - [3.6 Paso 5: Redacción de Secretos y Clasificación Epistémica de Dependencias](#36-paso-5-redacción-de-secretos-y-clasificación-epistémica-de-dependencias)
   - [3.7 Paso 6: ¿Cómo se Valida Qué Desplegar? Catálogo Interactivo, 6 Chequeos Pre-Flight y Viabilidad](#37-paso-6-cómo-se-valida-qué-desplegar-catálogo-interactivo-6-chequeos-pre-flight-y-viabilidad)
   - [3.8 Paso 7: Construcción del CMIR v2.1 y Síntesis Híbrida (Determinista + IA)](#38-paso-7-construcción-del-cmir-v21-y-síntesis-híbrida-determinista--ia)
   - [3.9 Paso 8: Artefactos Generados y Ciclo de Vida de Arranque en la Nube (`user_data.sh`)](#39-paso-8-artefactos-generados-y-ciclo-de-vida-de-arranque-en-la-nube-user_datash)
4. [Caso de Uso 2 (`vm_image`): Migración de Imágenes de Disco, ISO, VM y Captura de SO en Vivo Paso a Paso](#4-caso-de-uso-2-vm_image-migración-de-imágenes-de-disco-iso-vm-y-captura-de-so-en-vivo-paso-a-paso)
   - [4.1 ¿Qué Hace Funcionar al Caso 2 por Dentro?](#41-qué-hace-funcionar-al-caso-2-por-dentro)
   - [4.2 Modo A: Inspección Forense de Imágenes Binarias (`VMDK`, `QCOW2`, `VHD`, `VHDX`, `RAW`, `OVA`, `OVF`)](#42-modo-a-inspección-forense-de-imágenes-binarias-vmdk-qcow2-vhd-vhdx-raw-ova-ovf)
   - [4.3 Modo B: Sondeo y Captura en Caliente del Sistema Operativo en Vivo (`Live OS Capture`)](#43-modo-b-sondeo-y-captura-en-caliente-del-sistema-operativo-en-vivo-live-os-capture)
   - [4.4 ¿Cómo se Valida la Imagen? Bloqueadores, Remediación de Boot/Drivers y 8 Dimensiones de Fidelidad](#44-cómo-se-valida-la-imagen-bloqueadores-remediación-de-bootdrivers-y-8-dimensiones-de-fidelidad)
   - [4.5 Matriz Oficial de Estrategias: Replicación Continua (MGN / Migrate to VMs) vs Importación de Imagen](#45-matriz-oficial-de-estrategias-replicación-continua-mgn--migrate-to-vms-vs-importación-de-imagen)
   - [4.6 Catálogo Interactivo de Transformación y las 4 Salvaguardas para AWS Academy Learner Lab](#46-catálogo-interactivo-de-transformación-y-las-4-salvaguardas-para-aws-academy-learner-lab)
   - [4.7 Copia en Staging, Conversión `qemu-img convert` y Artefactos Multi-Plataforma](#47-copia-en-staging-conversión-qemu-img-convert-y-artefactos-multi-plataforma)
   - [4.8 Rehidratación Autónoma Cloud-Init y Portal Web de Telemetría en Vivo](#48-rehidratación-autónoma-cloud-init-y-portal-web-de-telemetría-en-vivo)
5. [Caso de Uso 3 (`datacenter_campaign`): Descubrimiento Masivo y Migración Selectiva de Subgrafos](#5-caso-de-uso-3-datacenter_campaign-descubrimiento-masivo-y-migración-selectiva-de-subgrafos)
6. [Estructura del Repositorio y Guía de Ejecución Rápida](#6-estructura-del-repositorio-y-guía-de-ejecución-rápida)

---

## 1. Visión General y los 3 Casos de Uso de CloudMove

Las herramientas tradicionales de migración a la nube suelen fallar en dos extremos:
1. **Re-arquitectura forzada**: intentan empaquetar aplicaciones monolíticas, con estado local o librerías científicas pesadas (`PostGIS`, `geopandas`, `scikit-learn`) dentro de funciones serverless con límites estrictos de tamaño y tiempo, rompiendo la aplicación original.
2. **Traducción ciega sin validación epistémica**: convierten inventarios en plantillas estáticas sin distinguir entre **dependencias observadas** (`observed`), **inferidas heurísticamente** (`inferred`) o **externas desconocidas** (`unknown`), y sin verificar si un recurso compartido (`is_shared=True`) está siendo utilizado por otros sistemas que no se van a migrar.

**CloudMove** resuelve este problema unificando tres escenarios de migración bajo un mismo motor semántico (**CMIR v2.1**) y un único orquestador de ciclo de vida (**`MigrationOrchestrator`**), apuntando exclusivamente a **AWS** y **GCP** (según [`ADR-001`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/docs/ADR/ADR-001-cloud-providers-scope.md) y [`ADR-003`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/docs/ADR/ADR-003-unified-migration-orchestrator-and-three-use-cases.md)):

| Caso de Uso | Identificador Interno | Entrada Principal | Motor Principal | Qué Produce y Despliega |
| :--- | :--- | :--- | :--- | :--- |
| **Caso 1: Aplicación desde Código Fuente / GitHub** | `app_source` | URL de GitHub (`https://github.com/org/repo`), rama/tag/SHA, directorio local o manifiestos | [`app_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py), [`github_connector.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/github_connector.py), [`ai_translator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/ai_translator.py) | VPC Multi-AZ, Security Groups/Firewalls, EC2/GCE o ALB+ASG, contenedores Docker Compose, hidratación automática de backups PostgreSQL/PostGIS (`.dump`/`.sql`), reescritura dinámica de `VITE_API_URL` vía IMDSv2 y smoke tests. |
| **Caso 2: Imagen de Disco, ISO, VM o Captura de SO en Vivo** | `vm_image` | Archivo binario de disco (`VMDK`, `QCOW2`, `VHD`, `VHDX`, `RAW`, `OVA`, `OVF`) o captura en caliente del SO físico/VM en ejecución | [`image_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py), [`replication_and_import.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/replication_and_import.py) | Copia verificada por SHA-256 en staging, conversión `qemu-img convert`, remediación de drivers (`ena`/`nvme`/`virtio`) y `/etc/fstab`, importación nativa (`ec2:ImportImage` / `MGN` / `GCP Image Import`), o rehidratación autónoma Cloud-Init con portal web de telemetría en vivo + lanzadores para VirtualBox y VMware. |
| **Caso 3: Campaña de Data Center y Subgrafos** | `datacenter_campaign` | Telemetría de agentes [`osquery`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/osquery_parser.py), snapshots cloud reales (`boto3` / GCP SDK) y campañas multi-sitio | [`campaigns.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/campaigns.py), [`resolver.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/dependencies/resolver.py), [`cloud_connector.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/cloud_connector.py) | Reconciliación de identidad canónica entre múltiples fuentes, cálculo de clausura transitiva de dependencias con BFS, aislamiento de recursos compartidos (`is_shared=True`) y migración por oleadas (*waves*). |

---

## 2. ¿Cómo Funciona CloudMove por Detrás? (Arquitectura Interna de 7 Capas)

El backend de CloudMove (construido en **Python 3.11+ / FastAPI**) está estructurado como un pipeline determinista de **7 capas desacopladas**. Ningún conector de descubrimiento genera código Terraform directamente: toda fuente de entrada debe primero convertirse en un grafo **CMIR v2.1**, pasar por el motor de resolución epistémica de dependencias, traducirse mediante un adaptador de proveedor y superar 4 niveles de validación estructural antes de poder ejecutarse.

```mermaid
flowchart TB
    subgraph L1["Capa 1: Motores de Descubrimiento Multi-Fuente"]
        GH["GitHub / Source Scanner<br/>(github_connector.py + app_migrator.py)"]
        VMI["Forense Binario & Captura SO en Vivo<br/>(image_migrator.py + qemu-img + lsblk)"]
        DC["Campañas Data Center & Agentes osquery<br/>(campaigns.py + osquery_parser.py + cloud_connector.py)"]
    end

    subgraph L2["Capa 2: Representación Intermedia Neutral (CMIR v2.1)"]
        CMIR["Grafo Semántico CMIR v2.1<br/>(cmir/models.py + cmir/builder.py)<br/>Jerarquía Niveles 0..8 + Evidencia Epistémica"]
    end

    subgraph L3["Capa 3: Motor de Grafos y Resolución de Dependencias"]
        NX["Grafo Dirigido networkx.DiGraph<br/>(graph/builder.py)"]
        BFS["Resolución BFS Directa y Transitiva<br/>(dependencies/resolver.py)<br/>Separa: Confirmadas vs Inferidas vs Desconocidas + Recursos Compartidos"]
    end

    subgraph L4["Capa 4: Adaptadores de Proveedor Cloud"]
        AWS["AWSAdapter (adapters/aws_adapter.py)<br/>VPC, Subnet, SG, EC2, ALB/ASG, EBS, RDS, S3"]
        GCP["GCPAdapter (adapters/gcp_adapter.py)<br/>Compute Network, Firewall, GCE, Disks, Cloud SQL, GCS"]
    end

    subgraph L5["Capa 5: Síntesis Modular HCL y Validación en 4 Niveles"]
        TFGEN["TerraformGenerator + AI/Deterministic Synthesizer<br/>(generators/terraform.py + ai_translator.py)<br/>provider.tf | variables.tf | main.tf | outputs.tf | user_data.sh"]
        VAL["Validador de 4 Compuertas (adapters/base.py)<br/>1. Balanceo {} | 2. Anti-Secretos | 3. Referencias var/resource | 4. terraform fmt"]
    end

    subgraph L6["Capa 6: Orquestación y Persistencia ACID"]
        ORCH["MigrationOrchestrator (migration/orchestrator.py)<br/>Máquina de 12 Estados + Compuerta Humana APPROVED"]
        DB[("SQLite WAL Transaccional<br/>(persistence/transactional_db.py)<br/>Optimistic Locking + Stage Locks + Idempotency Keys")]
    end

    subgraph L7["Capa 7: Ejecución Interactiva en la Nube Real"]
        DEPLOY["CloudDeploymentRunner (migration/cloud_deployer.py)<br/>Streaming terraform init / plan / apply / destroy + Lectura en Vivo de terraform.tfstate"]
    end

    GH --> CMIR
    VMI --> CMIR
    DC --> CMIR
    CMIR --> NX --> BFS
    BFS --> AWS & GCP
    AWS & GCP --> TFGEN --> VAL
    VAL --> ORCH
    ORCH <--> DB
    ORCH --> DEPLOY
```

---

### 2.1 Capa 1: Motores de Descubrimiento Multi-Fuente

Cada fuente de entrada cuenta con un analizador especializado que opera **estrictamente en modo de solo lectura** sobre el entorno origen:
- **Código Fuente y Repositorios GitHub** ([`backend/app/migration/github_connector.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/github_connector.py) y [`backend/app/migration/app_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py)): Fija el commit SHA exacto vía la API REST de GitHub, descarga el tarball en un directorio temporal aislado contra ataques *Zip-Slip*, inspecciona el AST/código estático de Python/JS/TS, analiza servicios en `docker-compose.yml` y decompila backups binarios de PostgreSQL (`PGDMP`).
- **Imágenes de Disco y Sistemas Operativos en Vivo** ([`backend/app/migration/image_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py)): Lee las cabeceras binarias mágicas (`KDMV`, `QFI\xfb`, `conectix`, `vhdxfile`, `0x55AA`, `EFI PART`, `ustar`), invoca `qemu-img info -U --output=json` y, cuando opera en modo de captura en vivo, sondea los dispositivos de bloque reales con `lsblk -J -b`, `os.statvfs()`, `/etc/os-release`, `ip -j addr`, `ss -tulpn`, `dpkg-query` y `ps`.
- **Telemetría de Agentes `osquery` y Cuentas Cloud** ([`backend/app/discovery/osquery_parser.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/osquery_parser.py), [`backend/app/discovery/campaigns.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/campaigns.py) y [`backend/app/discovery/cloud_connector.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/cloud_connector.py)): Normaliza snapshots de agentes instalados en servidores on-premise y reconcilia activos repetidos mediante llaves de identidad canónica (`canonical_identity_key`).

---

### 2.2 Capa 2: Representación Intermedia Neutral (CMIR v2.1)

Definida en [`backend/app/cmir/models.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/models.py) y construida mediante [`CMIRBuilder`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/builder.py), la **CloudMove Intermediate Representation (`CMIR v2.1`)** desacopla completamente el descubrimiento del proveedor cloud de destino.

Un documento [`CMIRGraph`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/models.py#L221-L263) contiene:
1. **Nodos (`CMIRNode`)**: Representan cualquier activo de infraestructura o aplicación, organizados en una **jerarquía estricta de 9 niveles (`0` a `8`)** definida en [`TYPE_LEVEL_MAP`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/models.py#L101-L132):
   - **Nivel 0 (`ORGANIZATION`)**: Organización o tenant raíz.
   - **Nivel 1 (`ENVIRONMENT`)**: Entorno (`production`, `staging`, `datacenter-bogota`).
   - **Nivel 2 (`SITE` / `NETWORK_ZONE`)**: Sitio físico o VPC/VNet (`network`, `vpc`).
   - **Nivel 3 (`SUBNET` / `CLUSTER` / `HYPERVISOR` / `FIREWALL`)**: Subredes, grupos de seguridad (`security_group`), hipervisores (`vmware_esxi`, `kvm`).
   - **Nivel 4 (`COMPUTE` / `LOAD_BALANCER`)**: Servidores físicos (`physical_server`), máquinas virtuales (`virtual_machine`, `compute`), balanceadores (`load_balancer`).
   - **Nivel 5 (`STORAGE` / `VOLUME`)**: Discos de bloque (`storage_volume`, `ebs`), buckets (`object_storage`), archivos de imagen (`disk_image`).
   - **Nivel 6 (`SERVICE` / `RUNTIME` / `CONTAINER`)**: Servicios de aplicación (`application_service`), contenedores (`container_service`), colas (`queue`).
   - **Nivel 7 (`DATABASE` / `DATASTORE`)**: Motores e instancias de bases de datos (`database`, `database_instance`, `cache`).
   - **Nivel 8 (`SCHEMA` / `PORT` / `CONFIG` / `IDENTITY`)**: Tablas, esquemas, puertos expuestos, configuraciones `.env` redactadas y roles IAM (`iam_role`).
2. **Evidencia Epistémica (`CMIREvidence`)**: Cada nodo y cada relación lleva adjunto un bloque [`CMIREvidence`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/models.py#L140-L154) con:
   - `evidence_type`:
     - `observed`: Confirmado directamente en manifiestos, cabeceras binarias, sockets de red activos o tablas del sistema operativo (confianza `0.95 – 1.0`).
     - `derived`: Calculado determinísticamente a partir de datos observados (ej. una subred deducida de la IP/máscara de una interfaz, confianza `0.85 – 0.95`).
     - `inferred`: Deducido heurísticamente (ej. presencia de `redis` en `requirements.txt` sin variable de conexión confirmada, confianza `0.50 – 0.75`).
     - `unknown`: Dependencia hacia un servicio externo cuya topología interna no es visible desde la fuente (ej. un webhook de pagos o API de terceros, confianza `<= 0.50`).
3. **Relaciones Tipadas (`CMIRRelationship`)**: Aristas dirigidas (`contains`, `depends_on`, `connects_to`, `reads_from`, `writes_to`, `mounted_on`, `exposed_by`, `authenticates_with`, `backed_by`) que conectan los nodos manteniendo su `evidence` y `confidence`.

---

### 2.3 Capa 3: Motor de Grafos (`networkx.DiGraph`) y Resolución Epistémica de Dependencias (BFS)

Una vez construido el `CMIRGraph`, CloudMove lo carga en memoria como un grafo dirigido de `networkx` mediante [`InfrastructureGraphBuilder`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/graph/builder.py) y ejecuta el motor [`DependencyResolver`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/dependencies/resolver.py).

Cuando el usuario selecciona un conjunto de nodos para migrar (o la aplicación completa), [`DependencyResolver.resolve_dependencies()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/dependencies/resolver.py#L51-L195) ejecuta **4 algoritmos en secuencia**:

1. **Expansión Jerárquica Descendente (`_expand_hierarchical_descendants`)**:
   Si el operador selecciona un nodo padre (por ejemplo, un servidor de Nivel 4 o una VPC de Nivel 2), el motor recorre las aristas `contains` hacia niveles inferiores (`target_level > source_level`) para incluir automáticamente sus volúmenes de disco, contenedores e instancias de base de datos alojadas localmente.
2. **Búsqueda en Anchura (BFS) con Separación Epistémica**:
   Recorre todas las aristas salientes y entrantes de dependencia (`depends_on`, `connects_to`, `mounted_on`, `backed_by`, etc.), pero **jamás mezcla hechos confirmados con suposiciones**:
   - Si una relación tiene `evidence_type == "unknown"`, el nodo destino se desvía a la lista `unknown_dependencies` y se genera una alerta de revisión manual.
   - Si una relación o nodo tiene `evidence_type == "inferred"` o `confidence < 0.75`, se clasifica en `inferred_dependencies` y **no se aprovisiona silenciosamente** sin validación del operador.
   - Solo las relaciones `observed` o `derived` con confianza suficiente avanzan como `direct_dependencies` (a 1 salto del nodo seleccionado) o `transitive_dependencies` (a $\ge 2$ saltos en el BFS).
3. **Detección y Protección de Recursos Compartidos (`is_shared`)**:
   Si un recurso requerido (por ejemplo, un cluster PostgreSQL central o un bus RabbitMQ) tiene `is_shared=True` —o el grafo detecta que otros nodos **fuera** de la selección actual también tienen aristas hacia él—, el motor lo marca en `shared_resources` con:
   ```python
   "auto_migrate": False,
   "requires_validation": True
   ```
   Esto impide que la migración de un servicio apague o mueva una base de datos compartida de la que todavía dependen otros sistemas en producción.

---

### 2.4 Capa 4: Adaptadores de Proveedor (`AWSAdapter` y `GCPAdapter`)

El subgrafo validado se entrega al adaptador correspondiente heredado de [`BaseProviderAdapter`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/base.py):
- **[`AWSAdapter`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/aws_adapter.py)**: Traduce los nodos CMIR a recursos nativos del proveedor `hashicorp/aws` (`~> 5.0`):
  - `network` $\rightarrow$ `aws_vpc` + `aws_internet_gateway` + `aws_route_table`
  - `subnet` $\rightarrow$ `aws_subnet` + `aws_route_table_association`
  - `security_group` / `firewall` $\rightarrow$ `aws_security_group`
  - `compute` / `virtual_machine` $\rightarrow$ `aws_instance` (o `aws_launch_template` + `aws_autoscaling_group`)
  - `load_balancer` $\rightarrow$ `aws_lb` + `aws_lb_target_group` + `aws_lb_listener`
  - `storage_volume` $\rightarrow$ `aws_ebs_volume` + `aws_volume_attachment`
  - `object_storage` $\rightarrow$ `aws_s3_bucket`
  - `database` / `database_instance` $\rightarrow$ `aws_db_instance` + `aws_db_subnet_group`
- **[`GCPAdapter`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/gcp_adapter.py)**: Traduce los mismos nodos CMIR a recursos nativos de `hashicorp/google` (`~> 5.0`):
  - `network` $\rightarrow$ `google_compute_network` (`auto_create_subnetworks = false`)
  - `subnet` $\rightarrow$ `google_compute_subnetwork`
  - `security_group` / `firewall` $\rightarrow$ `google_compute_firewall`
  - `compute` / `virtual_machine` $\rightarrow$ `google_compute_instance`
  - `storage_volume` $\rightarrow$ `google_compute_disk` + `google_compute_attached_disk`
  - `object_storage` $\rightarrow$ `google_storage_bucket`
  - `database` / `database_instance` $\rightarrow$ `google_sql_database_instance` + `google_sql_user`

Ambos adaptadores normalizan todos los nombres mediante [`sanitize_id()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/base.py#L46-L55) (`snake_case` válido para identificadores internos de Terraform) y [`sanitize_name()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/base.py#L57-L66) (`kebab-case` de máximo 60 caracteres para nombres en las APIs de AWS y GCP), e infieren recursos de red implícitos si el usuario seleccionó un servidor huérfano sin VPC asociada.

---

### 2.5 Capa 5: Generador Modular de Terraform HCL y Validador en 4 Niveles

El módulo [`TerraformGenerator`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/terraform.py) y el sintetizador híbrido [`ai_translator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/ai_translator.py) nunca generan un archivo monolítico desordenado; producen siempre una estructura modular de **4 archivos HCL** más scripts operativos:
1. **`provider.tf`**: Bloque `terraform { required_version = ">= 1.5.0" ... }` y configuración del `provider "aws"` o `provider "google"`.
2. **`variables.tf`**: Variables parametrizadas (`aws_region`, `gcp_project_id`, `environment`, `instance_type`, `db_password` con `sensitive = true`, `github_token`, `enable_vm_import`).
3. **`main.tf`**: Topología completa de red, seguridad, cómputo, almacenamiento, bases de datos y cloud-init (`user_data_base64 = base64gzip(file("${path.module}/user_data.sh"))`).
4. **`outputs.tf`**: Salidas listas para consumo automatizado (`public_ip`, `application_url`, `frontend_url`, `backend_api_url`, `ssh_command`, `rds_endpoint`, `migration_summary`).

Antes de dar por bueno el código generado, [`BaseProviderAdapter.validate_artifacts()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/base.py#L140-L246) ejecuta **4 niveles de validación**:
- **Nivel 1 — Balanceo Sintáctico de Bloques HCL**: Verifica que todas las llaves `{` y `}` estén exactamente balanceadas en cada archivo `.tf` y que existan los bloques obligatorios `terraform` y `provider`.
- **Nivel 2 — Escaneo Anti-Fuga de Secretos (`Secret Leak Guard`)**: Inspecciona línea por línea que no se hayan filtrado llaves `AKIA[0-9A-Z]{16}`, bloques `BEGIN RSA PRIVATE KEY` ni contraseñas en texto plano en `db_password` o `password`.
- **Nivel 3 — Integridad de Referencias Cruzadas (`var.*` y `resource.*`)**: Extrae todas las declaraciones `variable "X"` en `variables.tf` y `resource "tipo" "nombre"` en `main.tf`, y comprueba que toda referencia `var.X` o `aws_vpc.main.id` apunte a un símbolo realmente declarado.
- **Nivel 4 — Formateo Canónico con el Binario Oficial de Terraform**: Si `/usr/bin/terraform` está presente en el host, ejecuta `terraform fmt -check` / `terraform fmt` sobre el directorio de artefactos para garantizar estilo HCL canónico.

---

### 2.6 Capa 6: Orquestador de Máquina de Estados y Persistencia Transaccional ACID (`SQLite WAL`)

Todo plan de migración es gobernado por [`MigrationOrchestrator`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/orchestrator.py) y persistido en [`TransactionalDatabase`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py) (`backend/data/cloudmove_transactional.db`).

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> DISCOVERING: discover()
    DISCOVERING --> ASSESSED: Discovery & CMIR v2.1 listos
    ASSESSED --> PLAN_READY: generate_plan() (Terraform validado)
    PLAN_READY --> APPROVED: approve_plan() [Compuerta Humana Obligatoria]
    APPROVED --> PREPARING: execute_stage(prepare_target)
    PREPARING --> TESTING: execute_stage(replicate_or_deploy / smoke_test)
    TESTING --> READY_FOR_CUTOVER: Tests superados
    READY_FOR_CUTOVER --> COMPLETED: execute_stage(cutover)
    
    DISCOVERING --> FAILED
    ASSESSED --> FAILED
    PLAN_READY --> FAILED
    APPROVED --> FAILED
    PREPARING --> FAILED
    TESTING --> FAILED
    READY_FOR_CUTOVER --> FAILED
    
    FAILED --> PLAN_READY: Reintento idempotente desde recovery_point
    PREPARING --> ROLLED_BACK: rollback()
    TESTING --> ROLLED_BACK: rollback()
    READY_FOR_CUTOVER --> ROLLED_BACK: rollback()
    ROLLED_BACK --> PLAN_READY
```

**Garantías de Ingeniería del Orquestador**:
- **Compuerta de Aprobación Humana Obligatoria (`APPROVED`)**: Ninguna etapa de ejecución (`PREPARING`, `TESTING`, `READY_FOR_CUTOVER`) puede invocarse si un operador no ha firmado primero la transición `PLAN_READY -> APPROVED`.
- **Preservación Absoluta del Entorno Origen (`source_environment_destroyed = False`)**: Tanto durante la migración como en caso de `rollback()`, CloudMove jamás borra, modifica ni apaga las máquinas, discos o repositorios de origen. Un rollback limpia únicamente los recursos transitorios en la nube de destino y conserva el origen intacto.
- **Transacciones ACID y Concurrencia Optimista**: La base de datos SQLite opera con `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON` y transacciones `BEGIN IMMEDIATE`. Cada registro posee una columna `version`; si dos operadores intentan modificar el mismo plan simultáneamente, se lanza [`ConcurrencyConflictError`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py#L51-L52).
- **Bloqueos Exclusivos de Etapa (`StageLockedError`) e Idempotencia (`idempotency_key`)**: Antes de ejecutar una etapa, el orquestador adquiere un candado atómico (`locked_by`, `locked_at`) en la tabla `migration_stages` y registra la ejecución en `stage_executions` con `UNIQUE(migration_id, stage_id, idempotency_key)` para que reintentos de red devuelvan el resultado previo sin duplicar infraestructura.

---

### 2.7 Capa 7: Consola de Despliegue Interactivo en la Nube Real (`CloudDeploymentRunner`)

Implementado en [`backend/app/migration/cloud_deployer.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/cloud_deployer.py), este motor permite al usuario desplegar los artefactos generados directamente desde la interfaz web de CloudMove hacia su cuenta real de AWS o GCP:
- Ejecuta subprocesos reales de `/usr/bin/terraform` (`init`, `validate`, `plan`, `apply -auto-approve`, `refresh`, `destroy -auto-approve`, `force-unlock`) capturando `stdout`/`stderr` línea por línea en tiempo real mediante hilos lectores asíncronos.
- **Auto-reparación de RDS huérfanos (`_auto_import_orphaned_rds`)**: Si un `terraform apply` previo fue interrumpido mientras AWS creaba una instancia RDS lenta (10 min) y el reintento arroja `DBInstanceAlreadyExists`, CloudMove intercepta el error, ejecuta automáticamente `terraform import aws_db_instance.<addr> <db_id>` y reanuda el `apply` sin intervención manual.
- **Diagnóstico Inteligente de AWS Academy Learner Lab**: Detecta errores de sesión expirada (`InvalidClientTokenId`, `ExpiredToken`) o revocación de credenciales por creación no permitida de llaves IAM (`voc-cancel-cred`), mostrando instrucciones exactas de remediación.
- **Inspección en Vivo de `terraform.tfstate` (`inspect_tfstate`)**: Lee el archivo de estado real de Terraform para extraer todas las instancias, discos, IPs públicas, DNS de balanceadores, endpoints de bases de datos y construir las URLs clicables (`http://<IP>:3000`, `http://<IP>:8000/docs`, comando `ssh`) en el panel del usuario.

---

## 3. Caso de Uso 1 (`app_source`): Migración desde GitHub / Código Fuente Paso a Paso desde Cero

Esta sección explica con precisión quirúrgica cómo funciona el **Caso de Uso 1** desde el instante en que el usuario introduce una URL de GitHub (o ruta de código fuente) hasta que la aplicación queda ejecutándose en AWS o GCP con su frontend, su backend API y su base de datos restaurada.

### 3.1 Visión End-to-End del Caso 1

```mermaid
sequenceDiagram
    autonumber
    actor User as Operador / Usuario
    participant API as FastAPI (/api/v1/migrations/app/inspect)
    participant GH as GitHubConnector (github_connector.py)
    participant AM as AppMigrator (app_migrator.py)
    participant CAT as Catálogo de Transformación & Viabilidad
    participant CMIR as CMIR v2.1 + Adapters (AWS/GCP)
    participant AI as AI/Container Synthesizer (ai_translator.py)
    participant CLOUD as CloudDeploymentRunner (Terraform Live)

    User->>API: Ingresa URL de GitHub + Ref (main) + Proveedor (AWS/GCP)
    API->>GH: parse_github_url() & fetch_and_analyze_github_repository()
    GH->>GH: Consulta API GitHub (/commits/main) -> Fija Commit SHA (40 hex)
    GH->>GH: Descarga Tarball en Sandbox temporal (mkdtemp) con filtro Anti-Zip-Slip
    GH->>AM: Entrega árbol de archivos en modo estático (CERO ejecución de código)
    AM->>AM: 1. scan_local_filesystem_tree() (Lenguajes, bytes, manifiestos)
    AM->>AM: 2. discover_app_components_and_code() (Tiers Docker Compose, Rutas FastAPI, Fetch JS, Supabase)
    AM->>AM: 3. discover_database_backups_and_seeds() (Decompila PGDMP .dump / .sql, PostGIS, tablas y filas)
    AM->>AM: 4. Redacta secretos (.env) y clasifica dependencias (observed / inferred / unknown)
    AM->>CAT: build_github_to_cloud_transformation_catalog() + evaluate_app_migration_viability()
    CAT-->>User: Presenta Topología + 6 Chequeos Pre-Flight + Opciones Interactivas de Transformación
    User->>API: Confirma decisiones (user_decisions) y solicita Generar Plan
    API->>CMIR: build_application_cmir() -> DependencyResolver (BFS) -> AWSAdapter / GCPAdapter
    CMIR->>AI: generate_app_migration_artifacts() (main.tf, user_data.sh, docker-compose, migrate_database_data.sh)
    AI-->>User: Artefactos validados en 4 niveles listos para revisión (PLAN_READY)
    User->>CLOUD: Aprueba Plan (APPROVED) y ejecuta Despliegue en Vivo (terraform init -> plan -> apply)
    CLOUD-->>User: Infraestructura activa + DB restaurada + URLs en vivo (:3000, :8000, /health)
```

---

### 3.2 Paso 1: Ingesta desde GitHub, Pinning de Commit SHA y Sandbox Efímero Anti-Zip-Slip

Todo comienza en [`backend/app/migration/github_connector.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/github_connector.py):

1. **Validación y Normalización de URL (`parse_github_url`)**:
   Valida la URL mediante la expresión regular [`GITHUB_URL_REGEX`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/github_connector.py#L22-L24), soportando tanto `https://github.com/<owner>/<repo>` como `git@github.com:<owner>/<repo>.git` e incluso subrutas `/tree/<branch>/<subpath>`.
2. **Pinning Determinista del Commit SHA**:
   En lugar de clonar a ciegas una rama móvil, [`fetch_and_analyze_github_repository()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/github_connector.py#L64-L162) realiza una petición autenticada (si se provee `github_token`) a:
   ```http
   GET https://api.github.com/repos/{owner}/{repo}/commits/{resolved_ref}
   ```
   De allí extrae el **SHA inmutable de 40 caracteres hexadecimales** (`commit_sha`), el mensaje del commit, el autor y la fecha exacta. Esto garantiza que toda la auditoría y el despliegue en la nube apunten exactamente a la misma versión del código.
3. **Descarga en Sandbox Efímero con Protección Anti-Zip-Slip**:
   - Crea un directorio temporal aislado con `tempfile.mkdtemp(prefix="cloudmove_gh_")`.
   - Descarga el tarball oficial de ese commit (`https://api.github.com/repos/{owner}/{repo}/tarball/{commit_sha}`).
   - Antes de extraer cada archivo del `.tar.gz`, verifica miembro por miembro:
     ```python
     member_path = Path(member.name)
     if member_path.is_absolute() or ".." in member_path.parts:
         continue  # Bloqueo estricto contra ataques Zip-Slip / Path Traversal
     ```
   - **Seguridad de Análisis Estático (`static_analysis_only = True`)**: CloudMove **nunca ejecuta** `pip install`, `npm install`, hooks de pre-build ni código arbitrario del repositorio durante el descubrimiento. Al finalizar la lectura estática, el bloque `finally: shutil.rmtree(temp_dir, ignore_errors=True)` destruye por completo el directorio temporal.

---

### 3.3 Paso 2: Escaneo del Árbol de Archivos, Poda de Ruido y Lectura de Manifiestos

Con el código extraído en el sandbox temporal, [`scan_local_filesystem_tree()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L214-L320) en [`app_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py) recorre la estructura del proyecto:

1. **Poda de Directorios Ruidosos (`PRUNED_DIRS`)**:
   Ignora automáticamente `.git`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.pytest_cache`, `dist`, `build`, `.next` y `.terraform` para no distorsionar las métricas ni desperdiciar memoria.
2. **Desglose Cuantitativo de Lenguajes (`LANGUAGE_EXTENSIONS`)**:
   Contabiliza el número exacto de archivos y bytes por extensión (`.py` $\rightarrow$ Python, `.ts`/`.tsx` $\rightarrow$ TypeScript, `.js`/`.jsx` $\rightarrow$ JavaScript, `.java` $\rightarrow$ Java, `.go` $\rightarrow$ Go, `.rs` $\rightarrow$ Rust, `.sql` $\rightarrow$ SQL) y calcula el porcentaje exacto de cada lenguaje en el repositorio.
3. **Extracción Segura de Manifiestos (`MANIFEST_NAMES`)**:
   Lee en memoria (solo si pesan $\le 1\text{ MB}$) los archivos clave de arquitectura:
   - `package.json`, `requirements.txt`, `pyproject.toml`, `Pipfile`, `pom.xml`, `go.mod`
   - `Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`, `compose.yml`, `Procfile`
   - `.env`, `.env.example`, `.env.sample`, `.env.template`, `alembic.ini`, `nginx.conf`
   Además, escanea hasta un nivel de subdirectorios (`backend/Dockerfile`, `frontend-vite/package.json`, etc.) para capturar arquitecturas **monorepo multi-componente**.

---

### 3.4 Paso 3: Análisis Estático Profundo Multi-Componente (AST / Regex de Código)

A continuación, [`discover_app_components_and_code()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L761-L1084) realiza una radiografía completa de la arquitectura interna de la aplicación:

1. **Descubrimiento de Tiers y Servicios (`components`)**:
   - Si existe un archivo `docker-compose*.yml`, parsea cada bloque bajo `services:` extrayendo `build.context`, `dockerfile`, `ports` (`host_port:container_port`), `environment`, `env_file`, `depends_on` y `command`.
   - Clasifica automáticamente cada servicio según su rol arquitectónico (`tier`):
     - `frontend`: si usa `vite`, `react`, `nginx`, `next` o expone los puertos `3000` / `5173` / `80`.
     - `database`: si usa imágenes `postgres`, `postgis`, `mysql`, `redis`, `mongo`.
     - `backend`: servicios de API en Python (`FastAPI`, `Flask`, `Django`), Node (`Express`, `NestJS`), Go o Java.
   - Si el repositorio no tiene `docker-compose.yml`, detecta subdirectorios independientes que contengan su propio `Dockerfile`, `requirements.txt` o `package.json`.
2. **Inspección Profunda de Código Backend (`.py`)**:
   Recorre hasta 120 archivos `.py` buscando patrones reales en el código fuente:
   - **Endpoints REST y Routers**: Extrae decoradores `@app.get("/ruta")`, `@router.post("/ruta")` y prefijos `APIRouter(prefix="/api/v1")` para construir el catálogo real de endpoints HTTP de la aplicación (`api_routes`).
   - **Healthcheck real**: Identifica si el código define `/health`, `/healthz`, `/api/health` o `/ping` para configurar el Health Check del Application Load Balancer (`aws_lb_target_group`) y los smoke tests sin adivinar rutas inexistentes.
   - **Clientes de Bases de Datos y BaaS**: Detecta llamadas a `create_client(...)` del SDK de `supabase`, `create_engine(...)` de SQLAlchemy y esquemas de migración en `alembic.ini`.
3. **Inspección Profunda de Código Frontend (`.ts`, `.tsx`, `.js`, `.jsx`)**:
   - Extrae las llamadas HTTP salientes (`fetch(`${API_URL}/...`)` o `axios.get(...)`).
   - Detecta variables de entorno inyectadas en tiempo de compilación (`import.meta.env.VITE_API_URL`, `process.env.NEXT_PUBLIC_API_URL`, `REACT_APP_API_URL`).
   - Verifica si el frontend se conecta directamente a Supabase (`@supabase/supabase-js`) o si consume exclusivamente el backend propio.
4. **Mapeo de Enlaces Internos entre Servicios (`internal_service_links`)**:
   Cuando detecta que el componente `frontend` utiliza `VITE_API_URL` apuntando al puerto del componente `backend` (ej. `:8000`), crea un enlace formal `HTTP / REST API (VITE_API_URL)` entre ambos componentes. Este hallazgo es crucial porque en la nube el navegador del usuario final no puede conectarse a `http://localhost:8000`, sino a la IP pública o dominio asignado por AWS/GCP.

---

### 3.5 Paso 4: Inspección Forense de Backups de Bases de Datos (`PGDMP` / `.sql`) y Semillas

Uno de los diferenciadores más potentes del Caso 1 es [`discover_database_backups_and_seeds()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L519-L758). Si el repositorio incluye un volcado de base de datos (por ejemplo, `supabase_backup.dump`, `backup.sql`, `init.sql`) o archivos de datos geoespaciales/semilla (`.geojson`, `.json`), CloudMove **los abre y analiza por dentro**:

1. **Decompilación de Archivos Binarios `PGDMP` (`_extract_sql_from_pgdmp`)**:
   - Lee los primeros 5 bytes del archivo `.dump` o `.backup`. Si coinciden con la firma mágica binaria `b"PGDMP"` (formato *custom* de `pg_dump -Fc`), CloudMove ejecuta `/usr/bin/pg_restore -f - <archivo.dump>` para volcar en memoria todo el DDL (`CREATE TABLE`, `CREATE EXTENSION`, `CREATE FUNCTION`) y los bloques de datos (`COPY ... FROM stdin`).
   - Si `pg_restore` no estuviera instalado, cuenta con un **descompresor de respaldo en Python puro** que localiza flujos comprimidos `zlib` (`0x78 0x9c`, `0x78 0x01`, `0x78 0xda`) dentro del binario `PGDMP`, los descomprime con `zlib.decompress()` y reconstruye el catálogo de tablas y datos.
2. **Parseo Estructural del Volcado SQL (`_parse_sql_dump_text`)**:
   Analiza el contenido extraído del dump y determina con exactitud:
   - **Versión del servidor origen**: ej. `Dumped from database version 17.6 (Postgres / Supabase)`.
   - **Esquemas (`schemas`)**: distingue esquemas de aplicación (`public`) de esquemas internos de Supabase (`auth`, `storage`, `realtime`, `extensions`, `vault`).
   - **Extensiones Nativas Requeridas (`extensions`)**: detecta `CREATE EXTENSION IF NOT EXISTS postgis`, `pgcrypto`, `uuid-ossp`, `pg_stat_statements`, etc. Si detecta `postgis` o tipos de columna `geometry(Point, 4326)` / `geography`, marca automáticamente `requires_postgis = True` para que el contenedor o instancia RDS de destino utilice la imagen **`postgis/postgis:17-3.5`** en lugar de un PostgreSQL estándar que fallaría al restaurar las tablas geoespaciales.
   - **Tablas, Columnas y Conteo Exacto de Filas**:
     Parsea cada bloque `CREATE TABLE schema.tabla (...)` extrayendo nombres y tipos de columnas, y recorre cada bloque `COPY schema.tabla (...) FROM stdin; ... \.` contando línea por línea cuántos registros reales existen en el backup (por ejemplo: `public.zonas_wifi: 185 filas`, `public.puntos_interes: 420 filas`) y guardando hasta 3 filas de muestra con valores sensibles redactados.
3. **Detección de Semillas y Scripts de Carga (`seed_files` y `loader_scripts`)**:
   Localiza archivos `.geojson`, `.json` o `.csv` con colecciones de datos y scripts de Python (`import_data.py`, `seed.py`) que usan `psycopg2` o `sqlalchemy` para poblar la base de datos.

---

### 3.6 Paso 5: Redacción de Secretos y Clasificación Epistémica de Dependencias

En [`_analyze_source_payload()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1185-L1570), CloudMove aplica seguridad e inteligencia epistémica sobre las variables de entorno y librerías descubiertas:

1. **Redacción de Secretos en Doble Capa (`_redact_env_value` + `SecretRedactor`)**:
   - Cualquier variable en `.env` o `docker-compose.yml` cuyo nombre coincida con `SECRET_KEY_PATTERNS` (`password`, `secret`, `token`, `api_key`, `private_key`, `dsn`, `database_url`, `supabase_key`, etc.) ve su valor reemplazado inmediatamente por `***REDACTED***`.
   - Si una variable contiene una URI de conexión con credenciales embebidas (`postgresql://usuario:MiClaveSecreta@host:5432/db`), la expresión regular `URL_CREDENTIAL_PATTERN` enmascara únicamente la contraseña (`postgresql://usuario:***REDACTED***@host:5432/db`) preservando el esquema, el host y el puerto para que el analizador de topología sepa a qué motor se conecta sin exponer jamás la credencial.
2. **Clasificación Epistémica de Dependencias en 3 Categorías**:
   CloudMove evalúa cada dependencia detectada y la clasifica rigurosamente:

| Categoría | Tipo de Evidencia CMIR | Confianza | Criterio Exacto de Clasificación en [`app_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1400-L1535) |
| :--- | :--- | :---: | :--- |
| **`confirmed`** | `observed` | `0.92 – 0.98` | 1. Servicio declarado explícitamente en `docker-compose.yml` (ej. contenedor `postgres` o `redis`).<br/>2. Librería cliente en manifiesto **respaldada** por una variable de conexión real en `.env` (ej. `psycopg2` + `DATABASE_URL`).<br/>3. Proyecto con backup `.dump`/`.sql` verificado en el repositorio.<br/>4. Servicio externo BaaS (ej. **Supabase**) confirmado simultáneamente por SDK (`supabase` en `requirements.txt` / `@supabase/supabase-js`) y variables `SUPABASE_URL` / `SUPABASE_KEY`. |
| **`inferred`** | `inferred` | `0.65` | Librería o driver presente en `requirements.txt`, `package.json`, `pom.xml` o `go.mod` (ej. `redis`, `celery`, `pymongo`, `boto3`), pero **sin ningún servicio en `docker-compose` ni variable de entorno que confirme un endpoint activo**. Se marca con `requires_operator_confirmation = True`. |
| **`unknown`** | `unknown` | `0.50` | Variables de entorno que apuntan a integraciones HTTP externas (`STRIPE_WEBHOOK_SECRET`, `SENDGRID_API_URL`, `EXTERNAL_PAYMENT_API`) cuya infraestructura pertenece a un tercero y no puede ser descubierta ni migrada desde el código fuente. |

---

### 3.7 Paso 6: ¿Cómo se Valida Qué Desplegar? Catálogo Interactivo, 6 Chequeos Pre-Flight y Viabilidad

Antes de generar una sola línea de Terraform, CloudMove valida **qué se debe desplegar y cómo** a través de dos mecanismos en [`app_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py):

#### A. Catálogo Interactivo de Transformación (`build_github_to_cloud_transformation_catalog`)
Definido en [`app_migrator.py#L1573-L1970`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1573-L1970), este motor construye una matriz de decisiones (`selectable_items`) para cada elemento descubierto en el repositorio. Cada ítem tiene una opción recomendada por defecto (`default_choice`), pero el usuario puede cambiarla interactivamente en la UI o vía API (`user_decisions`):

1. **Arquitectura de Cómputo (`compute_architecture`)**:
   - `single_instance_docker_compose`: **1x Instancia EC2 `t3.micro` / GCE `e2-micro` (Elegible en Capa Gratuita)** ejecutando todos los contenedores con Docker Compose v2 + archivo Swap de 2 GB. *(Recomendado por defecto cuando se despliega en laboratorios AWS Academy o cuando se incluye base de datos PostGIS autocontenida para evitar problemas de sincronización de estado entre múltiples nodos).*
   - `ha_alb_asg_containers`: **Alta Disponibilidad Multi-AZ** con Application Load Balancer (`aws_lb`) + Auto Scaling Group (`aws_autoscaling_group`, `min=1, desired=2, max=3`) con reemplazo automático de instancias no saludables.
   - `decoupled_instances`: Instancias EC2/GCE separadas por cada tier (una para Frontend y otra para Backend).
2. **Estrategia por cada Componente Descubierto (`component:<nombre>`)**:
   - Para el **Frontend** (`React / Vite / Nginx`): puede desplegarse como **Contenedor Docker (`container_in_primary_host`)** exponiendo el puerto `3000`/`80` en la instancia, o transformarse a **Hosting Estático Serverless en S3 / Cloud Storage (`s3_static_website`)**.
   - Para el **Backend** (`FastAPI / Node / Go / Java`): contenedor gestionado con `restart: always`, healthcheck activo e inyección automática de `.env`.
3. **Estrategia de Base de Datos y Migración de Backups (`dep:<id>`)**:
   - **Opción 1 (`self_hosted_container`)**: Crea automáticamente un contenedor **PostgreSQL 17 + PostGIS 3.5 (`postgis/postgis:17-3.5`)** dentro del mismo stack de Docker Compose con volumen persistente (`pgdata`) y **restaura automáticamente el archivo `supabase_backup.dump` / `.sql`** durante el primer arranque (`$0.00/mes` adicionales).
   - **Opción 2 (`transform_to_cloud_managed`)**: Aprovisiona una instancia gestionada **Amazon RDS (`aws_db_instance` `db.t3.micro`)** o **Google Cloud SQL (`google_sql_database_instance`)**, abre la conectividad privada desde el Security Group de la aplicación e inyecta el script `migrate_database_data.sh` para volcar allí todas las tablas y filas del backup `.dump`.
   - **Opción 3 (`keep_external`)**: Mantiene la conexión hacia el servicio externo original (ej. seguir apuntando al proyecto en la nube de Supabase sin migrar la base de datos).
4. **Dimensionamiento de Disco y Prevención de `No Space Left on Device` (`storage_and_build_capacity`)**:
   - Permite elegir entre **30 GB `gp3` (máximo de Capa Gratuita de AWS)** o **50 GB `gp3`**, con creación obligatoria de **2 GB de Swap (`/swapfile`)** y limpieza de caché de construcción (`docker builder prune -af`).
5. **Reescritura Dinámica de URLs entre Frontend y Backend (`network_and_env_rewriting`)**:
   - **`auto_rewrite_public_ip` (Recomendado)**: En el arranque de la instancia, consulta la IP pública real vía EC2 Metadata Service v2 (`169.254.169.254`) y reescribe `VITE_API_URL=http://${PUBLIC_IP}:8000` antes de compilar el bundle de Vite, además de abrir los puertos `22, 80, 443, 3000, 5432, 8000` en el Security Group.

#### B. Los 6 Chequeos Preventivos Pre-Flight (`preflight_preventive_checks`)
En el mismo catálogo, CloudMove ejecuta **6 validaciones preventivas** basadas en fallos reales de despliegue en la nube:
1. **`disk_exhaustion_guard`**: Las AMIs oficiales de Ubuntu 22.04 traen por defecto solo **8 GB** de disco raíz. Compilar una imagen de PostGIS (~1.2 GB) + un backend Python con librerías geoespaciales/ML (~1.8 GB) + un frontend Node/Vite (~1.5 GB) llena los 8 GB y aborta `docker compose build` con `no space left on device`. CloudMove fuerza `root_block_device { volume_size = 30, volume_type = "gp3" }` en Terraform.
2. **`frontend_localhost_api_guard`**: Si un frontend SPA (`Vite`/`React`) se compila con `VITE_API_URL=http://localhost:8000` o `http://backend:8000`, cuando el usuario abra `http://<IP_PUBLICA>:3000` desde su navegador, el navegador intentará llamar al `localhost` de la laptop del usuario y fallará con `ERR_CONNECTION_REFUSED`. CloudMove inyecta un paso en `user_data.sh` que descubre la IP pública de la máquina y recompila el frontend con la URL pública real del backend.
3. **`database_backup_hydration_guard`**: Un archivo `.dump` exportado de Supabase contiene referencias a roles (`anon`, `authenticated`, `service_role`, `supabase_admin`), esquemas (`auth`, `extensions`) y funciones (`auth.uid()`) que no existen en un PostgreSQL limpio. CloudMove genera `migrate_database_data.sh`, que pre-crea esos roles y esquemas antes de ejecutar `pg_restore --no-owner --no-acl` para que ninguna tabla o llave foránea falle al restaurarse.
4. **`container_name_collision_and_env_guard`**: Limpia contenedores previos con `docker rm -f` y garantiza que exista el archivo `.env` antes de levantar el stack.
5. **`security_group_multi_port_guard`**: Garantiza reglas `ingress` en `aws_security_group` / `google_compute_firewall` para todos los puertos descubiertos en los componentes (`3000`, `8000`, `80`, `443`, `5432`, `22`).
6. **`aws_academy_iam_and_session_guard`**: Evita crear usuarios IAM o Access Keys prohibidas en AWS Academy Learner Lab (que disparan el script `voc-cancel-cred` y bloquean la cuenta).

#### C. Evaluación de Viabilidad sin Refactorización Forzada (`evaluate_app_migration_viability`)
Definida en [`app_migrator.py#L2261-L2400`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L2261-L2400), valida si el servicio objetivo solicitado (`vm`, `containers` o `serverless`) es compatible con la naturaleza real de la aplicación:
- Si el usuario pide `serverless` (`Cloud Run` / `App Runner`), pero la aplicación monta **volúmenes locales con estado** (`stateful_local_volumes`) o expone **múltiples puertos simultáneos** en el mismo servicio, CloudMove marca las incompatibilidades (`compatible_without_refactoring = False`) y recomienda mantener una estrategia contenerizada sobre instancia VM o ASG (`no_forced_refactoring = True`).

---

### 3.8 Paso 7: Construcción del CMIR v2.1 y Síntesis Híbrida (Determinista + IA)

Una vez validadas las opciones:
1. **[`build_application_cmir()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1973-L2258)** construye el grafo `CMIRGraph` v2.1 de la aplicación:
   - Crea el nodo de red (`vpc-{app}`), subred (`subnet-{app}`), grupo de seguridad (`sg-{app}` con todos los puertos requeridos) y el nodo de cómputo principal (`{app_id}`) en Nivel 4.
   - Si el usuario eligió transformar una base de datos a servicio gestionado (`transform_to_cloud_managed`), agrega el nodo `database` en Nivel 7 con `requires_data_migration = True` y su relación `depends_on` (`observed`).
   - Si la base de datos es un BaaS externo que se mantiene externo (`keep_external`) o se aloja como contenedor interno (`self_hosted_container`), el nodo no genera un recurso RDS redundante en Terraform.
2. **[`ai_translator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/ai_translator.py) y [`generate_app_migration_artifacts()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L2852-L3536)**:
   - Prepara el payload arquitectónico limpio sin secretos mediante [`prepare_ai_payload()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/ai_translator.py#L77-L207).
   - Genera los archivos de contenedorización optimizados mediante [`generate_auto_dockerfile_and_compose()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/ai_translator.py#L210-L370) y el script autónomo de provisión [`generate_container_user_data_sh()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/ai_translator.py#L373-L618).
   - Sintetiza los 4 archivos de Terraform (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`) adaptados a la topología elegida (`single_instance_docker_compose` o `ha_alb_asg_containers`) y los pasa por el validador de 4 niveles de `AWSAdapter` o `GCPAdapter`.

---

### 3.9 Paso 8: Artefactos Generados y Ciclo de Vida de Arranque en la Nube (`user_data.sh`)

En el directorio `generated/<plan_slug>/`, el Caso 1 emite **13 artefactos listos para producción**:

| Archivo Generado | Propósito Técnico Exacto |
| :--- | :--- |
| `provider.tf`, `variables.tf`, `main.tf`, `outputs.tf` | Código Terraform modular validado. Incluye VPC, Subnets, Internet Gateway, Security Group (`22, 80, 443, 3000, 5432, 8000`), EC2/GCE con disco `gp3` de `30 GB`, RDS/Cloud SQL opcional, S3/GCS opcional e inyección de `user_data.sh` comprimido con `base64gzip(...)`. |
| `user_data.sh` | Script Bash Cloud-Init que se ejecuta automáticamente como `root` durante el primer arranque de la instancia en la nube. |
| `Dockerfile.cloudmove` | Dockerfile multi-lenguaje auto-generado (Python/Node/Java/Go) por si el repositorio original carece de uno. |
| `docker-compose.cloudmove.yml` | Orquestación de contenedores con `restart: always`, healthchecks y servicio `db` (`postgis/postgis:17-3.5` o `postgres:16-alpine`) con volumen persistente `pgdata`. |
| `migrate_database_data.sh` | Script automatizado que restaura dumps `PGDMP` (`.dump`) o `.sql`, pre-crea roles/esquemas de Supabase + extensión `postgis`, ejecuta scripts semilla y verifica el conteo exacto de filas (`SELECT COUNT(*)`). |
| `{app_slug}.service` | Unidad `systemd` que garantiza que el stack de Docker Compose vuelva a levantarse automáticamente si la instancia EC2/GCE se reinicia. |
| `.env.cloud.template` | Plantilla de variables de entorno con todos los nombres descubiertos y secretos redactados. |
| `smoke_test.sh` | Script de verificación post-despliegue que comprueba por HTTP el endpoint `/health` y los puertos expuestos con reintentos exponenciales. |
| `app_migration_diff_report.json` | Reporte auditable JSON con el diff entre el código fuente origen y la topología cloud generada. |
| `DEPLOYMENT_INSTRUCTIONS.md` | Guía paso a paso con la arquitectura, comandos y checklist de cutover. |

#### ¿Qué hace exactamente `user_data.sh` cuando arranca la máquina en AWS o GCP?
1. **Expansión del Sistema de Archivos y Creación de Swap (`2 GB`)**: Ejecuta `growpart` / `resize2fs` sobre el volumen raíz de 30 GB y crea `/swapfile` (`2048 MB`) para evitar muertes por falta de RAM (*OOM Killer*) en instancias `t3.micro` (1 GB RAM) mientras compila paquetes de Python o TypeScript.
2. **Instalación de Docker Engine, Docker Compose v2 y Clientes PostgreSQL**: Instala `docker.io`, `docker-compose-v2`, `git`, `postgresql-client` (`pg_restore`, `psql`) y `jq`.
3. **Clonación del Repositorio en el Commit Exacto**: Clona el repositorio en `/opt/cloudmove/<app_slug>` y hace `git checkout <commit_sha>`.
4. **Descubrimiento de la IP Pública vía IMDSv2 y Reescritura de Variables Frontend**: Consulta `http://169.254.169.254/latest/meta-data/public-ipv4` y actualiza `VITE_API_URL=http://${PUBLIC_IP}:8000` tanto en `.env` como en los `args:` de compilación del contenedor `frontend`.
5. **Levantamiento del Contenedor PostGIS / RDS e Hidratación de Datos (`migrate_database_data.sh`)**:
   - Levanta primero el contenedor de base de datos (o conecta al endpoint de RDS).
   - Espera a que `pg_isready` responda positivamente.
   - Pre-crea los esquemas `auth`, `extensions`, `storage`, los roles `anon`, `authenticated`, `service_role`, `supabase_admin` y las extensiones `postgis`, `pgcrypto`, `uuid-ossp`.
   - Ejecuta `pg_restore --no-owner --no-acl` sobre el archivo `.dump` del repositorio y luego corre una consulta `SELECT table, COUNT(*)` para dejar constancia en `/var/log/cloudmove-user-data.log` de que todas las filas fueron migradas.
6. **Construcción Secuencial de Contenedores y Arranque del Servicio**: Construye y levanta `backend` y `frontend` con `docker compose up -d --build`, ejecuta `docker builder prune -af` para liberar espacio en disco y registra la unidad `systemd` (`systemctl enable --now <app>.service`).

---

## 4. Caso de Uso 2 (`vm_image`): Migración de Imágenes de Disco, ISO, VM y Captura de SO en Vivo Paso a Paso

El **Caso de Uso 2** aborda el escenario donde la carga de trabajo es una **máquina completa**: ya sea un archivo de imagen de disco o electrodoméstico virtual (`VMDK`, `QCOW2`, `VHD`, `VHDX`, `RAW`, `OVA`, `OVF`) exportado desde VMware ESXi, VirtualBox, Hyper-V o KVM/QEMU, o bien un **Sistema Operativo en Vivo (Linux físico o VM)** del cual se desea capturar el estado real de sus discos, particiones, paquetes, usuarios, servicios, procesos y archivos para llevarlo a AWS, GCP o hipervisores locales.

### 4.1 ¿Qué Hace Funcionar al Caso 2 por Dentro?

El corazón del Caso 2 reside en [`backend/app/migration/image_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py) (3,723 líneas) y [`backend/app/migration/replication_and_import.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/replication_and_import.py) (554 líneas).

```mermaid
flowchart TD
    START["Inicio Caso 2: inspect_vm_image()"] --> MODE{"¿Qué fuente se proporcionó?"}

    subgraph MODE_A["Modo A: Archivo de Imagen de Disco / VM / Appliance"]
        A1["Lectura Binaria Read-Only de Primeros 4 KiB y 256 KiB<br/>(inspect_binary_disk_header_and_structure)"]
        A2["Verificación de Magic Bytes:<br/>KDMV (VMDK) | QFI\\xfb (QCOW2) | conectix (VHD)<br/>vhdxfile (VHDX) | 0x55AA (MBR) | EFI PART (GPT) | ustar (OVA)"]
        A3["Ejecución de /usr/bin/qemu-img info -U --output=json<br/>(virtual-size, actual-size, dirty-flag, backing-filename)"]
        A4["Cálculo de Hash Criptográfico SHA-256<br/>(_compute_file_sha256 con soporte Sparse)"]
        A1 --> A2 --> A3 --> A4
    end

    subgraph MODE_B["Modo B: Captura en Caliente de SO en Vivo (Live OS Capture)"]
        B1["Sondeo de Bloques Físicos: lsblk -J -b + os.statvfs()<br/>(probe_live_storage_devices)"]
        B2["Quiesce de Buffers del Kernel: os.sync()<br/>(application_quiesced_snapshot)"]
        B3["Sondeo Real de las 8 Dimensiones del SO:<br/>/etc/os-release | pwd (Usuarios) | ip -j addr (Red)<br/>dpkg-query/rpm (Paquetes) | ss -tulpn & ps (Procesos/Puertos)<br/>systemd & cron | /etc, /opt, /var, /home + /proc/modules"]
        B4["Creación de Disco Virtual Arrancable en Staging:<br/>qemu-img create (.qcow2/.raw) + MBR (0x55AA) + GPT (EFI PART)"]
        B5["Empaquetado de Snapshot Real:<br/>system_image_snapshot.tar.gz + os_real_files_bundle.tar.gz<br/>+ create_full_raw_disk_clone.sh"]
        B1 --> B2 --> B3 --> B4 --> B5
    end

    MODE -->|"Ruta a archivo .vmdk/.qcow2/.vhd/.vhdx/.raw/.ova/.ovf"| A1
    MODE -->|"capture_live_os=True / live://local-os"| B1

    A4 --> VAL["Validación de Compatibilidad, Remediación de Boot/Drivers<br/>y Evaluación de las 8 Dimensiones de Fidelidad<br/>(evaluate_vm_image_compatibility)"]
    B5 --> VAL

    VAL --> CAT["Catálogo Interactivo de Transformación + 4 Salvaguardas AWS Academy<br/>(build_vm_image_transformation_catalog)"]
    CAT --> STG["Copia Verificada en Staging (source_sha256 == staging_sha256)<br/>+ Conversión qemu-img convert (si QCOW2 -> RAW)"]
    STG --> ART["Generación de Artefactos Cloud & Hipervisor:<br/>Terraform (AWS/GCP) + user_data.sh (Portal en Vivo)<br/>+ launch_virtualbox.sh + launch_vmware.sh (.vmx)"]
```

---

### 4.2 Modo A: Inspección Forense de Imágenes Binarias (`VMDK`, `QCOW2`, `VHD`, `VHDX`, `RAW`, `OVA`, `OVF`)

Cuando el operador entrega una ruta a un archivo de imagen existente, [`inspect_vm_image()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py#L1408-L1694) invoca a [`inspect_binary_disk_header_and_structure()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py#L406-L567), que abre el archivo **exclusivamente en modo binario de solo lectura (`"rb"`)** y examina sus primeros `4 KiB` y `256 KiB`:

#### 1. Reconocimiento de Firmas Mágicas Binarias (`Magic Bytes`)
CloudMove no confía únicamente en la extensión del nombre del archivo; verifica la estructura binaria real a nivel de bytes:

| Formato | Firma Binaria / Offset Exacto | Qué Desempaqueta CloudMove con `struct.unpack` |
| :--- | :--- | :--- |
| **`VMDK` (Binario Sparse)** | Bytes `0..4 == b"KDMV"` (`0x564d444b`) | Ejecuta `struct.unpack("<IIQ", header[4:20])` para extraer la versión del contenedor VMDK, los flags y el número exacto de sectores (`capacity_sectors * 512` bytes de capacidad virtual). |
| **`VMDK` (Descriptor de Texto)** | Empieza con `# Disk DescriptorFile` | Parsea las directivas `RW <sectores> SPARSE "<archivo-extent.vmdk>"` o `VMFS "<archivo-flat.vmdk>"`. **Detección Anti-Stub**: Verifica en disco si el archivo binario de datos (`-flat.vmdk` o `-s001.vmdk`) referenciado por el descriptor existe realmente. Si no existe, lo marca como `VMDK_TEXT_STUB` (`is_simulated_text_stub = True`) para impedir que llegue un archivo vacío a `ec2:ImportImage`. |
| **`QCOW2` (QEMU Copy-On-Write)** | Bytes `0..4 == b"QFI\xfb"` (`0x514649fb`) | Ejecuta `struct.unpack(">I", header[4:8])` para obtener la versión QCOW2 (`v2` o `v3`) y `struct.unpack(">Q", header[24:32])` para leer el tamaño virtual de 64 bits en *big-endian*. |
| **`VHD` (Microsoft Virtual PC / Hyper-V Gen 1)** | Bytes `0..8 == b"conectix"` (o footer final de 512 bytes) | Verifica la cabecera/footer de disco fijo o dinámico `VHD_CONNECTIX`. |
| **`VHDX` (Hyper-V Gen 2)** | Bytes `0..8 == b"vhdxfile"` | Verifica la firma de tipo de archivo `VHDX_FILE`. |
| **`RAW` / `.img` / `.iso`** | Bytes `510..512 == b"\x55\xaa"` (**MBR**) y/o Bytes `512..520 == b"EFI PART"` (**GPT**) | Verifica el código de arranque en el sector 0 (446 bytes), la firma MBR `0x55AA` y la cabecera de la tabla de particiones GUID (`EFI PART` en LBA 1). |
| **`OVA` (Open Virtual Appliance)** | Bytes `257..262 == b"ustar"` (Tar POSIX) | Verifica que sea un contenedor TAR válido que empaqueta el descriptor `.ovf` y los discos `.vmdk`. |
| **`OVF` (Descriptor XML)** | Contiene `<?xml` y `<Envelope` | Parsea el manifiesto XML para identificar todos los archivos de disco asociados (`disks`) y comprobar si falta algún disco secundario en el directorio. |

#### 2. Escaneo de Etiquetas de Partición GPT en UTF-16LE e Invocación de `qemu-img info`
- En los primeros `256 KiB` de la imagen, busca cadenas codificadas en `UTF-16LE` correspondientes a la tabla de entradas de partición GPT (`EFI-SYSTEM`, `BIOS-BOOT`, `LINUX-ROOT`, `ROOTFS`, `DATA-VOLUME`, `PGSQL-DATA`, `SWAP`) para reconstruir el esquema de particionamiento sin necesidad de montar el disco con privilegios `root`.
- Si `/usr/bin/qemu-img` está disponible en el sistema, ejecuta:
  ```bash
  /usr/bin/qemu-img info -U --output=json <ruta_imagen>
  ```
  Con el flag `-U` (*force share / read-only without locking*) extrae el `virtual-size` exacto, el `actual-size` en disco, el `cluster-size` y el indicador **`dirty-flag`** (que revela si la imagen fue copiada mientras la máquina virtual estaba encendida sin hacer *quiesce* del sistema de archivos).
- Finalmente, [`_compute_file_sha256()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py#L96-L131) calcula el digest criptográfico SHA-256 leyendo bloques de 1 MiB (con optimización para archivos *sparse* mayores de 1 GiB) para garantizar la integridad bit a bit entre la imagen origen y la copia de staging.

---

### 4.3 Modo B: Sondeo y Captura en Caliente del Sistema Operativo en Vivo (`Live OS Capture`)

Cuando el operador selecciona capturar la máquina en vivo (`capture_live_os=True` o ruta `live://local-os`) o un servidor remoto con agente enrolado, CloudMove ejecuta [`probe_live_storage_devices()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py#L140-L246) y [`capture_live_operating_system()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py#L774-L1085).

**Nada en este proceso es simulado**: CloudMove interroga directamente al kernel Linux y a las utilidades del sistema operativo para radiografiar la máquina real:

1. **Sondeo de Dispositivos de Bloque y Puntos de Montaje (`lsblk` + `os.statvfs`)**:
   - Ejecuta `lsblk -J -b -o NAME,PATH,SIZE,RO,TYPE,MOUNTPOINT,FSTYPE,MODEL,SERIAL,UUID,PARTUUID,LABEL`.
   - Para cada partición montada (`/`, `/boot/efi`, `/home`, `/var`, etc.), ejecuta la llamada al sistema `os.statvfs(mountpoint)` para calcular al byte la capacidad total (`size_gib`), los GiB realmente ocupados (`used_gib`), los GiB libres (`free_gib`) y el porcentaje de uso (`usage_percent`).
   - Identifica cuál es el disco físico raíz (ej. `/dev/nvme0n1` de `476.94 GiB` con `13.4 GiB` en uso) y cuál es la partición EFI (`/boot/efi` con sistema de archivos `vfat`).
2. **Sincronización de Buffers del Kernel (`os.sync()`)**:
   - Invoca `os.sync()` para forzar al kernel del sistema operativo a volcar todos los buffers de memoria caché pendientes hacia el disco físico antes de tomar el snapshot (`consistency_level = "application_quiesced_snapshot"`).
3. **Captura Exhaustiva de las 8 Dimensiones del Sistema Operativo**:
   - **SO, Kernel y Firmware**: Lee `/etc/os-release` (`PRETTY_NAME`, `VERSION_ID`), `platform.release()` (versión del kernel Linux), `platform.machine()` (`x86_64` / `aarch64`), `/proc/meminfo` (`MemTotal`), verifica la existencia de `/sys/firmware/efi` (para distinguir **UEFI** de **Legacy BIOS**), e inspecciona `/boot/grub` o `/boot/efi/EFI` para identificar el gestor de arranque (`GRUB2` vs `systemd-boot`).
   - **Usuarios y Grupos Reales (`_probe_real_users`)**: Lee la base de datos de cuentas del sistema mediante `pwd.getpwall()`, separando usuarios humanos (`UID >= 1000` o `root`) de cuentas de servicio (`UID < 1000`), registrando su UID, GID, directorio `$HOME` y shell.
   - **Interfaces de Red, Direcciones IP y Rutas (`_probe_real_network_interfaces`)**: Ejecuta `ip -j addr show` y lee `/sys/class/net/<iface>/address` y `/mtu` para capturar cada interfaz real (`eth0`, `enp3s0`, `wlan0`, `docker0`), su dirección MAC, su MTU, su estado operacional y sus bloques CIDR IPv4/IPv6.
   - **Paquetes Instalados Reales (`_probe_real_installed_packages`)**: Ejecuta `dpkg-query -W -f=${Package}=${Version}\n` (en Debian/Ubuntu) o `rpm -qa` (en RHEL/CentOS/Rocky) para obtener la lista completa de los miles de paquetes `.deb`/`.rpm` instalados en la máquina.
   - **Bases de Datos, Demonios y Servicios `systemd` (`_probe_running_applications_and_databases`)**: Escanea la tabla de procesos (`ps -eo comm`) buscando motores activos (`postgres`, `mysqld`, `mariadbd`, `redis-server`, `mongod`, `nginx`, `apache2`, `dockerd`, `containerd`, `sshd`, `uvicorn`, `gunicorn`, `node`, `java`) y lista las unidades `*.service` en `/etc/systemd/system` y `/lib/systemd/system`.
   - **Procesos Activos y Puertos TCP/UDP en Escucha (`_probe_live_running_processes_and_ports`)**: Ejecuta `ss -tulpn` para descubrir todos los puertos de red abiertos (`LISTEN` / `UNCONN`), filtrando puertos efímeros ($\ge 32768$) para conservar únicamente los puertos reales de servicios (ej. `80`, `443`, `3000`, `5432`, `8000`) y ejecuta `ps -eo pid,user,%cpu,%mem,comm,args --sort=-%mem` para capturar los procesos activos con mayor uso de memoria y CPU.
   - **Tareas Programadas (`_probe_live_scheduled_tasks`)**: Lee `/etc/crontab`, `/etc/cron.d/*`, `/var/spool/cron/crontabs` y `systemctl list-timers`.
   - **Árbol del Sistema de Archivos y Módulos del Kernel (`_probe_live_filesystem_and_kernel_metadata`)**: Inventaría el contenido real de `/etc`, `/opt`, `/srv`, `/var`, `/usr/local` y `/home` (con permisos octales, propietario, tamaño y fecha de modificación de cada archivo) y lee `/proc/modules` para registrar los módulos del kernel cargados.
4. **Creación de la Imagen Virtual en Staging y Empaquetado del Snapshot Real**:
   - Crea en `generated/live_captures/` una imagen de disco virtual arrancable (`.qcow2` o `.raw`) usando `/usr/bin/qemu-img create` e inyecta en sus primeros sectores un bloque de arranque MBR (`0x55AA`) y una cabecera GPT (`EFI PART`) con las etiquetas `UTF-16LE` de todas las particiones reales descubiertas por `lsblk`.
   - Genera **`system_image_snapshot_<hostname>.tar.gz`** y **`os_real_files_bundle.tar.gz`**, que empaquetan los archivos de configuración reales (`/etc/os-release`, `/etc/hostname`, `/etc/hosts`, `/etc/fstab`, `/etc/environment`, `/etc/sysctl.conf`, `/etc/crontab`, unidades `/etc/systemd/system/*.service`), el script de restauración `restore_system_image.sh` y todos los manifiestos JSON (`users_manifest.json`, `network_manifest.json`, `services_manifest.json`, `storage_manifest.json`, `processes_manifest.json`, `filesystem_manifest.json`, `installed_packages_manifest.txt`).
   - Genera además el script **`create_full_raw_disk_clone.sh`**, que permite al administrador con permisos `sudo` ejecutar un clonado bit a bit (`qemu-img convert -p -O qcow2 /dev/nvme0n1 ...` o `dd status=progress | gzip -c`) ya sea hacia un archivo local o por streaming directo hacia **Amazon S3** (`aws s3 cp - s3://...`) o **Google Cloud Storage** (`gcloud storage cp - gs://...`) sin ocupar espacio adicional en el disco local.

---

### 4.4 ¿Cómo se Valida la Imagen? Bloqueadores, Remediación de Boot/Drivers y 8 Dimensiones de Fidelidad

Una vez inspeccionada la imagen (por Modo A o Modo B), [`evaluate_vm_image_compatibility()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py#L1697-L1988) evalúa si la máquina puede arrancar de forma segura en AWS o GCP.

#### 1. Los 4 Bloqueadores Críticos (`blockers`)
Si ocurre cualquiera de estas 4 condiciones, CloudMove marca `compatible = False` y detiene el aprovisionamiento hasta que se corrija:
1. **`simulated_text_stub_missing_extent`**: El archivo proporcionado es un descriptor de texto VMDK/OVF de pocos bytes que apunta a un disco binario (`-flat.vmdk`) inexistente, y se solicitó validación estricta (`require_authentic_binary = True`).
2. **`dirty_live_disk`**: La cabecera binaria QCOW2/VMDK tiene activo el `dirty-flag` o se indicó que la imagen RAW fue copiada en caliente sin hacer *quiesce* ni snapshot LVM/ZFS/VSS (`source_running_during_raw_copy = True`), lo que causaría corrupción de `ext4`/`xfs` o de tablas PostgreSQL al arrancar en la nube.
3. **`missing_disk_files`**: Un manifiesto multi-disco (`.ovf` o servidor con discos de datos separados) referencia volúmenes secundarios que no se encuentran en el directorio de origen.
4. **`require_live_memory_state = True`**: Si el usuario exige explícitamente preservar el estado volátil de la memoria RAM o las conexiones TCP abiertas sin corte, CloudMove bloquea la migración basada en imagen explicando la limitación física documentada en [`ADR-004`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/docs/ADR/ADR-004-vm-image-migration-fidelity-and-limitations.md): *la importación de imágenes de disco o replicación de bloques migra el estado persistente en disco, nunca la memoria RAM volátil ni los sockets TCP en vuelo*.

#### 2. Validación de Formato, Bootloader y Drivers Paravirtuales (`remediation_steps`)
CloudMove verifica y planifica automáticamente las remediaciones necesarias para el hipervisor de destino:
- **Conversión Automática de Formato (`conversion_plan`)**:
  - **AWS (`ec2:ImportImage`)** acepta nativamente `VMDK`, `VHD`, `VHDX`, `RAW` y `OVA`. Si la imagen de entrada es **`QCOW2`**, CloudMove programa una conversión sin pérdida (`qemu-img convert -f qcow2 -O raw <staging.qcow2> <staging.raw>`) trabajando **exclusivamente sobre la copia en staging**.
  - **GCP (`compute.images.insert`)** acepta `RAW` (empaquetado como `disk.raw` dentro de `.tar.gz`), `VMDK`, `VHD`, `VHDX`, `QCOW2` y `OVA`.
- **Inyección de Drivers Paravirtuales de Red y Almacenamiento**:
  - En **AWS (Hipervisor Nitro — familias `t3`, `m5`, `c5`, `r6i`)**: verifica que el `initramfs` (Linux) o el registro de controladores (Windows) incluya los módulos **`ena`** (*Elastic Network Adapter*) y **`nvme` / `nvme_core`** (ya que Nitro expone los volúmenes EBS como dispositivos `/dev/nvme0n1`, no como `/dev/xvda`). Si faltan, añade el paso de remediación `dracut -f --add-drivers 'ena nvme nvme_core'` / `update-initramfs -u`.
  - En **GCP (Compute Engine)**: verifica la presencia de los módulos VirtIO **`virtio_blk`**, **`virtio_scsi`**, **`virtio_net`** y **`gvnic`**.
- **Normalización de `/etc/fstab` a `UUID=`**:
  Si el archivo `/etc/fstab` de la máquina origen monta particiones por nombre de dispositivo físico (`/dev/sda1`, `/dev/sdb1`), al arrancar en AWS Nitro (donde los discos pasan a llamarse `/dev/nvme0n1p1`) el arranque caería en *emergency mode*. CloudMove normaliza los montajes para usar `UUID=<blkid>` o `LABEL=`.
- **Reconfiguración de Red DHCP y Consola Serial (`ttyS0`)**:
  Elimina reglas persistentes de `udev` (`70-persistent-net.rules`) que atan la configuración de red a la dirección MAC antigua de VMware/VirtualBox, habilita DHCP para que la instancia tome su IP privada de la VPC de AWS/GCP, y añade `console=ttyS0,115200n8` en `/etc/default/grub` para diagnóstico desde la consola serial de EC2/GCE.

#### 3. Las 8 Dimensiones de Fidelidad y el Reporte Diff (`generate_source_vs_target_diff_report`)
Para que el usuario sepa exactamente qué se preserva al 100%, qué se adapta y qué no se transfiere, CloudMove evalúa las **8 dimensiones de fidelidad** y genera `inventory_diff_report.json`:

| # | Dimensión de Fidelidad | Estado en CloudMove | Qué Ocurre Exactamente |
| :---: | :--- | :--- | :--- |
| **1** | **Sistema Operativo, Kernel y Usuarios** | `preserved` | Se conserva la distribución, versión, cuentas de usuario, UIDs/GIDs, hashes y permisos. |
| **2** | **Volúmenes de Disco, Particiones y Archivos** | `preserved_with_uuid_normalization` | Todos los volúmenes (`root` + discos de datos secundarios) se mapean a volúmenes EBS (`gp3`) o Persistent Disks (`pd-balanced`), normalizando `/etc/fstab` a `UUID=`. |
| **3** | **Paquetes Instalados, Binarios y Runtimes** | `preserved` | Los paquetes `.deb`/`.rpm`, librerías en `/usr` y aplicaciones en `/opt` o `/srv` permanecen intactos en el disco o manifiesto de restauración. |
| **4** | **Servicios del Sistema (`systemd`) y Tareas (`cron`)** | `preserved` | Todas las unidades `.service` habilitadas y los jobs de `crontab` / timers se mantienen activos tras el arranque. |
| **5** | **Configuración de Red, Firewalls y Puertos** | `adapted_to_cloud_vpc` | Las IPs estáticas on-premise y MACs fijas se adaptan a DHCP dentro de la VPC de AWS/GCP, y los puertos TCP/UDP descubiertos por `ss -tulpn` se traducen a reglas de `aws_security_group` o `google_compute_firewall`. |
| **6** | **Arranque (UEFI/BIOS) y Drivers de Hipervisor** | `remediated_automatically` | El modo `UEFI` o `Legacy BIOS` se configura en la AMI/Instancia, y se aseguran los drivers `ena`/`nvme` (AWS) o `virtio`/`gvnic` (GCP). |
| **7** | **Consistencia Transaccional de Bases de Datos en Disco** | `verified_by_consistency_level` | Validada mediante `application_quiesced_snapshot` (`os.sync()`) o `cold_disk_image` (`dirty-flag == False`). |
| **8** | **Estado Volátil de Memoria RAM y Sockets TCP Activos** | `not_transferred_by_design` | Documentado explícitamente: la RAM volátil y las sesiones TCP en vuelo se reinician limpiamente en el primer boot de la instancia en la nube. |

---

### 4.5 Matriz Oficial de Estrategias: Replicación Continua (MGN / Migrate to VMs) vs Importación de Imagen

El módulo [`backend/app/migration/replication_and_import.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/replication_and_import.py) implementa la función [`select_machine_migration_strategy()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/replication_and_import.py#L106-L185), que selecciona e invoca los servicios nativos de AWS (`boto3`) y GCP (`google-cloud-compute` / `vmmigration`):

| Tipo de Activo Origen | Destino AWS | Destino GCP | Cuándo se Usa y Qué APIs Invoca |
| :--- | :--- | :--- | :--- |
| **Servidor Físico o VM en Vivo con Agente / Conector de Hipervisor** (`live_server`, `hypervisor_vm` con requerimiento de corte mínimo) | **AWS Application Migration Service (`aws_mgn`)** | **GCP Migrate to Virtual Machines (`gcp_vmmigration`)** | Cuando se requiere **replicación continua a nivel de bloque** con *cutover* de pocos minutos. Usa `boto3.client("mgn")` (`describe_source_servers`, `start_Replication`, `start_test`, `start_cutover`) o la API `vmmigration.googleapis.com`. |
| **Archivo de Imagen de Disco / Appliance Exportado o Snapshot de Disco** (`disk_image`: `VMDK`, `QCOW2`, `VHD`, `VHDX`, `RAW`, `OVA`) | **AWS VM Import/Export (`aws_vm_import`)** o **Rehidratación Cloud-Init (`autonomous_cloud_init`)** | **GCP Compute Engine Image Import (`gcp_image_import`)** | Sube el disco desde staging hacia un bucket S3 (`aws_s3_bucket`) o GCS (`google_storage_bucket`) e invoca `ec2:ImportImage` (`describe_import_image_tasks`) para registrar una AMI privada, o `compute.images.insert` en GCP. |

---

### 4.6 Catálogo Interactivo de Transformación y las 4 Salvaguardas para AWS Academy Learner Lab

Al igual que en el Caso 1, el Caso 2 cuenta con [`build_vm_image_transformation_catalog()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py#L1991-L2277), que expone opciones interactivas para el modo de despliegue, el tipo de instancia, el dimensionamiento de cada disco y los puertos del Security Group.

Además, incorpora **4 salvaguardas automáticas críticas** diseñadas específicamente para evitar los bloqueos de permisos más comunes en cuentas restringidas como **AWS Academy Learner Lab (`Vocareum`)**:

1. **Salvaguarda 1 — Límite de 100 GiB por Volumen EBS de la Política IAM `Pvoclabs2`**:
   - **El problema real**: En AWS Academy, la política IAM `Pvoclabs2` deniega cualquier llamada a `ec2:CreateVolume` o `ec2:RunInstances` cuyo volumen EBS supere los **100 GiB** (`403 UnauthorizedOperation`). Si el usuario captura su laptop o servidor físico con un disco NVMe de **476 GiB** (aunque solo tenga **13.4 GiB** ocupados), intentar crear un volumen EBS de 476 GiB falla inmediatamente.
   - **Cómo lo resuelve CloudMove**: Calcula los GiB realmente utilizados en el sistema de archivos (`used_gib` vía `os.statvfs`) y selecciona por defecto un volumen raíz **`30 GiB gp3`** (elegible en Capa Gratuita y muy por debajo del tope de 100 GiB de `Pvoclabs2`), mientras registra la capacidad física original (`476.94 GiB`) en la etiqueta auditable `Source_Capacity_GiB` del recurso Terraform.
2. **Salvaguarda 2 — Bypass del Rol IAM `vmimport` (`autonomous_cloud_init` por defecto)**:
   - **El problema real**: El servicio clásico `ec2:ImportImage` de AWS exige que exista un rol IAM llamado exactamente `vmimport` con permisos de confianza hacia `vmie.amazonaws.com`. En AWS Academy y cuentas corporativas restringidas, el permiso `iam:CreateRole` está bloqueado.
   - **Cómo lo resuelve CloudMove**: Define como modo recomendado **`autonomous_cloud_init` (`enable_vm_import = false`)**. Cuando este modo está activo, Terraform no invoca `aws_ami_copy` ni exige el rol `vmimport`; en su lugar, lanza una instancia EC2 HVM base (Ubuntu 22.04 LTS) e inyecta un script `user_data.sh` comprimido con `base64gzip` que reconstruye toda la estructura capturada del sistema operativo origen sin requerir ningún permiso IAM especial. (Si el usuario opera en una cuenta AWS estándar con permisos IAM completos, puede seleccionar la opción `s3_vm_import_ami` o pasar `-var="enable_vm_import=true"`).
3. **Salvaguarda 3 — Deduplicación Automática del Puerto 22 (SSH)**:
   - **El problema real**: Cuando `ss -tulpn` escanea un servidor Linux en vivo, casi siempre descubre `sshd` escuchando en el puerto `22`. Si el generador de Terraform añade una regla para cada puerto descubierto además de la regla base de administración SSH (`22`), la API de AWS rechaza la creación del Security Group con `InvalidParameterValue: Duplicate permission`.
   - **Cómo lo resuelve CloudMove**: Filtra y deduplica el puerto `22` de la lista de puertos de aplicación antes de sintetizar el bloque `aws_security_group`.
4. **Salvaguarda 4 — Compresión `base64gzip` bajo el Límite Estricto de 16 KB de EC2 User-Data**:
   - **El problema real**: AWS EC2 rechaza cualquier instancia cuyo atributo `user_data` supere los **16,384 bytes (16 KB)**. Como CloudMove incrusta dentro de `user_data.sh` el archivo tar.gz con los archivos reales capturados del sistema operativo (`os_real_files_bundle.tar.gz`) y el manifiesto JSON completo de procesos, paquetes y árbol de directorios, el script en texto plano mide entre 35 KB y 90 KB.
   - **Cómo lo resuelve CloudMove**: En `main.tf`, en lugar de usar `user_data = file(...)`, utiliza la función nativa de Terraform:
     ```hcl
     user_data_base64 = base64gzip(file("${path.module}/user_data.sh"))
     ```
     Cloud-Init en Ubuntu/Debian detecta automáticamente la cabecera `gzip`, descomprime el script en memoria al arrancar y permite inyectar decenas de kilobytes de archivos reales manteniendo el payload comprimido por debajo de ~6 KB.

---

### 4.7 Copia en Staging, Conversión `qemu-img convert` y Artefactos Multi-Plataforma

Durante la generación de artefactos ([`generate_vm_image_migration_artifacts()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py#L2446-L3723)), CloudMove ejecuta primero [`prepare_and_verify_staging_copy()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py#L2280-L2443):

1. **Verificación Criptográfica de Integridad (`staging_verification.json`)**:
   - Copia la imagen de origen hacia `generated/staging_images/<plan_slug>/` utilizando `cp --sparse=always` (para conservar los bloques dispersos sin inflar el uso de disco).
   - Calcula el hash SHA-256 de la copia y comprueba que **`source_sha256 == staging_copy_sha256`** (`checksum_verified = True`, `source_untouched = True`).
   - Si el formato de entrada es `QCOW2` y el destino es AWS, ejecuta `/usr/bin/qemu-img convert -f qcow2 -O raw` **únicamente sobre la copia en staging**, generando el archivo `.raw` listo para S3 y registrando su nuevo hash SHA-256 (`converted_sha256`).

2. **Artefactos Emitidos en `generated/<plan_slug>/`**:
   Además de los 4 archivos de Terraform (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`) y `user_data.sh`, el Caso 2 genera herramientas para desplegar la máquina tanto en la nube como en hipervisores locales:
   - **`deploy_to_aws.sh` / `deploy_to_gcp.sh`**: Script automatizado que crea el bucket S3/GCS, sube el archivo de imagen desde staging (`aws s3 cp` / `gsutil cp`), ejecuta el flujo de importación y aplica el plan de Terraform.
   - **`create_full_raw_disk_clone.sh`**: Script de clonación de bloques físicos (`dd` / `qemu-img convert`) con soporte para destino `local`, streaming directo a `s3` o streaming directo a `gcs`.
   - **`restore_system_image.sh`**: Script de restauración post-arranque que reinstala la lista exacta de paquetes (`dpkg`/`rpm`), recrea usuarios/grupos, aplica `/etc/sysctl.conf` y habilita los servicios `systemd`.
   - **`launch_virtualbox.sh`**: Script listo para ejecutar en la máquina local que convierte la imagen de staging a formato **`.vdi`** al vuelo (`VBoxManage convertfromraw` o `qemu-img convert -O vdi`), registra una máquina virtual en **Oracle VirtualBox** (`VBoxManage createvm`), configura RAM, CPUs, controlador SATA, adaptador de red con port-forwarding (`8080 -> 80`, `2222 -> 22`) y la arranca (`VBoxManage startvm`).
   - **`launch_vmware.sh` + `<plan_slug>.vmx`**: Genera el archivo de descriptor de máquina virtual `.vmx` para **VMware Workstation / Player / Fusion**, convierte la imagen a `.vmdk` si es necesario (`qemu-img convert -O vmdk`) e inicia la VM con `vmrun start` o `vmplayer`.
   - **`image_manifest.json`, `staging_verification.json` e `inventory_diff_report.json`**: Manifiestos completos de auditoría técnica.

---

### 4.8 Rehidratación Autónoma Cloud-Init y Portal Web de Telemetría en Vivo

Cuando se despliega el Caso 2 en AWS o GCP mediante la consola interactiva de CloudMove, el script `user_data.sh` ([`_generate_vm_rehydration_user_data_sh()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py#L2459-L2966)) realiza la **rehidratación completa en vivo**:

1. **Extracción de Archivos Reales Capturados (`/etc/cloudmove_migrated_root`)**:
   Decodifica el bundle `os_real_files_bundle.tar.gz` incrustado en Base64 y extrae en `/etc/cloudmove_migrated_root/` todos los archivos reales capturados de la máquina origen (`/etc/os-release`, `/etc/hostname`, `/etc/hosts`, `/etc/fstab`, `/etc/sysctl.conf`, `/etc/crontab`, unidades `systemd` y configuraciones).
2. **Recreación de Usuarios Humanos y Aplicación de Parámetros de Kernel**:
   Recrea los usuarios humanos descubiertos en la máquina origen (`useradd -m -s /bin/bash`), aplica los parámetros de kernel de `/etc/sysctl.conf` y monta automáticamente cualquier volumen EBS / Persistent Disk secundario en `/mnt/cloudmove_ebs` registrándolo por `UUID=` en `/etc/fstab`.
3. **Portal Web Interactivo y Explorador de Archivos en Vivo (`cloudmove-os-telemetry.service`)**:
   Para que el operador pueda verificar visualmente desde su navegador que la máquina migrada está viva y contiene toda la información capturada del sistema operativo origen, `user_data.sh` registra y levanta el servicio `systemd` `cloudmove-os-telemetry.service` (con un servidor multihilo en Python que escucha simultáneamente en los puertos **`80`**, **`3000`** y **`8000`**):
   - **`GET /` (Dashboard Interactivo en Vivo)**: Muestra el estado en tiempo real de la instancia EC2/GCE (Uptime, Load Average, RAM libre/usada, discos montados con `df -h`, tabla de comparación entre el disco físico origen y el volumen EBS en la nube), junto con pestañas interactivas que permiten explorar:
     - El **Explorador del Sistema de Archivos Capturado** (`/etc`, `/opt`, `/var`, `/home`, `/usr/local`, `/srv`) con permisos, propietarios y visor de contenido de los archivos reales extraídos en `/etc/cloudmove_migrated_root`.
     - La tabla de **Procesos Activos y Puertos de Red** capturados de la máquina origen.
     - El listado completo de **Paquetes Instalados (`dpkg`/`rpm`), Servicios `systemd`, Usuarios y Tareas `cron`**.
   - **`GET /api/manifest`**: Devuelve el JSON completo del manifiesto del sistema operativo migrado.
   - **`GET /api/live-tree`**: Devuelve en JSON los archivos reales extraídos en el disco de la instancia en la nube junto con la salida en vivo de `df -h` y `lsblk`.
   - **`GET /health`**: Endpoint JSON de salud (`{"status": "healthy", "use_case": "vm_image", ...}`) para chequeos automatizados.

---

## 5. Caso de Uso 3 (`datacenter_campaign`): Descubrimiento Masivo y Migración Selectiva de Subgrafos

Para entornos empresariales con decenas o cientos de servidores distribuidos en múltiples sitios, el **Caso de Uso 3** ([`backend/app/discovery/campaigns.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/campaigns.py), [`backend/app/discovery/osquery_parser.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/osquery_parser.py) y [`backend/app/api/routers/agents.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/api/routers/agents.py)) proporciona:

1. **Enrolamiento Seguro de Agentes y Sondeo con `osquery`**:
   - Generación de tokens de enrolamiento con hash SHA-256, fecha de expiración y límite de usos en la tabla `agent_enrollment_tokens`.
   - El agente ejecuta consultas `osquery` sobre tablas del sistema (`system_info`, `os_version`, `interface_addresses`, `listening_ports`, `process_open_sockets`, `processes`, `deb_packages`, `rpm_packages`, `mounts`, `block_devices`, `systemd_units`) y envía snapshots firmados al backend.
2. **Reconciliación de Identidad Canónica (`canonical_identity_key`)**:
   - Cuando un mismo servidor es reportado múltiples veces (por distintos escaneos de red, hipervisores o agentes en distintas fases de una campaña), [`CampaignManager`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/campaigns.py) unifica el activo bajo una llave canónica determinista (`machine_id` / UUID de SMBIOS / MAC primaria + hostname normalizado) y gestiona su estado de ciclo de vida (`discovered -> updated -> stale -> decommissioned -> migrated`).
3. **Migración Selectiva de Subgrafos y Oleadas (*Waves*)**:
   - El operador puede seleccionar un subconjunto de servidores o una aplicación específica dentro del grafo global del Data Center.
   - [`DependencyResolver`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/dependencies/resolver.py) calcula la clausura transitiva de dependencias mediante BFS, separa las dependencias confirmadas de las inferidas/desconocidas y **bloquea la migración automática de recursos compartidos (`is_shared=True`)** hasta que el arquitecto valide si la base de datos o cola compartida debe clonarse, mantenerse híbrida por VPN o migrarse en una oleada conjunta.

---

## 6. Estructura del Repositorio y Guía de Ejecución Rápida

### 6.1 Mapa de Directorios Clave

```text
CapstoneProject_TI/
├── backend/
│   ├── app/
│   │   ├── adapters/                  # Adaptadores de proveedor Cloud (AWS y GCP) + Validador de 4 niveles
│   │   │   ├── base.py                # BaseProviderAdapter y validate_artifacts()
│   │   │   ├── aws_adapter.py         # Traducción CMIR -> Terraform AWS Provider (~> 5.0)
│   │   │   └── gcp_adapter.py         # Traducción CMIR -> Terraform Google Provider (~> 5.0)
│   │   ├── api/routers/               # Endpoints FastAPI REST
│   │   │   ├── migration.py           # Orquestación, Casos 1, 2 y 3, Catálogos de Transformación y Cloud Deploy
│   │   │   ├── discovery.py           # Ingesta osquery, escaneo cloud real y campañas
│   │   │   ├── graph.py               # Consultas al grafo y resolución de dependencias BFS
│   │   │   ├── terraform.py           # Generación y descarga de paquetes Terraform
│   │   │   └── agents.py              # Enrolamiento, heartbeat y tareas de agentes remotos
│   │   ├── cmir/                      # Representación Intermedia Neutral CMIR v2.1
│   │   │   ├── models.py              # CMIRGraph, CMIRNode, CMIRRelationship, CMIREvidence, Niveles 0..8
│   │   │   └── builder.py             # CMIRBuilder y validación de invariantes del grafo
│   │   ├── dependencies/              # Motor de resolución de dependencias
│   │   │   └── resolver.py            # DependencyResolver (BFS, separación epistémica e is_shared)
│   │   ├── discovery/                 # Parsers de telemetría de infraestructura
│   │   │   ├── osquery_parser.py      # Normalización de snapshots osquery -> CMIR v2.1
│   │   │   ├── campaigns.py           # Campañas por fases y reconciliación de identidad canónica
│   │   │   └── cloud_connector.py     # Descubrimiento real en AWS (boto3) y GCP + Drift Detection
│   │   ├── generators/                # Síntesis de Infraestructura como Código
│   │   │   ├── terraform.py           # Generador modular HCL (provider.tf, variables.tf, main.tf, outputs.tf)
│   │   │   └── ai_translator.py       # Orquestador Híbrido (Gemini + Fallback Determinista HA & Docker)
│   │   ├── graph/                     # Construcción de grafos dirigidos en memoria
│   │   │   └── builder.py             # InfrastructureGraphBuilder (networkx.DiGraph)
│   │   ├── migration/                 # Motores de los Casos de Uso y Ejecución Cloud
│   │   │   ├── orchestrator.py        # MigrationOrchestrator (Máquina de 12 estados + Safety Guarantees)
│   │   │   ├── github_connector.py    # Pinning SHA en GitHub + Sandbox efímero Anti-Zip-Slip
│   │   │   ├── app_migrator.py        # Caso 1: AST/Regex, PGDMP parser, Catálogo y Artefactos App
│   │   │   ├── image_migrator.py      # Caso 2: Forense binario, Captura de SO en vivo, Catálogo y Rehidratación
│   │   │   ├── replication_and_import.py # Caso 2: Matriz MGN/VM Import (AWS) y Migrate to VMs/Image Import (GCP)
│   │   │   └── cloud_deployer.py      # CloudDeploymentRunner (Streaming Terraform CLI + lectura de tfstate)
│   │   ├── persistence/               # Almacenamiento Transaccional ACID
│   │   │   └── transactional_db.py    # SQLite WAL, Optimistic Concurrency, Stage Locks e Idempotencia
│   │   └── security/                  # Hardening, RBAC, Auditoría y Redacción de Secretos
│   │       └── security_hardening.py  # SecretRedactor, RBAC y cadena de auditoría SHA-256
│   └── tests/                         # Suite de pruebas automatizadas (Unitarias, Integración y E2E)
├── frontend/                          # Interfaz Web Interactiva (Asistente de los 3 Casos de Uso + Visor de Grafo)
├── docs/                              # Documentación de Arquitectura y ADRs (ADR-001 a ADR-004)
└── generated/                         # Directorio de salida de planes Terraform, copias en staging y capturas
```

### 6.2 Ejecución Local del Proyecto

1. **Iniciar el Backend (FastAPI en puerto `8000`)**:
   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   - Documentación interactiva OpenAPI (Swagger UI): `http://localhost:8000/docs`
   - Verificación de salud y estado de componentes: `http://localhost:8000/health`

2. **Iniciar el Frontend (en puerto `3000`)**:
   ```bash
   cd frontend
   python3 -m http.server 3000
   ```
   - Interfaz gráfica principal de CloudMove: `http://localhost:3000`

3. **Ejecutar la Suite de Pruebas**:
   ```bash
   cd backend
   pytest -q
   ```
