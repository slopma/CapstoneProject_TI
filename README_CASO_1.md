# CloudMove — Guía Técnica del Caso de Uso 1 (`app_source`)
## Cómo pasa una app desde código fuente o GitHub hasta Terraform en AWS

> **Proyecto:** CloudMove — Plataforma Web de Abstracción Semántica y Migración Selectiva a AWS  
> **Capstone Project in IT · Universidad EAFIT · 2026-2**  
> **Caso analizado:** Caso 1 (`app_source`) — Migración guiada desde aplicación, código fuente o repositorio GitHub hacia **AWS**

---

## Tabla de Contenidos

1. [Qué hace el Caso de Uso 1 y qué problema resuelve](#1-qué-hace-el-caso-de-uso-1-y-qué-problema-resuelve)
2. [Vista general: el camino completo de punta a punta](#2-vista-general-el-camino-completo-de-punta-a-punta)
3. [Dónde vive cada parte del código en el repositorio](#3-dónde-vive-cada-parte-del-código-en-el-repositorio)
4. [Fase 1: Cómo analiza el código sin ejecutarlo (`Discovery`)](#4-fase-1-cómo-analiza-el-código-sin-ejecutarlo-discovery)
   - [4.1. Tres formas de entregar la app (`GitHub`, `Directorio Local`, `Inline/Runtime`)](#41-tres-formas-de-entregar-la-app-github-directorio-local-inlineruntime)
   - [4.2. Conector GitHub: validación, commit fijo y sandbox limpio anti-Zip-Slip](#42-conector-github-validación-commit-fijo-y-sandbox-limpio-anti-zip-slip)
   - [4.3. Recorrido del árbol de archivos y lectura de manifiestos](#43-recorrido-del-árbol-de-archivos-y-lectura-de-manifiestos)
   - [4.4. Detección de apps con varios servicios y escaneo estático (AST/Regex)](#44-detección-de-apps-con-varios-servicios-y-escaneo-estático-astregex)
   - [4.5. Qué saca de cada lenguaje, framework y contenedor](#45-qué-saca-de-cada-lenguaje-framework-y-contenedor)
   - [4.6. Seguridad: cómo oculta secretos y contraseñas en URLs](#46-seguridad-cómo-oculta-secretos-y-contraseñas-en-urls)
   - [4.7. Cómo separa hechos confirmados de suposiciones (`observed`, `inferred`, `unknown`)](#47-cómo-separa-hechos-confirmados-de-suposiciones-observed-inferred-unknown)
5. [Fase 2: Cómo traduce lo encontrado al modelo intermedio (`CMIR v2.1`)](#5-fase-2-cómo-traduce-lo-encontrado-al-modelo-intermedio-cmir-v21)
   - [5.1. Por qué existe CMIR y qué trae en v2.1](#51-por-qué-existe-cmir-y-qué-trae-en-v21)
   - [5.2. Cómo arma el subgrafo paso a paso (`build_application_cmir`)](#52-cómo-arma-el-subgrafo-paso-a-paso-build_application_cmir)
   - [5.3. Niveles jerárquicos (0 a 8) y enlaces padre-hijo](#53-niveles-jerárquicos-0-a-8-y-enlaces-padre-hijo)
6. [Fase 3: Grafo en memoria, dependencias y chequeo de viabilidad](#6-fase-3-grafo-en-memoria-dependencias-y-chequeo-de-viabilidad)
   - [6.1. El grafo `networkx.DiGraph` y el recorrido BFS (`resolve_dependencies`)](#61-el-grafo-networkxdigraph-y-el-recorrido-bfs-resolve_dependencies)
   - [6.2. Viabilidad en la nube sin obligarte a reescribir la app (`evaluate_app_migration_viability`)](#62-viabilidad-en-la-nube-sin-obligarte-a-reescribir-la-app-evaluate_app_migration_viability)
7. [Fase 4: Cómo convierte el CMIR a recursos reales de AWS (`AWSAdapter`)](#7-fase-4-cómo-convierte-el-cmir-a-recursos-reales-de-aws-awsadapter)
   - [7.1. Por qué el adaptador y el generador HCL viven separados (`BaseProviderAdapter`)](#71-por-qué-el-adaptador-y-el-generador-hcl-viven-separados-baseprovideradapter)
   - [7.2. Tabla completa de traducción (`CMIR` → `AWS`)](#72-tabla-completa-de-traducción-cmir--aws)
   - [7.3. Limpieza de nombres (`safe_id` vs `safe_name`) y estructura resultante](#73-limpieza-de-nombres-safe_id-vs-safe_name-y-estructura-resultante)
8. [Fase 5: Cómo genera, formatea y revisa el Terraform y los scripts operativos](#8-fase-5-cómo-genera-formatea-y-revisa-el-terraform-y-los-scripts-operativos)
   - [8.1. Los 4 archivos HCL modulares (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`)](#81-los-4-archivos-hcl-modulares-providertf-variablestf-maintf-outputstf)
   - [8.2. Cómo construye `main.tf` por dentro: red, reglas, secretos y recursos](#82-cómo-construye-maintf-por-dentro-red-reglas-secretos-y-recursos)
   - [8.3. Formateo con `/usr/bin/terraform fmt` y revisión en 4 pasos](#83-formateo-con-usrbinterraform-fmt-y-revisión-en-4-pasos)
   - [8.4. Scripts complementarios y paquete descargable (`bundle.zip`)](#84-scripts-complementarios-y-paquete-descargable-bundlezip)
9. [Fase 6: Máquina de estados, 12 etapas y base de datos transaccional](#9-fase-6-máquina-de-estados-12-etapas-y-base-de-datos-transaccional)
   - [9.1. Estados explícitos de `MigrationOrchestrator`](#91-estados-explícitos-de-migrationorchestrator)
   - [9.2. Las 12 etapas guiadas del Caso de Uso 1 (`uc1-stage-01` a `uc1-stage-12`)](#92-las-12-etapas-guiadas-del-caso-de-uso-1-uc1-stage-01-a-uc1-stage-12)
10. [Caso real paso a paso: migración de `CocoaApp` (`ReportCocoApp.json`)](#10-caso-real-paso-a-paso-migración-de-cocoaapp-reportcocoappjson)
11. [Referencia de endpoints API REST del Caso 1](#11-referencia-de-endpoints-api-rest-del-caso-1)

---

## 1. Qué hace el Caso de Uso 1 y qué problema resuelve

La idea del **Caso de Uso 1 (`app_source`)** es simple: tomas una aplicación que ya existe —desde un **repositorio de GitHub** (público o privado), una **carpeta local** o incluso una lista de **manifiestos y procesos que están corriendo**— y CloudMove la convierte siempre en el mismo resultado predecible sobre **AWS**:

1. **Un inventario técnico limpio y seguro**: escanea el código sin correrlo, oculta contraseñas automáticamente y clava el análisis a un `commit_sha` fijo para que nadie te cambie el código a mitad de camino.
2. **Un subgrafo neutral en formato CMIR v2.1**: ahí guarda cada pieza de la app junto con su **estado epistémico** (en la práctica: qué tan seguro está CloudMove de que esa pieza existe, clasificándola en `observed`, `derived`, `inferred` o `unknown`), un puntaje de confianza (`0.0` a `1.0`) y la prueba de dónde la encontró.
3. **Un diagnóstico honesto de compatibilidad en AWS sin obligarte a reescribir nada**: si detecta que la app guarda archivos en disco local o abre varios puertos TCP, te avisa que un contenedor efímero como ECS Fargate perdería esos datos y te recomienda pasar a `vm_rehost` (EC2 + EBS) o usar almacenamiento compartido (EFS).
4. **Un paquete completo listo para desplegar**: Terraform modular revisado con `terraform fmt -check`, scripts para migrar bases de datos (`pg_dump`/`pg_restore` con chequeo SHA-256), unidad `systemd`, plantilla `.env` sin secretos, pruebas rápidas (`smoke_test.sh`) y una guía de despliegue paso a paso (`DEPLOYMENT_INSTRUCTIONS.md`).

---

## 2. Vista general: el camino completo de punta a punta

Así fluyen los datos por dentro desde que entra una aplicación hasta que queda lista en el orquestador:

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

    subgraph Translation["5. Traducción al Proveedor Destino (adapters/aws_adapter.py)"]
        AdapterChoice{"target_provider == aws"}
        AWS_Ad["AWSAdapter.translate_cmir()\nMapea AWS_RESOURCE_MAP + sanitiza safe_id / safe_name"]
    end

    subgraph Generation["6. Generación y Validación IaC (generators/terraform.py & deployment_guide_generator.py)"]
        TF_Gen["generate_aws_terraform_files()"]
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
    TF_Gen --> TF_Files --> TF_Fmt --> TF_Val --> Extra_Art --> Orch --> DB
```

---

## 3. Dónde vive cada parte del código en el repositorio

Cada parte del Caso 1 vive en su propio módulo para no mezclar el análisis de archivos con el Terraform ni con la interfaz web:

| Parte del flujo | Archivo en el repositorio | Clases y funciones clave | Qué hace |
| :--- | :--- | :--- | :--- |
| **1. Conector GitHub** | [`backend/app/discovery/github_connector.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/github_connector.py) | `GitHubConnector`, `parse_repo_url()`, `validate_repository()`, `resolve_and_pin_commit()`, `get_repository_tree()`, `ephemeral_checkout()`, `build_hierarchical_tree()` | Habla con la API REST de GitHub, valida repos públicos o privados, fija el commit SHA de 40 caracteres y descomprime el código en una carpeta temporal segura. |
| **2. Limpieza de secretos** | [`backend/app/discovery/connectors.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/connectors.py) y [`app_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L100-L127) | `SecretRedactor.redact_text()`, `redact_env_value()` | Tapa contraseñas, tokens, llaves PEM y claves metidas dentro de URLs de conexión antes de guardar nada en el CMIR o en la base de datos. |
| **3. Motor Caso 1 (`app_source`)** | [`backend/app/migration/app_migrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py) | `inspect_application_source()`, `scan_local_filesystem_tree()`, `discover_app_components_and_code()`, `_analyze_source_payload()`, `build_application_cmir()`, `evaluate_app_migration_viability()`, `build_app_migration_stages()`, `generate_app_migration_artifacts()` | Lee el código estáticamente en varios lenguajes, clasifica dependencias, arma el CMIR de la app, evalúa viabilidad en AWS y escribe los scripts operativos. |
| **4. Modelo CMIR v2.1** | [`backend/app/cmir/models.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/models.py) y [`backend/app/cmir/builder.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/builder.py) | `CMIR`, `CMIRNode`, `CMIRRelationship`, `CMIREvidence`, `build_hierarchical_cmir()`, `build_cmir_hierarchy()`, `TYPE_LEVEL_MAP` | Define los esquemas Pydantic v2.1, normaliza evidencias, asigna niveles jerárquicos del 0 al 8 y enlaza cada padre con sus hijos. |
| **5. Grafo y dependencias** | [`backend/app/graph/builder.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/graph/builder.py) y [`backend/app/dependencies/resolver.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/dependencies/resolver.py) | `build_graph()`, `resolve_dependencies()` | Mete el CMIR en un grafo `networkx.DiGraph` y corre un recorrido en anchura (BFS) separando dependencias confirmadas, inferidas, desconocidas y compartidas. |
| **6. Adaptador AWS** | [`backend/app/adapters/base.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/base.py), [`aws_adapter.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/aws_adapter.py) | `BaseProviderAdapter`, `AWSAdapter`, `translate_cmir()`, `generate_iac()`, `validate_artifacts()` | Convierte cada `CMIRNode` genérico a su recurso en Terraform (`aws_*`), limpia los nombres y revisa el HCL resultante. |
| **7. Generador Terraform HCL** | [`backend/app/generators/terraform.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/terraform.py) | `generate_aws_terraform_files()`, `format_terraform_code()` | Escribe los 4 archivos HCL (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`) y les pasa `terraform fmt`. |
| **8. Generador de guías AWS** | [`backend/app/migration/deployment_guide_generator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/deployment_guide_generator.py) | `generate_deployment_guide()`, `_build_case_1_guide()` | Arma el manual `DEPLOYMENT_INSTRUCTIONS.md` con el commit, puerto, runtime y servicios AWS que escogiste (EC2/ALB+ASG/ECS/RDS). |
| **9. Orquestador y API REST** | [`backend/app/migration/orchestrator.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/orchestrator.py) y [`backend/app/api/routers/migration.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/api/routers/migration.py) | `MigrationOrchestrator`, `/api/v1/migration/github/validate`, `/use-case-1/inspect`, `/use-case-1/migrate`, `/jobs/{id}/*` | Lleva la máquina de estados, exige aprobación (`APPROVED`), corre pruebas pre-cutover, arma el `.zip` y persiste todo en SQLite ACID. |
| **10. Interfaz Web (UI)** | [`frontend/src/components/migration/MigrationOrchestratorWorkspace.jsx`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/frontend/src/components/migration/MigrationOrchestratorWorkspace.jsx), [`RepositoryTreeViewer.jsx`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/frontend/src/components/migration/RepositoryTreeViewer.jsx), [`IaCViewer.jsx`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/frontend/src/components/migration/IaCViewer.jsx) | Componentes React 19 | Muestra el formulario GitHub/Local, el explorador de carpetas del repo, el visor por pestañas del Terraform y el control paso a paso de las 12 etapas. |

---

## 4. Fase 1: Cómo analiza el código sin ejecutarlo (`Discovery`)

Todo arranca en [`inspect_application_source()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L130-L183) dentro de `backend/app/migration/app_migrator.py`.

> [!IMPORTANT]
> **Análisis estático de solo lectura:** CloudMove **nunca corre código** del proyecto que está analizando (`static_analysis_only = True`, `arbitrary_code_executed = False`). No hace `pip install`, ni `npm install`, ni importa módulos del repositorio: lee archivos como texto plano usando expresiones regulares y recorrido de carpetas.

### 4.1. Tres formas de entregar la app (`GitHub`, `Directorio Local`, `Inline/Runtime`)

`inspect_application_source()` soporta tres entradas distintas que puedes combinar según lo que tengas a mano:

1. **Desde GitHub (`github_url`, `github_ref`, `github_token`)**: si mandas una URL de GitHub, usa `GitHubConnector` para fijar el commit exacto, bajar el código a una carpeta temporal limpia, analizarlo con `_analyze_source_payload()` y adjuntar `git_meta`.
2. **Desde una carpeta local (`source_path`)**: resuelve la ruta con `Path(source_path).expanduser().resolve()`, revisa que exista y analiza los archivos directo en disco.
3. **Manifiestos en memoria (`inline_files`) y datos de ejecución (`runtime_metadata`)**: si no pasas ni GitHub ni carpeta local, usa el microservicio de ejemplo `DEFAULT_INLINE_APP` (una app FastAPI con PostgreSQL, Redis, S3 y `.env` en `docker-compose.yml`) o el diccionario `inline_files` que mandes en el JSON, sumando puertos o procesos reportados en `runtime_metadata`.

---

### 4.2. Conector GitHub: validación, commit fijo y sandbox limpio anti-Zip-Slip

Cuando pegas una URL de GitHub, [`GitHubConnector`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/discovery/github_connector.py#L212-L525) sigue exactamente estos 4 pasos:

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

1. **Validar la URL (`parse_repo_url`)**: revisa con `GITHUB_URL_REGEX` tanto enlaces HTTPS (`https://github.com/owner/repo`) como SSH (`git@github.com:owner/repo.git`), saca `(owner, repo)` y rechaza cualquier dominio que no sea GitHub.
2. **Pinning de commit (`resolve_and_pin_commit`)**: en la práctica, clonar una rama móvil como `main` es un riesgo porque alguien podría hacer `git push` entre que analizas el repo y despliegas en AWS. Para evitarlo, si no indicas rama o tag, busca `default_branch` vía `validate_repository()`, consulta `/repos/{owner}/{repo}/commits/{target_ref}` y guarda el **`commit_sha` de 40 caracteres** (junto con `short_sha`, `commit_message`, `author_name` y `author_date`). Desde ahí todo queda amarrado a esa foto exacta.
3. **Bajar y descomprimir sin trampas de ruta (`download_and_extract_tarball`)**: pide `/repos/{owner}/{repo}/tarball/{commit_sha}` con las cabeceras `Accept: application/vnd.github+json` y `X-GitHub-Api-Version: 2022-11-28`. Antes de extraer cada entrada del `.tar.gz`, revisa que no traiga rutas absolutas ni `..` (ataque conocido como Zip-Slip):
   ```python
   for member in tar.getmembers():
       member_path = Path(member.name)
       if member_path.is_absolute() or ".." in member_path.parts:
           continue
       tar.extract(member, extract_dir)
   ```
4. **Borrar el rastro al salir (`ephemeral_checkout`)**: como está escrito con `@contextmanager`, en cuanto termina el bloque `with`, el `finally:` corre `shutil.rmtree(temp_dir, ignore_errors=True)`. Así el servidor nunca se llena con copias viejas de repositorios.

---

### 4.3. Recorrido del árbol de archivos y lectura de manifiestos

Ya con la carpeta lista en disco, [`scan_local_filesystem_tree(target_dir)`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L186-L293) hace cuatro cosas:

1. **Salta carpetas que solo meten ruido**: mientras camina el árbol con `os.walk(target_dir)`, poda directo en memoria (`dirnames[:] = ...`) las carpetas de dependencias o builds:
   `{".git", ".svn", ".hg", "__pycache__", ".venv", "venv", "node_modules", ".idea", ".vscode", "dist", "build", ".next", "target", "bin", "obj", ".pytest_cache", ".mypy_cache"}`.
2. **Cuenta lenguajes por extensión**: busca cada extensión en `LANGUAGE_EXTENSIONS` (`.py` → `Python`, `.tsx` → `TypeScript (React)`, `.go` → `Go`, `.java` → `Java`, `.tf` → `Terraform`, etc.) y va sumando archivos (`ext_counter`) y bytes (`ext_bytes`) para sacar el porcentaje real de cada lenguaje.
3. **Lee manifiestos pequeños (`is_manifest_file`)**: ubica archivos cuyos nombres coinciden con `MANIFEST_NAMES` (`requirements.txt`, `pyproject.toml`, `package.json`, `pom.xml`, `build.gradle`, `go.mod`, `Cargo.toml`, `Dockerfile`, `docker-compose*.yml`, `.env*`, `alembic.ini`, `app_manifest.yaml`). Si pesan $\le 1\text{ MB}$ (`1_048_576` bytes), los lee como UTF-8 y los guarda en `manifests_content` tanto por ruta relativa (`backend/requirements.txt`) como por nombre corto (`requirements.txt`).
4. **Arma el árbol JSON (`build_hierarchical_tree`)**: convierte la lista plana de rutas en un árbol anidado de nodos `directory` y `file` (carpetas primero y archivos ordenados alfabéticamente) listo para que `RepositoryTreeViewer.jsx` lo pinte en pantalla.

---

### 4.4. Detección de apps con varios servicios y escaneo estático (AST/Regex)

Muchos proyectos modernos no tienen todo en la raíz: traen un `backend/` en FastAPI y un `frontend/` en React dentro del mismo repo. Para no quedarse corto, [`discover_app_components_and_code(target_dir, files_map)`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L296-L566) busca esa estructura por capas:

1. **Servicios desde Docker Compose o subcarpetas**:
   - Si encuentra algún `*compose*.yml`, lee el bloque `services:` línea por línea y saca `context:`, `dockerfile:`, los puertos `host:container` y `depends_on:`. Luego etiqueta el `tier` de cada servicio como `"backend"` (si el nombre contiene `back`, `api`, `server`, `srv`), `"frontend"` (`front`, `ui`, `web`, `client`) o `"service"`.
   - Si **no** hay Docker Compose, revisa las subcarpetas de primer nivel buscando cuáles traen su propio `Dockerfile`, `requirements.txt`, `pyproject.toml` o `package.json`. Cuando ve un `frontend` y un `backend` juntos, asume de entrada `depends_on: ["backend"]`.
2. **Escaneo de código Python (`*.py`)**:
   Revisa los `.py` de cada componente buscando:
   - Instancias de `FastAPI(`.
   - Uso del SDK de Supabase (`create_client` junto a `"supabase"`).
   - Prefijos de routers con `re.finditer(r"prefix=[\"']([^\"']+)[\"']", txt)` → anota `ROUTER /api/...`.
   - Endpoints explícitos con `re.finditer(r"@(app|router)\.(get|post|put|delete|patch)\([\"']([^\"']+)[\"']", txt)` → guarda rutas como `GET /health` o `POST /login` en `discovered_endpoints`.
3. **Escaneo de código Frontend (`*.ts`, `*.tsx`, `*.js`, `*.jsx`)**:
   - Busca clientes `@supabase/supabase-js` (`createClient`).
   - Busca llamadas HTTP salientes con `re.finditer(r"fetch\((?:`([^`]+)`|\"([^\"]+)\"|'([^']+)')", txt)` y las apunta en `discovered_api_calls`.
4. **Detección de migraciones y BaaS (`alembic.ini` y `*.supabase.co`)**:
   - Mira si existe `alembic.ini` en la raíz o en `backend/alembic.ini` para prender `alembic_detected = True`.
   - Busca URLs de Supabase con `https://([a-zA-Z0-9_-]+)\.supabase\.co` y guarda el `project_ref` y `endpoint`.
5. **Conexiones internas (`internal_service_links`)**:
   Si hay más de un componente (`len(components) > 1`), marca el patrón como `"multi_tier_decoupled"`. Y si el frontend llama a `VITE_API_URL` o `API_URL` en sus `fetch()`, registra un enlace HTTP/REST verificado entre el frontend y el puerto del backend.

---

### 4.5. Qué saca de cada lenguaje, framework y contenedor

Dentro de [`_analyze_source_payload()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L569-L1160), CloudMove junta todo según el tipo de archivo:

| Archivo / Fuente | Qué saca exactamente | Qué asume si falta algún dato |
| :--- | :--- | :--- |
| **`app_manifest.yaml`** | `name`, `runtime`, `entrypoint`, `healthcheck` / `health_endpoint`. | Deduce el lenguaje (`Python`, `Node.js`, `Java`, `Go`) a partir de `runtime`. |
| **Python (`requirements.txt`, `pyproject.toml`)** | Librerías con versión, `requires-python`, nombre del proyecto y frameworks (`fastapi`, `flask`, `django`, `tornado`, `aiohttp`). | Si no hay `Dockerfile`, pone `runtime = "python:3.11"` y `runtime_constraints = ">=3.10,<4.0"`. |
| **Node.js (`package.json`)** | `name`, `engines.node`, script `scripts.start`, `dependencies` y `devDependencies`, detectando `express`, `next`, `nestjs`/`@nestjs/core`, `fastify`, `react`, `vite`. | Si no hay `Dockerfile`, pone `runtime = "node:20"` y comando `npm start (...)`. |
| **Java (`pom.xml`, `build.gradle`, `build.gradle.kts`)** | `<java.version>` o `<maven.compiler.source>`, `<artifactId>`, dependencias Maven/Gradle y `Spring Boot` o `Quarkus`. | Pone `runtime = "openjdk:{ver}"`, arranque `java -jar target/{slug}.jar` y agrega `/actuator/health` (Spring Boot) o `/q/health` (Quarkus) a `health_endpoints`. |
| **Go (`go.mod`)** | Línea `go 1.x`, nombre en `module`, dependencias y `gin-gonic/gin`, `gofiber/fiber`, `labstack/echo`. | Pone `runtime = "golang:{ver}"` y binario `./bin/{slug}`. |
| **`Dockerfile`** | Imagen en `FROM`, puertos en `EXPOSE`, volúmenes en `VOLUME ["/ruta"]`, sonda `HEALTHCHECK` y comandos `CMD` / `ENTRYPOINT`. | Toma el `FROM` exacto como `runtime` (por ejemplo, `python:3.11-slim` o `nginx:alpine`). |
| **`docker-compose.yml`** | Puertos `- "host:container"`, variables `- KEY=VALUE`, volúmenes `- /host:/container`, nombres bajo `services:` y `healthcheck`. | Suma puertos/volúmenes y toma los servicios declarados como prueba confirmada de bases de datos, cachés o colas. |

> [!NOTE]
> Si después de leer todos los manifiestos y `runtime_metadata` no aparece ningún puerto, CloudMove usa `[8080]`. Si nadie definió un `HEALTHCHECK`, asume `["/health"]` y deja anotada esa suposición en la lista `assumptions`.

---

### 4.6. Seguridad: cómo oculta secretos y contraseñas en URLs

Al leer `.env`, `.env.example` o la sección `environment:` de `docker-compose.yml`, cada par `clave=valor` pasa por [`redact_env_value(key, raw_value)`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L100-L127):

1. **Filtro por nombre de variable (`SECRET_KEY_PATTERNS`)**:
   Revisa el nombre contra esta expresión regular:
   ```python
   SECRET_KEY_PATTERNS = re.compile(
       r"(SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|PRIVATE_KEY|CREDENTIAL|AUTH_KEY|CLIENT_SECRET|DB_PASS)",
       re.IGNORECASE,
   )
   ```
   Si coincide (o si el valor trae `"PRIVATE KEY"`), cambia el contenido por `"[REDACTED_SECRET]"` y marca `is_secret = True`, `value_stored = False`.
2. **Ocultar solo la contraseña en cadenas de conexión (`URL_CREDENTIAL_PATTERN`)**:
   Si una variable como `DATABASE_URL` o `REDIS_URL` viene con usuario y clave metidos en la URL (`postgresql://admin:MiClaveSecreta123@postgres:5432/appdb`), la expresión regular `r"([a-zA-Z0-9+.-]+://[^:/\s]+:)([^@\s]+)(@)"` reemplaza **únicamente la contraseña**:
   ```text
   Entrada:  postgresql://admin:MiClaveSecreta123@postgres:5432/appdb
   Salida:   postgresql://admin:[REDACTED_SECRET]@postgres:5432/appdb
   ```
   Con eso CloudMove todavía sabe que es `postgresql://`, qué host usa (`postgres`), el puerto (`5432`) y la base (`appdb`), sin guardar nunca tu clave real.
3. **Segundo filtro sobre el texto del valor (`SecretRedactor.redact_text`)**:
   Aunque una variable se llame distinto (por ejemplo `EXTRA_CONFIG`), `SecretRedactor` revisa si el valor tiene forma de llave AWS (`AKIA...`), token JWT/Bearer o clave privada y también lo tapa.

---

### 4.7. Cómo separa hechos confirmados de suposiciones (`observed`, `inferred`, `unknown`)

Una regla clave de CloudMove v2.1 (explicada en [`ADR-002`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/docs/ADR/ADR-002-extended-cmir-v2_1-and-evidence-provenance.md)) es **no mezclar un dato visto en el código con una corazonada**. En la práctica, ese "estado epistémico" simplemente responde *cómo sabe CloudMove que esa dependencia existe*:

| Servicio / Dependencia | Cuándo cuenta como `confirmed` (`epistemic_state = "observed"`) | Cuándo queda como `inferred` (`epistemic_state = "inferred"`) | Cuándo queda como `unknown` (`epistemic_state = "unknown"`) |
| :--- | :--- | :--- | :--- |
| **Supabase (BaaS PostgreSQL + Auth)** | Cuando encuentra `@supabase/supabase-js` o `supabase` junto con la URL `https://<ref>.supabase.co` (`confidence = 0.99`, `requires_data_migration = False`). | — | — |
| **PostgreSQL (`database_instance`)** | Cuando hay un servicio `postgres`/`db` en `docker-compose.yml` **o** aparecen tanto el driver (`psycopg`, `sqlalchemy`, `pg`, `asyncpg`, `pgx`) como la variable de conexión (`DATABASE_URL`, `POSTGRES_HOST`, `SPRING_DATASOURCE_URL`) (`confidence = 0.98`, `requires_data_migration = True`). | Cuando está el driver (`psycopg2-binary`, `pg`, etc.) en `requirements.txt` o `package.json`, pero **no** hay servicio en Compose ni variable con endpoint (`confidence = 0.65`). | — |
| **Enlace Frontend ↔ Backend (`service_mesh_link`)** | Cuando `discover_app_components_and_code` confirma que el Frontend llama a la API del Backend con `VITE_API_URL` / `depends_on` (`confidence = 0.98`). | — | — |
| **Redis (`cache`)** | Cuando hay servicio `redis` en Compose **o** cliente (`redis`, `ioredis`, `go-redis`) + variable `REDIS_URL`/`REDIS_HOST` (`confidence = 0.96`). | — | — |
| **RabbitMQ / AMQP (`queue`)** | Cuando aparecen al mismo tiempo un servicio `rabbit`/`mq` en Compose **y** `RABBITMQ_URL`/`BROKER_URL` (`confidence = 0.92`). | Cuando solo aparece la librería (`celery`, `pika`, `amqplib`) o falta uno de los dos lados (`confidence = 0.70`). | — |
| **Almacenamiento (`storage` S3/GCS)** | — | Cuando encuentra `*BUCKET*` o SDKs (`boto3`, `aws-sdk`, `storage`) (`confidence = 0.78`). | — |
| **APIs HTTP externas (`network_connection`)** | — | — | Cualquier URL externa `*_API_URL` o `*_WEBHOOK` (como `EXTERNAL_API_URL=https://api.external-service.com/v1`): solo leyendo el código no se puede saber si ese servidor es público o está detrás de una VPN privada (`confidence = 0.50`). |

---

## 5. Fase 2: Cómo traduce lo encontrado al modelo intermedio (`CMIR v2.1`)

### 5.1. Por qué existe CMIR y qué trae en v2.1

Si tuvieras $N$ fuentes (GitHub, carpetas locales, discos VM, campañas osquery/Proxmox, cuentas cloud en vivo) y $M$ destinos distintos, terminarías manteniendo $N \times M$ traductores enredados entre sí. Para evitarlo, todo pasa primero por **CMIR (CloudMove Intermediate Representation) v2.1** validado con Pydantic v2 ([`backend/app/cmir/models.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/models.py)):

- **`CMIRNode`**: representa cualquier componente con:
  - Identidad fija: `id`, `canonical_id` (`asset:<categoria>:<slug>`), `name`, `type`, `category`.
  - Jerarquía: `parent_id`, `children_ids`, `level` (`0` a `8`).
  - Contexto técnico: `provider`, `platform`, `engine`, `location`, `environment`, `is_shared`, `security`, `network`, `metadata`.
  - Evidencia v2.1: `epistemic_state` (`observed | derived | inferred | unknown`), `confidence` (`0.0` a `1.0`), `source_connector`, `discovered_at` y la lista `evidence: List[CMIREvidence]` explicando de dónde salió el nodo.
- **`CMIRRelationship`**: representa una flecha dirigida (`source` → `target`) con `type` (`runs_on`, `exposes`, `mounts`, `requires_identity`, `reads_from`, `connects_to`, `inferred_relation`, `communicates_with`, `consumes_api`, `part_of`), su propio `epistemic_state`, `confidence` y lista `evidence`.

---

### 5.2. Cómo arma el subgrafo paso a paso (`build_application_cmir`)

[`build_application_cmir(app_discovery, target_provider, deployment_mode)`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1162-L1488) agarra el diccionario que salió de `inspect_application_source()` y va armando el subgrafo en este orden:

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

1. **Nodo de cómputo (`compute-{slug}-host`)**:
   - Usa `type = "virtual_machine"` si `deployment_mode == "vm_rehost"`, o `type = "container"` si `deployment_mode == "container"`.
   - Adjunta la evidencia del runtime y, si viene de GitHub (`git_metadata`), agrega una evidencia con `confidence = 1.0` guardando URL, `commit_sha` de 40 caracteres, autor y mensaje del commit.
2. **Nodo de aplicación (`app-{slug}`)**:
   - `type = "application"`, `parent_id = compute_id`, `platform = framework`.
   - En `metadata` guarda `start_commands`, `exposed_ports`, `health_endpoints` y **solo los nombres** de las variables (`env_var_keys`), así nunca entra ningún valor de `.env` al grafo CMIR.
   - Agrega la arista `app-{slug} --[runs_on]--> compute-{slug}-host`.
3. **Sub-nodos cuando hay varios servicios (`len(components) > 1`)**:
   - Por cada servicio (por ejemplo `backend` y `frontend`), crea su nodo `compute-{slug}-{c_slug}` y su `app-{slug}-{c_slug}` (`parent_id = c_comp_id`), conectados por `runs_on` hacia su host y `part_of` hacia la app raíz `app-{slug}`.
   - Por cada enlace en `internal_service_links`, crea `consumes_api` entre los dos servicios (ej. `app-cocoaapp-frontend --[consumes_api]--> app-cocoaapp-backend`).
4. **Puertos (`port-{slug}-{p}`)**:
   - Por cada puerto en `exposed_ports`, crea un nodo `type = "port"`, `parent_id = compute_id`, con `metadata: {"port": p, "protocol": "tcp"}` y la relación `exposes`.
5. **Volúmenes (`vol-{slug}-{idx}`)**:
   - Por cada ruta en `persistent_volumes`, crea `type = "volume"`, `parent_id = compute_id`, `metadata: {"mount_path": vol_path, "size_gib": 50}` y la relación `mounts`.
6. **Identidad (`identity-{slug}-sa`)**:
   - Crea un nodo `type = "identity"` con `epistemic_state = "derived"` y `metadata: {"role_type": "IAM Role" if provider == "aws" else "GCP Service Account"}`, unido por `requires_identity`.
7. **Dependencias (`dep-...`)**:
   - Convierte cada entrada de `app_discovery["dependencies"]` en un `CMIRNode` conservando su `type` (`database_instance`, `cache`, `queue`, `storage`, `network_connection`), `engine`, `epistemic_state`, `confidence` y `evidence`, y agrega la arista (`reads_from`, `reads_and_writes`, `connects_to`, `inferred_relation` o `communicates_with`) desde `app-{slug}`.

---

### 5.3. Niveles jerárquicos (0 a 8) y enlaces padre-hijo

Al terminar, `build_application_cmir()` llama a [`build_cmir_hierarchy()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/cmir/builder.py#L117-L249) en `backend/app/cmir/builder.py`, que hace tres ajustes:

1. Revisa `TYPE_LEVEL_MAP` y asigna el nivel del 0 al 8 a cada nodo:
   - `virtual_machine` → **Nivel 5** (Máquina virtual / cómputo)
   - `application` → **Nivel 6** (Aplicación)
   - `application_component` / `service` / `workload` → **Nivel 7** (Componente / servicio)
   - `container`, `database_instance`, `cache`, `storage`, `volume`, `queue`, `identity`, `port`, `network_connection` → **Nivel 8** (Recurso atómico)
2. Convierte todas las evidencias en objetos `CMIREvidence` validados.
3. Recorre todos los nodos con `parent_id` (como `app-{slug}`, `port-{slug}-80` y `vol-{slug}-0`) y agrega sus IDs en el arreglo `children_ids` del nodo padre para que la UI pueda expandir y contraer el árbol en dos direcciones.

---

## 6. Fase 3: Grafo en memoria, dependencias y chequeo de viabilidad

### 6.1. El grafo `networkx.DiGraph` y el recorrido BFS (`resolve_dependencies`)

Con el CMIR listo, [`evaluate_app_migration_viability()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1491-L1593) pasa el modelo por el motor de grafos:

1. **Armar el grafo dirigido ([`build_graph(cmir)`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/graph/builder.py))**:
   Crea un `networkx.DiGraph()`, mete cada `CMIRNode` como vértice, añade aristas jerárquicas (`is_hierarchy = True`) de `parent_id` a hijo y agrega las relaciones de `cmir.relationships` como aristas dirigidas.
2. **Resolver dependencias con BFS ([`resolve_dependencies(graph, [app_id])`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/dependencies/resolver.py#L6-L158))**:
   - **Paso 1 (Hijos del nodo elegido)**: incluye `app-{slug}` y todos sus descendientes (`get_descendants`).
   - **Paso 2 (Salientes y filtro epistémico)**: revisa las aristas salientes (`out_edges`) que no son de jerarquía:
     - Si la arista o el destino es `unknown`, lo mete en `unknown_dependencies`.
     - Si es `inferred` o `type == "inferred_relation"`, lo manda a `inferred_dependencies` (guardando la razón en `inferred_dependency_details`) y, mientras `include_inferred=False`, **no lo mezcla con `confirmed_dependencies`**.
     - Si es `observed` o `derived`, lo pone en `required_direct` y `confirmed_dependencies`.
   - **Paso 3 (Cierre transitivo en anchura)**: usa una cola FIFO (`to_visit`) para encontrar dependencias indirectas a dos o más saltos (`required_transitive`).
   - **Paso 4 (Cuidado con recursos compartidos)**: revisa las aristas entrantes (`in_edges`) de cada dependencia. Si tiene `is_shared = True` o alguien por fuera del subgrafo también la usa, la mete en `shared_dependencies` y crea una política en `shared_dependency_policies` con `auto_migrate = False` y `requires_validation = True` para no mover sin permiso una base compartida.

---

### 6.2. Viabilidad en la nube sin obligarte a reescribir la app (`evaluate_app_migration_viability`)

Aquí CloudMove revisa si el modo elegido (`deployment_mode = "vm_rehost"` o `"container"`) mantiene el comportamiento de la app en destino (`aws` o `gcp`):

1. **Cuidado con discos locales en contenedores (`stateful_local_filesystem`)**:
   Si pides `deployment_mode == "container"` (AWS ECS Fargate) pero la app monta volúmenes locales (`persistent_volumes` no vacío), reporta la incompatibilidad porque el disco de Fargate se borra al reiniciar el contenedor, y sugiere `vm_rehost` (`Amazon EC2 + EBS`) o almacenamiento compartido (`Amazon EFS`).
2. **Avisos por suposiciones o URLs externas (`warnings`)**:
   - Saca un warning por cada dependencia `inferred` (`inferred_count > 0`) para confirmarla antes del cutover.
   - Saca un warning por cada endpoint externo `unknown` (`unknown_count > 0`).
3. **Arquitectura recomendada en AWS (`target_architecture`)**:
   Arma el mapa de servicios sugeridos en **AWS**:
   `Amazon EC2` / `ECS Fargate` / `ALB + ASG`, `Amazon RDS for PostgreSQL (Multi-AZ) + AWS DMS / pg_dump`, `Amazon ElastiCache for Redis`, `Amazon MQ / SQS`, `Amazon EBS gp3 + Amazon S3`, `AWS Secrets Manager` y `Amazon VPC + Security Groups`.

---

## 7. Fase 4: Cómo convierte el CMIR a recursos reales de AWS (`AWSAdapter`)

### 7.1. Por qué el adaptador y el generador HCL viven separados (`BaseProviderAdapter`)

Para no revolver reglas de negocio de AWS con plantillas de texto HCL, la traducción pasa por dos etapas limpias:

```text
[ Objeto CMIR v2.1 (Nodos Neutros) ]
                 │
                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ CAPA 1: ADAPTADOR EXCLUSIVO AWS (backend/app/adapters/aws_adapter.py)│
│ - AWSAdapter.translate_cmir(cmir)                                  │
│ Traduce cada CMIRNode neutro a un diccionario con el tipo de       │
│ recurso de Terraform AWS, regiones válidas e IDs sanitizados.      │
└────────────────────────────────────────────────────────────────────┘
                 │  Lista de diccionarios traducidos (List[Dict])
                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ CAPA 2: GENERADOR SINTÁCTICO HCL (backend/app/generators/terraform.py)│
│ - generate_aws_terraform_files(translated_resources)               │
│ Emite los archivos provider.tf, variables.tf, main.tf y outputs.tf │
│ y los formatea con /usr/bin/terraform fmt.                         │
└────────────────────────────────────────────────────────────────────┘
```

---

### 7.2. Tabla completa de traducción (`CMIR` → `AWS`)

Cuando `generate_app_migration_artifacts()` llama a `adapter.generate_iac(cmir)`, [`AWSAdapter`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/aws_adapter.py) busca el tipo de cada `CMIRNode` dentro de `AWS_RESOURCE_MAP`:

| Nodo en el CMIR del Caso 1 (`node.type`) | Qué representa en la app | Recurso Terraform en **AWS** (`AWS_RESOURCE_MAP`) |
| :--- | :--- | :--- |
| **`virtual_machine`** / **`compute`** | Host de ejecución (`compute-{slug}-host`) en modo `vm_rehost` | `aws_instance` |
| **`container`** / **`application_component`** | Contenedor o microservicio en modo `container` | `aws_ecs_task_definition` / `aws_autoscaling_group` + `aws_lb` |
| **`application`** | App principal (`app-{slug}`) o sub-apps (`app-{slug}-{comp}`) | `aws_instance` |
| **`port`** / **`listening_port`** | Puerto TCP expuesto (`port-{slug}-{p}`, ej. `80`, `8000`, `8080`) | `aws_security_group_rule` *(e inyectado como regla `ingress` en `aws_security_group.app_sg`)* |
| **`volume`** / **`disk`** | Ruta persistente montada (`vol-{slug}-{idx}`) | `aws_ebs_volume` (`gp3`, 50 GiB) |
| **`identity`** / **`role`** | Identidad de mínimo privilegio (`identity-{slug}-sa`) | `aws_iam_role` |
| **`database_instance`** / **`database`** | Base relacional confirmada o inferida (`dep-{slug}-postgresql`) | `aws_db_instance` (`postgres` / `mysql` + `aws_db_subnet_group`) |
| **`cache`** | Caché en memoria (`dep-{slug}-redis`) | `aws_elasticache_cluster` (`redis`, puerto `6379`) |
| **`storage`** / **`bucket`** | Bucket de objetos (`dep-{slug}-object-storage`) | `aws_s3_bucket` |
| **`queue`** / **`topic`** | Cola asíncrona (`dep-{slug}-rabbitmq`) | `aws_sqs_queue` *(o `aws_mq_broker` en discovery replatform)* |
| **`network_connection`** | Endpoint HTTPS externo en `.env` (`dep-{slug}-ext-*`) | `aws_security_group_rule` |
| **`secret`** | Secreto parametrizado | `aws_secretsmanager_secret` |
| **`system_service`** / **`process`** | Servicio `systemd` o proceso dentro del SO | `in_guest_service` / `in_guest_process` *(no crea otra EC2; genera `{slug}.service`)* |

---

### 7.3. Limpieza de nombres (`safe_id` vs `safe_name`) y estructura resultante

Terraform exige identificadores HCL sin espacios ni guiones raros en bloques `resource "<tipo>" "<safe_id>"` (normalmente `snake_case`), mientras que AWS pide `kebab-case` en minúsculas para recursos como buckets S3 o instancias RDS.

Por eso `translate_node(node: CMIRNode)` genera ambos nombres sobre cada nodo:

```python
safe_name = node.name.lower().replace(" ", "-").replace("_", "-").replace("/", "-")
safe_id   = node.id.lower().replace("-", "_").replace(".", "_").replace(":", "_").replace("/", "_")
```

Y devuelve un diccionario uniforme como este:

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

## 8. Fase 5: Cómo genera, formatea y revisa el Terraform y los scripts operativos

### 8.1. Los 4 archivos HCL modulares (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`)

[`backend/app/generators/terraform.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/terraform.py) toma la lista de diccionarios traducidos y la reparte en los cuatro archivos clásicos de cualquier proyecto Terraform:

| Archivo HCL | Qué lleva adentro |
| :--- | :--- |
| **`provider.tf`** | Declara `terraform { required_version = ">= 1.5.0" }`, fija los providers `hashicorp/aws ~> 5.0` y `hashicorp/random ~> 3.5` (para contraseñas aleatorias) y configura `provider "aws"` con `var.aws_region`. |
| **`variables.tf`** | Declara `aws_region`, `environment`, `vpc_cidr`, `ssh_ingress_cidr`, `db_ingress_cidr` (`10.0.0.0/16` por defecto), `ami_id` y **`db_password`** marcada con `sensitive = true` y `default = null` para no dejar contraseñas quemadas. |
| **`main.tf`** | Trae la red base (contraseña aleatoria, VPC, IGW, subredes pública y privadas Multi-AZ, Security Groups con CIDRs parametrizados, DB Subnet Groups, roles IAM) y todos los `resource` salidos del CMIR. |
| **`outputs.tf`** | Expone los datos útiles del despliegue (`vpc_id`, `public_subnet_id`, IP/DNS de la instancia o ALB y `database_connection_url` privado cuando hay base de datos). |

---

### 8.2. Cómo construye `main.tf` por dentro: red, reglas, secretos y recursos

Si abres [`generate_aws_terraform_files()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/terraform.py), ves que `main.tf` se arma en 5 pasos:

#### Paso 1: Contraseña segura sin quemarla en el código (`random_password` + `locals`)
Para que `terraform plan` y `terraform apply` corran sin pedir contraseñas fijas en `variables.tf`, escribe arriba en `main.tf`:
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
Si pasas `TF_VAR_db_password`, usa la tuya; si no, Terraform inventa una clave aleatoria de 24 caracteres dentro del state.

#### Paso 2: Juntar todos los puertos expuestos y armar la VPC
Busca entre los recursos traducidos cualquier nodo `cmir_type == "port"` o listas `metadata.exposed_ports`:
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
Por cada puerto ordenado en `sorted(app_ingress_ports)`, agrega una regla `ingress` TCP a `aws_security_group.app_sg`, además de crear `aws_vpc.target_vpc`, `aws_internet_gateway.igw`, `aws_subnet.public_subnet` (`10.0.1.0/24`), `aws_subnet.private_subnet_a` (`10.0.2.0/24`) y `aws_subnet.private_subnet_b` (`10.0.3.0/24`).

#### Paso 3: Cerrar la capa de datos (`has_db` / `has_cache`)
Revisa si existe alguna base de datos o caché entre los recursos:
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
Cuando `has_db` o `has_cache` da `True`, crea dos piezas clave:
1. `aws_security_group.data_sg`, cuyas reglas para los puertos `5432` (PostgreSQL) y `6379` (Redis) **cierran `0.0.0.0/0`** y dejan entrar tráfico solo desde el Security Group de la aplicación (`security_groups = [aws_security_group.app_sg.id]`).
2. `aws_db_subnet_group.db_subnets` uniendo las dos subredes privadas Multi-AZ (`private_subnet_a` y `private_subnet_b`).

#### Paso 4: Emitir los bloques `resource` según cada tipo
Luego recorre recurso por recurso en `resources`:
- **Filtro In-Guest**: si `r_type in ("in_guest_service", "in_guest_process")` o `cmir_type in ("system_service", "process")`, se lo salta con `continue`, porque un servicio `systemd` o proceso vive dentro del SO de la máquina y no debe crear otra VM aparte.
- **`aws_instance`**: emite la instancia EC2 en la subred con `aws_security_group.app_sg` (o `aws_launch_template` + `aws_autoscaling_group` en modo HA contenerizado sin dejar otra EC2 suelta), buscando dinámicamente la AMI oficial de Ubuntu LTS.
- **`aws_db_instance`**: elige `postgres` o `mysql`, conecta `password = local.effective_db_password`, fija `publicly_accessible = false`, la pone en `aws_db_subnet_group.db_subnets.name` y la cierra con `[aws_security_group.data_sg.id]`.
- **`aws_elasticache_cluster`**: crea el clúster Redis 7 en el puerto `6379` detrás de `data_sg`.
- **`aws_s3_bucket`**: crea el bucket `cloudmove-{r_name}` con control de acceso uniforme.
- **`aws_ebs_volume`**: crea el disco SSD `gp3` de 50 GiB para cada ruta `VOLUME`.
- **Etiquetas de origen (`tags`)**: cada recurso lleva su enlace directo al nodo CMIR del que nació:
  ```hcl
  tags = {
    Name      = "cocoaapp-runtime-host"
    CMIR_ID   = "compute-cocoaapp-host"
    ManagedBy = "CloudMove"
  }
  ```

---

### 8.3. Formateo con `/usr/bin/terraform fmt` y revisión en 4 pasos

Antes de marcar el plan como `PLAN_READY`, CloudMove pasa dos filtros de calidad sobre el HCL generado:

1. **Formateo oficial (`format_terraform_code` en [`terraform.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/generators/terraform.py#L8-L35))**:
   Para cada `.tf`, revisa si `/usr/bin/terraform` está instalado (`shutil.which("terraform")`). Si está, escribe un archivo temporal y ejecuta `terraform fmt` (`subprocess.run(..., timeout=5)`) para dejar la indentación oficial de HashiCorp.
2. **Validación en 4 niveles (`BaseProviderAdapter.validate_artifacts` en [`base.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/adapters/base.py#L66-L162))**:
   - **Nivel 1 (Archivos no vacíos y llaves `{}`)**: comprueba que ningún `.tf` esté vacío y que haya exactamente las mismas `{` que `}`.
   - **Nivel 2 (Sin credenciales filtradas)**: escanea que no aparezcan llaves AWS (`\bAKIA[0-9A-Z]{16}\b`) ni llaves privadas (`BEGIN RSA PRIVATE KEY`). Si ve una, frena todo con error.
   - **Nivel 3 (Referencias cruzadas `var.*` y recursos)**: saca todas las declaraciones `variable "<nombre>"` y `resource "<tipo>" "<nombre>"` de los archivos y confirma que toda referencia en `main.tf` u `outputs.tf` apunte a algo que realmente existe.
   - **Nivel 4 (Chequeo CLI real `terraform fmt -check`)**:
     Pone los 4 `.tf` en un directorio temporal y corre `/usr/bin/terraform fmt -check -no-color <tmp_dir>`. Si sale con código `0`, guarda:
     ```json
     "terraform_cli_installed": true,
     "terraform_fmt_check_passed": true,
     "terraform_cli_output": "terraform fmt -check: OK (0 errors)"
     ```
     Si `valid` da `False`, el `MigrationOrchestrator` pasa el plan a `FAILED` para que nadie pueda aprobar código roto.

---

### 8.4. Scripts complementarios y paquete descargable (`bundle.zip`)

Subir infraestructura vacía no basta para dejar andando una app real. Por eso [`generate_app_migration_artifacts()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1742-L1852) y [`generate_deployment_guide()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/deployment_guide_generator.py#L83-L443) arman **6 archivos más** y meten todo dentro del `.zip` de `GET /api/v1/migration/jobs/{migration_id}/bundle.zip`:

| Archivo en `bundle.zip` | Para qué sirve |
| :--- | :--- |
| **`{slug}.service`** | Unidad `systemd` lista para arrancar la app en EC2 (`WorkingDirectory=/srv/{slug}`, `EnvironmentFile=/etc/{slug}/{slug}.env`, `ExecStart={start_cmd}`, `Restart=on-failure`). |
| **`.env.cloud.template`** | Plantilla `.env` con todas las llaves encontradas y los secretos tapados (`[REDACTED_SECRET]`), lista para llenar desde AWS Secrets Manager o Google Secret Manager. |
| **`migrate_database_data.sh`** | Script Bash (`set -euo pipefail`) en 4 pasos: saca el dump en origen con `pg_dump --format=custom --serializable-deferrable`, verifica el checksum `sha256sum`, lo restaura en Amazon RDS o Cloud SQL con `pg_restore` y compara el conteo de filas por tabla. |
| **`smoke_test.sh`** | Revisa con `nc -z -w 3 127.0.0.1 $port` que cada puerto responda y pega un `curl -fsS http://127.0.0.1:{main_port}{health_ep}` esperando HTTP 200 OK. |
| **`app_migration_diff_report.json`** | Reporte JSON que resume el runtime conservado, comando de arranque, puertos, endpoint de salud, cantidad de secretos ocultados y si lleva migración de base de datos. |
| **`DEPLOYMENT_INSTRUCTIONS.md`** | Guía paso a paso armada por `_build_case_1_guide()` con los comandos exactos para clonar en el commit fijado (`git checkout {commit_sha}`), instalar dependencias, subir la imagen Docker a **Amazon ECR** (o **Google Artifact Registry**), correr `terraform init/plan/apply`, desplegar en **ECS Fargate** (o **Cloud Run**), cargar secretos en **Secrets Manager**, correr migraciones (`alembic upgrade head` / `prisma migrate`) y verificar el servicio. |

---

## 9. Fase 6: Máquina de estados, 12 etapas y base de datos transaccional

### 9.1. Estados explícitos de `MigrationOrchestrator`

Cada plan del Caso 1 lo maneja [`MigrationOrchestrator`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/orchestrator.py) y se guarda en SQLite WAL mediante [`TransactionalDatabase`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py):

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

**Reglas de seguridad operativa del orquestador:**
1. **Aprobación obligatoria (`APPROVED`)**: `advance_execution()` no deja pasar a `PREPARING`, `TESTING` ni `CUTOVER` si alguien no aprobó antes el plan con `approve_migration()`, guardando `approved_by` y `approved_at`.
2. **Control optimista y candados por etapa**: toda escritura revisa `expected_version` (si dos personas editan el mismo plan al tiempo, responde HTTP 409 Conflict) y toma un bloqueo exclusivo (`acquire_stage_lock`) en base de datos para que nadie ejecute la misma etapa dos veces en paralelo.
3. **Idempotencia (`idempotency_key`)**: en la práctica, significa que si se cae el internet y tu navegador reenvía la misma orden con la misma `idempotency_key`, la tabla `stage_executions` ya la tiene guardada y te devuelve el resultado previo sin crear servidores duplicados.
4. **Sin simular que hay nube real (`simulated_dry_run` vs `live_cloud`)**: si faltan credenciales reales o corres con `dry_run=True`, marca `execution_mode = "simulated_dry_run"` y `completed_in_real_cloud = False`. Nunca dice que desplegó en AWS si no fue cierto.
5. **El origen no se toca (`source_environment_destroyed = False`)**: CloudMove trabaja bajo `PRESERVED_READ_ONLY_STANDBY`, dejando el repositorio y la app original quietos para poder volver atrás apuntando de nuevo el DNS si hace falta.

---

### 9.2. Las 12 etapas guiadas del Caso de Uso 1 (`uc1-stage-01` a `uc1-stage-12`)

[`build_app_migration_stages()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/app_migrator.py#L1701-L1740) parte la migración en 12 pasos ordenados, cada uno con su punto de recuperación (`checkpoint-uc1-stage-01` hasta `checkpoint-uc1-stage-12`):

| Orden | ID de etapa | Transición de estado | Qué hace en ese paso |
| :---: | :--- | :---: | :--- |
| **1** | `uc1-stage-01` | `DISCOVERING → ASSESSED` | Escaneo estático de código, manifiestos y runtime (sin ejecutar nada) y ocultación de secretos. |
| **2** | `uc1-stage-02` | `DISCOVERING → ASSESSED` | Construcción del CMIR v2.1 y clasificación de dependencias (`confirmed`, `inferred`, `unknown`). |
| **3** | `uc1-stage-03` | `DISCOVERING → ASSESSED` | Evaluación de viabilidad y arquitectura objetivo en AWS sin obligar a refactorizar el código. |
| **4** | `uc1-stage-04` | `ASSESSED → PLAN_READY` | Generación y validación de Terraform (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`), runbook de BD, unidad `systemd` y plantilla `.env`. |
| **5** | `uc1-stage-05` | `PLAN_READY → APPROVED` | Aprobación del plan por el operador y chequeo de prerrequisitos IAM y recursos compartidos. |
| **6** | `uc1-stage-06` | `APPROVED → PREPARING` | Aprovisionamiento de VPC, subredes privadas, Security Groups para los puertos expuestos e identidad IAM. |
| **7** | `uc1-stage-07` | `APPROVED → PREPARING` | Creación de RDS, caché y volúmenes; dump consistente (`pg_dump`) con chequeo SHA-256. |
| **8** | `uc1-stage-08` | `PREPARING → TESTING` | Empaquetado y despliegue de la app en el entorno nuevo e inyección de secretos. |
| **9** | `uc1-stage-09` | `PREPARING → TESTING` | Pruebas rápidas (`Smoke Tests`): comprueba que el proceso arranque, abra puertos TCP y responda `200 OK` en `/health`. |
| **10** | `uc1-stage-10` | `TESTING → READY_FOR_CUTOVER` | Pruebas funcionales (`verify_application_health_and_functional_tests`) e informe comparativo pre-cutover. |
| **11** | `uc1-stage-11` | `READY_FOR_CUTOVER → COMPLETED` | Cutover hacia la nube: drenado de conexiones, sincronización final y cambio de DNS o balanceador. |
| **12** | `uc1-stage-12` | `READY_FOR_CUTOVER → COMPLETED` | Revisión final de errores/latencia tras el cambio y retención del origen en espera para rollback rápido. |

---

## 10. Caso real paso a paso: migración de `CocoaApp` (`ReportCocoApp.json`)

En una corrida real documentada en [`ReportCocoApp.json`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/ReportCocoApp.json) (`migration_id: "mig-app-aws-b6d554"`), se migró el repositorio real de GitHub `https://github.com/slopma/CocoaApp` hacia **AWS**. Así pasaron los datos reales por cada módulo:

### 10.1. Entrada y commit fijado en GitHub
- **Input (`source_config`)**:
  ```json
  {
    "deployment_mode": "vm_rehost",
    "github_url": "https://github.com/slopma/CocoaApp",
    "github_ref": "main"
  }
  ```
- **Commit fijado por `GitHubConnector`**:
  - `commit_sha`: `"ae95bb73fba3f9d932bafe411981327185d52895"` (`short_sha`: `"ae95bb73"`)
  - `author_name`: `"Alejandro Castrillón"`
  - `commit_message`: `"Merge pull request #18 from slopma/auth"`
  - Extraído en sandbox temporal: `/tmp/cloudmove_gh_hifdkosu/unpacked/slopma-CocoaApp-ae95bb7`

### 10.2. Qué encontró el escaneo estático (`source_environment`)
- **Árbol del repositorio**: `90` archivos y `22` directorios (`371,599` bytes). Lenguajes: `JavaScript (React)` (35 archivos), `Python` (29 archivos), `JSON` (7 archivos), `CSS` (4 archivos).
- **Manifiestos leídos (`14` archivos)**: `.env`, `.env.example`, `Dockerfile`, `backend/.env`, `backend/Dockerfile`, `backend/requirements.txt`, `frontend-vite/.env`, `frontend-vite/Dockerfile`, `frontend-vite/package.json`, `package.json`, `requirements.txt`.
- **Runtime, framework y puertos**:
  - `framework`: `"FastAPI"` (visto en `backend/requirements.txt`: `fastapi==0.104.1`, `uvicorn==0.24.0`, `SQLAlchemy==2.0.29`, `alembic==1.13.1`, `psycopg2-binary==2.9.9`) + Frontend React Vite (`react@^18.2.0`, `@supabase/supabase-js@^2.57.4`).
  - `runtime`: `"nginx:alpine"`, `start_commands`: `["[\"nginx\", \"-g\", \"daemon off;\"]"]`, `exposed_ports`: `[80]`, `health_endpoints`: `["/health"]`.
- **Dependencias clasificadas**:
  1. `dep-cocoaapp-postgresql-inferred` (`type: "database_instance"`, `engine: "postgres"`, `epistemic_state: "inferred"`, `confidence: 0.65`): deducida porque estaban `psycopg2-binary==2.9.9` y `SQLAlchemy==2.0.29` en `requirements.txt`, pero sin un PostgreSQL local en Compose.
  2. `dep-cocoaapp-ext-vite-api-url` (`type: "network_connection"`, `engine: "https"`, `epistemic_state: "unknown"`, `confidence: 0.50`): vista en `.env` (por ejemplo `VITE_API_URL` apuntando al backend original).

### 10.3. Subgrafo CMIR v2.1 generado (`build_application_cmir`)
El motor armó **6 nodos `CMIRNode`** y **5 relaciones `CMIRRelationship`**:
- `compute-cocoaapp-host` (`type: "virtual_machine"`, `level: 5`, `children_ids: ["app-cocoaapp", "port-cocoaapp-80"]`)
- `app-cocoaapp` (`type: "application"`, `level: 6`, `parent_id: "compute-cocoaapp-host"`)
- `port-cocoaapp-80` (`type: "port"`, `level: 8`, `parent_id: "compute-cocoaapp-host"`, `metadata: {"port": 80, "protocol": "tcp"}`)
- `identity-cocoaapp-sa` (`type: "identity"`, `level: 8`, `epistemic_state: "derived"`, `metadata: {"role_type": "IAM Role"}`)
- `dep-cocoaapp-postgresql-inferred` (`type: "database_instance"`, `level: 8`, `engine: "postgres"`, `epistemic_state: "inferred"`)
- `dep-cocoaapp-ext-vite-api-url` (`type: "network_connection"`, `level: 8`, `epistemic_state: "unknown"`)

### 10.4. Traducción de `AWSAdapter` y bloques emitidos en `main.tf`
`AWSAdapter` tradujo el grafo y `generate_aws_terraform_files()` sacó **12 bloques `resource` en `main.tf`** (validados con `terraform fmt -check: OK (0 errors)`):
1. `aws_vpc.target_vpc` (`10.0.0.0/16`)
2. `aws_internet_gateway.igw`
3. `aws_subnet.public_subnet` (`10.0.1.0/24`)
4. `aws_subnet.private_subnet_a` (`10.0.2.0/24`, `${var.aws_region}a`)
5. `aws_subnet.private_subnet_b` (`10.0.3.0/24`, `${var.aws_region}b`)
6. `aws_security_group.app_sg` (puertos TCP `80` y `443`)
7. `aws_security_group.data_sg` (cerrando `5432` y `6379` solo para `[aws_security_group.app_sg.id]`)
8. `aws_db_subnet_group.db_subnets`
9. `aws_instance.compute_cocoaapp_host` (`CMIR_ID = "compute-cocoaapp-host"`)
10. `aws_instance.app_cocoaapp` (`CMIR_ID = "app-cocoaapp"`)
11. `aws_instance.identity_cocoaapp_sa` (`CMIR_ID = "identity-cocoaapp-sa"`)
12. `aws_db_instance.dep_cocoaapp_postgresql_inferred` (`engine = "postgres"`, `instance_class = "db.t3.micro"`, `db_subnet_group_name = aws_db_subnet_group.db_subnets.name`, `vpc_security_group_ids = [aws_security_group.data_sg.id]`, `CMIR_ID = "dep-cocoaapp-postgresql-inferred"`)

---

## 11. Referencia de endpoints API REST del Caso 1

Todas las rutas del Caso 1 cuelgan de `/api/v1/migration` en [`backend/app/api/routers/migration.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/api/routers/migration.py):

| Método | Ruta | Entrada (`JSON`) | Qué hace y qué devuelve |
| :---: | :--- | :--- | :--- |
| **`POST`** | `/api/v1/migration/github/validate` | `{"github_url": "https://github.com/owner/repo", "github_token": "..."}` | Valida el repo en la API de GitHub, lista ramas y tags, toma la rama por defecto y devuelve el árbol de archivos (`tree`). |
| **`POST`** | `/api/v1/migration/use-case-1/inspect` | `AppInspectRequest` (`github_url`, `github_ref`, `source_path`, `inline_files`, `target_provider`, `deployment_mode`) | Corre en solo lectura `inspect_application_source()` + `build_application_cmir()` + `evaluate_app_migration_viability()`, devolviendo el análisis, el CMIR v2.1 y la viabilidad sin crear aún un job en BD. |
| **`POST`** | `/api/v1/migration/use-case-1/migrate` | `AppInspectRequest` | Crea el plan (`use_case="app_source"`) en `MigrationOrchestrator`, corre discovery, arma el CMIR, genera y valida Terraform y deja el plan en `PLAN_READY`. |
| **`POST`** | `/api/v1/migration/jobs/{id}/approve` | `{"approved_by": "...", "notes": "..."}` | Firma la compuerta de aprobación (`PLAN_READY → APPROVED`) para poder ejecutar el despliegue. |
| **`POST`** | `/api/v1/migration/jobs/{id}/advance` | `{"dry_run": true, "operator_id": "..."}` | Avanza por `APPROVED → PREPARING → TESTING → READY_FOR_CUTOVER → COMPLETED` con candado exclusivo e idempotencia. |
| **`GET`** | `/api/v1/migration/jobs/{id}/deployment-guide` | *(Ninguno)* | Devuelve el Markdown `DEPLOYMENT_INSTRUCTIONS.md` armado a la medida de la app. |
| **`GET`** | `/api/v1/migration/jobs/{id}/bundle.zip` | *(Ninguno)* | Empaqueta y descarga el `.zip` con los 4 archivos `.tf` (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`), `{slug}.service`, `.env.cloud.template`, `migrate_database_data.sh`, `smoke_test.sh`, `app_migration_diff_report.json`, `migration_report.json` y `DEPLOYMENT_INSTRUCTIONS.md`. |
