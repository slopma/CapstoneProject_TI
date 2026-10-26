# CloudMove — Diagnóstico de Arquitectura de Descubrimiento Masivo y Planificación de Migración

## 1. Arquitectura Actual Comprobada

Tras inspeccionar el repositorio real en `/home/lacastrilp/Documentos/Semestre 2026-2/CapstoneProject_TI`, el sistema **CloudMove v2.0** está estructurado como un monorepo con cuatro bloques principales:

1. **Backend (`backend/app/`)**: API REST con FastAPI que gestiona:
   - **CMIR v2.0 (`backend/app/cmir/`)**: Modelo Intermedio de Migración Cloud (`CMIR`, `CMIRNode`, `CMIRRelationship`) con jerarquía de niveles `0–8` (Organización → Entorno → Región → VPC/Sitio → Subred → Host/VM → Servicio → Almacenamiento/Puerto).
   - **Motor de Grafos y Dependencias (`backend/app/graph/`, `backend/app/dependencies/`)**: basado en `networkx.DiGraph` (`build_graph`, `resolve_dependencies`) para calcular dependencias directas, transitivas, compartidas y opcionales.
   - **Adaptadores y Generadores Multi-Cloud (`backend/app/adapters/`, `backend/app/generators/`)**: traducción desde CMIR hacia AWS (Terraform modular: `provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`), Azure y Kubernetes.
   - **Módulo de Discovery (`backend/app/discovery/`)**:
     - `osquery_parser.py`: parser determinista y explicativo de inventarios `cloudmove.discovery.v1` generados por `osquery`.
     - `cmir_bridge.py`: puente que transforma activos descubiertos en nodos CMIR v2.0 y grafos React Flow.
     - `terraform_bridge.py`: motor de trazabilidad JSON → CMIR → AWS Terraform (`replatform` y `rehost`).
     - `campaigns.py`: primera iteración del almacén de campañas de data center.
2. **Agente Local y Recolector (`cloudmove_osquery_export.py` y `cloudmove_agent/`)**:
   - Recolector de solo lectura sobre `osqueryi` (16 tablas de hardware, red, paquetes Debian, unidades systemd, módulos del kernel y procesos).
   - Instalador multiplataforma desacoplado (`osquery_installer.py`) con verificación de hash SHA-256 y protección contra Path Traversal.
3. **Frontend (`frontend/src/`)**: SPA en React 19 + Vite 8 + `@xyflow/react` 12 con vistas de Arquitectura Jerárquica, vista de Discovery (`DiscoveryWorkspace.jsx`, `DiscoverySections.jsx`, `DiscoveryDiagramCanvas.jsx`, `DataCenterCampaignPanel.jsx`) y modal de previsualización de migración (`MigrationPreviewModal.jsx`).
4. **Inventarios y Artefactos IaC (`inventory/`, `generated/`, `docs/`)**: ejemplos CMIR empresariales (`onprem-enterprise-example.json`, `enterprise-multicloud-example.json`), inventario real de Kali Linux (`docs/cloudmove-osquery-inventory.json`) y módulos Terraform generados (`generated/aws/`).

---

## 2. Tecnologías y Versiones Relevantes

- **Python**: `3.14.7` (ejecutándose en Linux).
- **Backend**: `fastapi`, `uvicorn[standard]`, `pydantic` (v2), `networkx`, `jinja2`, `boto3`, `google-cloud-compute`, `python-dotenv`, `pytest` (`9.1.1`), `httpx`.
- **Herramienta de Discovery Local**: `osqueryi 5.23.1` instalada en `/usr/bin/osqueryi` (symlink a `/opt/osquery/bin/osqueryd`).
- **Frontend**: `react ^19.2.8`, `react-dom ^19.2.8`, `@xyflow/react ^12.11.6`, `reactflow ^11.11.4`, `vite ^8.3.0`, `oxlint ^1.81.0`.
- **Persistencia Actual**: archivos JSON locales estructurados en `backend/data/` e `inventory/` (no hay servidor PostgreSQL ni Redis/Celery configurado en Docker Compose dentro del repositorio actual).

---

## 3. Componentes Existentes Reutilizables

