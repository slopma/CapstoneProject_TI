# CloudMove — Cómo Funciona por Dentro y Cómo Está Construido

**CloudMove** es una plataforma web pensada para analizar aplicaciones y servidores existentes, pasarlos por un modelo intermedio neutro (**CMIR v2.1**), revisar qué dependencias están confirmadas y cuáles son solo suposiciones, generar el código **Terraform HCL** y desplegar la migración paso a paso hacia **Amazon Web Services (AWS)**.

> **Así corre cuando se usa en la web sobre AWS**: CloudMove está montada como una aplicación web pública en AWS (EC2 + Docker Compose + Nginx + Certbot). Cada persona entra desde su navegador y maneja sus propias migraciones con **credenciales aisladas por pestaña (`sessionStorage` + bóveda en memoria/sesión)**. El backend nunca deja que la petición de un usuario use el rol IAM ni el metadata IMDSv2 del servidor donde corre CloudMove (`ALLOW_SERVER_AWS_FALLBACK=false`), bloquea ataques SSRF hacia redes internas/IMDS y separa los datos del propio servidor de control.

En esta guía te contamos cómo funciona CloudMove por debajo, desde su arquitectura de 7 capas hasta el detalle paso a paso de sus dos flujos principales: el [**Caso de Uso 1 (`app_source`: desde GitHub o código fuente)**] y el [**Caso de Uso 2 (`vm_image`: imágenes de disco, VM o captura en vivo con agente remoto)**].

### Quiénes construimos CloudMove

Este proyecto nació como nuestro trabajo de grado (**Capstone Project in IT · Universidad EAFIT · 2026-2**) hecho por:
- **Sara Lopez Marin**
- **Luis Alejandro Castrillón Pulgarín**

---

## Tabla de Contenidos

