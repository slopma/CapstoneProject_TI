# CloudMove — Informe Técnico Completo: Caso de Uso 1 (`app_source`)
## Funcionamiento Interno Extremo a Extremo: Del Descubrimiento Estático al Modelo CMIR v2.1, Traducción Cloud y Generación de Terraform

> **Proyecto:** CloudMove — Plataforma de Abstracción Semántica y Migración Selectiva Multicloud  
> **Capstone Project in IT · Universidad EAFIT · 2026-2**  
> **Caso de Uso Analizado:** Caso 1 (`app_source`) — Migración Guiada desde Aplicación, Código Fuente o Repositorio GitHub hacia **AWS** y **GCP**

---

## Tabla de Contenidos

1. [Resumen Ejecutivo del Caso de Uso 1](#1-resumen-ejecutivo-del-caso-de-uso-1)
2. [Arquitectura General y Flujo Extremo a Extremo](#2-arquitectura-general-y-flujo-extremo-a-extremo)
3. [Mapa de Módulos y Archivos que Intervienen](#3-mapa-de-módulos-y-archivos-que-intervienen)
4. [Fase 1: Cómo Funciona Internamente el Descubrimiento (`Discovery`)](#4-fase-1-cómo-funciona-internamente-el-descubrimiento-discovery)
   - [4.1. Tres Vectores de Entrada (`GitHub`, `Directorio Local`, `Inline/Runtime`)](#41-tres-vectores-de-entrada-github-directorio-local-inlineruntime)
   - [4.2. Conector GitHub: Validación, Commit Pinning y Sandbox Efímero Anti-Zip-Slip](#42-conector-github-validación-commit-pinning-y-sandbox-efímero-anti-zip-slip)
   - [4.3. Escaneo Recursivo del Árbol de Archivos e Identificación de Manifiestos](#43-escaneo-recursivo-del-árbol-de-archivos-e-identificación-de-manifiestos)
   - [4.4. Inspección Profunda Multi-Componente y Análisis Estático de Código (AST/Regex)](#44-inspección-profunda-multi-componente-y-análisis-estático-de-código-astregex)
   - [4.5. Reglas de Extracción por Lenguaje, Framework y Contenedor](#45-reglas-de-extracción-por-lenguaje-framework-y-contenedor)
   - [4.6. Política de Seguridad: Redacción Estricta de Secretos y Credenciales en URIs](#46-política-de-seguridad-redacción-estricta-de-secretos-y-credenciales-en-uris)
   - [4.7. Motor de Detección y Clasificación Epistémica de Dependencias (`observed`, `inferred`, `unknown`)](#47-motor-de-detección-y-clasificación-epistémica-de-dependencias-observed-inferred-unknown)
5. [Fase 2: Cómo Transforma lo Descubierto al Modelo Intermedio Neutral (`CMIR v2.1`)](#5-fase-2-cómo-transforma-lo-descubierto-al-modelo-intermedio-neutral-cmir-v21)
   - [5.1. Por qué Existe el CMIR y Qué Estructura Tiene en v2.1](#51-por-qué-existe-el-cmir-y-qué-estructura-tiene-en-v21)
   - [5.2. Construcción Paso a Paso del Subgrafo CMIR (`build_application_cmir`)](#52-construcción-paso-a-paso-del-subgrafo-cmir-build_application_cmir)
   - [5.3. Asignación Automática de Niveles Jerárquicos (0 a 8) y Sincronización Padre-Hijo](#53-asignación-automática-de-niveles-jerárquicos-0-a-8-y-sincronización-padre-hijo)
6. [Fase 3: Grafo en Memoria, Resolución de Dependencias y Evaluación de Viabilidad](#6-fase-3-grafo-en-memoria-resolución-de-dependencias-y-evaluación-de-viabilidad)
   - [6.1. Construcción del `networkx.DiGraph` y Recorrido BFS (`resolve_dependencies`)](#61-construcción-del-networkxdigraph-y-recorrido-bfs-resolve_dependencies)
   - [6.2. Evaluación de Viabilidad sin Refactorización Forzada (`evaluate_app_migration_viability`)](#62-evaluación-de-viabilidad-sin-refactorización-forzada-evaluate_app_migration_viability)
7. [Fase 4: Cómo Traduce el CMIR a Recursos Nativos de AWS y GCP (`Adapters`)](#7-fase-4-cómo-traduce-el-cmir-a-recursos-nativos-de-aws-y-gcp-adapters)
   - [7.1. El Patrón `BaseProviderAdapter` y la Separación entre Traductor y Generador](#71-el-patrón-baseprovideradapter-y-la-separación-entre-traductor-y-generador)
   - [7.2. Matriz Completa de Traducción Semántica (`CMIR` → `AWS` vs `GCP`)](#72-matriz-completa-de-traducción-semántica-cmir--aws-vs-gcp)
   - [7.3. Sanitización Léxica (`safe_id` vs `safe_name`) y Estructura del Diccionario Traducido](#73-sanitización-léxica-safe_id-vs-safe_name-y-estructura-del-diccionario-traducido)
8. [Fase 5: Cómo Crea, Formatea y Valida el Código Terraform y los Artefactos Operativos](#8-fase-5-cómo-crea-formatea-y-valida-el-código-terraform-y-los-artefactos-operativos)
   - [8.1. Generación Modular de los 4 Archivos HCL (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`)](#81-generación-modular-de-los-4-archivos-hcl-providertf-variablestf-maintf-outputstf)
   - [8.2. Cómo Construye `main.tf` Internamente: Red, Seguridad Dinámica, Secretos y Recursos](#82-cómo-construye-maintf-internamente-red-seguridad-dinámica-secretos-y-recursos)
   - [8.3. Formateo con `/usr/bin/terraform fmt` y Auditoría Estructural de 4 Niveles](#83-formateo-con-usrbinterraform-fmt-y-auditoría-estructural-de-4-niveles)
   - [8.4. Generación de Artefactos Operativos Complementarios y Guía de Despliegue (`bundle.zip`)](#84-generación-de-artefactos-operativos-complementarios-y-guía-de-despliegue-bundlezip)
9. [Fase 6: Orquestación por Etapas, Máquina de Estados y Persistencia Transaccional](#9-fase-6-orquestación-por-etapas-máquina-de-estados-y-persistencia-transaccional)
   - [9.1. Máquina de Estados Explícita del `MigrationOrchestrator`](#91-máquina-de-estados-explícita-del-migrationorchestrator)
   - [9.2. Las 12 Etapas Guiadas del Caso de Uso 1 (`uc1-stage-01` a `uc1-stage-12`)](#92-las-12-etapas-guiadas-del-caso-de-uso-1-uc1-stage-01-a-uc1-stage-12)
10. [Caso de Estudio Real Auditable: Trazabilidad Completa de `CocoaApp` (`ReportCocoApp.json`)](#10-caso-de-estudio-real-auditable-trazabilidad-completa-de-cocoaapp-reportcocoappjson)
11. [Referencia de Endpoints API REST del Caso 1](#11-referencia-de-endpoints-api-rest-del-caso-1)

---

## 1. Resumen Ejecutivo del Caso de Uso 1

El **Caso de Uso 1 (`app_source` — Migración Guiada desde Aplicación)** permite tomar una aplicación existente —a partir de un **repositorio real de GitHub** (público o privado), un **directorio local de código fuente** o un conjunto de **manifiestos y descriptores de procesos en ejecución**— y transformarla de manera determinista en:

1. Un **inventario técnico profundo y seguro** (con secretos redactados automáticamente y revisión de código fijada a un commit SHA inmutable).
2. Un **subgrafo semántico neutral CMIR v2.1** donde cada nodo y dependencia conserva su estado epistémico (`observed`, `derived`, `inferred`, `unknown`), nivel de confianza (`0.0` a `1.0`) y evidencia auditable.
3. Una **evaluación de viabilidad cloud en AWS o GCP** que **nunca fuerza refactorizaciones destructivas** (por ejemplo, si detecta estado persistente en disco local o múltiples puertos TCP, alerta de la incompatibilidad con contenedores efímeros tipo Cloud Run/Fargate y recomienda o adapta a `vm_rehost` en EC2/Compute Engine o almacenamiento compartido EFS/Filestore).
4. Un **paquete completo de Infraestructura como Código (Terraform modular)** validado sintácticamente con el binario real `terraform fmt -check`, acompañado de scripts de migración de datos de bases de datos (`pg_dump`/`pg_restore` con verificación SHA-256), unidades `systemd`, plantillas `.env` saneadas, pruebas de humo (`smoke_test.sh`) y un manual de despliegue paso a paso (`DEPLOYMENT_INSTRUCTIONS.md`).

---

## 2. Arquitectura General y Flujo Extremo a Extremo

El siguiente diagrama ilustra el pipeline interno completo que ejecuta CloudMove cuando el usuario invoca el Caso de Uso 1:

```mermaid
flowchart TB
    subgraph Input["1. Fuentes de Entrada (Caso 1: app_source)"]
        GH["Repositorio GitHub\n(URL + Branch/Tag/SHA + Token)"]
        LocalDir["Directorio Local\n(source_path en disco)"]
        Inline["Manifiestos Inline + Runtime Metadata\n(DEFAULT_INLINE_APP / procesos)"]
    end

    subgraph Discovery["2. Motor de Descubrimiento Estático (github_connector.py & app_migrator.py)"]
        Pin["GitHubConnector.resolve_and_pin_commit()\nFija SHA inmutable de 40 caracteres"]
        Sandbox["GitHubConnector.ephemeral_checkout()\nDescarga tarball + filtro Anti-Zip-Slip"]
        TreeScan["scan_local_filesystem_tree()\nÁrbol jerárquico, lenguajes y manifiestos"]
        DeepCode["discover_app_components_and_code()\nDocker Compose, subcarpetas, routers FastAPI, fetch() React, Supabase, Alembic"]
        Payload["_analyze_source_payload()\nRuntime, versión, puertos, volúmenes, healthcheck, start_commands"]
        Redactor["redact_env_value() + SecretRedactor\nRedacción de secretos y URIs con credenciales"]
        DepClass["Clasificador Epistémico de Dependencias\nconfirmed (observed) vs inferred vs unknown"]
    end

    subgraph CMIR_Layer["3. Abstracción Semántica Neutral (app_migrator.py & cmir/builder.py)"]
        BuildAppCMIR["build_application_cmir()\nCrea nodos compute, application, port, volume, identity, dependencies"]
        Hierarchy["build_cmir_hierarchy()\nAsigna niveles 0-8 (TYPE_LEVEL_MAP) y sincroniza parent_id <-> children_ids"]
        CMIR_Obj["Objeto Pydantic CMIR v2.1\n(Nodos + Relaciones + CMIREvidence)"]
    end

    subgraph Graph_Viability["4. Grafo, Dependencias y Viabilidad (graph/builder.py & dependencies/resolver.py)"]
        NX["build_graph(cmir)\nConstruye networkx.DiGraph"]
        BFS["resolve_dependencies()\nRecorrido BFS: directas, transitivas, inferidas y protección shared"]
        Viability["evaluate_app_migration_viability()\nDetecta incompatibilidades stateful/multi-port y define target_architecture"]
    end

    subgraph Translation["5. Traducción al Proveedor Destino (adapters/aws_adapter.py & gcp_adapter.py)"]
        AdapterChoice{"target_provider?"}
        AWS_Ad["AWSAdapter.translate_cmir()\nMapea AWS_RESOURCE_MAP + sanitiza safe_id / safe_name"]
        GCP_Ad["GCPAdapter.translate_cmir()\nMapea GCP_RESOURCE_MAP + sanitiza safe_id / safe_name"]
    end

    subgraph Generation["6. Generación y Validación IaC (generators/terraform.py & deployment_guide_generator.py)"]
        TF_Gen["generate_aws_terraform_files() /\ngenerate_gcp_terraform_files()"]
        TF_Files["4 Archivos HCL Modulares:\nprovider.tf, variables.tf, main.tf, outputs.tf"]
        TF_Fmt["format_terraform_code()\nEjecuta /usr/bin/terraform fmt"]
        TF_Val["BaseProviderAdapter.validate_artifacts()\nLlaves {}, anti-leaks AKIA/PEM, refs cruzadas var.*/resource.* y terraform fmt -check"]
        Extra_Art["generate_app_migration_artifacts() +\ngenerate_deployment_guide()\n.service, .env.cloud.template, migrate_database_data.sh, smoke_test.sh, DEPLOYMENT_INSTRUCTIONS.md"]
    end

    subgraph Orchestration["7. Orquestación y Persistencia ACID (migration/orchestrator.py & transactional_db.py)"]
        Orch["MigrationOrchestrator\n12 Etapas (uc1-stage-01..12) + Máquina de Estados Explícita"]
        DB["TransactionalDatabase (SQLite WAL)\nConcurrencia optimista + Stage Locks + Idempotencia"]
    end

    GH --> Pin --> Sandbox --> TreeScan
    LocalDir --> TreeScan
    Inline --> DeepCode
    TreeScan --> DeepCode --> Payload --> Redactor --> DepClass
    DepClass --> BuildAppCMIR --> Hierarchy --> CMIR_Obj
    CMIR_Obj --> NX --> BFS --> Viability
    Viability --> AdapterChoice
    AdapterChoice -->|aws| AWS_Ad --> TF_Gen
    AdapterChoice -->|gcp| GCP_Ad --> TF_Gen
    TF_Gen --> TF_Files --> TF_Fmt --> TF_Val --> Extra_Art --> Orch --> DB
```

---

## 3. Mapa de Módulos y Archivos que Intervienen

Cada responsabilidad del Caso 1 está desacoplada en módulos específicos dentro del repositorio:

| Capa Arquitectónica | Archivo en el Repositorio | Funciones / Clases Clave | Responsabilidad Principal |
| :--- | :--- | :--- | :--- |
| **1. Conector GitHub** | [`backend/app/discovery/github_connector.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/github_connector.py) | `GitHubConnector`, `parse_repo_url()`, `validate_repository()`, `resolve_and_pin_commit()`, `get_repository_tree()`, `ephemeral_checkout()`, `build_hierarchical_tree()` | Conecta con la API REST de GitHub, valida repositorios públicos/privados, fija el commit SHA de 40 caracteres y extrae el tarball en un directorio temporal seguro. |
| **2. Redacción de Secretos** | [`backend/app/discovery/connectors.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/connectors.py) y [`app_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L100-L127) | `SecretRedactor.redact_text()`, `redact_env_value()` | Intercepta contraseñas, tokens, claves privadas PEM y credenciales embebidas en URLs de conexión antes de que lleguen al CMIR o a la base de datos. |
| **3. Motor Caso 1 (`app_source`)** | [`backend/app/migration/app_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py) | `inspect_application_source()`, `scan_local_filesystem_tree()`, `discover_app_components_and_code()`, `_analyze_source_payload()`, `build_application_cmir()`, `evaluate_app_migration_viability()`, `build_app_migration_stages()`, `generate_app_migration_artifacts()` | Ejecuta el análisis estático multi-lenguaje, clasifica dependencias, construye el CMIR de la aplicación, evalúa viabilidad cloud y genera artefactos operativos. |
| **4. Modelo Semántico CMIR v2.1** | [`backend/app/cmir/models.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/models.py) y [`backend/app/cmir/builder.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/builder.py) | `CMIR`, `CMIRNode`, `CMIRRelationship`, `CMIREvidence`, `build_hierarchical_cmir()`, `build_cmir_hierarchy()`, `TYPE_LEVEL_MAP` | Define los esquemas Pydantic v2.1, normaliza evidencias epistémicas, asigna niveles jerárquicos (0-8) y enlaza padres con hijos. |
| **5. Grafo y Dependencias** | [`backend/app/graph/builder.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/graph/builder.py) y [`backend/app/dependencies/resolver.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/dependencies/resolver.py) | `build_graph()`, `resolve_dependencies()` | Convierte el CMIR en un `networkx.DiGraph` y ejecuta búsqueda en anchura (BFS) separando dependencias confirmadas, inferidas, desconocidas y compartidas. |
| **6. Adaptadores Cloud** | [`backend/app/adapters/base.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/base.py), [`aws_adapter.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/aws_adapter.py), [`gcp_adapter.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/gcp_adapter.py) | `BaseProviderAdapter`, `AWSAdapter`, `GCPAdapter`, `translate_cmir()`, `generate_iac()`, `validate_artifacts()` | Traduce cada nodo abstracto `CMIRNode` a su tipo específico en Terraform (`aws_*` o `google_*`), sanitiza identificadores y valida el HCL generado. |
| **7. Generador Terraform HCL** | [`backend/app/generators/terraform.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/terraform.py) | `generate_aws_terraform_files()`, `generate_gcp_terraform_files()`, `format_terraform_code()` | Construye los bloques sintácticos HCL en 4 archivos (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`) y ejecuta `terraform fmt`. |
| **8. Generador de Guías Cloud** | [`backend/app/migration/deployment_guide_generator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/deployment_guide_generator.py) | `generate_deployment_guide()`, `_build_case_1_guide()` | Genera el manual interactivo `DEPLOYMENT_INSTRUCTIONS.md` adaptado al commit, puerto, runtime y proveedor (AWS ECS Fargate/RDS o GCP Cloud Run/Cloud SQL). |
| **9. Orquestador y API REST** | [`backend/app/migration/orchestrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/orchestrator.py) y [`backend/app/api/routers/migration.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/api/routers/migration.py) | `MigrationOrchestrator`, `/api/v1/migration/github/validate`, `/use-case-1/inspect`, `/use-case-1/migrate`, `/jobs/{id}/*` | Gestiona la máquina de estados, compuertas de aprobación (`APPROVED`), pruebas pre-cutover, empaquetado `.zip` y persistencia SQLite ACID. |
| **10. Interfaz de Usuario (UI)** | [`frontend/src/components/migration/MigrationOrchestratorWorkspace.jsx`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/frontend/src/components/migration/MigrationOrchestratorWorkspace.jsx), [`RepositoryTreeViewer.jsx`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/frontend/src/components/migration/RepositoryTreeViewer.jsx), [`IaCViewer.jsx`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/frontend/src/components/migration/IaCViewer.jsx) | Componentes React 19 | Formulario de inspección GitHub/Local, explorador interactivo del árbol del repositorio, visor multi-pestaña de Terraform y panel de control de las 12 etapas. |

---

## 4. Fase 1: Cómo Funciona Internamente el Descubrimiento (`Discovery`)

El punto de entrada del descubrimiento en el Caso 1 es la función [`inspect_application_source()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L130-L183) en `backend/app/migration/app_migrator.py`.

> [!IMPORTANT]
> **Garantía de Análisis Estático Seguro:** CloudMove **jamás ejecuta código arbitrario** del repositorio analizado (`static_analysis_only = True`, `arbitrary_code_executed = False`). Toda la inspección se realiza mediante análisis léxico, expresiones regulares y árboles de archivos sobre manifiestos y código fuente en modo de solo lectura.

### 4.1. Tres Vectores de Entrada (`GitHub`, `Directorio Local`, `Inline/Runtime`)

`inspect_application_source()` acepta tres modalidades mutuamente complementarias:

1. **Repositorio de GitHub (`github_url`, `github_ref`, `github_token`)**: Si se recibe `github_url`, instancia `GitHubConnector`, fija el commit SHA exacto, descarga el código en un directorio temporal aislado y llama a `_analyze_source_payload()` adjuntando `git_meta`.
2. **Ruta del Sistema de Archivos Local (`source_path`)**: Si se recibe una ruta local, la resuelve con `Path(source_path).expanduser().resolve()`, verifica su existencia y analiza el directorio directamente.
3. **Manifiestos en Memoria (`inline_files`) y Metadatos de Proceso (`runtime_metadata`)**: Si no se provee ni `github_url` ni `source_path`, utiliza por defecto el microservicio de referencia `DEFAULT_INLINE_APP` (una aplicación FastAPI con PostgreSQL, Redis, S3 y variables de entorno en `docker-compose.yml`) o el diccionario `inline_files` suministrado en el payload JSON, combinándolo con puertos/procesos activos pasados en `runtime_metadata`.

---

### 4.2. Conector GitHub: Validación, Commit Pinning y Sandbox Efímero Anti-Zip-Slip

Cuando el usuario ingresa una URL de GitHub en el Caso 1, [`GitHubConnector`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/github_connector.py#L212-L525) ejecuta una secuencia estricta de 4 pasos:

```mermaid
sequenceDiagram
    actor User as Operador / UI
    participantMigrator as inspect_application_source()
    participant GH as GitHubConnector
    participant API as GitHub REST API (v2022-11-28)
    participant TempFS as Sandbox Efímero (/tmp/cloudmove_gh_*)

    User->>participantMigrator: github_url, github_ref, github_token
    participantMigrator->>GH: ephemeral_checkout(url, ref, token)
    GH->>GH: parse_repo_url(url) via GITHUB_URL_REGEX
    GH->>API: GET /repos/{owner}/{repo}/commits/{ref}
    API-->>GH: Commit JSON (SHA de 40 chars, autor, fecha, mensaje)
    GH->>TempFS: tempfile.mkdtemp(prefix="cloudmove_gh_")
    GH->>API: GET /repos/{owner}/{repo}/tarball/{commit_sha}
    API-->>GH: Stream binario .tar.gz
    GH->>TempFS: Extracción segura filtrando rutas absolutas y ".." (Anti-Zip-Slip)
    GH-->>participantMigrator: yield (checkout_path, pinned_metadata)
    participantMigrator->>TempFS: scan_local_filesystem_tree() + discover_app_components_and_code()
    participantMigrator-->>GH: Sale del bloque with
    GH->>TempFS: shutil.rmtree(temp_dir, ignore_errors=True)
```

1. **Validación de Formato URL (`parse_repo_url`)**: Valida mediante `GITHUB_URL_REGEX` tanto URLs HTTPS (`https://github.com/owner/repo`) como SSH (`git@github.com:owner/repo.git`), extrayendo la tupla `(owner, repo)` y rechazando cualquier dominio distinto de GitHub.
2. **Inmovilización de Revisión (`resolve_and_pin_commit`)**: Si el usuario no especificó rama o tag (`ref`), consulta primero `validate_repository()` para obtener `default_branch` (ej. `main`). Luego consulta `/repos/{owner}/{repo}/commits/{target_ref}` y obtiene el **`commit_sha` inmutable de 40 caracteres** (más `short_sha`, `commit_message`, `author_name` y `author_date`). Esto evita que un `git push` ocurrido a mitad de la planificación altere lo que se analizó frente a lo que se despliega.
3. **Descarga y Protección Anti-Path-Traversal (`download_and_extract_tarball`)**: Descarga el archivo `/repos/{owner}/{repo}/tarball/{commit_sha}` usando cabeceras oficiales `Accept: application/vnd.github+json` y `X-GitHub-Api-Version: 2022-11-28`. Al descomprimir con `tarfile.open()`, inspecciona cada miembro antes de extraerlo:
   ```python
   for member in tar.getmembers():
       member_path = Path(member.name)
       if member_path.is_absolute() or ".." in member_path.parts:
           continue
       tar.extract(member, extract_dir)
   ```
4. **Limpieza Garantizada (`ephemeral_checkout`)**: Implementado como un `@contextmanager`. En cuanto termina el análisis estático dentro del bloque `with`, el bloque `finally:` ejecuta `shutil.rmtree(temp_dir, ignore_errors=True)`, garantizando que ningún archivo ni código del usuario quede persistido en el disco del servidor.

---

### 4.3. Escaneo Recursivo del Árbol de Archivos e Identificación de Manifiestos

Una vez localizado el directorio en [`scan_local_filesystem_tree(target_dir)`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L186-L293):

1. **Poda de Directorios de Ruido**: Recorre el árbol con `os.walk(target_dir)` excluyendo in-situ (`dirnames[:] = ...`) los directorios que no aportan definición arquitectónica o contienen dependencias compiladas:
   `{".git", ".svn", ".hg", "__pycache__", ".venv", "venv", "node_modules", ".idea", ".vscode", "dist", "build", ".next", "target", "bin", "obj", ".pytest_cache", ".mypy_cache"}`.
2. **Clasificación Léxica por Extensión**: Cruza la extensión de cada archivo contra el catálogo `LANGUAGE_EXTENSIONS` (que mapea `.py` → `Python`, `.tsx` → `TypeScript (React)`, `.go` → `Go`, `.java` → `Java`, `.tf` → `Terraform`, etc.) y acumula tanto el conteo de archivos (`ext_counter`) como el peso en bytes (`ext_bytes`) para calcular la distribución porcentual de lenguajes del proyecto.
3. **Detección y Lectura Segura de Manifiestos (`is_manifest_file`)**: Identifica todos los archivos cuyo nombre coincide con `MANIFEST_NAMES` (`requirements.txt`, `pyproject.toml`, `package.json`, `pom.xml`, `build.gradle`, `go.mod`, `Cargo.toml`, `Dockerfile`, `docker-compose*.yml`, `.env*`, `alembic.ini`, `app_manifest.yaml`). Si el archivo pesa $\le 1\text{ MB}$ (`1_048_576` bytes), lee su contenido en texto UTF-8 y lo indexa en `manifests_content` tanto por su ruta relativa (`backend/requirements.txt`) como por su nombre base (`requirements.txt`).
4. **Construcción del Árbol Visual (`build_hierarchical_tree`)**: Transforma la lista plana de rutas en un árbol JSON recursivo de nodos `directory` y `file` (ordenando carpetas primero y archivos después alfabéticamente) para ser renderizado en el componente `RepositoryTreeViewer.jsx` del frontend.

---

### 4.4. Inspección Profunda Multi-Componente y Análisis Estático de Código (AST/Regex)

Antes de quedarse únicamente con los manifiestos de la raíz, CloudMove invoca [`discover_app_components_and_code(target_dir, files_map)`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L296-L566) para descubrir arquitecturas **multi-servicio o desacopladas** (por ejemplo, un repositorio monorepo que contiene un `backend/` en FastAPI y un `frontend-vite/` en React):

1. **Descubrimiento de Servicios desde Docker Compose o Subdirectorios**:
   - Si existe algún archivo `*compose*.yml`, parsea el bloque `services:` línea por línea extrayendo cada servicio, su `context:`, su `dockerfile:`, sus puertos `host:container` y su lista `depends_on:`. Clasifica automáticamente el `tier` del componente en `"backend"` (si el nombre contiene `back`, `api`, `server`, `srv`), `"frontend"` (si contiene `front`, `ui`, `web`, `client`) o `"service"`.
   - Si **no** hay Docker Compose, inspecciona las subcarpetas de primer nivel buscando aquellas que tengan su propio `Dockerfile`, `requirements.txt`, `pyproject.toml` o `package.json`. Si detecta un componente `frontend` y otro `backend`, infiere la relación inicial `depends_on: ["backend"]`.
2. **Escaneo Profundo de Código Python (`*.py`)**:
   Recorre todos los archivos `.py` de cada componente buscando:
   - Instanciación de `FastAPI(`.
   - Uso del SDK de Supabase (`create_client` + `"supabase"`).
   - Prefijos de enrutadores: `re.finditer(r"prefix=[\"']([^\"']+)[\"']", txt)` → registra `ROUTER /api/...`.
   - Endpoints HTTP explícitos: `re.finditer(r"@(app|router)\.(get|post|put|delete|patch)\([\"']([^\"']+)[\"']", txt)` → registra `GET /health`, `POST /login`, etc., en `discovered_endpoints`.
3. **Escaneo Profundo de Código Frontend (`*.ts`, `*.tsx`, `*.js`, `*.jsx`)**:
   Recorre los archivos de código cliente buscando:
   - Inicialización de `@supabase/supabase-js` (`createClient`).
   - Llamadas HTTP salientes: `re.finditer(r"fetch\((?:`([^`]+)`|\"([^\"]+)\"|'([^']+)')", txt)` → registra las URLs consumidas en `discovered_api_calls`.
4. **Detección de Herramientas de Migración de Esquema (`alembic.ini`) y BaaS (`*.supabase.co`)**:
   - Verifica si existe `alembic.ini` en la raíz o en `backend/alembic.ini`, activando `alembic_detected = True`.
   - Busca referencias a proyectos de Supabase mediante `https://([a-zA-Z0-9_-]+)\.supabase\.co`, extrayendo el `project_ref` y el `endpoint`.
5. **Mapeo de Enlaces de Malla Interna (`internal_service_links`)**:
   Si hay múltiples componentes (`len(components) > 1`), marca el patrón arquitectónico como `"multi_tier_decoupled"`. Si el frontend invoca `VITE_API_URL` o `API_URL` en sus `fetch()` o depende del backend, registra un enlace interno verificado HTTP/REST entre el componente frontend y el puerto del componente backend.

---

### 4.5. Reglas de Extracción por Lenguaje, Framework y Contenedor

Dentro de [`_analyze_source_payload()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L569-L1160), el analizador consolida los metadatos operativos siguiendo reglas específicas para cada tecnología:

| Fuente / Manifiesto | Qué Extrae Exactamente | Valores por Defecto / Inferencias |
| :--- | :--- | :--- |
| **`app_manifest.yaml`** | `name`, `runtime`, `entrypoint`, `healthcheck` / `health_endpoint`. | Infiere el lenguaje (`Python`, `Node.js`, `Java`, `Go`) a partir de la cadena `runtime`. |
| **Python (`requirements.txt`, `pyproject.toml`)** | Paquetes con sus restricciones de versión, `requires-python`, nombre del proyecto y frameworks (`fastapi`, `flask`, `django`, `tornado`, `aiohttp`). | Si no hay `Dockerfile`, asigna `runtime = "python:3.11"` y `runtime_constraints = ">=3.10,<4.0"`. |
| **Node.js (`package.json`)** | `name`, `engines.node`, script `scripts.start`, `dependencies` y `devDependencies`, detectando `express`, `next`, `nestjs`/`@nestjs/core`, `fastify`, `react`, `vite`. | Si no hay `Dockerfile`, asigna `runtime = "node:20"` y comando `npm start (...)`. |
| **Java (`pom.xml`, `build.gradle`, `build.gradle.kts`)** | `<java.version>` o `<maven.compiler.source>`, `<artifactId>`, dependencias Maven/Gradle y frameworks `Spring Boot` o `Quarkus`. | Asigna `runtime = "openjdk:{ver}"`, comando `java -jar target/{slug}.jar` y agrega automáticamente `/actuator/health` (Spring Boot) o `/q/health` (Quarkus) a `health_endpoints`. |
| **Go (`go.mod`)** | Directiva `go 1.x`, nombre del `module`, módulos requeridos y frameworks `gin-gonic/gin`, `gofiber/fiber`, `labstack/echo`. | Asigna `runtime = "golang:{ver}"` y comando `./bin/{slug}`. |
| **`Dockerfile`** | Imagen base en `FROM`, puertos en `EXPOSE`, rutas de persistencia en `VOLUME ["/ruta"]`, URL de sonda en `HEALTHCHECK` y comandos en `CMD` / `ENTRYPOINT`. | Sobrescribe `runtime` con la imagen base exacta del contenedor (ej. `python:3.11-slim` o `nginx:alpine`). |
| **`docker-compose.yml`** | Mapeos de puertos `- "host:container"`, variables `- KEY=VALUE`, montajes de volumen `- /host:/container`, nombres de servicios bajo `services:` y URLs de `healthcheck`. | Agrega los puertos expuestos, las rutas de volumen y usa los servicios declarados como evidencia confirmada de bases de datos/cachés/colas. |

> [!NOTE]
> Si tras inspeccionar todos los manifiestos y `runtime_metadata` la aplicación no declara ningún puerto explícito, CloudMove asigna el puerto estándar `[8080]`. Si no declara `HEALTHCHECK`, asume `["/health"]` y registra esta suposición explícitamente en la lista `assumptions` del reporte de descubrimiento.

---

### 4.6. Política de Seguridad: Redacción Estricta de Secretos y Credenciales en URIs

Al parsear `.env`, `.env.example` y la sección `environment:` de `docker-compose.yml`, cada par `clave=valor` pasa obligatoriamente por [`redact_env_value(key, raw_value)`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L100-L127):

1. **Detección por Nombre de Clave (`SECRET_KEY_PATTERNS`)**:
   Evalúa la expresión regular:
   ```python
   SECRET_KEY_PATTERNS = re.compile(
       r"(SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|PRIVATE_KEY|CREDENTIAL|AUTH_KEY|CLIENT_SECRET|DB_PASS)",
       re.IGNORECASE,
   )
   ```
   Si el nombre de la variable coincide (o el valor contiene `"PRIVATE KEY"`), el valor se reemplaza inmediatamente por `"[REDACTED_SECRET]"` y se marca `is_secret = True`, `value_stored = False`.
2. **Redacción Quirúrgica de Credenciales en URLs de Conexión (`URL_CREDENTIAL_PATTERN`)**:
   Si una variable como `DATABASE_URL` o `REDIS_URL` contiene usuario y contraseña en línea (`postgresql://admin:MiClaveSecreta123@postgres:5432/appdb`), la expresión regular `r"([a-zA-Z0-9+.-]+://[^:/\s]+:)([^@\s]+)(@)"` reemplaza **únicamente el segmento de la contraseña**:
   ```text
   Entrada:  postgresql://admin:MiClaveSecreta123@postgres:5432/appdb
   Salida:   postgresql://admin:[REDACTED_SECRET]@postgres:5432/appdb
   ```
   De este modo, CloudMove conserva el protocolo (`postgresql://`), el host (`postgres`), el puerto (`5432`) y la base de datos (`appdb`) para construir la topología, sin almacenar jamás la contraseña en el CMIR ni en disco.
3. **Filtro Adicional por Patrones de Valor (`SecretRedactor.redact_text`)**:
   Incluso si el nombre de la variable parece inocuo, `SecretRedactor` inspecciona el valor buscando patrones de claves AWS (`AKIA...`), tokens JWT/Bearer o cadenas de alta entropía, redactándolos si se detectan.

---

### 4.7. Motor de Detección y Clasificación Epistémica de Dependencias (`observed`, `inferred`, `unknown`)

Una de las características de diseño más importantes de CloudMove v2.1 (documentada en [`ADR-002`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/docs/ADR/ADR-002-extended-cmir-v2_1-and-evidence-provenance.md)) es que **nunca confunde una pista heurística con un hecho confirmado**. El analizador clasifica cada dependencia descubierta en tres estados epistémicos:

| Servicio / Dependencia | Cuándo se Clasifica como `confirmed` (`epistemic_state = "observed"`) | Cuándo se Clasifica como `inferred` (`epistemic_state = "inferred"`) | Cuándo se Clasifica como `unknown` (`epistemic_state = "unknown"`) |
| :--- | :--- | :--- | :--- |
| **Supabase (BaaS PostgreSQL + Auth)** | Cuando detecta el SDK `@supabase/supabase-js` o `supabase` junto con la URL verificada `https://<ref>.supabase.co` (`confidence = 0.99`, `requires_data_migration = False`). | — | — |
| **PostgreSQL (`database_instance`)** | Cuando existe un servicio `postgres`/`db` en `docker-compose.yml` **o** están presentes tanto el driver (`psycopg`, `sqlalchemy`, `pg`, `asyncpg`, `pgx`) como la variable de conexión (`DATABASE_URL`, `POSTGRES_HOST`, `SPRING_DATASOURCE_URL`) (`confidence = 0.98`, `requires_data_migration = True`). | Cuando el driver (`psycopg2-binary`, `pg`, etc.) aparece en los paquetes instalados (`requirements.txt` / `package.json`), pero **no** hay servicio en Compose ni variable de entorno con endpoint confirmado (`confidence = 0.65`). | — |
| **Enlace Interno Frontend ↔ Backend (`service_mesh_link`)** | Cuando `discover_app_components_and_code` verifica que el componente Frontend consume la API del componente Backend vía `VITE_API_URL` / `depends_on` (`confidence = 0.98`). | — | — |
| **Redis (`cache`)** | Cuando hay servicio `redis` en Compose **o** librería cliente (`redis`, `ioredis`, `go-redis`) + variable `REDIS_URL`/`REDIS_HOST` (`confidence = 0.96`). | — | — |
| **RabbitMQ / AMQP (`queue`)** | Cuando existe simultáneamente un servicio `rabbit`/`mq` en Compose **y** la variable `RABBITMQ_URL`/`BROKER_URL` (`confidence = 0.92`). | Cuando solo aparece la librería (`celery`, `pika`, `amqplib`) o solo uno de los indicadores sin confirmación cruzada (`confidence = 0.70`). | — |
| **Almacenamiento de Objetos (`storage` S3/GCS)** | — | Cuando detecta una variable con `*BUCKET*` o un SDK de almacenamiento (`boto3`, `aws-sdk`, `storage`) (`confidence = 0.78`). | — |
| **Endpoints HTTP Externos (`network_connection`)** | — | — | Cualquier variable externa `*_API_URL` o `*_WEBHOOK` (ej. `EXTERNAL_API_URL=https://api.external-service.com/v1`), porque desde el análisis estático se desconoce si ese host es público en Internet o requiere un túnel VPN/DirectConnect privado desde la nube (`confidence = 0.50`). |

---

## 5. Fase 2: Cómo Transforma lo Descubierto al Modelo Intermedio Neutral (`CMIR v2.1`)

### 5.1. Por qué Existe el CMIR y Qué Estructura Tiene en v2.1

Sin un modelo intermedio, traducir $N$ tipos de orígenes (GitHub, directorios locales, imágenes VM, campañas osquery/Proxmox, AWS live, GCP live) hacia $M$ proveedores destino exigiría mantener $N \times M$ traductores acoplados. Con **CMIR (CloudMove Intermediate Representation) v2.1**, todos los descubrimientos convergen primero en una representación matemática única validada con Pydantic v2 ([`backend/app/cmir/models.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/models.py)):

- **`CMIRNode`**: Representa cualquier entidad arquitectónica con:
  - Identidad determinista: `id`, `canonical_id` (`asset:<categoria>:<slug>`), `name`, `type`, `category`.
  - Ubicación en la jerarquía: `parent_id`, `children_ids`, `level` (`0` a `8`).
  - Contexto técnico: `provider`, `platform`, `engine`, `location`, `environment`, `is_shared`, `security`, `network`, `metadata`.
  - Trazabilidad epistémica v2.1: `epistemic_state` (`observed | derived | inferred | unknown`), `confidence` (`0.0` a `1.0`), `source_connector`, `discovered_at` y una lista tipada `evidence: List[CMIREvidence]`.
- **`CMIRRelationship`**: Representa una arista dirigida (`source` → `target`) con su `type` semántico (`runs_on`, `exposes`, `mounts`, `requires_identity`, `reads_from`, `connects_to`, `inferred_relation`, `communicates_with`, `consumes_api`, `part_of`), su propio `epistemic_state`, `confidence` y lista `evidence`.

---

### 5.2. Construcción Paso a Paso del Subgrafo CMIR (`build_application_cmir`)

La función [`build_application_cmir(app_discovery, target_provider, deployment_mode)`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1162-L1488) toma el diccionario devuelto por `inspect_application_source()` y construye los nodos y relaciones del modelo neutral siguiendo este orden exacto:

```mermaid
flowchart LR
    subgraph Host["Nivel 5: Compute Host"]
        CompNode["CMIRNode: compute-{slug}-host\ntype: virtual_machine | container\ncanonical_id: asset:compute:{slug}"]
    end

    subgraph AppLayer["Nivel 6: Aplicación"]
        AppNode["CMIRNode: app-{slug}\ntype: application\nparent_id: compute-{slug}-host"]
    end

    subgraph AtomicResources["Nivel 8: Recursos Atómicos, Red, Identidad y Datos"]
        PortNode["CMIRNode: port-{slug}-{p}\ntype: port (tcp)\nparent_id: compute-{slug}-host"]
        VolNode["CMIRNode: vol-{slug}-{idx}\ntype: volume (50 GiB)\nparent_id: compute-{slug}-host"]
        IdNode["CMIRNode: identity-{slug}-sa\ntype: identity (IAM Role / GCP SA)\nepistemic_state: derived"]
        DBNode["CMIRNode: dep-{slug}-postgresql\ntype: database_instance (postgres)\nepistemic_state: observed | inferred"]
        CacheNode["CMIRNode: dep-{slug}-redis\ntype: cache (redis)\nepistemic_state: observed"]
        ExtNode["CMIRNode: dep-{slug}-ext-*\ntype: network_connection (https)\nepistemic_state: unknown"]
    end

    AppNode -->|runs_on| CompNode
    AppNode -->|exposes| PortNode
    AppNode -->|mounts| VolNode
    AppNode -->|requires_identity| IdNode
    AppNode -->|reads_from / inferred_relation| DBNode
    AppNode -->|connects_to| CacheNode
    AppNode -->|communicates_with| ExtNode
```

1. **Nodo Host de Ejecución (`compute-{slug}-host`)**:
   - Si `deployment_mode == "vm_rehost"`, le asigna `type = "virtual_machine"`. Si `deployment_mode == "container"`, le asigna `type = "container"`.
   - Adjunta la evidencia del runtime detectado y, si provino de GitHub (`git_metadata`), agrega una segunda evidencia con `confidence = 1.0` registrando la URL del repositorio, el `commit_sha` de 40 caracteres, el autor y el mensaje del commit.
2. **Nodo de Aplicación Principal (`app-{slug}`)**:
   - `type = "application"`, `parent_id = compute_id`, `platform = framework`.
   - En `metadata` guarda `start_commands`, `exposed_ports`, `health_endpoints` y **únicamente la lista de nombres** de las variables de entorno (`env_var_keys`), garantizando que ningún valor de variable de entorno viaje dentro del grafo CMIR.
   - Crea la relación `app-{slug} --[runs_on]--> compute-{slug}-host`.
3. **Sub-Nodos Multi-Componente (si `len(components) > 1`)**:
   - Por cada microservicio o capa descubierta (ej. `backend`, `frontend`), crea un nodo `compute-{slug}-{c_slug}` y un nodo `app-{slug}-{c_slug}` (`parent_id = c_comp_id`), con relaciones `runs_on` hacia su cómputo y `part_of` hacia la aplicación raíz `app-{slug}`.
   - Por cada enlace en `internal_service_links`, añade una relación `consumes_api` entre el nodo de aplicación origen y el destino (ej. `app-cocoaapp-frontend --[consumes_api]--> app-cocoaapp-backend`).
4. **Nodos de Puertos Expuestos (`port-{slug}-{p}`)**:
   - Por cada puerto TCP en `exposed_ports`, crea un nodo `type = "port"`, `parent_id = compute_id`, con `metadata: {"port": p, "protocol": "tcp"}` y la relación `app-{slug} --[exposes]--> port-{slug}-{p}`.
5. **Nodos de Volúmenes Persistentes (`vol-{slug}-{idx}`)**:
   - Por cada ruta en `persistent_volumes`, crea un nodo `type = "volume"`, `parent_id = compute_id`, con `metadata: {"mount_path": vol_path, "size_gib": 50}` y la relación `app-{slug} --[mounts]--> vol-{slug}-{idx}`.
6. **Nodo de Identidad de Mínimo Privilegio (`identity-{slug}-sa`)**:
   - Crea un nodo `type = "identity"` con `epistemic_state = "derived"` y `metadata: {"role_type": "IAM Role" if provider == "aws" else "GCP Service Account"}`, enlazado mediante `app-{slug} --[requires_identity]--> identity-{slug}-sa`.
7. **Nodos de Dependencias Externas e Internas (`dep-...`)**:
   - Itera sobre `app_discovery["dependencies"]` y convierte cada una en un `CMIRNode` preservando su `type` (`database_instance`, `cache`, `queue`, `storage`, `network_connection`), su `engine` (`postgres`, `redis`, `rabbitmq`, `s3_compatible`, `https`), su `epistemic_state`, su `confidence` y su lista `evidence`.
   - Añade la relación correspondiente (`reads_from`, `reads_and_writes`, `connects_to`, `inferred_relation`, `communicates_with`) desde `app-{slug}` hacia `dep["id"]`.

---

### 5.3. Asignación Automática de Niveles Jerárquicos (0 a 8) y Sincronización Padre-Hijo

Al finalizar la creación de las listas `nodes` y `relationships`, `build_application_cmir()` invoca [`build_cmir_hierarchy()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/builder.py#L117-L249) en `backend/app/cmir/builder.py`. Esta función:

1. Consulta el diccionario `TYPE_LEVEL_MAP` para asignar a cada nodo su nivel dentro de la taxonomía de 9 niveles de CloudMove:
   - `virtual_machine` → **Nivel 5** (Unidad de Virtualización / Máquina Virtual)
   - `application` → **Nivel 6** (Ámbito de Aplicación)
   - `application_component` / `service` / `workload` → **Nivel 7** (Componente / Servicio)
   - `container`, `database_instance`, `cache`, `storage`, `volume`, `queue`, `identity`, `port`, `network_connection` → **Nivel 8** (Recurso Atómico / Componente Técnico)
2. Normaliza todas las entradas de evidencia a instancias validadas de `CMIREvidence`.
3. Recorre todos los nodos que tienen `parent_id` (por ejemplo, `app-{slug}`, `port-{slug}-80` y `vol-{slug}-0` que apuntan a `compute-{slug}-host`) e inyecta automáticamente sus IDs dentro del arreglo `children_ids` del nodo padre, dejando el árbol bidireccionalmente consistente para la navegación drill-down del frontend.

---

## 6. Fase 3: Grafo en Memoria, Resolución de Dependencias y Evaluación de Viabilidad

### 6.1. Construcción del `networkx.DiGraph` y Recorrido BFS (`resolve_dependencies`)

Con el objeto `CMIR` construido, [`evaluate_app_migration_viability()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1491-L1593) ejecuta dos operaciones sobre el motor de grafos:

1. **Construcción del Grafo Dirigido ([`build_graph(cmir)`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/graph/builder.py))**:
   Instancia un `networkx.DiGraph()`, inserta cada `CMIRNode` como vértice con todos sus atributos Pydantic serializados, añade aristas jerárquicas (`is_hierarchy = True`) desde cada `parent_id` hacia su hijo, y añade todas las relaciones semánticas de `cmir.relationships` como aristas dirigidas.
2. **Resolución Topológica y Epistémica de Dependencias ([`resolve_dependencies(graph, [app_id])`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/dependencies/resolver.py#L6-L158))**:
   - **Paso 1 (Expansión de Descendientes)**: Incluye el nodo seleccionado (`app-{slug}`) y todos sus hijos jerárquicos (`get_descendants`).
   - **Paso 2 (Dependencias Directas y Filtro Epistémico)**: Inspecciona las aristas salientes (`out_edges`) no jerárquicas:
     - Si la arista o el nodo destino tiene `epistemic_state == "unknown"`, lo registra en `unknown_dependencies`.
     - Si la arista tiene `epistemic_state == "inferred"` o `type == "inferred_relation"`, la añade a `inferred_dependencies` (con su explicación detallada en `inferred_dependency_details`) y, si `include_inferred=False` (valor por defecto), **no la mezcla silenciosamente con las dependencias confirmadas (`confirmed_dependencies`)**.
     - Si la arista es `observed` o `derived`, la clasifica en `required_direct` y `confirmed_dependencies`.
   - **Paso 3 (Cierre Transitivo BFS)**: Mediante una cola FIFO (`to_visit`), recorre en anchura todas las dependencias de segundo o mayor grado (`required_transitive`).
   - **Paso 4 (Detección y Protección de Recursos Compartidos)**: Para cada dependencia requerida, inspecciona sus aristas entrantes (`in_edges`). Si está marcada con `is_shared = True` o tiene consumidores fuera del subgrafo seleccionado, la clasifica en `shared_dependencies` y genera una política en `shared_dependency_policies` con `auto_migrate = False` y `requires_validation = True`.

---

### 6.2. Evaluación de Viabilidad sin Refactorización Forzada (`evaluate_app_migration_viability`)

CloudMove evalúa si el modo de despliegue solicitado (`deployment_mode = "vm_rehost"` o `"container"`) preserva el comportamiento de la aplicación en la nube destino (`aws` o `gcp`):

1. **Regla Anti-Pérdida de Datos en Sistemas de Archivos Locales (`stateful_local_filesystem`)**:
   Si se solicita `deployment_mode == "container"` (AWS ECS Fargate o Google Cloud Run) pero la aplicación monta volúmenes locales (`persistent_volumes` no vacío), registra una incompatibilidad explícita explicando que el sistema de archivos local en Fargate/Cloud Run es efímero, y recomienda usar `vm_rehost` (`Amazon EC2 + EBS` / `Google Compute Engine + Persistent Disk`) o adjuntar almacenamiento elástico compartido (`Amazon EFS` / `Cloud Filestore`).
2. **Regla de Múltiples Puertos en Google Cloud Run (`multi_port_listener_on_cloud_run`)**:
   Si el destino es `gcp`, el modo es `"container"` y la aplicación expone más de un puerto TCP (`len(exposed_ports) > 1`), detecta que Cloud Run solo permite exponer un único puerto HTTP/gRPC por servicio y cambia automáticamente `recommended_deployment_mode = "vm_rehost"` (Google Compute Engine o GKE) para preservar todos los puertos TCP sin modificar el código.
3. **Generación de Advertencias Epistémicas (`warnings`)**:
   - Emite una advertencia por cada dependencia inferida (`inferred_count > 0`) recordando al arquitecto que debe validar su uso antes del cutover.
   - Emite una advertencia por cada endpoint externo con alcanzabilidad desconocida (`unknown_count > 0`).
4. **Síntesis de Arquitectura Objetivo (`target_architecture`)**:
   Construye el mapa de servicios cloud recomendados para la aplicación:
   - **En AWS**: `Amazon EC2` / `ECS Fargate` / `EKS`, `Amazon RDS for PostgreSQL (Multi-AZ) + AWS DMS / pg_dump`, `Amazon ElastiCache for Redis`, `Amazon MQ for RabbitMQ`, `Amazon EBS gp3 + Amazon S3`, `AWS Secrets Manager` y `Amazon VPC + Security Groups`.
   - **En GCP**: `Google Compute Engine` / `Cloud Run v2` / `GKE`, `Cloud SQL for PostgreSQL (Regional HA)`, `Memorystore for Redis`, `Cloud Pub/Sub`, `Persistent Disk SSD + Cloud Storage (GCS)`, `Google Secret Manager` y `Google VPC Network + Firewall Rules`.

---

## 7. Fase 4: Cómo Traduce el CMIR a Recursos Nativos de AWS y GCP (`Adapters`)

### 7.1. El Patrón `BaseProviderAdapter` y la Separación entre Traductor y Generador

Para evitar mezclar la lógica de negocio de mapeo cloud con la concatenación de cadenas HCL, CloudMove divide la transformación final en dos capas claramente separadas:

```text
[ Objeto CMIR v2.1 (Nodos Neutros) ]
                 │
                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ CAPA 1: ADAPTADOR DE PROVEEDOR (backend/app/adapters/*.py)         │
│ - AWSAdapter.translate_cmir(cmir)                                  │
│ - GCPAdapter.translate_cmir(cmir)                                  │
│ Traduce cada CMIRNode neutro a un diccionario con el tipo de       │
│ recurso de Terraform destino, regiones válidas e IDs sanitizados.  │
└────────────────────────────────────────────────────────────────────┘
                 │  Lista de diccionarios traducidos (List[Dict])
                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ CAPA 2: GENERADOR SINTÁCTICO HCL (backend/app/generators/terraform.py)│
│ - generate_aws_terraform_files(translated_resources)               │
│ - generate_gcp_terraform_files(translated_resources)               │
│ Emite los archivos provider.tf, variables.tf, main.tf y outputs.tf │
│ y los formatea con /usr/bin/terraform fmt.                         │
└────────────────────────────────────────────────────────────────────┘
```

---

### 7.2. Matriz Completa de Traducción Semántica (`CMIR` → `AWS` vs `GCP`)

Cuando `generate_app_migration_artifacts()` invoca `adapter.generate_iac(cmir)`, el adaptador recorre cada `CMIRNode` en `cmir.resources` y consulta su tabla de traducción (`AWS_RESOURCE_MAP` en [`aws_adapter.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/aws_adapter.py#L9-L66) o `GCP_RESOURCE_MAP` en [`gcp_adapter.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/gcp_adapter.py#L9-L66)):

| Nodo en el Subgrafo CMIR del Caso 1 (`node.type`) | Qué Representa en la Aplicación Descubierta | Recurso Terraform en **AWS** (`AWS_RESOURCE_MAP`) | Recurso Terraform en **GCP** (`GCP_RESOURCE_MAP`) |
| :--- | :--- | :--- | :--- |
| **`virtual_machine`** / **`compute`** | Host de ejecución de la aplicación (`compute-{slug}-host`) en modo `vm_rehost` | `aws_instance` | `google_compute_instance` |
| **`container`** / **`application_component`** | Contenedor de la aplicación o microservicio en modo `container` | `aws_ecs_task_definition` | `google_cloud_run_v2_service` |
| **`application`** | Aplicación principal (`app-{slug}`) o sub-aplicaciones (`app-{slug}-{comp}`) | `aws_instance` | `google_compute_instance` |
| **`port`** / **`listening_port`** | Puerto TCP expuesto por la aplicación (`port-{slug}-{p}`, ej. `80`, `8000`, `8080`) | `aws_security_group_rule` *(e inyectado como bloque `ingress` en `aws_security_group.app_sg`)* | `google_compute_firewall` |
| **`volume`** / **`disk`** | Ruta de almacenamiento persistente montada (`vol-{slug}-{idx}`) | `aws_ebs_volume` (`gp3`, 50 GiB) | `google_compute_disk` (`pd-ssd`, 50 GiB) |
| **`identity`** / **`role`** | Identidad de carga de trabajo de mínimo privilegio (`identity-{slug}-sa`) | `aws_iam_role` | `google_service_account` |
| **`database_instance`** / **`database`** | Base de datos relacional confirmada o inferida (`dep-{slug}-postgresql`) | `aws_db_instance` (`postgres` / `mysql` + `aws_db_subnet_group`) | `google_sql_database_instance` (`POSTGRES_15` / `MYSQL_8_0` + `google_sql_user`) |
| **`cache`** | Clúster de caché en memoria (`dep-{slug}-redis`) | `aws_elasticache_cluster` (`redis`, puerto `6379`) | `google_redis_instance` (`REDIS_7_0`, `BASIC`) |
| **`storage`** / **`bucket`** | Bucket de almacenamiento de objetos (`dep-{slug}-object-storage`) | `aws_s3_bucket` | `google_storage_bucket` |
| **`queue`** / **`topic`** | Cola de mensajería asíncrona (`dep-{slug}-rabbitmq`) | `aws_sqs_queue` *(o `aws_mq_broker` en discovery replatform)* | `google_pubsub_topic` |
| **`network_connection`** | Endpoint HTTPS externo referenciado en `.env` (`dep-{slug}-ext-*`) | `aws_security_group_rule` | `google_compute_firewall` |
| **`secret`** | Secreto parametrizado para gestor de secretos | `aws_secretsmanager_secret` | `google_secret_manager_secret` |
| **`system_service`** / **`process`** | Demonio `systemd` o proceso en ejecución dentro del SO | `in_guest_service` / `in_guest_process` *(no crea VM extra; se genera como archivo `{slug}.service`)* | `in_guest_service` / `in_guest_process` *(se genera como archivo `{slug}.service`)* |

---

### 7.3. Sanitización Léxica (`safe_id` vs `safe_name`) y Estructura del Diccionario Traducido

Terraform HCL exige que los identificadores de bloques (`resource "<tipo>" "<safe_id>"`) no contengan espacios, puntos ni dos puntos, y por convención utiliza `snake_case`, mientras que los nombres de recursos dentro de las APIs de AWS y GCP (como buckets S3, identificadores RDS o instancias Compute Engine) exigen `kebab-case` en minúsculas.

Por ello, `translate_node(node: CMIRNode)` ejecuta dos transformaciones léxicas sobre cada nodo:

```python
safe_name = node.name.lower().replace(" ", "-").replace("_", "-").replace("/", "-")
safe_id   = node.id.lower().replace("-", "_").replace(".", "_").replace(":", "_").replace("/", "_")
```

Y retorna un diccionario normalizado por cada recurso del CMIR:

```json
{
  "id": "dep-cocoaapp-postgresql-inferred",
  "canonical_id": "asset:dep:dep-cocoaapp-postgresql-inferred",
  "safe_id": "dep_cocoaapp_postgresql_inferred",
  "name": "cocoaapp-postgresql",
  "safe_name": "cocoaapp-postgresql",
  "cmir_type": "database_instance",
  "type": "aws_db_instance",
  "engine": "postgres",
  "platform": null,
  "location": "us-east-1",
  "environment": "production",
  "epistemic_state": "inferred",
  "confidence": 0.65,
  "security": {},
  "network": {},
  "metadata": {
    "port": 5432,
    "classification": "inferred",
    "requires_data_migration": true
  }
}
```

---

## 8. Fase 5: Cómo Crea, Formatea y Valida el Código Terraform y los Artefactos Operativos

### 8.1. Generación Modular de los 4 Archivos HCL (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`)

El módulo [`backend/app/generators/terraform.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/terraform.py) recibe la lista de diccionarios traducidos por el adaptador y construye una arquitectura Terraform modular dividida en cuatro archivos estándar de industria:

| Archivo HCL | Propósito y Contenido Generado |
| :--- | :--- |
| **`provider.tf`** | Define el bloque `terraform { required_version = ">= 1.5.0" }` y fija las versiones de los proveedores oficiales (`hashicorp/aws ~> 5.0` o `hashicorp/google ~> 5.0`, junto con `hashicorp/random ~> 3.5` para generación criptográfica de contraseñas). Configura el bloque `provider` consumiendo las variables de región/proyecto. |
| **`variables.tf`** | Declara todas las variables parametrizables: `aws_region` (o `gcp_project_id`, `gcp_region`, `gcp_zone`), `environment`, `vpc_cidr` (o `subnet_cidr`), `ami_id` (o `custom_image_name`) y **`db_password`** marcada explícitamente con `sensitive = true` y `default = null` para evitar contraseñas en texto plano. |
| **`main.tf`** | Contiene la infraestructura base (generador aleatorio de contraseñas, VPC, IGW, subredes públicas y privadas Multi-AZ, Security Groups / Firewalls dinámicos, Subnet Groups de base de datos, cuentas de servicio) seguida de todos los bloques `resource` emitidos para cada nodo del CMIR. |
| **`outputs.tf`** | Exporta los identificadores de la red y subredes aprovisionadas (`vpc_id`, `public_subnet_id` en AWS; `gcp_vpc_id`, `gcp_primary_subnet_id` en GCP) para integración con pipelines CI/CD o módulos posteriores. |

---

### 8.2. Cómo Construye `main.tf` Internamente: Red, Seguridad Dinámica, Secretos y Recursos

Analizando [`generate_aws_terraform_files()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/terraform.py#L37-L449) y [`generate_gcp_terraform_files()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/terraform.py#L456-L808), la construcción de `main.tf` sigue 5 pasos algorítmicos:

#### Paso 1: Gestión de Credenciales Maestras con Cero Hardcoding (`random_password` + `locals`)
Para garantizar que `terraform plan` y `terraform apply` funcionen de inmediato sin obligar a hardcodear una contraseña en `variables.tf`, el generador emite al inicio de `main.tf`:
```hcl
# Dynamic secure credentials generation (zero hardcoded secrets)
resource "random_password" "db_master_password" {
  length  = 24
  special = false
}

locals {
  effective_db_password = var.db_password != null && var.db_password != "" ? var.db_password : random_password.db_master_password.result
}
```
Si el operador inyecta `TF_VAR_db_password`, se usa ese valor; de lo contrario, Terraform genera una contraseña aleatoria segura de 24 caracteres en el estado local/remoto.

#### Paso 2: Recolección Dinámica de Puertos Expuestos y Creación del Perímetro de Red
El generador inspecciona todos los recursos traducidos del CMIR buscando nodos con `cmir_type == "port"` o listas `metadata.exposed_ports`:
```python
app_ingress_ports = {80, 443}
for r in resources:
    if r.get("cmir_type") == "port":
        pval = r.get("metadata", {}).get("port")
        if isinstance(pval, int):
            app_ingress_ports.add(pval)
    for ep in r.get("metadata", {}).get("exposed_ports", []):
        if isinstance(ep, int):
            app_ingress_ports.add(ep)
```
Por cada puerto ordenado en `sorted(app_ingress_ports)`, construye un bloque `ingress` TCP en `aws_security_group.app_sg` (además de crear `aws_vpc.target_vpc`, `aws_internet_gateway.igw`, `aws_subnet.public_subnet` en `10.0.1.0/24`, `aws_subnet.private_subnet_a` en `10.0.2.0/24` y `aws_subnet.private_subnet_b` en `10.0.3.0/24`).

#### Paso 3: Aislamiento Automático de la Capa de Datos (`has_db` / `has_cache`)
El generador verifica si entre los recursos traducidos existe alguna base de datos o caché:
```python
has_db = any(
    r.get("cmir_type") in ("database", "database_instance", "database_schema")
    or r.get("type") == "aws_db_instance"
    for r in resources
)
has_cache = any(
    r.get("cmir_type") == "cache" or r.get("type") == "aws_elasticache_cluster"
    for r in resources
)
```
Si `has_db` o `has_cache` es `True`, inyecta automáticamente:
1. Un grupo de seguridad dedicado para datos (`aws_security_group.data_sg`) cuyas reglas `ingress` para los puertos `5432` (PostgreSQL) y `6379` (Redis) **no permiten tráfico desde `0.0.0.0/0`**, sino exclusivamente desde el grupo de seguridad de la aplicación (`security_groups = [aws_security_group.app_sg.id]`).
2. Un `aws_db_subnet_group.db_subnets` que agrupa las dos subredes privadas Multi-AZ (`private_subnet_a` y `private_subnet_b`).

#### Paso 4: Emisión Polimórfica de Bloques `resource` por Tipo Traducido
A continuación, itera sobre cada recurso `r` en `resources`:
- **Filtro In-Guest**: Si `r_type in ("in_guest_service", "in_guest_process")` o `cmir_type in ("system_service", "process")`, hace `continue` (ya que un servicio `systemd` o proceso corre dentro del sistema operativo de la VM y no debe convertirse en una máquina virtual adicional).
- **Si `r_type == "aws_instance"`** (o `google_compute_instance` en GCP):
  Emite la instancia de cómputo conectada a la subred y al `aws_security_group.app_sg`, resolviendo dinámicamente la AMI (`var.ami_id != "" ? var.ami_id : "ami-0c55b159cbfafe1f0"`).
- **Si `r_type == "aws_db_instance"`** (o `google_sql_database_instance` en GCP):
  Detecta el motor (`postgres` o `mysql`), asigna `password = local.effective_db_password`, `publicly_accessible = false`, la ubica en `aws_db_subnet_group.db_subnets.name` y la protege con `[aws_security_group.data_sg.id]`. En GCP, crea tanto el `google_sql_database_instance` con alta disponibilidad regional (`availability_type = "REGIONAL"`, IP privada en `google_compute_network.target_vpc.id`) como el recurso `google_sql_user`.
- **Si `r_type == "aws_elasticache_cluster"`** (o `google_redis_instance` en GCP):
  Emite el clúster Redis 7 en el puerto `6379` protegido por `data_sg` (o conectado a `authorized_network = google_compute_network.target_vpc.id` en GCP).
- **Si `r_type == "aws_s3_bucket"`** (o `google_storage_bucket` en GCP):
  Emite el bucket con prefijo `cloudmove-{r_name}` y control de acceso uniforme.
- **Si `r_type == "aws_ebs_volume"`** (o `google_compute_disk` en GCP):
  Emite el volumen de bloques SSD (`gp3` en AWS / `pd-ssd` en GCP) de 50 GiB para las rutas `VOLUME` detectadas en la aplicación.
- **Trazabilidad en Tags/Labels**: Cada recurso emitido incluye etiquetas de auditoría que vinculan el recurso cloud con su nodo CMIR original:
  ```hcl
  tags = {
    Name      = "cocoaapp-runtime-host"
    CMIR_ID   = "compute-cocoaapp-host"
    ManagedBy = "CloudMove"
  }
  ```

---

### 8.3. Formateo con `/usr/bin/terraform fmt` y Auditoría Estructural de 4 Niveles

Antes de dar por válido el código Terraform generado y permitir que el orquestador pase al estado `PLAN_READY`, CloudMove ejecuta dos mecanismos de control de calidad:

1. **Formateo Canónico (`format_terraform_code` en [`terraform.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/terraform.py#L8-L35))**:
   Por cada uno de los 4 archivos (`.tf`), verifica si el binario `/usr/bin/terraform` está instalado (`shutil.which("terraform")`). Si está disponible, escribe el código en un archivo temporal y ejecuta `terraform fmt` mediante `subprocess.run(..., timeout=5)`, devolviendo el HCL formateado según el estándar oficial de HashiCorp.
2. **Validación Estructural y de Referencias Cruzadas (`BaseProviderAdapter.validate_artifacts` en [`base.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/base.py#L66-L162))**:
   Inspecciona el paquete de archivos `.tf` en 4 niveles:
   - **Nivel 1 (Integridad Léxica y Balanceo de Llaves)**: Verifica que ningún archivo esté vacío y que el número de llaves de apertura `{` sea exactamente igual al de llaves de cierre `}` en cada archivo `.tf`.
   - **Nivel 2 (Escaneo Anti-Fuga de Credenciales)**: Busca patrones de claves de acceso AWS (`\bAKIA[0-9A-Z]{16}\b`) o llaves privadas (`BEGIN RSA PRIVATE KEY`). Si encuentra alguna, aborta la validación con error crítico.
   - **Nivel 3 (Resolución Cruzada de Símbolos HCL)**:
     Extrae todas las declaraciones `variable "<nombre>"` y `resource "<tipo>" "<nombre>"` a lo largo de todos los archivos `.tf`. Luego, sobre el código sin comentarios, busca todas las referencias `var.<nombre>` y `(aws|google)_<tipo>.<nombre>.<atributo>`. Si `main.tf` u `outputs.tf` referencia una variable o un recurso que no fue declarado en `variables.tf` o `main.tf`, registra el error exacto.
   - **Nivel 4 (Verificación CLI Real `terraform fmt -check`)**:
     Escribe los 4 archivos en un directorio temporal y ejecuta `/usr/bin/terraform fmt -check -no-color <tmp_dir>`. Si el código de retorno es `0`, registra:
     ```json
     "terraform_cli_installed": true,
     "terraform_fmt_check_passed": true,
     "terraform_cli_output": "terraform fmt -check: OK (0 errors)"
     ```
     Si `valid` resulta `False`, el `MigrationOrchestrator` transiciona automáticamente el trabajo al estado `FAILED` e impide su aprobación.

---

### 8.4. Generación de Artefactos Operativos Complementarios y Guía de Despliegue (`bundle.zip`)

Como aprovisionar infraestructura vacía en Terraform no equivale por sí solo a migrar una aplicación en producción, [`generate_app_migration_artifacts()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1742-L1852) y [`generate_deployment_guide()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/deployment_guide_generator.py#L83-L443) generan **6 artefactos adicionales** que se empaquetan junto con los 4 archivos `.tf` en el archivo descargable `GET /api/v1/migration/jobs/{migration_id}/bundle.zip`:

| Archivo en `bundle.zip` | Cómo se Crea y Para Qué Sirve |
| :--- | :--- |
| **`{slug}.service`** | Unidad `systemd` lista para producción (`WorkingDirectory=/srv/{slug}`, `EnvironmentFile=/etc/{slug}/{slug}.env`, `ExecStart={start_cmd}`, `Restart=on-failure`) para ejecutar la aplicación en instancias EC2 o Compute Engine. |
| **`.env.cloud.template`** | Plantilla de configuración con todas las claves de variables de entorno descubiertas y sus valores sensibles redactados (`[REDACTED_SECRET]`), lista para poblar desde AWS Secrets Manager o Google Secret Manager. |
| **`migrate_database_data.sh`** | Runbook Bash (`set -euo pipefail`) de 4 pasos para migrar los datos reales de la base de datos: (1) snapshot consistente en origen con `pg_dump --format=custom --serializable-deferrable`, (2) cálculo y verificación de hash `sha256sum`, (3) restauración en Amazon RDS o Google Cloud SQL con `pg_restore`, y (4) verificación de paridad de conteo de filas por tabla. |
| **`smoke_test.sh`** | Script automatizado post-despliegue que comprueba con `nc -z -w 3 127.0.0.1 $port` cada puerto TCP expuesto por la aplicación y ejecuta `curl -fsS http://127.0.0.1:{main_port}{health_ep}` para validar respuesta HTTP 200 OK. |
| **`app_migration_diff_report.json`** | Reporte JSON auditable de paridad funcional que certifica el runtime preservado, el comando de entrada, los puertos, el endpoint de salud, el número de secretos redactados y si incluye migración de datos de base de datos. |
| **`DEPLOYMENT_INSTRUCTIONS.md`** | Manual técnico paso a paso generado dinámicamente por `_build_case_1_guide()` con los comandos exactos para clonar el repositorio en el commit fijado (`git checkout {commit_sha}`), instalar dependencias según el lenguaje detectado, construir y publicar la imagen Docker en **Amazon ECR** (o **Google Artifact Registry**), ejecutar `terraform init/plan/apply`, desplegar en **ECS Fargate** (o **Cloud Run**), cargar secretos en **Secrets Manager**, correr migraciones (`alembic upgrade head` / `prisma migrate`) y verificar el servicio. |

---

## 9. Fase 6: Orquestación por Etapas, Máquina de Estados y Persistencia Transaccional

### 9.1. Máquina de Estados Explícita del `MigrationOrchestrator`

Todo trabajo del Caso 1 es gobernado por [`MigrationOrchestrator`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/orchestrator.py) y almacenado transaccionalmente en SQLite WAL ([`TransactionalDatabase`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py)):

```mermaid
stateDiagram-v2
    [*] --> DRAFT: create_migration(use_case="app_source")
    DRAFT --> DISCOVERING: run_discovery_and_assessment()
    DISCOVERING --> ASSESSED: inspect_application_source() + build_application_cmir() + evaluate_viability() [0 blockers]
    DISCOVERING --> FAILED: Bloqueadores críticos o error de conector GitHub
    ASSESSED --> PLAN_READY: generate_plan_and_artifacts() [Terraform válido]
    ASSESSED --> FAILED: Fallo en validate_artifacts()
    PLAN_READY --> APPROVED: approve_migration() [Compuerta humana obligatoria]
    APPROVED --> PREPARING: advance_execution() [Etapas 6 y 7]
    PREPARING --> TESTING: advance_execution() [Etapas 8 y 9]
    TESTING --> READY_FOR_CUTOVER: advance_execution() + verify_application_health_and_functional_tests() [Etapa 10]
    TESTING --> FAILED: Fallo de arranque o HTTP 503 en sonda de salud
    READY_FOR_CUTOVER --> COMPLETED: advance_execution() [Etapas 11 y 12: Cutover + Validación Post-Cutover]
    PREPARING --> ROLLED_BACK: rollback_migration()
    TESTING --> ROLLED_BACK: rollback_migration()
    READY_FOR_CUTOVER --> ROLLED_BACK: rollback_migration()
    FAILED --> PREPARING: retry_failed_stage()
    FAILED --> ROLLED_BACK: rollback_migration()
```

**Salvaguardas Arquitectónicas del Orquestador:**
1. **Compuerta de Aprobación Obligatoria (`APPROVED`)**: Ninguna llamada a `advance_execution()` puede iniciar el aprovisionamiento (`PREPARING`), las pruebas (`TESTING`) ni el `CUTOVER` si el plan no ha sido aprobado previamente mediante `approve_migration()`, registrando `approved_by` y `approved_at`.
2. **Control de Concurrencia Optimista y Bloqueo Atómico de Etapa**: Cada mutación verifica `expected_version` (devolviendo HTTP 409 Conflict ante escrituras concurrentes) y adquiere un cerrojo exclusivo en base de datos (`acquire_stage_lock`) para que dos operadores no puedan ejecutar la misma etapa simultáneamente.
3. **Ejecución Idempotente (`idempotency_key`)**: Cada intento de ejecución de etapa se registra en la tabla `idempotent_stage_executions`. Si se reenvía una petición con la misma `idempotency_key`, devuelve el resultado previo sin duplicar recursos.
4. **Honestidad Operativa (`simulated_dry_run` vs `live_cloud`)**: Si no hay credenciales reales activas o se ejecuta con `dry_run=True`, el orquestador marca explícitamente `execution_mode = "simulated_dry_run"` y `completed_in_real_cloud = False`, sin fingir jamás que se crearon recursos en una cuenta real de AWS o GCP.
5. **Preservación Estricta del Origen (`source_environment_destroyed = False`)**: CloudMove opera bajo la política `PRESERVED_READ_ONLY_STANDBY`, garantizando que el código y el entorno de origen permanezcan intactos para permitir un rollback inmediato revirtiendo el enrutamiento/DNS.

---

### 9.2. Las 12 Etapas Guiadas del Caso de Uso 1 (`uc1-stage-01` a `uc1-stage-12`)

La función [`build_app_migration_stages()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1701-L1740) estructura el ciclo de vida del Caso 1 en 12 etapas secuenciales con puntos de recuperación (`checkpoint-uc1-stage-01` a `checkpoint-uc1-stage-12`):

| Orden | ID de Etapa | Estado del Orquestador Asociado | Descripción Técnica de la Etapa |
| :---: | :--- | :---: | :--- |
| **1** | `uc1-stage-01` | `DISCOVERING → ASSESSED` | Descubrimiento estático de código, manifiestos y runtime (sin ejecutar código arbitrario) y redacción de secretos. |
| **2** | `uc1-stage-02` | `DISCOVERING → ASSESSED` | Construcción del subgrafo CMIR v2.1 y clasificación de dependencias (`confirmed`, `inferred`, `unknown`). |
| **3** | `uc1-stage-03` | `DISCOVERING → ASSESSED` | Evaluación de viabilidad y arquitectura destino en AWS/GCP sin forzar refactorización de código. |
| **4** | `uc1-stage-04` | `ASSESSED → PLAN_READY` | Generación y validación de artefactos Terraform (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`), runbook de BD, unidad `systemd` y plantilla `.env`. |
| **5** | `uc1-stage-05` | `PLAN_READY → APPROVED` | Aprobación del plan por el arquitecto y confirmación de prerrequisitos IAM/Service Account y políticas de recursos compartidos. |
| **6** | `uc1-stage-06` | `APPROVED → PREPARING` | Aprovisionamiento de red VPC, subredes privadas, Security Groups / Firewalls para los puertos expuestos e identidad de carga. |
| **7** | `uc1-stage-07` | `APPROVED → PREPARING` | Aprovisionamiento de instancias de bases de datos (RDS/Cloud SQL), caché y volúmenes; ejecución de volcado consistente (`pg_dump`) y verificación de integridad SHA-256. |
| **8** | `uc1-stage-08` | `PREPARING → TESTING` | Empaquetado y despliegue de la aplicación en el entorno aislado de destino e inyección de secretos desde Secrets Manager / Secret Manager. |
| **9** | `uc1-stage-09` | `PREPARING → TESTING` | Pruebas de humo (`Smoke Tests`): verificación de arranque del proceso, escucha en puertos TCP y respuesta `200 OK` en el endpoint de salud. |
| **10** | `uc1-stage-10` | `TESTING → READY_FOR_CUTOVER` | Pruebas funcionales de extremo a extremo (`verify_application_health_and_functional_tests`) e informe comparativo de comportamiento pre-cutover. |
| **11** | `uc1-stage-11` | `READY_FOR_CUTOVER → COMPLETED` | Cutover controlado de tráfico hacia la nube: drenado de conexiones activas, sincronización delta final y conmutación de DNS/Balanceador. |
| **12** | `uc1-stage-12` | `READY_FOR_CUTOVER → COMPLETED` | Validación final post-cutover de métricas de error/latencia y retención del entorno de origen en espera fría para rollback seguro. |

---

## 10. Caso de Estudio Real Auditable: Trazabilidad Completa de `CocoaApp` (`ReportCocoApp.json`)

En la raíz del repositorio se encuentra el archivo [`ReportCocoApp.json`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/ReportCocoApp.json), que contiene la traza real de una ejecución completa del Caso de Uso 1 (`migration_id: "mig-app-aws-b6d554"`) migrando el repositorio real de GitHub `https://github.com/slopma/CocoaApp` hacia **AWS**. A continuación se muestra cómo fluyeron los datos reales a través de cada etapa interna:

### 10.1. Entrada y Pinning en GitHub
- **Input (`source_config`)**:
  ```json
  {
    "deployment_mode": "vm_rehost",
    "github_url": "https://github.com/slopma/CocoaApp",
    "github_ref": "main"
  }
  ```
- **Commit Fijado por `GitHubConnector`**:
  - `commit_sha`: `"ae95bb73fba3f9d932bafe411981327185d52895"` (`short_sha`: `"ae95bb73"`)
  - `author_name`: `"Alejandro Castrillón"`
  - `commit_message`: `"Merge pull request #18 from slopma/auth"`
  - Extraído en sandbox efímero: `/tmp/cloudmove_gh_hifdkosu/unpacked/slopma-CocoaApp-ae95bb7`

### 10.2. Hallazgos del Descubrimiento Estático (`source_environment`)
- **Árbol del Repositorio**: `90` archivos y `22` directorios (`371,599` bytes). Lenguajes detectados: `JavaScript (React)` (35 archivos), `Python` (29 archivos), `JSON` (7 archivos), `CSS` (4 archivos).
- **Manifiestos Inspeccionados (`14` archivos)**: `.env`, `.env.example`, `Dockerfile`, `backend/.env`, `backend/Dockerfile`, `backend/requirements.txt`, `frontend-vite/.env`, `frontend-vite/Dockerfile`, `frontend-vite/package.json`, `package.json`, `requirements.txt`.
- **Runtime, Framework y Puertos**:
  - `framework`: `"FastAPI"` (detectado en `backend/requirements.txt`: `fastapi==0.104.1`, `uvicorn==0.24.0`, `SQLAlchemy==2.0.29`, `alembic==1.13.1`, `psycopg2-binary==2.9.9`) + Frontend React Vite (`react@^18.2.0`, `@supabase/supabase-js@^2.57.4`).
  - `runtime`: `"nginx:alpine"`, `start_commands`: `["[\"nginx\", \"-g\", \"daemon off;\"]"]`, `exposed_ports`: `[80]`, `health_endpoints`: `["/health"]`.
- **Dependencias Clasificadas Epistémicamente**:
  1. `dep-cocoaapp-postgresql-inferred` (`type: "database_instance"`, `engine: "postgres"`, `epistemic_state: "inferred"`, `confidence: 0.65`): Inferida por la presencia de `psycopg2-binary==2.9.9` y `SQLAlchemy==2.0.29` en `requirements.txt` sin un servicio local de PostgreSQL en Compose.
  2. `dep-cocoaapp-ext-vite-api-url` (`type: "network_connection"`, `engine: "https"`, `epistemic_state: "unknown"`, `confidence: 0.50`): Detectada en `.env` (`VITE_API_URL=http://54.227.24.240t:8000`).

### 10.3. Subgrafo CMIR v2.1 Generado (`build_application_cmir`)
El motor construyó **6 nodos `CMIRNode`** y **5 relaciones `CMIRRelationship`**:
- `compute-cocoaapp-host` (`type: "virtual_machine"`, `level: 5`, `children_ids: ["app-cocoaapp", "port-cocoaapp-80"]`)
- `app-cocoaapp` (`type: "application"`, `level: 6`, `parent_id: "compute-cocoaapp-host"`)
- `port-cocoaapp-80` (`type: "port"`, `level: 8`, `parent_id: "compute-cocoaapp-host"`, `metadata: {"port": 80, "protocol": "tcp"}`)
- `identity-cocoaapp-sa` (`type: "identity"`, `level: 8`, `epistemic_state: "derived"`, `metadata: {"role_type": "IAM Role"}`)
- `dep-cocoaapp-postgresql-inferred` (`type: "database_instance"`, `level: 8`, `engine: "postgres"`, `epistemic_state: "inferred"`)
- `dep-cocoaapp-ext-vite-api-url` (`type: "network_connection"`, `level: 8`, `epistemic_state: "unknown"`)

### 10.4. Traducción por `AWSAdapter` y Generación HCL en `main.tf`
`AWSAdapter` tradujo los nodos del CMIR y `generate_aws_terraform_files()` emitió **12 bloques `resource` en `main.tf`** (validados con `terraform fmt -check: OK (0 errors)`):
1. `aws_vpc.target_vpc` (`10.0.0.0/16`)
2. `aws_internet_gateway.igw`
3. `aws_subnet.public_subnet` (`10.0.1.0/24`)
4. `aws_subnet.private_subnet_a` (`10.0.2.0/24`, `${var.aws_region}a`)
5. `aws_subnet.private_subnet_b` (`10.0.3.0/24`, `${var.aws_region}b`)
6. `aws_security_group.app_sg` (con `ingress` en puertos TCP `80` y `443`)
7. `aws_security_group.data_sg` (restringiendo los puertos `5432` y `6379` únicamente a `[aws_security_group.app_sg.id]`)
8. `aws_db_subnet_group.db_subnets`
9. `aws_instance.compute_cocoaapp_host` (`CMIR_ID = "compute-cocoaapp-host"`)
10. `aws_instance.app_cocoaapp` (`CMIR_ID = "app-cocoaapp"`)
11. `aws_instance.identity_cocoaapp_sa` (`CMIR_ID = "identity-cocoaapp-sa"`)
12. `aws_db_instance.dep_cocoaapp_postgresql_inferred` (`engine = "postgres"`, `instance_class = "db.t3.micro"`, `db_subnet_group_name = aws_db_subnet_group.db_subnets.name`, `vpc_security_group_ids = [aws_security_group.data_sg.id]`, `CMIR_ID = "dep-cocoaapp-postgresql-inferred"`)

---

## 11. Referencia de Endpoints API REST del Caso 1

Todos los endpoints del Caso de Uso 1 están expuestos bajo el prefijo `/api/v1/migration` en [`backend/app/api/routers/migration.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/api/routers/migration.py):

| Método | Ruta | Cuerpo de Entrada (`JSON`) | Acción Interna y Respuesta |
| :---: | :--- | :--- | :--- |
| **`POST`** | `/api/v1/migration/github/validate` | `{"github_url": "https://github.com/owner/repo", "github_token": "..."}` | Valida el repositorio en GitHub REST API, lista ramas y tags disponibles, fija la rama por defecto y devuelve el árbol jerárquico completo del repositorio (`tree`). |
| **`POST`** | `/api/v1/migration/use-case-1/inspect` | `AppInspectRequest` (`github_url`, `github_ref`, `source_path`, `inline_files`, `target_provider`, `deployment_mode`) | Ejecuta en modo de solo lectura `inspect_application_source()` + `build_application_cmir()` + `evaluate_app_migration_viability()`, devolviendo el análisis completo, el CMIR v2.1 y la viabilidad sin crear aún un job persistente. |
| **`POST`** | `/api/v1/migration/use-case-1/migrate` | `AppInspectRequest` | Crea un trabajo de migración (`use_case="app_source"`) en el `MigrationOrchestrator`, ejecuta automáticamente el descubrimiento, construye el CMIR, genera y valida los archivos Terraform y deja el trabajo en estado `PLAN_READY`. |
| **`POST`** | `/api/v1/migration/jobs/{id}/approve` | `{"approved_by": "...", "notes": "..."}` | Aprueba formalmente el plan (`PLAN_READY → APPROVED`), habilitando las etapas de ejecución. |
| **`POST`** | `/api/v1/migration/jobs/{id}/advance` | `{"dry_run": true, "operator_id": "..."}` | Avanza el trabajo por las etapas `APPROVED → PREPARING → TESTING → READY_FOR_CUTOVER → COMPLETED` con bloqueo atómico e idempotencia. |
| **`GET`** | `/api/v1/migration/jobs/{id}/deployment-guide` | *(Ninguno)* | Devuelve en Markdown la guía paso a paso `DEPLOYMENT_INSTRUCTIONS.md` personalizada para la aplicación. |
| **`GET`** | `/api/v1/migration/jobs/{id}/bundle.zip` | *(Ninguno)* | Empaqueta y descarga en formato `.zip` los 4 archivos Terraform (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`), `{slug}.service`, `.env.cloud.template`, `migrate_database_data.sh`, `smoke_test.sh`, `app_migration_diff_report.json`, `migration_report.json` y `DEPLOYMENT_INSTRUCTIONS.md`. |