| Componente | Ruta | Cómo se reutiliza |
|---|---|---|
| Modelo CMIR v2.0 | `backend/app/cmir/models.py` | Representación canónica de recursos y relaciones con jerarquía `0–8` y metadatos tipados. |
| Resolutor de Dependencias | `backend/app/dependencies/resolver.py` | Cálculo de grupos de migración (olas) y dependencias directas, transitivas y compartidas sobre `networkx.DiGraph`. |
| Parser Osquery | `backend/app/discovery/osquery_parser.py` | Normalización de servidores Linux, distinción de estados (`observed`, `derived`, `inferred`, `unavailable`, `error`). |
| Puente CMIR & Terraform | `backend/app/discovery/cmir_bridge.py`, `terraform_bridge.py` | Conversión de activos descubiertos a topología interactiva y código Terraform AWS. |
| Recolector Osquery | `cloudmove_osquery_export.py` | Identificación real del sistema operativo local sin modificar el equipo. |

---

## 4. Capacidades Implementadas y Verificables

1. Importación, validación y normalización del inventario real `docs/cloudmove-osquery-inventory.json` (`rabbitmq-kali`).
2. Construcción de grafo CMIR v2.0 y diagrama interactivo React Flow para un host individual.
3. Generación de código Terraform modular (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`) a partir del inventario osquery.
4. Instalador multi-OS de `osquery` con verificación SHA-256 y prueba funcional (`verify_osquery_binary`).
5. Estructura inicial de campañas (`/api/v1/campaigns`).

---

## 5. Capacidades Parcialmente Implementadas

1. **Descubrimiento de Bases de Datos**: actualmente solo detecta indicios de paquetes/puertos en el host (`postgresql-18`, `rabbitmq-server`), pero carece de un conector estructurado (`DatabaseDiscoveryConnector`) que separe: (1) metadata de instancia, (2) metadata de esquema/catálogo, (3) métricas de tamaño/espacios, (4) metadata de backup/HA y (5) estado de preparación para migrar.
2. **Campañas Masivas**: el módulo `campaigns.py` inicial orquesta estados de agentes, pero aún no implementa todos los contratos desacoplados (`InfrastructureConnector`, `OperatingSystemConnector`, `DatabaseDiscoveryConnector`, `ArchitectureFileScanner`, `MigrationReadinessService`) ni los endpoints completos de consulta de activos individuales (`/api/v1/assets`, `/api/v1/assets/{id}`, `/api/v1/assets/{id}/relationships`, `/api/v1/assets/{id}/migration-readiness`, `/api/v1/connectors`, `POST /api/v1/connectors/{id}/test`).

---

## 6. Capacidades Ausentes (Por Implementar en esta Fase)

1. **Conector Real de Hipervisor basándose en API Oficial (`ProxmoxVEConnector` / `VSphereConnector`)**: adaptador HTTP compatible con la API REST oficial de Proxmox VE (`/api2/json/nodes`, `/api2/json/cluster/resources`, `/api2/json/nodes/{node}/qemu/{vmid}/config`, `/api2/json/nodes/{node}/storage`) con manejo real de tickets/tokens API, paginación, timeouts, errores de permisos (`401`/`403`) y modo fixture reproducible cuando no hay credenciales en `.env`.
2. **Escáner de Archivos de Arquitectura y Protección de Secretos (`ArchitectureFileScanner`)**: inspección controlada de artefactos del repositorio (`generated/aws/*.tf`, `generated/k8s/manifests.yaml`, `generated/azure/main.tf`, `inventory/*.json`, archivos `.env.example`, Dockerfiles/manifiestos de fixtures) con **redacción estricta de secretos** (enmascaramiento de contraseñas, tokens, claves privadas y cadenas de conexión, conservando solo la referencia y clasificación del artefacto).
3. **Conector de Metadata de Bases de Datos y Almacenamiento (`DatabaseDiscoveryConnector` y `StorageDiscoveryService`)**: recolección de metadata de instancias PostgreSQL/MySQL/SQL Server/MongoDB (separando instancia, esquemas/tablas, tamaños, replicación, backups y preparación sin extraer filas ni datos sensibles) y mapeo de datastores, discos virtuales y volúmenes persistentes.
4. **Servicio de Preparación y Orden de Migración (`MigrationReadinessService`)**: cálculo de olas de migración (*migration waves*), detección de bloqueos (dependencias compartidas, SO no soportado, falta de backup verificado, discos sin formato exportable), tamaño estimado de cargas y nivel de compatibilidad (`verified_compatible`, `preliminary_compatible`, `known_incompatible`, `pending_validation`).
5. **Seguridad Transversal y Autenticación/Autorización de API**: validación de encabezados de rol/alcance (`X-CloudMove-Role`, `X-CloudMove-Env`), aislamiento entre entornos, prevención de SSRF en conectores y prohibición estricta de ejecutar instalaciones o cambios durante `discover_plan`.

---

## 7. Problemas de Arquitectura y Riesgos Técnicos Detectados

- **Ausencia de broker externo (Redis/Celery/PostgreSQL) en el entorno local**: añadir una dependencia obligatoria a un servidor PostgreSQL o Redis externo rompería la ejecución local inmediata si esos demonios no están corriendo. **Solución**: implementar persistencia atómica con soporte de *Transactional Outbox* y cola de trabajos asíncrona en segundo plano (`JobQueue` con `ThreadPoolExecutor` + estado persistido en disco/SQLite-compatible), manteniendo contratos limpios para conectar PostgreSQL/Celery en producción.
- **Riesgo de confusión entre descubrimiento y migración efectiva**: la interfaz y el API deben distinguir explícitamente entre metadata descubierta y datos migrados.

---

## 8. Entidades Existentes y Compatibilidad con el Modelo Unificado

- `CMIRNode` y `CMIRRelationship` (`backend/app/cmir/models.py`) se mantienen intactos.
- El modelo unificado de campañas amplía la representación con: `environments`, `sites`, `connectors`, `discovery_collectors`, `network_ranges`, `assets` (con detalles específicos de `vm_metadata`, `os_metadata`, `database_metadata`, `storage_metadata`), `asset_identifiers` (IDs nativos de hipervisor, UUID de SO, MAC, IP, DNS), `asset_observations` (con fuente, timestamp, confianza y `campaign_id`), `architecture_artifacts` (con referencias de secretos redactadas), `relationships`, `migration_readiness` y `outbox_events`.

---

## 9. Endpoints Existentes que se Reutilizan y Nuevos Endpoints a Exponer

- **Existentes conservados**:
  - `/api/v1/architecture/*`, `/api/v1/migration/*`, `/api/v1/discovery/*`
  - `POST /api/v1/campaigns`, `GET /api/v1/campaigns`, `GET /api/v1/campaigns/{id}`, `POST /api/v1/campaigns/{id}/plan`, `POST /api/v1/campaigns/{id}/approve`, `POST /api/v1/campaigns/{id}/execute`, `POST /api/v1/campaigns/{id}/cancel`, `GET /api/v1/campaigns/{id}/assets`, `GET /api/v1/campaigns/{id}/tasks`, `GET /api/v1/campaigns/{id}/report`, `GET /api/v1/assets/{id}/health`
- **Nuevos endpoints requeridos por Fase 7**:
  - `GET /api/v1/assets` (con filtros por `asset_type`, `site_id`, `provider`, `os_family`, `state`, `environment_id`)
  - `GET /api/v1/assets/{id}` (detalle completo del activo: VM, SO, BD, almacenamiento, observaciones e identificadores externos)
  - `GET /api/v1/assets/{id}/observations` (historial de observaciones por fuente y vigencia)
  - `GET /api/v1/assets/{id}/relationships` (grafo de dependencias entrantes y salientes con procedencia y confianza)
  - `GET /api/v1/assets/{id}/migration-readiness` (evaluación detallada de preparación para migración, riesgos, ola sugerida y datos faltantes)
  - `GET /api/v1/connectors` y `POST /api/v1/connectors` (listado y registro validado contra SSRF)
  - `POST /api/v1/connectors/{id}/test` (prueba de conectividad, permisos, paginación y estado del conector)

---

## 10. Archivos a Crear o Modificar

- **Nuevos**:
  - `docs/discovery-architecture-assessment.md` (este documento)
  - `docs/discovery-implementation-plan.md` (plan priorizado)
  - `backend/app/discovery/connectors.py` (`InfrastructureConnector`, `ProxmoxVEConnector`, `OperatingSystemConnector`, `DatabaseDiscoveryConnector`, `ArchitectureFileScanner`, `SecretRedactor`, `SimulatedCollectorFixture`)
  - `backend/app/discovery/readiness.py` (`AssetNormalizer`, `AssetReconciler`, `DependencyMapper`, `PackageCompatibilityService`, `MigrationReadinessService`, `JobQueue`)
- **Modificados**:
  - `backend/app/discovery/campaigns.py` (integración de las abstracciones de Fase 2–10 en `CampaignService` y modo estricto `discover_plan`)
  - `backend/app/api/routers/campaigns.py` (nuevos endpoints `/assets`, `/assets/{id}`, `/assets/{id}/relationships`, `/assets/{id}/migration-readiness`, `/connectors`, `/connectors/{id}/test` y guardas de seguridad/aislamiento de entorno)
  - `frontend/src/components/discovery/DataCenterCampaignPanel.jsx` (filtros por tipo/sitio/SO/estado, inspector profundo de VM/SO/Base de Datos/Almacenamiento/Artefactos IaC/Dependencias y plan de olas de migración)
  - `backend/tests/test_discovery.py` (pruebas unitarias, de integración y de seguridad de Fases 12 y 14)

---

## 11. Decisiones Arquitectónicas Propuestas y Justificación

1. **Conector Real Prioritario — Proxmox VE API (`ProxmoxVEConnector`)**: el inventario real del proyecto (`rabbitmq-kali`) corre sobre virtualización KVM/QEMU (`pve-node-01`), por lo que Proxmox VE REST API (`/api2/json/...`) es el conector de hipervisor más coherente con el entorno real. Implementa cliente HTTP real con `urllib.request`/`httpx` usando `PVEAPIToken` y validación TLS, más soporte de fixture determinista cuando no se definen credenciales en `.env`.
2. **Opción A/C (Fleet + CloudMove)**: CloudMove lidera el descubrimiento multi-fuente, la topología CMIR, el escaneo de artefactos y el plan de migración, mientras delega la administración continua de agentes en Fleet (`AgentManagementProvider`), evitando mantener un protocolo propietario de C2.
3. **Separación Estricta `discover_plan` vs. Ejecución**: en modo `discover_plan`, cualquier intento de invocar tareas de instalación de agentes o modificación devuelve un bloqueo explícito de política (`409 Conflict` / `blocked_in_discover_plan`), garantizando operación 100% de solo lectura.

---

## 12. Dependencias Externas y Variables de Entorno

No se requieren librerías adicionales fuera de las ya instaladas en `backend/requirements.txt`.
Variables de entorno opcionales para conexión en vivo (nunca almacenadas en el repositorio):
- `PROXMOX_API_URL` (ej. `https://pve.datacenter.local:8006/api2/json`)
- `PROXMOX_TOKEN_ID` (ej. `cloudmove-ro@pve!discovery`)
- `PROXMOX_TOKEN_SECRET` (secreto de solo lectura `PVEAuditor`)
- `PROXMOX_VERIFY_SSL` (`true` por defecto)
- `FLEET_API_URL` y `FLEET_API_TOKEN`
- `CLOUDMOVE_API_KEY` / `CLOUDMOVE_DEFAULT_ENV`

---

## 13. Riesgos y Limitaciones para Probar sin Infraestructura de Producción

- Sin un clúster vCenter/Proxmox o bases de datos remotas de producción accesibles desde este contenedor de desarrollo, las respuestas de la API de hipervisor y catálogos de bases de datos remotos se validan mediante el **Colector de Prueba Reproducible (`SimulatedCollectorFixture`)** y pruebas de contrato HTTP contra el adaptador `ProxmoxVEConnector` (incluyendo simulación de `401 Unauthorized`, `403 Forbidden`, timeouts, paginación y respuestas parciales), combinadas con el escaneo real del host local (`osqueryi`) y el escaneo real de los archivos de arquitectura del repositorio (`generated/` e `inventory/`).