1. [Qué resuelve CloudMove y sus 2 casos de uso](#1-qué-resuelve-cloudmove-y-sus-2-casos-de-uso)
2. [Cómo funciona por dentro: arquitectura de 7 capas](#2-cómo-funciona-por-dentro-arquitectura-de-7-capas)
   - [2.1 Capa 1: Motores de descubrimiento en solo lectura](#21-capa-1-motores-de-descubrimiento-en-solo-lectura)
   - [2.2 Capa 2: Modelo intermedio neutral (`CMIR v2.1`)](#22-capa-2-modelo-intermedio-neutral-cmir-v21)
   - [2.3 Capa 3: Grafo `networkx.DiGraph` y resolución de dependencias (BFS)](#23-capa-3-grafo-networkxdigraph-y-resolución-de-dependencias-bfs)
   - [2.4 Capa 4: Adaptador único de destino (`AWSAdapter`)](#24-capa-4-adaptador-único-de-destino-awsadapter)
   - [2.5 Capa 5: Generador modular de Terraform HCL y chequeo en 4 niveles](#25-capa-5-generador-modular-de-terraform-hcl-y-chequeo-en-4-niveles)
   - [2.6 Capa 6: Orquestador de estados y base transaccional ACID (`SQLite WAL`)](#26-capa-6-orquestador-de-estados-y-base-transaccional-acid-sqlite-wal)
   - [2.7 Capa 7: Consola de despliegue real con Terraform (`CloudDeploymentRunner`)](#27-capa-7-consola-de-despliegue-real-con-terraform-clouddeploymentrunner)
3. [Caso de Uso 1 (`app_source`): migrar desde GitHub o código fuente](#3-caso-de-uso-1-app_source-migrar-desde-github-o-código-fuente)
   - [3.1 Flujo completo del Caso 1](#31-flujo-completo-del-caso-1)
   - [3.2 Paso 1: Bajada desde GitHub, commit SHA fijo y sandbox limpio anti-Tar-Slip](#32-paso-1-bajada-desde-github-commit-sha-fijo-y-sandbox-limpio-anti-tar-slip)
   - [3.3 Paso 2: Recorrido de carpetas, poda de ruido y lectura de manifiestos](#33-paso-2-recorrido-de-carpetas-poda-de-ruido-y-lectura-de-manifiestos)
   - [3.4 Paso 3: Escaneo estático de código multi-componente (AST / Regex)](#34-paso-3-escaneo-estático-de-código-multi-componente-ast--regex)
   - [3.5 Paso 4: Lectura directa de backups PostgreSQL (`PGDMP` / `.sql`) y semillas](#35-paso-4-lectura-directa-de-backups-postgresql-pgdmp--sql-y-semillas)
   - [3.6 Paso 5: Ocultación de secretos y clasificación de dependencias](#36-paso-5-ocultación-de-secretos-y-clasificación-de-dependencias)
   - [3.7 Paso 6: Opciones interactivas, 6 chequeos pre-flight y viabilidad](#37-paso-6-opciones-interactivas-6-chequeos-pre-flight-y-viabilidad)
   - [3.8 Paso 7: Armado del CMIR v2.1 y generación híbrida (reglas + IA)](#38-paso-7-armado-del-cmir-v21-y-generación-híbrida-reglas--ia)
   - [3.9 Paso 8: Archivos generados y arranque automático en la EC2 (`user_data.sh`)](#39-paso-8-archivos-generados-y-arranque-automático-en-la-ec2-user_datash)
4. [Caso de Uso 2 (`vm_image`): imágenes de disco, ISO, VM y captura en vivo del SO](#4-caso-de-uso-2-vm_image-imágenes-de-disco-iso-vm-y-captura-en-vivo-del-so)
   - [4.1 Qué mueve al Caso 2 por debajo](#41-qué-mueve-al-caso-2-por-debajo)
   - [4.2 Modo A: Lectura binaria de imágenes (`VMDK`, `QCOW2`, `VHD`, `VHDX`, `RAW`, `OVA`, `OVF`)](#42-modo-a-lectura-binaria-de-imágenes-vmdk-qcow2-vhd-vhdx-raw-ova-ovf)
   - [4.3 Modo B: Sondeo y captura en vivo del sistema operativo (`Live OS Capture`)](#43-modo-b-sondeo-y-captura-en-vivo-del-sistema-operativo-live-os-capture)
   - [4.4 Validación de la imagen: bloqueadores, drivers de arranque y las 8 dimensiones de fidelidad](#44-validación-de-la-imagen-bloqueadores-drivers-de-arranque-y-las-8-dimensiones-de-fidelidad)
   - [4.5 Cuándo usa replicación continua (`AWS MGN`) o importación de imagen](#45-cuándo-usa-replicación-continua-aws-mgn-o-importación-de-imagen)
   - [4.6 Catálogo interactivo y las 4 protecciones para AWS Academy Learner Lab](#46-catálogo-interactivo-y-las-4-protecciones-para-aws-academy-learner-lab)
   - [4.7 Copia en staging, conversión `qemu-img convert` y scripts multi-hipervisor](#47-copia-en-staging-conversión-qemu-img-convert-y-scripts-multi-hipervisor)
   - [4.8 Rehidratación con Cloud-Init y portal web de telemetría en vivo](#48-rehidratación-con-cloud-init-y-portal-web-de-telemetría-en-vivo)
5. [Estructura del proyecto y comandos para correrlo](#5-estructura-del-proyecto-y-comandos-para-correrlo)

---

## 1. Qué resuelve CloudMove y sus 2 casos de uso

Casi todas las herramientas automáticas de migración se estrellan contra dos problemas muy comunes:
1. **Te obligan a reescribir la app**: intentan meter a la fuerza una aplicación monolítica, con archivos en disco local o librerías científicas pesadas (`PostGIS`, `geopandas`, `scikit-learn`) dentro de funciones *serverless* con topes estrictos de peso y tiempo de respuesta, y terminan rompiéndola.
2. **Convierten todo a ciegas**: pasan inventarios directos a plantillas sin decirte qué **vieron de verdad** (`observed`), qué **supusieron por una librería** (`inferred`) y qué **no conocen porque está fuera** (`unknown`). Tampoco frenan cuando un recurso compartido (`is_shared=True`) atiende otros servicios que no pensabas mover todavía.

**CloudMove** resuelve ambos problemas juntando dos escenarios bajo un mismo modelo intermedio (**CMIR v2.1**) y un solo orquestador (**`MigrationOrchestrator`**), apuntando exclusivamente hacia **AWS**:

| Caso de Uso | ID interno | Qué recibe | Módulo principal | Qué termina entregando |
| :--- | :--- | :--- | :--- | :--- |
| **Caso 1: Aplicación desde código fuente o GitHub** | `app_source` | URL de GitHub (`https://github.com/org/repo`), rama/tag/SHA, carpeta local o manifiestos | [`app_migrator.py`](./backend/app/migration/app_migrator.py), [`github_connector.py`](./backend/app/discovery/github_connector.py), [`ai_translator.py`](./backend/app/generators/ai_translator.py) | VPC Multi-AZ, Security Groups, EC2 o ALB+ASG, contenedores Docker Compose, restauración de backups PostgreSQL/PostGIS (`.dump`/`.sql`), reescritura dinámica de `VITE_API_URL` vía IMDSv2 y smoke tests. |
| **Caso 2: Imagen de disco, ISO, VM o captura en vivo del SO** | `vm_image` | Archivo binario (`VMDK`, `QCOW2`, `VHD`, `VHDX`, `RAW`, `OVA`, `OVF`) o servidor vivo conectado con [`cloudmove-agent`](./cloudmove_agent/agent_daemon.py) | [`image_migrator.py`](./backend/app/migration/image_migrator.py), [`uc2_live_probe.py`](./backend/app/migration/uc2_live_probe.py), [`uc2_staging.py`](./backend/app/migration/uc2_staging.py), [`replication_and_import.py`](./backend/app/migration/replication_and_import.py) | Copia en staging comprobada con SHA-256, conversión `qemu-img convert`, ajuste de drivers (`ena`/`nvme`) y `/etc/fstab`, transferencia segura de carpetas por chunks (`1 MiB`), importación nativa (`ec2:ImportImage` / `AWS MGN`), o rehidratación autónoma Cloud-Init con portal web de telemetría en vivo + scripts para VirtualBox y VMware. |

---

## 2. Cómo funciona por dentro: arquitectura de 7 capas

El backend (**Python 3.11+ / FastAPI**) está partido en **7 capas ordenadas y sin ciclos**. Ningún conector escupirá código Terraform por su cuenta: todo lo que entra tiene que convertirse primero en un grafo **CMIR v2.1**, pasar por el filtro de dependencias, traducirse en `AWSAdapter` y superar 4 revisiones antes de tocar la consola de despliegue.

```mermaid
flowchart TB
    subgraph L1["Capa 1: Motores de Descubrimiento Multi-Fuente"]
        GH["GitHub y Source Scanner (github_connector.py + app_migrator.py)"]
        VMI["Inspección Binaria y Captura SO en Vivo (image_migrator.py + uc2_live_probe.py)"]
        AGT["Agente Remoto Outbound y Descubrimiento AWS (agent_daemon.py + cloud_live_discovery.py)"]
    end

    subgraph L2["Capa 2: Representación Intermedia Neutral (CMIR v2.1)"]
        CMIR["Grafo Semántico CMIR v2.1<br/>(cmir/models.py + cmir/builder.py)<br/>Jerarquía Niveles 0..8 + Evidencia Epistémica"]
    end

    subgraph L3["Capa 3: Motor de Grafos y Resolución de Dependencias"]
        NX["Grafo Dirigido networkx.DiGraph<br/>(graph/builder.py)"]
        BFS["Resolución BFS Directa y Transitiva<br/>(dependencies/resolver.py)<br/>Separa: Confirmadas vs Inferidas vs Desconocidas + Recursos Compartidos"]
    end

    subgraph L4["Capa 4: Adaptador Exclusivo de Proveedor Cloud"]
        AWS["AWSAdapter (adapters/aws_adapter.py)<br/>VPC, Subnet, SG, EC2, ALB/ASG, EBS, RDS, S3"]
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
    AGT --> CMIR
    CMIR --> NX --> BFS
    BFS --> AWS
    AWS --> TFGEN --> VAL
    VAL --> ORCH
    ORCH <--> DB
    ORCH --> DEPLOY
```

---

### 2.1 Capa 1: Motores de descubrimiento en solo lectura

Cada tipo de origen tiene su propio módulo lector que **jamás modifica el sistema de origen**:
- **Código fuente y GitHub** ([`backend/app/discovery/github_connector.py`](./backend/app/discovery/github_connector.py) y [`backend/app/migration/app_migrator.py`](./backend/app/migration/app_migrator.py)): clava el análisis al commit SHA exacto vía la API REST de GitHub, baja el `.tar.gz` a un directorio temporal bloqueando *Tar-Slip* y enlaces simbólicos (`filter="data"`), escanea el código Python/JS/TS sin ejecutarlo, lee `docker-compose.yml` y extrae la estructura de backups `PGDMP` de PostgreSQL.
- **Imágenes de disco y SO en vivo** ([`backend/app/migration/image_migrator.py`](./backend/app/migration/image_migrator.py)): inspecciona firmas binarias (`KDMV`, `QFI\xfb`, `conectix`, `vhdxfile`, `0x55AA`, `EFI PART`, `ustar`), corre `qemu-img info -U --output=json` y, cuando captura una máquina encendida, lee directo del sistema operativo con `lsblk -J -b`, `os.statvfs()`, `/etc/os-release`, `ip -j addr`, `ss -tulpn`, `dpkg-query` y `ps`.
- **Agente remoto y cuentas AWS** ([`cloudmove_agent/agent_daemon.py`](./cloudmove_agent/agent_daemon.py), [`backend/app/discovery/osquery_parser.py`](./backend/app/discovery/osquery_parser.py) y [`backend/app/discovery/cloud_live_discovery.py`](./backend/app/discovery/cloud_live_discovery.py)): recoge inventarios reales desde hosts remotos con comunicación saliente segura y consulta recursos vivos en AWS usando las credenciales temporales del usuario.

---

### 2.2 Capa 2: Modelo intermedio neutral (`CMIR v2.1`)

Definida en [`backend/app/cmir/models.py`](./backend/app/cmir/models.py) y armada en [`CMIRBuilder`](./backend/app/cmir/builder.py), la **CloudMove Intermediate Representation (`CMIR v2.1`)** separa la forma en que se descubren los datos de cómo se generan los recursos en AWS.

Cada [`CMIRGraph`](./backend/app/cmir/models.py#L221-L263) agrupa tres piezas:
1. **Nodos (`CMIRNode`)**: cualquier activo de infraestructura o app, acomodado en **9 niveles (`0` a `8`)** dentro de [`TYPE_LEVEL_MAP`](./backend/app/cmir/models.py#L101-L132):
   - **Nivel 0 (`ORGANIZATION`)**: organización o tenant raíz.
   - **Nivel 1 (`ENVIRONMENT`)**: entorno (`production`, `staging`, `datacenter-bogota`).
   - **Nivel 2 (`SITE` / `NETWORK_ZONE`)**: sitio físico o VPC/VNet (`network`, `vpc`).
   - **Nivel 3 (`SUBNET` / `CLUSTER` / `HYPERVISOR` / `FIREWALL`)**: subredes, `security_group` e hipervisores (`vmware_esxi`, `kvm`).
   - **Nivel 4 (`COMPUTE` / `LOAD_BALANCER`)**: servidores físicos (`physical_server`), VMs (`virtual_machine`, `compute`) y balanceadores (`load_balancer`).
   - **Nivel 5 (`STORAGE` / `VOLUME`)**: discos (`storage_volume`, `ebs`), buckets (`object_storage`) e imágenes (`disk_image`).
   - **Nivel 6 (`SERVICE` / `RUNTIME` / `CONTAINER`)**: servicios de app (`application_service`), contenedores (`container_service`) y colas (`queue`).
   - **Nivel 7 (`DATABASE` / `DATASTORE`)**: bases de datos y cachés (`database`, `database_instance`, `cache`).
   - **Nivel 8 (`SCHEMA` / `PORT` / `CONFIG` / `IDENTITY`)**: tablas, esquemas, puertos, variables `.env` ocultadas y roles IAM (`iam_role`).
2. **Evidencia y certeza (`CMIREvidence`)**: aquí es donde vive el "estado epistémico", que en palabras simples indica qué tan confiable es cada dato según de dónde salió [`CMIREvidence`](./backend/app/cmir/models.py#L140-L154):
   - `observed`: visto tal cual en un manifiesto, cabecera binaria, socket abierto o tabla del SO (confianza `0.95 – 1.0`).
   - `derived`: calculado sin ambigüedad desde un dato visto —por ejemplo la subred sacada de IP y máscara— (confianza `0.85 – 0.95`).
   - `inferred`: deducido por pistas —como ver `redis` en `requirements.txt` sin ninguna URL configurada— (confianza `0.50 – 0.75`).
   - `unknown`: apunta a un servicio externo que el escaneo no alcanza a ver por dentro —como un webhook de pagos— (confianza `<= 0.50`).
3. **Relaciones (`CMIRRelationship`)**: flechas con tipo (`contains`, `depends_on`, `connects_to`, `reads_from`, `writes_to`, `mounted_on`, `exposed_by`, `authenticates_with`, `backed_by`) que también llevan su `evidence` y `confidence`.

---

### 2.3 Capa 3: Grafo `networkx.DiGraph` y resolución de dependencias (BFS)

Con el `CMIRGraph` construido, CloudMove lo mete en un grafo dirigido de `networkx` mediante [`InfrastructureGraphBuilder`](./backend/app/graph/builder.py) y corre [`DependencyResolver`](./backend/app/dependencies/resolver.py).

Cuando marcas qué quieres migrar, [`DependencyResolver.resolve_dependencies()`](./backend/app/dependencies/resolver.py#L51-L195) aplica esta secuencia:

1. **Bajar a todos los hijos (`_expand_hierarchical_descendants`)**:
   Si seleccionas un nodo grande (como un servidor Nivel 4 o una VPC Nivel 2), sigue las aristas `contains` hacia abajo (`target_level > source_level`) para sumar también sus discos, contenedores y bases locales.
2. **Búsqueda en anchura (BFS) separando hechos de sospechas**:
   Camina todas las flechas de dependencia (`depends_on`, `connects_to`, `mounted_on`, `backed_by`), manteniendo aparte lo que no está seguro:
   - Si `evidence_type == "unknown"`, lo manda a `unknown_dependencies` y levanta alerta para revisión manual.
   - Si `evidence_type == "inferred"` o `confidence < 0.75`, lo aparta en `inferred_dependencies` para no crear infraestructura por accidente sin que lo confirmes.
   - Solo lo `observed` o `derived` con buena confianza entra en `direct_dependencies` (1 salto) o `transitive_dependencies` ($\ge 2$ saltos en el BFS).
3. **Freno para recursos compartidos (`is_shared`)**:
   Si una base o cola requerida trae `is_shared=True` —o si en el grafo hay otros servicios **por fuera** de tu selección apuntándole—, el resolver la pone en `shared_resources` con:
   ```python
   "auto_migrate": False,
   "requires_validation": True
   ```
   Así evita que al migrar un servicio tumbes o muevas una base que todavía alimenta a otros sistemas.

---

### 2.4 Capa 4: Adaptador único de destino (`AWSAdapter`)

El subgrafo ya filtrado pasa a [`AWSAdapter`](./backend/app/adapters/aws_adapter.py), que hereda de [`BaseProviderAdapter`](./backend/app/adapters/base.py) y traduce únicamente hacia `hashicorp/aws` (`~> 5.0`):
- `network` $\rightarrow$ `aws_vpc` + `aws_internet_gateway` + `aws_route_table`
- `subnet` $\rightarrow$ `aws_subnet` + `aws_route_table_association`
- `security_group` / `firewall` $\rightarrow$ `aws_security_group` (con los puertos `22` y `5432` parametrizados mediante `var.ssh_ingress_cidr` y `var.db_ingress_cidr`)
- `compute` / `virtual_machine` $\rightarrow$ `aws_instance` (o `aws_launch_template` + `aws_autoscaling_group` en modo HA)
- `load_balancer` $\rightarrow$ `aws_lb` + `aws_lb_target_group` + `aws_lb_listener`
- `storage_volume` $\rightarrow$ `aws_ebs_volume` + `aws_volume_attachment`
- `object_storage` $\rightarrow$ `aws_s3_bucket`
- `database` / `database_instance` $\rightarrow$ `aws_db_instance` + `aws_db_subnet_group`

Para que Terraform y AWS no rechacen identificadores raros, normaliza cada nombre con [`sanitize_id()`](./backend/app/adapters/base.py#L46-L55) (`snake_case` para bloques HCL) y [`sanitize_name()`](./backend/app/adapters/base.py#L57-L66) (`kebab-case` de máximo 60 caracteres para AWS). Si alguien seleccionó un servidor suelto sin VPC alrededor, el adaptador le arma la red mínima implícita.

---

### 2.5 Capa 5: Generador modular de Terraform HCL y chequeo en 4 niveles

[`TerraformGenerator`](./backend/app/generators/terraform.py) y [`ai_translator.py`](./backend/app/generators/ai_translator.py) siempre reparten el HCL en **4 archivos modulares** más los scripts operativos:
1. **`provider.tf`**: bloque `terraform { required_version = ">= 1.5.0" ... }` y `provider "aws"`.
2. **`variables.tf`**: variables parametrizables (`aws_region`, `environment`, `instance_type`, `ssh_ingress_cidr`, `db_ingress_cidr`, `db_password` con `sensitive = true`, `github_token`, `enable_vm_import`).
3. **`main.tf`**: red, Security Groups, cómputo, almacenamiento, bases y cloud-init (`user_data_base64 = base64gzip(file("${path.module}/user_data.sh"))`).
4. **`outputs.tf`**: salidas listas para leer (`public_ip`, `application_url`, `frontend_url`, `backend_api_url`, `ssh_command`, `rds_endpoint`, `migration_summary`).

Antes de aceptar el paquete generado, [`BaseProviderAdapter.validate_artifacts()`](./backend/app/adapters/base.py#L140-L246) corre 4 chequeos:
- **Nivel 1 — Llaves balanceadas**: verifica que cada `.tf` tenga la misma cantidad de `{` y `}` y incluya `terraform` y `provider`.
- **Nivel 2 — Sin credenciales quemadas (`Secret Leak Guard`)**: revisa línea por línea buscando llaves `AKIA[0-9A-Z]{16}`, `BEGIN RSA PRIVATE KEY` o contraseñas planas en `db_password` / `password`.
- **Nivel 3 — Referencias cruzadas (`var.*` y `resource.*`)**: extrae lo declarado en `variables.tf` y `main.tf` y confirma que toda referencia usada apunte a un recurso o variable real.
- **Nivel 4 — Formato con Terraform CLI**: si está `/usr/bin/terraform`, corre `terraform fmt -check` / `terraform fmt` para asegurar sintaxis limpia.

---

### 2.6 Capa 6: Orquestador de estados y base transaccional ACID (`SQLite WAL`)

Todo plan corre bajo [`MigrationOrchestrator`](./backend/app/migration/orchestrator.py) y se guarda en [`TransactionalDatabase`](./backend/app/persistence/transactional_db.py) (`backend/data/cloudmove_transactional.db`).

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

*(Nota del flujo en [`orchestrator.py`](./backend/app/migration/orchestrator.py): si una falla pasa ya ejecutando etapas, el reintento puede retomar el estado en progreso desde su `recovery_point`.)*

Lo que el orquestador garantiza en cada corrida:
- **Aprobación manual obligatoria (`APPROVED`)**: nadie puede ejecutar `PREPARING`, `TESTING` ni `READY_FOR_CUTOVER` hasta que un operador apruebe la transición `PLAN_READY -> APPROVED`.
- **El origen queda intacto (`source_environment_destroyed = False`)**: ni durante la migración ni en un `rollback()` CloudMove borra o apaga el servidor o repositorio original; el rollback solo limpia lo creado en AWS.
- **Transacciones ACID y control optimista de versión**: SQLite corre con `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON` y `BEGIN IMMEDIATE` en escrituras. Cada fila tiene un campo `version`: si dos personas editan el mismo plan al tiempo, el segundo recibe [`ConcurrencyConflictError`](./backend/app/persistence/transactional_db.py#L51-L52) en vez de pisar cambios.
- **Candado por etapa (`StageLockedError`) e idempotencia (`idempotency_key`)**: antes de correr una etapa toma un lock exclusivo (`locked_by`, `locked_at`) en `migration_stages` y anota cada ejecución en `stage_executions` bajo `UNIQUE(migration_id, stage_id, idempotency_key)`. En la práctica, esa **idempotencia** significa que si se corta la red y tu navegador reenvía la misma petición con la misma clave, devuelve el resultado anterior sin duplicar instancias en AWS.

---

### 2.7 Capa 7: Consola de despliegue real con Terraform (`CloudDeploymentRunner`)

En [`backend/app/migration/cloud_deployer.py`](./backend/app/migration/cloud_deployer.py), la app puede lanzar Terraform directo sobre **tu propia cuenta AWS** manteniendo aislada cada sesión:
- Solo inyecta las variables `AWS_*` permitidas desde las credenciales que mandaste en la petición HTTP (`_build_env` activa `AWS_EC2_METADATA_DISABLED=true` cuando no hay credenciales en el request y `ALLOW_SERVER_AWS_FALLBACK=false`), así ningún usuario puede colarse usando el rol IAM de la EC2 donde corre CloudMove.
- Lanza comandos reales de `/usr/bin/terraform` (`init`, `validate`, `plan`, `apply -auto-approve`, `refresh`, `destroy -auto-approve`, `force-unlock`) y va transmitiendo `stdout`/`stderr` línea por línea en vivo.
- **Rescate de RDS a medias (`_auto_import_orphaned_rds`)**: como crear un RDS tarda varios minutos, si un `apply` se corta y el siguiente intento falla con `DBInstanceAlreadyExists`, CloudMove captura el error, corre `terraform import aws_db_instance.<addr> <db_id>` y sigue el `apply` solo.
- **Mensajes claros para AWS Academy Learner Lab**: detecta sesiones vencidas (`InvalidClientTokenId`, `ExpiredToken`) o revocación por intentar crear Access Keys (`voc-cancel-cred`), y muestra cómo resolverlo.
- **Lectura del estado real (`inspect_tfstate`)**: lee `terraform.tfstate` para sacar IPs públicas, DNS, endpoints de BD, IDs reales y armar los enlaces directos que ves en pantalla.

---

## 3. Caso de Uso 1 (`app_source`): migrar desde GitHub o código fuente

Aquí ves de principio a fin qué pasa cuando pegas una URL de GitHub (o apuntas a una carpeta local) hasta que el frontend, el backend y la base de datos quedan respondiendo en **AWS**.

### 3.1 Flujo completo del Caso 1

```mermaid
sequenceDiagram
    autonumber
    actor User as Operador / Usuario
    participant API as FastAPI (/api/v1/migration/use-case-1/inspect)
    participant GH as GitHubConnector (discovery/github_connector.py)
    participant AM as AppMigrator (app_migrator.py)
    participant CAT as Catálogo de Transformación & Viabilidad
    participant CMIR as CMIR v2.1 + AWSAdapter
    participant AI as AI/Container Synthesizer (ai_translator.py)
    participant CLOUD as CloudDeploymentRunner (Terraform Live)

    User->>API: Ingresa URL de GitHub + Ref (main) + Credenciales efímeras AWS
    API->>GH: parse_repo_url() & ephemeral_checkout()
    GH->>GH: Consulta API GitHub (/commits/main) -> Fija Commit SHA (40 hex)
    GH->>GH: Descarga Tarball en Sandbox temporal (mkdtemp) con filtro Anti-Tar-Slip y Symlink Guard
    GH->>AM: Entrega árbol de archivos en modo estático (CERO ejecución de código)
    AM->>AM: 1. scan_local_filesystem_tree() (Lenguajes, bytes, manifiestos)
    AM->>AM: 2. discover_app_components_and_code() (Tiers Docker Compose, Rutas FastAPI, Fetch JS, Supabase)
    AM->>AM: 3. discover_database_backups_and_seeds() (Decompila PGDMP .dump / .sql, PostGIS, tablas y filas)
    AM->>AM: 4. Redacta secretos (.env) y clasifica dependencias (observed / inferred / unknown)
    AM->>CAT: build_github_to_cloud_transformation_catalog() + evaluate_app_migration_viability()
    CAT-->>User: Presenta Topología + 6 Chequeos Pre-Flight + Opciones Interactivas de Transformación
    User->>API: Confirma decisiones (user_decisions) y solicita Generar Plan
    API->>CMIR: build_application_cmir() -> DependencyResolver (BFS) -> AWSAdapter
    CMIR->>AI: generate_app_migration_artifacts() (main.tf, user_data.sh, docker-compose, migrate_database_data.sh)
    AI-->>User: Artefactos validados en 4 niveles listos para revisión (PLAN_READY)
    User->>CLOUD: Aprueba Plan (APPROVED) y ejecuta Despliegue en Vivo (terraform init -> plan -> apply)
    CLOUD-->>User: Infraestructura activa + DB restaurada + URLs en vivo
```

---

### 3.2 Paso 1: Bajada desde GitHub, commit SHA fijo y sandbox limpio anti-Tar-Slip

Todo empieza en [`backend/app/discovery/github_connector.py`](./backend/app/discovery/github_connector.py):

1. **Validar la URL (`parse_repo_url`)**: acepta `https://github.com/<owner>/<repo>` y subrutas de rama/archivo.
2. **Pinning del commit SHA**: en lugar de depender de una rama que puede cambiar si alguien sube otro commit mientras planeas la migración, [`resolve_and_pin_commit()`](./backend/app/discovery/github_connector.py#L351-L390) consulta (usando el token en memoria solo para esa llamada):
   ```http
   GET https://api.github.com/repos/{owner}/{repo}/commits/{resolved_ref}
   ```
   De ahí saca el **SHA fijo de 40 caracteres hexadecimales** (`commit_sha`), el mensaje, el autor y la fecha. Desde ese momento, el análisis y el despliegue en EC2 usan exactamente la misma versión del código.
3. **Extracción segura en carpeta temporal**:
   - Crea una carpeta temporal en `/tmp` con `tempfile.mkdtemp(prefix="cloudmove_gh_")`.
   - Baja el tarball oficial de ese SHA (`https://api.github.com/repos/{owner}/{repo}/tarball/{commit_sha}`).
   - Antes de extraer cualquier entrada del `.tar.gz`, filtra rutas absolutas o saltos `..`:
     ```python
     member_path = Path(member.name)
     if member_path.is_absolute() or ".." in member_path.parts:
         continue  # Bloqueo estricto contra ataques Zip-Slip / Path Traversal
     ```
   - **Sin ejecutar código (`static_analysis_only = True`)**: nunca corre `pip install`, `npm install`, scripts de compilación ni archivos del repo. Al terminar la lectura, `finally: shutil.rmtree(temp_dir, ignore_errors=True)` borra el directorio temporal.

---

### 3.3 Paso 2: Recorrido de carpetas, poda de ruido y lectura de manifiestos

Con el tarball ya abierto en la carpeta temporal, [`scan_local_filesystem_tree()`](./backend/app/migration/app_migrator.py#L214-L320) de [`app_migrator.py`](./backend/app/migration/app_migrator.py) hace el inventario base:

1. **Salta carpetas ruidosas (`PRUNED_DIRS`)**: ignora `.git`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.pytest_cache`, `dist`, `build`, `.next` y `.terraform`.
2. **Mide lenguajes por extensión (`LANGUAGE_EXTENSIONS`)**: cuenta archivos y bytes por extensión (`.py` $\rightarrow$ Python, `.ts`/`.tsx` $\rightarrow$ TypeScript, `.js`/`.jsx` $\rightarrow$ JavaScript, `.java` $\rightarrow$ Java, `.go` $\rightarrow$ Go, `.rs` $\rightarrow$ Rust, `.sql` $\rightarrow$ SQL) para sacar el porcentaje real de cada lenguaje.
3. **Lee manifiestos clave (`MANIFEST_NAMES`)**: abre en memoria (con límite de $\le 1\text{ MB}$ por archivo):
   - `package.json`, `requirements.txt`, `pyproject.toml`, `Pipfile`, `pom.xml`, `go.mod`
   - `Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`, `compose.yml`, `Procfile`
   - `.env`, `.env.example`, `.env.sample`, `.env.template`, `alembic.ini`, `nginx.conf`
   Además baja un nivel en subcarpetas (`backend/Dockerfile`, `frontend-vite/package.json`, etc.) para no perder servicios en proyectos monorepo.

---

### 3.4 Paso 3: Escaneo estático de código multi-componente (AST / Regex)

Después, [`discover_app_components_and_code()`](./backend/app/migration/app_migrator.py#L761-L1084) inspecciona cómo hablan las piezas entre sí:

1. **Capas y servicios (`components`)**:
   - Si existe `docker-compose*.yml`, lee cada servicio bajo `services:` (`build.context`, `dockerfile`, `ports` `host:container`, `environment`, `env_file`, `depends_on`, `command`) y clasifica su `tier`:
     - `frontend`: si detecta `vite`, `react`, `nginx`, `next` o puertos `3000` / `5173` / `80`.
     - `database`: si usa imágenes `postgres`, `postgis`, `mysql`, `redis` o `mongo`.
     - `backend`: APIs en Python (`FastAPI`, `Flask`, `Django`), Node (`Express`, `NestJS`), Go o Java.
   - Si no hay `docker-compose.yml`, detecta subcarpetas independientes que tengan su propio `Dockerfile`, `requirements.txt` o `package.json`.
2. **Lectura de código Python (`.py`)**:
   Recorre hasta 120 archivos `.py` buscando:
   - **Rutas HTTP reales**: saca decoradores `@app.get("/ruta")`, `@router.post("/ruta")` y prefijos `APIRouter(prefix="/api/v1")` para armar `api_routes`.
   - **Healthcheck real**: busca `/health`, `/healthz`, `/api/health` o `/ping` para configurar la sonda del Application Load Balancer (`aws_lb_target_group`) y los smoke tests sobre un endpoint que de verdad exista.
   - **Clientes de datos y BaaS**: encuentra llamadas `create_client(...)` de `supabase`, `create_engine(...)` de SQLAlchemy y configuraciones en `alembic.ini`.
3. **Lectura de código Frontend (`.ts`, `.tsx`, `.js`, `.jsx`)**:
   - Saca llamadas HTTP salientes (`fetch(`${API_URL}/...`)`, `axios.get(...)`).
   - Identifica variables compiladas en build (`import.meta.env.VITE_API_URL`, `process.env.NEXT_PUBLIC_API_URL`, `REACT_APP_API_URL`).
   - Revisa si el frontend habla directo con Supabase (`@supabase/supabase-js`) o si solo consume el backend.
4. **Enlaces internos (`internal_service_links`)**:
   Si ve que el `frontend` usa `VITE_API_URL` apuntando al puerto del `backend` (ej. `:8000`), crea un enlace formal `HTTP / REST API (VITE_API_URL)` entre ambos. Ese detalle importa muchísimo en AWS porque el navegador de un usuario final jamás va a poder conectarse a `http://localhost:8000`; necesita la IP pública o el dominio del servidor en la nube.

---

### 3.5 Paso 4: Lectura directa de backups PostgreSQL (`PGDMP` / `.sql`) y semillas

Una ventaja grande del Caso 1 está en [`discover_database_backups_and_seeds()`](./backend/app/migration/app_migrator.py#L519-L758). Cuando el repo incluye un volcado de BD (`supabase_backup.dump`, `backup.sql`, `init.sql`) o archivos semilla (`.geojson`, `.json`), CloudMove los inspecciona por dentro:

1. **Lectura de dumps binarios `PGDMP` (`_extract_sql_from_pgdmp`)**:
   - Lee los primeros 5 bytes del `.dump` o `.backup`. Si empiezan con `b"PGDMP"` (formato *custom* de `pg_dump -Fc`), corre `/usr/bin/pg_restore -f - <archivo.dump>` para sacar en memoria el DDL (`CREATE TABLE`, `CREATE EXTENSION`, `CREATE FUNCTION`) y los bloques de filas (`COPY ... FROM stdin`).
   - Si no estuviera `pg_restore` instalado, trae un respaldo en Python puro que busca flujos comprimidos `zlib` (`0x78 0x9c`, `0x78 0x01`, `0x78 0xda`) dentro del binario y los descomprime con `zlib.decompress()`.
2. **Análisis del SQL (`_parse_sql_dump_text`)**:
   - **Versión del motor origen**: por ejemplo `Dumped from database version 17.6 (Postgres / Supabase)`.
   - **Esquemas (`schemas`)**: separa `public` de esquemas propios de Supabase (`auth`, `storage`, `realtime`, `extensions`, `vault`).
   - **Extensiones (`extensions`)**: detecta `CREATE EXTENSION IF NOT EXISTS postgis`, `pgcrypto`, `uuid-ossp`, `pg_stat_statements`, etc. Si ve `postgis` o columnas `geometry(Point, 4326)` / `geography`, activa `requires_postgis = True` para levantar **`postgis/postgis:17-3.5`** en vez de un PostgreSQL pelado que rompería al importar geometrías.
   - **Tablas, columnas y conteo exacto de filas**: lee cada `CREATE TABLE schema.tabla (...)` con sus columnas y cuenta línea por línea cada `COPY schema.tabla (...) FROM stdin; ... \.` (por ejemplo: `public.zonas_wifi: 185 filas`, `public.puntos_interes: 420 filas`), guardando hasta 3 filas de ejemplo con valores sensibles tapados.
3. **Semillas y scripts (`seed_files`, `loader_scripts`)**:
   Ubica archivos `.geojson`, `.json`, `.csv` y scripts Python (`import_data.py`, `seed.py`) que usan `psycopg2` o `sqlalchemy` para cargar datos.

---

### 3.6 Paso 5: Ocultación de secretos y clasificación de dependencias

En [`_analyze_source_payload()`](./backend/app/migration/app_migrator.py#L1185-L1570), CloudMove limpia contraseñas y clasifica lo que encontró en tres niveles claros:

1. **Doble filtro de secretos (`_redact_env_value` + `SecretRedactor`)**:
   - Cualquier variable en `.env` o `docker-compose.yml` cuyo nombre encaje con `SECRET_KEY_PATTERNS` (`password`, `secret`, `token`, `api_key`, `private_key`, `dsn`, `database_url`, `supabase_key`, etc.) cambia su valor a `***REDACTED***`.
   - Si una URI trae usuario y clave en línea (`postgresql://usuario:MiClaveSecreta@host:5432/db`), `URL_CREDENTIAL_PATTERN` tapa solo la clave (`postgresql://usuario:***REDACTED***@host:5432/db`) manteniendo motor, host y puerto visibles para armar el grafo sin filtrar secretos.
2. **Clasificación de dependencias en 3 niveles**:

| Categoría | Evidencia CMIR | Confianza | Cuándo aplica según [`app_migrator.py`](./backend/app/migration/app_migrator.py#L1400-L1535) |
| :--- | :--- | :---: | :--- |
| **`confirmed`** | `observed` | `0.92 – 0.98` | 1. Servicio declarado en `docker-compose.yml` (ej. `postgres` o `redis`).<br/>2. Librería en manifiesto **junto con** una variable de conexión real en `.env` (ej. `psycopg2` + `DATABASE_URL`).<br/>3. Repositorio con backup `.dump`/`.sql` comprobado.<br/>4. BaaS externo (ej. **Supabase**) confirmado a la vez por SDK (`supabase` / `@supabase/supabase-js`) y variables `SUPABASE_URL` / `SUPABASE_KEY`. |
| **`inferred`** | `inferred` | `0.65` | Librería presente en `requirements.txt`, `package.json`, `pom.xml` o `go.mod` (`redis`, `celery`, `pymongo`, `boto3`), pero **sin servicio en `docker-compose` ni variable de entorno que apunte a un host real**. Queda con `requires_operator_confirmation = True`. |
| **`unknown`** | `unknown` | `0.50` | Variables hacia APIs HTTP externas (`STRIPE_WEBHOOK_SECRET`, `SENDGRID_API_URL`, `EXTERNAL_PAYMENT_API`) que pertenecen a terceros y no se pueden inspeccionar desde tu código. |

---

### 3.7 Paso 6: Opciones interactivas, 6 chequeos pre-flight y viabilidad

Antes de emitir Terraform, [`app_migrator.py`](./backend/app/migration/app_migrator.py) prepara las opciones que puedes ajustar desde la UI y corre chequeos preventivos:

#### A. Catálogo de transformación (`build_github_to_cloud_transformation_catalog`)
Definido en [`app_migrator.py#L1573-L1970`](./backend/app/migration/app_migrator.py#L1573-L1970), arma una tabla de decisiones (`selectable_items`) con un valor recomendado por defecto (`default_choice`) editable vía UI o `user_decisions`:

1. **Arquitectura de cómputo (`compute_architecture`)**:
   - `single_instance_docker_compose`: **1x Instancia EC2 `t3.micro` / GCE `e2-micro` (Capa Gratuita)** corriendo todo con Docker Compose v2 y 2 GB de Swap. *(Recomendado por defecto en AWS Academy o cuando llevas PostGIS dentro del mismo stack para evitar problemas de estado repartido entre nodos).*
   - `ha_alb_asg_containers`: **Alta Disponibilidad Multi-AZ** con Application Load Balancer (`aws_lb`) + Auto Scaling Group (`aws_autoscaling_group`, `min=1, desired=2, max=3`).
   - `decoupled_instances`: instancias separadas por capa (una para Frontend y otra para Backend).
2. **Estrategia por componente (`component:<nombre>`)**:
   - **Frontend** (`React / Vite / Nginx`): contenedor Docker en la instancia (`container_in_primary_host`) exponiendo `3000`/`80`, o sitio estático serverless en S3 / Cloud Storage (`s3_static_website`).
   - **Backend** (`FastAPI / Node / Go / Java`): contenedor con `restart: always`, healthcheck activo y `.env` inyectado.
3. **Estrategia de base de datos y backups (`dep:<id>`)**:
   - **`self_hosted_container`**: levanta un contenedor **PostgreSQL 17 + PostGIS 3.5 (`postgis/postgis:17-3.5`)** en Docker Compose con volumen persistente (`pgdata`) y **restaura solo el `.dump` / `.sql`** en el primer arranque sin costo extra.
   - **`transform_to_cloud_managed`**: crea un **Amazon RDS (`aws_db_instance` `db.t3.micro`)** o **Google Cloud SQL (`google_sql_database_instance`)**, abre acceso solo desde el Security Group de la app e inyecta `migrate_database_data.sh`.
   - **`keep_external`**: mantiene la conexión al servicio externo actual (como seguir usando un proyecto existente en la nube de Supabase sin mover datos).
4. **Tamaño de disco (`storage_and_build_capacity`)**:
   - **30 GB `gp3` (tope Capa Gratuita AWS)** o **50 GB `gp3`**, más **2 GB de Swap (`/swapfile`)** y `docker builder prune -af` para no quedarse sin espacio compilando imágenes.
5. **Reescritura de URLs entre Frontend y Backend (`network_and_env_rewriting`)**:
   - **`auto_rewrite_public_ip` (Recomendado)**: al arrancar en EC2 consulta la IP pública con IMDSv2 (`169.254.169.254`), cambia `VITE_API_URL=http://${PUBLIC_IP}:8000` antes de compilar Vite y abre los puertos `22, 80, 443, 3000, 5432, 8000` en el Security Group.

#### B. Los 6 chequeos Pre-Flight (`preflight_preventive_checks`)
Nacieron directo de errores reales al desplegar en AWS:
1. **`disk_exhaustion_guard`**: Ubuntu 22.04 trae solo **8 GB** de disco raíz por defecto; entre PostGIS (~1.2 GB), Python ML/GIS (~1.8 GB) y Vite/Node (~1.5 GB), un `docker compose build` revienta con `no space left on device`. CloudMove fuerza `root_block_device { volume_size = 30, volume_type = "gp3" }`.
2. **`frontend_localhost_api_guard`**: si compilas Vite/React con `VITE_API_URL=http://localhost:8000` o `http://backend:8000`, cuando alguien abra `http://<IP_PUBLICA>:3000`, su navegador llamará al `localhost` de su propio PC (`ERR_CONNECTION_REFUSED`). `user_data.sh` busca la IP pública real y recompila el bundle apuntando al backend en AWS.
3. **`database_backup_hydration_guard`**: los `.dump` sacados de Supabase traen roles (`anon`, `authenticated`, `service_role`, `supabase_admin`), esquemas (`auth`, `extensions`) y funciones (`auth.uid()`) que un Postgres nuevo no tiene. `migrate_database_data.sh` pre-crea esos roles y esquemas antes de correr `pg_restore --no-owner --no-acl`.
4. **`container_name_collision_and_env_guard`**: limpia contenedores viejos con `docker rm -f` y crea `.env` si falta antes de levantar Compose.
5. **`security_group_multi_port_guard`**: asegura reglas `ingress` en `aws_security_group` / `google_compute_firewall` para todos los puertos detectados (`3000`, `8000`, `80`, `443`, `5432`, `22`).
6. **`aws_academy_iam_and_session_guard`**: evita crear usuarios IAM o Access Keys dentro de AWS Academy Learner Lab (lo cual dispara `voc-cancel-cred` y bloquea la sesión).

#### C. Viabilidad sin reescritura forzada (`evaluate_app_migration_viability`)
En [`app_migrator.py#L2261-L2400`](./backend/app/migration/app_migrator.py#L2261-L2400) valida si el modo pedido (`vm`, `containers` o `serverless`) encaja con la app: si pides `serverless` (`Cloud Run` / `App Runner`) teniendo **volúmenes locales con estado** (`stateful_local_volumes`) o **varios puertos abiertos** en el mismo servicio, marca `compatible_without_refactoring = False` y recomienda correr contenedores sobre VM o ASG (`no_forced_refactoring = True`).

---

### 3.8 Paso 7: Armado del CMIR v2.1 y generación híbrida (reglas + IA)

Con tus opciones listas:
1. **[`build_application_cmir()`](./backend/app/migration/app_migrator.py#L1973-L2258)** arma el `CMIRGraph` v2.1: red (`vpc-{app}`), subred (`subnet-{app}`), grupo de seguridad (`sg-{app}`) y nodo principal (`{app_id}` en Nivel 4). Solo agrega un nodo `database` en Nivel 7 (y su RDS en Terraform) cuando elegiste `transform_to_cloud_managed`; si escogiste `keep_external` o `self_hosted_container`, no crea un RDS innecesario.
2. **[`ai_translator.py`](./backend/app/generators/ai_translator.py) y [`generate_app_migration_artifacts()`](./backend/app/migration/app_migrator.py#L2852-L3536)**:
   - Arma el payload limpio sin secretos en [`prepare_ai_payload()`](./backend/app/generators/ai_translator.py#L77-L207).
   - Escribe `Dockerfile.cloudmove`, `docker-compose.cloudmove.yml` ([`generate_auto_dockerfile_and_compose()`](./backend/app/generators/ai_translator.py#L210-L370)) y el `user_data.sh` ([`generate_container_user_data_sh()`](./backend/app/generators/ai_translator.py#L373-L618)).
   - Genera `provider.tf`, `variables.tf`, `main.tf` y `outputs.tf` según la topología (`single_instance_docker_compose` o `ha_alb_asg_containers`) y los pasa por los 4 niveles de validación de `AWSAdapter` o `GCPAdapter`.

---

### 3.9 Paso 8: Archivos generados y arranque automático en la EC2 (`user_data.sh`)

En `generated/<plan_slug>/`, el Caso 1 produce **13 artefactos**:

| Archivo generado | Qué hace |
| :--- | :--- |
| `provider.tf`, `variables.tf`, `main.tf`, `outputs.tf` | Terraform modular con VPC, subnets, IGW, Security Group (`22, 80, 443, 3000, 5432, 8000` parametrizando `22` y `5432` vía `ssh_ingress_cidr` y `db_ingress_cidr`), EC2 o ALB+ASG con disco `gp3` de `30 GB`, RDS/S3 opcionales e inyección de `user_data.sh` comprimido con `base64gzip(...)`. |
| `user_data.sh` | Script Cloud-Init que corre como `root` la primera vez que prende la EC2. |
| `Dockerfile.cloudmove` | Dockerfile auto-generado (Python/Node/Java/Go) si el repositorio no traía uno. |
| `docker-compose.cloudmove.yml` | Stack con `restart: always`, healthchecks y servicio `db` (`postgis/postgis:17-3.5` o `postgres:16-alpine`) sobre volumen `pgdata`. |
| `migrate_database_data.sh` | Restaura `.dump` (`PGDMP`) o `.sql`, crea antes roles/esquemas de Supabase + `postgis`, corre semillas y valida conteo de filas (`SELECT COUNT(*)`). |
| `{app_slug}.service` | Unidad `systemd` para levantar otra vez el stack de Docker Compose si la EC2 se reinicia. |
| `.env.cloud.template` | Variables de entorno detectadas con todos los secretos redactados. |
| `smoke_test.sh` | Prueba por HTTP `/health` y los puertos abiertos con reintentos exponenciales tras el despliegue. |
| `app_migration_diff_report.json` | JSON comparando código origen vs topología generada en AWS. |
| `DEPLOYMENT_INSTRUCTIONS.md` | Manual paso a paso con arquitectura, comandos y checklist de corte. |

#### Qué ejecuta `user_data.sh` al prender la EC2
1. **Crecer disco raíz y montar 2 GB de Swap**: corre `growpart` / `resize2fs` sobre el volumen de 30 GB y crea `/swapfile` (`2048 MB`) para que una `t3.micro` de 1 GB de RAM no muera por *OOM Killer* compilando paquetes Python o Vite.
2. **Instalar herramientas**: instala `docker.io`, `docker-compose-v2`, `git`, `postgresql-client` (`pg_restore`, `psql`) y `jq`.
3. **Clonar en el commit fijado**: clona el repo en `/opt/cloudmove/<app_slug>` y hace `git checkout <commit_sha>`.
4. **Detectar IP pública vía IMDSv2 y ajustar frontend**: consulta `http://169.254.169.254/latest/meta-data/public-ipv4` y actualiza `VITE_API_URL=http://${PUBLIC_IP}:8000` en `.env` y en los `args:` de build del contenedor `frontend`.
5. **Levantar BD e importar el backup (`migrate_database_data.sh`)**: prende primero el contenedor `db` (o conecta a RDS), espera `pg_isready`, crea esquemas (`auth`, `extensions`, `storage`), roles (`anon`, `authenticated`, `service_role`, `supabase_admin`) y extensiones (`postgis`, `pgcrypto`, `uuid-ossp`), corre `pg_restore --no-owner --no-acl` sobre el `.dump` y deja en `/var/log/cloudmove-user-data.log` el conteo `SELECT table, COUNT(*)` de cada tabla.
6. **Compilar, levantar y registrar servicio**: ejecuta `docker compose up -d --build`, libera espacio con `docker builder prune -af` y activa `<app>.service` con `systemctl enable --now`.

---

## 4. Caso de Uso 2 (`vm_image`): imágenes de disco, ISO, VM y captura en vivo del SO

El **Caso de Uso 2** sirve cuando quieres mover una **máquina completa**: ya sea un archivo de disco virtual (`VMDK`, `QCOW2`, `VHD`, `VHDX`, `RAW`, `OVA`, `OVF`) exportado de VMware ESXi, VirtualBox, Hyper-V o KVM/QEMU, o un **Linux vivo** del que quieres capturar sus discos, particiones, paquetes, usuarios, servicios, procesos y archivos para llevarlos a **AWS** o probarlos en un hipervisor local.

### 4.1 Qué mueve al Caso 2 por debajo

La lógica vive en [`backend/app/migration/image_migrator.py`](./backend/app/migration/image_migrator.py) (junto a [`uc2_live_probe.py`](./backend/app/migration/uc2_live_probe.py) y [`uc2_rehydration_portal.py`](./backend/app/migration/uc2_rehydration_portal.py)) y [`backend/app/migration/replication_and_import.py`](./backend/app/migration/replication_and_import.py):

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

    VAL --> CAT["Catálogo Interactivo de Transformación + 4 Protecciones AWS Academy<br/>(build_vm_image_transformation_catalog)"]
    CAT --> STG["Copia Verificada en Staging (source_sha256 == staging_sha256)<br/>+ Conversión qemu-img convert (si QCOW2 -> RAW)"]
    STG --> ART["Generación de Artefactos AWS & Hipervisor:<br/>Terraform AWS + user_data.sh (Portal en Vivo)<br/>+ launch_virtualbox.sh + launch_vmware.sh (.vmx)"]
```

---

### 4.2 Modo A: Lectura binaria de imágenes (`VMDK`, `QCOW2`, `VHD`, `VHDX`, `RAW`, `OVA`, `OVF`)

Cuando pasas la ruta a un disco virtual, [`inspect_vm_image()`](./backend/app/migration/image_migrator.py#L1408-L1694) llama a [`inspect_binary_disk_header_and_structure()`](./backend/app/migration/image_migrator.py#L406-L567), que abre el archivo solo en lectura binaria (`"rb"`) y lee los primeros `4 KiB` y `256 KiB`:

#### 1. Chequeo de firmas mágicas (`Magic Bytes`)
En lugar de creerle a la extensión del nombre del archivo, revisa los primeros bytes reales:

| Formato | Bytes / offset exacto | Qué lee con `struct.unpack` |
| :--- | :--- | :--- |
| **`VMDK` (Binario Sparse)** | Bytes `0..4 == b"KDMV"` (`0x564d444b`) | Corre `struct.unpack("<IIQ", header[4:20])` para sacar versión, flags y sectores totales (`capacity_sectors * 512`). |
| **`VMDK` (Descriptor de texto)** | Empieza por `# Disk DescriptorFile` | Lee líneas `RW <sectores> SPARSE "<archivo-extent.vmdk>"` o `VMFS "<archivo-flat.vmdk>"`. **Anti-stub**: revisa si el archivo binario de datos (`-flat.vmdk` / `-s001.vmdk`) existe en disco; si no está, lo marca `VMDK_TEXT_STUB` (`is_simulated_text_stub = True`) para frenar antes de subir basura a `ec2:ImportImage`. |
| **`QCOW2` (QEMU Copy-On-Write)** | Bytes `0..4 == b"QFI\xfb"` (`0x514649fb`) | Usa `struct.unpack(">I", header[4:8])` (versión `v2`/`v3`) y `struct.unpack(">Q", header[24:32])` para leer el tamaño virtual de 64 bits en *big-endian*. |
| **`VHD` (Virtual PC / Hyper-V Gen 1)** | Bytes `0..8 == b"conectix"` (o footer de 512 bytes al final) | Confirma disco fijo o dinámico `VHD_CONNECTIX`. |
| **`VHDX` (Hyper-V Gen 2)** | Bytes `0..8 == b"vhdxfile"` | Confirma firma `VHDX_FILE`. |
| **`RAW` / `.img` / `.iso`** | Bytes `510..512 == b"\x55\xaa"` (**MBR**) y/o Bytes `512..520 == b"EFI PART"` (**GPT**) | Revisa bootloader en sector 0 (446 bytes), firma MBR `0x55AA` y tabla GUID (`EFI PART` en LBA 1). |
| **`OVA` (Open Virtual Appliance)** | Bytes `257..262 == b"ustar"` (Tar POSIX) | Comprueba que sea un TAR válido con su `.ovf` y discos `.vmdk` dentro. |
| **`OVF` (Descriptor XML)** | Trae `<?xml` y `<Envelope` | Parsea el XML buscando cada disco asociado (`disks`) para detectar si falta alguno en la carpeta. |

#### 2. Etiquetas GPT en `UTF-16LE` y `qemu-img info`
- En los primeros `256 KiB` busca textos `UTF-16LE` propios de particiones GPT (`EFI-SYSTEM`, `BIOS-BOOT`, `LINUX-ROOT`, `ROOTFS`, `DATA-VOLUME`, `PGSQL-DATA`, `SWAP`) sin tener que montar el disco con `root`.
- Si está `/usr/bin/qemu-img`, corre:
  ```bash
  /usr/bin/qemu-img info -U --output=json <ruta_imagen>
  ```
  El flag `-U` lee sin bloquear el archivo y saca `virtual-size`, `actual-size`, `cluster-size` y el `dirty-flag` (que delata si alguien copió la VM prendida sin pausar el filesystem).
- Por último, [`_compute_file_sha256()`](./backend/app/migration/image_migrator.py#L96-L131) calcula el hash SHA-256 leyendo bloques de 1 MiB (optimizado para archivos *sparse* mayores de 1 GiB) para asegurar luego que la copia en staging sea idéntica bit a bit.

---

### 4.3 Modo B: Sondeo y captura en vivo del sistema operativo (`Live OS Capture`)

Si eliges capturar una máquina en vivo (`capture_live_os=True`, `live://local-os` o un equipo conectado vía agente), corren [`probe_live_storage_devices()`](./backend/app/migration/image_migrator.py#L140-L246) y [`capture_live_operating_system()`](./backend/app/migration/image_migrator.py#L774-L1085). Todo sale directo del kernel Linux y comandos reales del sistema:

1. **Discos y espacio ocupado (`lsblk` + `os.statvfs`)**:
   - Corre `lsblk -J -b -o NAME,PATH,SIZE,RO,TYPE,MOUNTPOINT,FSTYPE,MODEL,SERIAL,UUID,PARTUUID,LABEL`.
   - Llama `os.statvfs(mountpoint)` en cada punto de montaje (`/`, `/boot/efi`, `/home`, `/var`) para medir con precisión tamaño total (`size_gib`), espacio usado (`used_gib`), libre (`free_gib`) y porcentaje (`usage_percent`).
   - Identifica el disco raíz (ej. `/dev/nvme0n1` de `476.94 GiB` con `13.4 GiB` usados) y la partición EFI (`/boot/efi`, `vfat`).
2. **Vaciar caché de escritura a disco (`os.sync()`)**:
   - Ejecuta `os.sync()` para que el kernel baje a disco lo que tenía en buffers de memoria antes de tomar la captura (`consistency_level = "application_quiesced_snapshot"`).
3. **Recolección completa de las 8 partes del SO**:
   - **SO, kernel y boot**: `/etc/os-release` (`PRETTY_NAME`, `VERSION_ID`), `platform.release()`, `platform.machine()` (`x86_64` / `aarch64`), `/proc/meminfo` (`MemTotal`), presencia de `/sys/firmware/efi` (**UEFI** vs **Legacy BIOS**) y gestor `/boot/grub` o `/boot/efi/EFI` (`GRUB2` vs `systemd-boot`).
   - **Usuarios y grupos (`_probe_real_users`)**: lee `pwd.getpwall()`, separando usuarios reales (`UID >= 1000` o `root`) de cuentas del sistema (`UID < 1000`).
   - **Red e interfaces (`_probe_real_network_interfaces`)**: `ip -j addr show` + `/sys/class/net/<iface>/address` y `/mtu` (MAC, MTU, IPs v4/v6 de `eth0`, `enp3s0`, `wlan0`, `docker0`).
   - **Paquetes (`_probe_real_installed_packages`)**: `dpkg-query -W -f=${Package}=${Version}\n` (Debian/Ubuntu) o `rpm -qa` (RHEL/Rocky/Alma).
   - **Servicios y bases de datos (`_probe_running_applications_and_databases`)**: `ps -eo comm` buscando `postgres`, `mysqld`, `mariadbd`, `redis-server`, `mongod`, `nginx`, `apache2`, `dockerd`, `containerd`, `sshd`, `uvicorn`, `gunicorn`, `node`, `java` más unidades `*.service` en `/etc/systemd/system` y `/lib/systemd/system`.
   - **Procesos y puertos abiertos (`_probe_live_running_processes_and_ports`)**: `ss -tulpn` filtrando puertos efímeros ($\ge 32768$) para dejar los reales de escucha (`80`, `443`, `3000`, `5432`, `8000`) y `ps -eo pid,user,%cpu,%mem,comm,args --sort=-%mem`.
   - **Cron y timers (`_probe_live_scheduled_tasks`)**: `/etc/crontab`, `/etc/cron.d/*`, `/var/spool/cron/crontabs` y `systemctl list-timers`.
   - **Archivos y módulos del kernel (`_probe_live_filesystem_and_kernel_metadata`)**: inventario de `/etc`, `/opt`, `/srv`, `/var`, `/usr/local`, `/home` (con permisos, dueño, tamaño y fecha) y `/proc/modules`.
4. **Imagen virtual en staging y paquetes de captura**:
   - Crea en `generated/live_captures/` una imagen `.qcow2` o `.raw` con `/usr/bin/qemu-img create`, escribiendo firma MBR (`0x55AA`) y cabecera GPT (`EFI PART`) con las etiquetas `UTF-16LE` de las particiones vistas en `lsblk`.
   - Genera **`system_image_snapshot_<hostname>.tar.gz`** y **`os_real_files_bundle.tar.gz`** con archivos de `/etc` (`/etc/os-release`, `/etc/hostname`, `/etc/hosts`, `/etc/fstab`, `/etc/environment`, `/etc/sysctl.conf`, `/etc/crontab`, `/etc/systemd/system/*.service`), `restore_system_image.sh` y los manifiestos JSON (`users_manifest.json`, `network_manifest.json`, `services_manifest.json`, `storage_manifest.json`, `processes_manifest.json`, `filesystem_manifest.json`, `installed_packages_manifest.txt`).
   - Deja también **`create_full_raw_disk_clone.sh`** por si el administrador quiere clonar el disco bloque a bloque (`qemu-img convert -p -O qcow2 /dev/nvme0n1 ...` o `dd status=progress | gzip -c`) hacia disco local, **Amazon S3** (`aws s3 cp - s3://...`) o **Google Cloud Storage** (`gcloud storage cp - gs://...`).

---

### 4.4 Validación de la imagen: bloqueadores, drivers de arranque y las 8 dimensiones de fidelidad

[`evaluate_vm_image_compatibility()`](./backend/app/migration/image_migrator.py) revisa si esa máquina puede arrancar sin daños en AWS:

#### 1. Los 4 bloqueadores (`blockers`)
Si pasa cualquiera de estos cuatro casos, marca `compatible = False` y frena antes de aprovisionar:
1. **`simulated_text_stub_missing_extent`**: el `.vmdk`/`.ovf` es solo un descriptor de texto sin su archivo binario (`-flat.vmdk`) y pediste chequeo estricto (`require_authentic_binary = True`).
2. **`dirty_live_disk`**: la cabecera tiene el `dirty-flag` encendido o marcaste que un RAW se copió sin *quiesce* (`source_running_during_raw_copy = True`), lo que corrompería particiones `ext4`/`xfs` o tablas PostgreSQL.
3. **`missing_disk_files`**: un `.ovf` o máquina con varios discos referencia volúmenes que no están en la carpeta.
4. **`require_live_memory_state = True`**: si el usuario marca que necesita copiar tal cual la RAM volátil y sockets TCP activos sin reiniciar procesos, CloudMove bloquea la migración por límite físico del almacenamiento: *mover discos o replicar bloques migra lo guardado en disco, nunca memoria RAM volátil ni conexiones TCP vivas*.

#### 2. Ajustes automáticos de formato, drivers y arranque (`remediation_steps`)
- **Conversión de formato (`conversion_plan`)**: **AWS (`ec2:ImportImage`)** recibe `VMDK`, `VHD`, `VHDX`, `RAW` y `OVA`; si entra un **`QCOW2`**, programa `qemu-img convert -f qcow2 -O raw <staging.qcow2> <staging.raw>` sobre la copia en staging (sin tocar el original).
- **Drivers de hipervisor AWS Nitro (`t3`, `m5`, `c5`, `r6i`)**: revisa módulos **`ena`** (red) y **`nvme` / `nvme_core`** (discos EBS llegan como `/dev/nvme0n1`, no `/dev/xvda`), preparando `dracut -f --add-drivers 'ena nvme nvme_core'` / `update-initramfs -u`.
- **Normalización de `/etc/fstab` a `UUID=`**: si el origen monta `/dev/sda1`, en Nitro fallaría en *emergency mode* al cambiar de nombre el dispositivo; lo pasa a `UUID=<blkid>` o `LABEL=`.
- **DHCP y consola serial (`ttyS0`)**: borra reglas atadas a MACs viejas (`70-persistent-net.rules`), deja red en DHCP para la VPC de AWS y suma `console=ttyS0,115200n8` en `/etc/default/grub`.

#### 3. Las 8 dimensiones de fidelidad (`generate_source_vs_target_diff_report`)
Para dejar claro qué queda igual, qué se adapta y qué no viaja, arma `inventory_diff_report.json` evaluando 8 puntos:

| # | Dimensión | Estado en CloudMove | Qué pasa en realidad |
| :---: | :--- | :--- | :--- |
| **1** | **SO, kernel y usuarios** | `preserved` | Se mantienen distro, versión, usuarios, UIDs/GIDs, hashes y permisos. |
| **2** | **Discos, particiones y archivos** | `preserved_with_uuid_normalization` | Todo volumen (`root` + discos extra) pasa a EBS (`gp3`), con `/etc/fstab` por `UUID=`. |
| **3** | **Paquetes, binarios y runtimes** | `preserved` | Paquetes `.deb`/`.rpm`, librerías de `/usr` y apps en `/opt` o `/srv` quedan intactos. |
| **4** | **Servicios `systemd` y `cron`** | `preserved` | Unidades `.service` y tareas `crontab`/timers siguen activas al iniciar. |
| **5** | **Red, firewalls y puertos** | `adapted_to_cloud_vpc` | IPs fijas y MACs pasan a DHCP dentro de la VPC, y los puertos vistos en `ss -tulpn` se vuelven reglas de `aws_security_group`. |
| **6** | **Arranque (UEFI/BIOS) y drivers** | `remediated_automatically` | Se configura `UEFI` o `Legacy BIOS` y se garantizan los módulos `ena`/`nvme`. |
| **7** | **Consistencia de bases en disco** | `verified_by_consistency_level` | Confirmada por `application_quiesced_snapshot` (`os.sync()`) o `cold_disk_image` (`dirty-flag == False`). |
| **8** | **RAM volátil y sockets TCP activos** | `not_transferred_by_design` | Se deja por escrito: la RAM y sockets abiertos se reinician limpios en el primer boot de la EC2. |

---

### 4.5 Cuándo usa replicación continua (`AWS MGN`) o importación de imagen

En [`backend/app/migration/replication_and_import.py`](./backend/app/migration/replication_and_import.py), [`select_machine_migration_strategy()`](./backend/app/migration/replication_and_import.py#L106-L185) decide el mecanismo en AWS:

| Qué estás migrando | Servicio elegido en AWS | Cuándo conviene y qué invoca (`boto3`) |
| :--- | :--- | :--- |
| **Servidor físico o VM prendida con agente** (`live_server`, `hypervisor_vm` buscando mínimo downtime) | **AWS Application Migration Service (`aws_mgn`)** | Cuando necesitas replicar bloques de forma continua para hacer un corte rápido. Usa `boto3.client("mgn")` (`describe_source_servers`, `start_Replication`, `start_test`, `start_cutover`). |
| **Archivo de disco exportado o snapshot** (`disk_image`: `VMDK`, `QCOW2`, `VHD`, `VHDX`, `RAW`, `OVA`) | **AWS VM Import/Export (`aws_vm_import`)** o **Rehidratación Cloud-Init (`autonomous_cloud_init`)** | Sube la imagen a S3 (`aws_s3_bucket`) y llama `ec2:ImportImage` (`describe_import_image_tasks`) para crear una AMI, o rehidrata por Cloud-Init cuando la cuenta tiene permisos restringidos (como AWS Academy). |

---

### 4.6 Catálogo interactivo y las 4 protecciones para AWS Academy Learner Lab

Igual que el Caso 1, [`build_vm_image_transformation_catalog()`](./backend/app/migration/image_migrator.py#L1991-L2277) te deja escoger tipo de instancia, tamaño de disco y puertos. Además trae **4 reglas automáticas** pensadas para que **AWS Academy Learner Lab (`Vocareum`)** no te bloquee al desplegar:

1. **Tope de 100 GiB por volumen EBS (política IAM `Pvoclabs2`)**:
   - **Problema**: `Pvoclabs2` rechaza con `403 UnauthorizedOperation` cualquier disco EBS mayor a **100 GiB**. Si capturas una laptop con disco de **476 GiB** pero solo **13.4 GiB** ocupados, pedir 476 GiB falla al instante.
   - **Cómo lo evita**: mide el uso real con `os.statvfs` (`used_gib`), sugiere un volumen **`30 GiB gp3`** (dentro de Capa Gratuita y muy debajo de 100 GiB) y guarda el dato físico (`476.94 GiB`) en la etiqueta `Source_Capacity_GiB`.
2. **Sin requerir el rol IAM `vmimport` (`autonomous_cloud_init` por defecto)**:
   - **Problema**: `ec2:ImportImage` exige que exista el rol `vmimport`, y en AWS Academy `iam:CreateRole` está prohibido.
   - **Cómo lo evita**: deja activo **`autonomous_cloud_init` (`enable_vm_import = false`)**. En ese modo Terraform arranca una Ubuntu 22.04 LTS limpia e inyecta el `user_data.sh` para reconstruir los archivos y servicios del origen sin crear roles IAM especiales. (Si tienes una cuenta AWS normal, puedes escoger `s3_vm_import_ami` o pasar `-var="enable_vm_import=true"`).
3. **Deduplicación del puerto 22 (SSH)**:
   - **Problema**: `ss -tulpn` detecta casi siempre `sshd` en el `22`; si se suma otra regla `22` aparte de la regla base de SSH, AWS devuelve `InvalidParameterValue: Duplicate permission`.
   - **Cómo lo evita**: quita el `22` de la lista de puertos descubiertos antes de generar `aws_security_group`.
4. **Compresión `base64gzip` para no pasar el límite de 16 KB en EC2 User-Data**:
   - **Problema**: AWS EC2 rechaza cualquier `user_data` que pase de **16,384 bytes (16 KB)**, y el script con el paquete `os_real_files_bundle.tar.gz` y el manifiesto suele pesar entre 35 KB y 90 KB en texto plano.
   - **Cómo lo evita**: `main.tf` manda el archivo comprimido desde Terraform:
     ```hcl
     user_data_base64 = base64gzip(file("${path.module}/user_data.sh"))
     ```
     Cloud-Init detecta la cabecera `gzip`, lo descomprime al arrancar y mantiene el envío por debajo de ~6 KB.

---

### 4.7 Copia en staging, conversión `qemu-img convert` y scripts multi-hipervisor

Antes de emitir archivos, [`generate_vm_image_migration_artifacts()`](./backend/app/migration/image_migrator.py#L2446-L3723) corre [`prepare_and_verify_staging_copy()`](./backend/app/migration/image_migrator.py#L2280-L2443):

1. **Copia intacta verificada con SHA-256 (`staging_verification.json`)**:
   - Copia la imagen a `generated/staging_images/<plan_slug>/` usando `cp --sparse=always` para respetar huecos dispersos sin llenar el disco innecesariamente.
   - Comprueba con SHA-256 que el archivo copiado sea idéntico al original (`source_sha256 == staging_copy_sha256`, `checksum_verified = True`, `source_untouched = True`).
   - Si el origen es `QCOW2`, corre `/usr/bin/qemu-img convert -f qcow2 -O raw` solo sobre la copia de staging y saca el nuevo `converted_sha256`.
2. **Artefactos generados en `generated/<plan_slug>/`**:
   Aparte de los 4 `.tf` y `user_data.sh`, crea scripts para probar en AWS o en tu propio equipo:
   - **`deploy_to_aws.sh`**: sube la imagen al bucket S3, ejecuta la importación y aplica Terraform.
   - **`create_full_raw_disk_clone.sh`**: clonación directa (`dd` / `qemu-img convert`) a disco local o streaming hacia `s3`.
   - **`restore_system_image.sh`**: reinstala paquetes (`dpkg`/`rpm`), recrea usuarios, aplica `/etc/sysctl.conf` y habilita servicios `systemd`.
   - **`launch_virtualbox.sh`**: convierte la imagen a `.vdi` al vuelo (`VBoxManage convertfromraw` / `qemu-img convert -O vdi`), crea la VM en **VirtualBox** (`VBoxManage createvm`), asigna RAM/CPUs/red (`8080 -> 80`, `2222 -> 22`) y la prende (`VBoxManage startvm`).
   - **`launch_vmware.sh` + `<plan_slug>.vmx`**: genera el `.vmx` para **VMware Workstation / Player / Fusion**, convierte a `.vmdk` si hace falta y arranca la VM con `vmrun start` o `vmplayer`.
   - **`image_manifest.json`, `staging_verification.json`, `inventory_diff_report.json`**: reportes JSON con toda la evidencia del proceso.

---

### 4.8 Rehidratación con Cloud-Init y portal web de telemetría en vivo

Cuando levantas el Caso 2 en AWS, `user_data.sh` deja la instancia rehidratada y verificable desde el navegador:

1. **Descompresión de archivos capturados (`/opt/cloudmove/os_capture/rootfs`)**:
   Extrae en `/opt/cloudmove/os_capture/rootfs/` (y copia al volumen EBS `/mnt/cloudmove_ebs/rootfs/`) los archivos reales de `/etc`, además de recibir lotes extra enviados desde staging por el usuario con filtro anti-Tar-Slip y anti-symlinks.
2. **Usuarios y montajes persistentes**:
   Crea los usuarios humanos detectados (`useradd -m -s /bin/bash`), carga parámetros de `/etc/sysctl.conf` y monta discos EBS adicionales en `/mnt/cloudmove_ebs` anotándolos por `UUID=` en `/etc/fstab`.
3. **Portal web de verificación en vivo (`cloudmove-os-telemetry.service`)**:
   Registra el servicio `systemd` `cloudmove-os-telemetry.service` (servidor Python multihilo en los puertos **`80`**, **`3000`** y **`8000`**) con estas rutas:
   - **`GET /` (Dashboard en vivo)**: muestra el estado real de la EC2 (uptime, load average, RAM, salida `df -h`, comparación disco origen vs volumen EBS), el **Explorador de archivos migrados** (`/etc`, `/opt`, `/var`, `/home`, `/usr/local`, `/srv` dentro de `/etc/cloudmove_migrated_root`), la tabla de procesos/puertos capturados, paquetes (`dpkg`/`rpm`), servicios `systemd`, usuarios y tareas `cron`.
   - **`GET /api/manifest`**: entrega el JSON completo del manifiesto migrado.
   - **`GET /api/live-tree`**: devuelve el árbol de archivos ya escritos en la EC2 junto con la salida real de `df -h` y `lsblk`.
   - **`GET /health`**: healthcheck JSON (`{"status": "healthy", "use_case": "vm_image", ...}`).

---

## 5. Estructura del proyecto y comandos para correrlo

### 5.1 Mapa de directorios clave

```text
CapstoneProject_TI/
├── backend/
│   ├── app/
│   │   ├── adapters/                  # Adaptador exclusivo AWS + Validador de 4 niveles
│   │   │   ├── base.py                # BaseProviderAdapter y validate_artifacts()
│   │   │   └── aws_adapter.py         # Traducción CMIR -> Terraform AWS Provider (~> 5.0)
│   │   ├── core/                      # Controles transversales de seguridad y plano de control
│   │   │   └── security.py            # Protección SSRF DNS/redirects, validate_safe_id e IMDSv2 guard
│   │   ├── api/routers/               # Endpoints FastAPI REST
│   │   │   ├── migration.py           # Router agregador de Casos 1 y 2
│   │   │   ├── migration_uc1.py       # Endpoints del Caso 1 (GitHub y aplicaciones)
│   │   │   ├── migration_uc2.py       # Endpoints del Caso 2 (VMs, captura en vivo y staging)
│   │   │   ├── discovery.py           # Ingesta osquery y escaneo AWS multi-región real
│   │   │   ├── graph.py               # Consultas al grafo y resolución de dependencias BFS
│   │   │   ├── architecture.py        # Exportación Archify + vistas del subgrafo CMIR
│   │   │   ├── terraform.py           # Generación y descarga de paquetes Terraform
│   │   │   └── agents.py              # Enrolamiento, heartbeat con anti-replay nonce y tareas de agentes
│   │   ├── cmir/                      # Representación Intermedia Neutral CMIR v2.1
│   │   │   ├── models.py              # CMIRGraph, CMIRNode, CMIRRelationship, CMIREvidence, Niveles 0..8
│   │   │   └── builder.py             # CMIRBuilder y validación de invariantes del grafo
│   │   ├── dependencies/              # Motor de resolución de dependencias
│   │   │   └── resolver.py            # DependencyResolver (BFS, separación epistémica e is_shared)
│   │   ├── discovery/                 # Conectores y parsers de telemetría de infraestructura
│   │   │   ├── github_connector.py    # Pinning SHA en GitHub + Tarball sandbox Anti-Tar-Slip
│   │   │   ├── osquery_parser.py      # Normalización de snapshots osquery -> CMIR v2.1
│   │   │   ├── connectors.py          # Conectores VMware/Proxmox + SecretRedactor + SSRF Guard
│   │   │   └── cloud_live_discovery.py # Descubrimiento multi-región real en AWS (boto3) + Drift Detection
│   │   ├── generators/                # Síntesis de Infraestructura como Código
│   │   │   ├── terraform.py           # Generador modular HCL (provider.tf, variables.tf, main.tf, outputs.tf)
│   │   │   └── ai_translator.py       # Orquestador Híbrido (Gemini + Fallback Determinista HA & Docker)
│   │   ├── graph/                     # Construcción de grafos dirigidos en memoria
│   │   │   └── builder.py             # InfrastructureGraphBuilder (networkx.DiGraph)
│   │   ├── migration/                 # Motores de los Casos de Uso y Ejecución Cloud
│   │   │   ├── orchestrator.py        # MigrationOrchestrator (Máquina de 12 estados + Safety Guarantees)
│   │   │   ├── app_migrator.py        # Caso 1: AST/Regex, PGDMP parser, Catálogo y Artefactos App
│   │   │   ├── image_migrator.py      # Caso 2: Validación de compatibilidad, catálogo y artefactos VM
│   │   │   ├── uc2_live_probe.py      # Caso 2: Lectura binaria de discos y captura de SO en vivo
│   │   │   ├── uc2_rehydration_portal.py # Caso 2: user_data.sh y portal de telemetría EC2
│   │   │   ├── replication_and_import.py # Caso 2: Matriz AWS MGN y AWS VM Import/Export
│   │   │   ├── uc2_staging.py         # Staging seguro por chunks y descarga autenticada para UC2
│   │   │   └── cloud_deployer.py      # CloudDeploymentRunner (Terraform CLI aislado por petición + tfstate)
│   │   ├── persistence/               # Almacenamiento Transaccional ACID
│   │   │   └── transactional_db.py    # SQLite WAL, Optimistic Concurrency, Stage Locks, Nonces e Idempotencia
│   │   └── security/                  # Hardening, RBAC, Auditoría y Redacción de Secretos
│   │       └── security_hardening.py  # SecretRedactor, RBAC y cadena de auditoría SHA-256
│   └── tests/                         # Suite de pruebas automatizadas (Unitarias, Integración y Seguridad)
├── cloudmove_agent/                   # Agente autónomo outbound para captura de servidores y SO locales
├── deploy/aws/                        # Plantilla Terraform + user_data para desplegar CloudMove en AWS
├── frontend/                          # Interfaz Web Interactiva React 19 + Vite (proxy Nginx /api -> :8000)
├── docs/                              # Documentación detallada carpeta por carpeta (docs/README.md)
└── generated/                         # Directorio de salida de planes Terraform, copias en staging y capturas
```

*(Si quieres ver el detalle archivo por archivo ya actualizado con los módulos nuevos tras la refactorización, revisa también [`docs/README.md`](./docs/README.md)).*

### 5.2 Cómo levantarlo y probarlo

1. **Levantar en producción web (Docker Compose + proxy inverso)**:
   ```bash
   cp .env.example .env
   # Configurar CORS_ORIGINS, CLOUDMOVE_API_URL y ALLOW_SERVER_AWS_FALLBACK=false
   docker compose up -d --build
   ```
   - La plantilla de [`deploy/aws/`](./deploy/aws) crea la EC2 detrás de Caddy/Nginx (`80`/`443` y `/api/* -> 127.0.0.1:8000`), con TLS automático si pasas `domain_name` y acceso SSH restringido mediante `allowed_ssh_cidrs`.

2. **Correr el backend en local (puerto `8000`)**:
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
   - Swagger UI: `http://127.0.0.1:8000/docs`
   - Healthcheck: `http://127.0.0.1:8000/health`

3. **Correr el frontend React + Vite en local (puerto `3000`)**:
   ```bash
   npm --prefix frontend install
   npm --prefix frontend run dev -- --port 3000
   ```
   - Interfaz web: `http://localhost:3000` (o `npm --prefix frontend run build` para generar el estático de producción).

4. **Correr pruebas y linter**:
   ```bash
   .venv/bin/python3 -m pytest -v
   npm --prefix frontend run lint
   npm --prefix frontend run build
   ```
