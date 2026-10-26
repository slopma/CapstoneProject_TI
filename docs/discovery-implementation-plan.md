# CloudMove — Plan de Implementación Priorizado: Descubrimiento Masivo y Planificación de Migración

## Principio Rector

Priorizar el modo **`discover_plan`** (100% solo lectura, sin instalar agentes ni modificar sistemas descubiertos) para garantizar que CloudMove descubra, identifique, normalice, reconcilie activos sin duplicados, mapee dependencias (VMs, servidores, bases de datos, almacenamiento y artefactos de arquitectura con secretos redactados) y genere un plan verificable de preparación y olas de migración.

---

## Orden de Implementación por Dependencias y Riesgo

### Etapa 1 — Contratos de Conectores, Redacción de Secretos y Escáner de Arquitectura (`backend/app/discovery/connectors.py`)
1. Implementar `SecretRedactor` para detectar y enmascarar contraseñas, tokens, claves privadas (`PRIVATE KEY`), cadenas de conexión con credenciales y variables sensibles en archivos de configuración y logs.
2. Implementar `ArchitectureFileScanner` restringido a directorios autorizados del proyecto (`generated/aws`, `generated/azure`, `generated/k8s`, `inventory` y fixtures de prueba), extrayendo recursos IaC, imágenes de contenedores, puertos, volúmenes persistentes y referencias a secretos enmascaradas.
3. Implementar `InfrastructureConnector` y el conector real `ProxmoxVEConnector` (compatible con la API REST oficial `/api2/json` de Proxmox VE, validación anti-SSRF, control de timeouts, paginación, manejo de permisos insuficientes `403` y credenciales expiradas `401`).
4. Implementar `OperatingSystemConnector` (SSH Linux / WinRM Windows / Osquery local) y `DatabaseDiscoveryConnector` (metadata de instancia, esquemas/tablas, tamaños, replicación/HA y backups para PostgreSQL, MySQL, SQL Server y MongoDB sin extraer filas ni datos sensibles).
5. Implementar el `SimulatedCollectorFixture` con escenarios reproducibles (VMs, servidores físicos, bases de datos, datastores, nodos sin permisos SSH, timeouts y sistemas incompatibles).

### Etapa 2 — Normalización, Reconciliación, Dependencias y Preparación de Migración (`backend/app/discovery/readiness.py`)
1. Implementar `AssetNormalizer` y `AssetReconciler`:
   - Prioridad de identidad: ID nativo del proveedor (`hypervisor_id` / `cloud_instance_id`) → UUID de SO → MAC/IP → DNS/Hostname.
   - Prohibición de fusión automática cuando la correlación es ambigua (`ambiguous`).
   - Registro de `asset_identifiers` y `asset_observations` con fuente, marca de tiempo, confianza y vigencia.
2. Implementar `DependencyMapper`:
   - Construcción del grafo tipado: ` aplicación → VM`, `VM → host de virtualización`, `VM → red`, `VM → datastore/volumen`, `aplicación → base de datos`, `base de datos → servidor anfitrión`, `contenedor/servicio → configuración IaC`, `activo → backup`.
3. Implementar `PackageCompatibilityService` y `MigrationReadinessService`:
   - Evaluación de compatibilidad (`verified_compatible`, `preliminary_compatible`, `known_incompatible`, `pending_validation`).
   - Cálculo de olas de migración (*Wave 1: Almacenamiento/Red base*, *Wave 2: Bases de datos y estado*, *Wave 3: Servicios/Brokers*, *Wave 4: Aplicaciones y Frontend*) basado en el grafo de dependencias.

### Etapa 3 — Motor de Campañas Persistente, Cola de Trabajos y Modo `discover_plan` (`backend/app/discovery/campaigns.py`)
1. Integrar `CampaignService`, `DiscoveryPlanner` y `JobQueue` con patrón *Transactional Outbox*, límites de concurrencia por conector y entorno, reintentos idempotentes y soporte de resultados parciales cuando un nodo falla o da timeout.
2. Garantizar por código y tests que `discover_plan` rechace cualquier operación de instalación o alteración.

### Etapa 4 — Endpoints REST y Controles de Seguridad (`backend/app/api/routers/campaigns.py`)
1. Exponer y documentar:
   - `POST /api/v1/campaigns`, `GET /api/v1/campaigns`, `GET /api/v1/campaigns/{id}`
   - `POST /api/v1/campaigns/{id}/plan`, `GET /api/v1/campaigns/{id}/assets`, `GET /api/v1/campaigns/{id}/tasks`, `GET /api/v1/campaigns/{id}/report`
   - `GET /api/v1/assets`, `GET /api/v1/assets/{id}`, `GET /api/v1/assets/{id}/observations`, `GET /api/v1/assets/{id}/relationships`, `GET /api/v1/assets/{id}/migration-readiness`
   - `GET /api/v1/connectors`, `POST /api/v1/connectors`, `POST /api/v1/connectors/{id}/test`
2. Incorporar validación de autenticación/autorización por rol y aislamiento por `environment_id`.

### Etapa 5 — Interfaz de Usuario en CloudMove (`frontend/src/components/discovery/DataCenterCampaignPanel.jsx`)
1. Incorporar filtros por tipo de activo (`virtual_machine`, `physical_server`, `database_instance`, `storage_datastore`, `architecture_artifact`), sitio, proveedor, SO y estado (`discovered`, `identified`, `verified`, `partially_inventoried`, `needs_review`, `unreachable`, `out_of_scope`).
2. Añadir vista de detalle profundo de cada activo mostrando metadata de VM, SO, Bases de Datos (instancia, esquema, tamaño, backup), Almacenamiento, Artefactos de Arquitectura (con secretos enmascarados), Dependencias y Plan/Olas de Preparación de Migración.

### Etapa 6 — Suite de Pruebas Unitarias, de Integración y de Seguridad (`backend/tests/test_discovery.py`)
1. Ejecutar y verificar pruebas unitarias, de integración y de seguridad exigidas en las Fases 12 y 14.
