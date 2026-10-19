# CloudMove Discovery Analyzer, Parser e Interactive Infrastructure Diagram

## 1. Visión General

El módulo **CloudMove Discovery** transforma inventarios recopilados por **osquery** (esquema `cloudmove.discovery.v1`) —y deja preparada la arquitectura para **Open-AudIT** y recolectores de bases de datos— en:

1. **Modelo Normalizado Epistémico (`cloudmove.normalized.v1`)** con clasificación explícita de cada hallazgo (`observed`, `derived`, `inferred`, `unavailable`, `error`).
2. **Análisis Explicativo de 9 Dimensiones (`DataPointExplanation`)** para cada recurso y métrica (qué es, valor detectado, interpretación, por qué importa, impacto en migración a AWS, procedencia, estado epistémico, limitaciones y acción sugerida).
3. **Representación Intermedia CMIR v2 (`CMIR`)** validada mediante `build_hierarchical_cmir` y `validate_cmir` para integrarse nativamente con el motor de grafos de CloudMove.
4. **Diagrama Principal Interactivo en React Flow (`@xyflow/react`)** con vistas **Topología Completa**, **Red y Puertos**, **Almacenamiento**, **Runtime y Servicios** y **Relevancia para Migración AWS**, además de un cajón de inspección detallada sincronizado con las secciones del inventario.
5. **Exportación Multi-Formato**: JSON normalizado (`cloudmove.normalized.v1`), modelo CMIR v2 (`cmir`), informe ejecutivo en Markdown (`markdown`) y diagrama de arquitectura en Mermaid (`mermaid`).

---

## 2. Arquitectura de Módulos Reutilizados y Nuevos

### Módulos existentes reutilizados
- [`backend/app/cmir/models.py`](../backend/app/cmir/models.py): Modelos `CMIR`, `CMIRNode`, `CMIRRelationship`, `HierarchyLevel` y `ValidationResult`.
- [`backend/app/cmir/builder.py`](../backend/app/cmir/builder.py): `build_hierarchical_cmir` y `TYPE_LEVEL_MAP` (ampliado de forma retrocompatible con los tipos de recursos de discovery).
- [`backend/app/cmir/validator.py`](../backend/app/cmir/validator.py): `validate_cmir` para garantizar integridad de nodos, relaciones y jerarquía.
- [`frontend/src/components/architecture/TechnicalIcons.jsx`](../frontend/src/components/architecture/TechnicalIcons.jsx): Sistema de iconografía SVG técnica monocromática.

### Nuevos módulos en el Backend (`backend/app/discovery/`)
- [`backend/app/discovery/models.py`](../backend/app/discovery/models.py):
  - `DataState`: Enumeración epistémica (`observed`, `derived`, `inferred`, `unavailable`, `error`).
  - `DataPointExplanation`: Estructura de 9 campos explicativos orientados a evaluación de migración a AWS.
  - `BaseDiscoveryCollectorParser`: Interfaz abstracta para cualquier recolector de infraestructura.
  - `OpenAudITCollectorAdapter`: Adaptador extensible para inventarios de dispositivos de Open-AudIT.
  - `DATABASE_COLLECTOR_SPECS`: Especificaciones de catálogo para recolectores de bases de datos (`PostgreSQL`, `MySQL`, `SQLServer`) sin credenciales en texto plano.
- [`backend/app/discovery/osquery_parser.py`](../backend/app/discovery/osquery_parser.py):
  - `OsqueryDiscoveryParser`: Parser tolerante a fallos por sección, conversión segura de enteros serializados como cadenas (`safe_int`), formateo legible de bytes (`format_bytes`) conservando el valor crudo, separación estricta entre discos físicos (`lsblk` / `block_devices`) y particiones/montajes (`mounts`), cruce de puertos en escucha con procesos (`listening_ports` ↔ `processes`), clasificación de paquetes Debian por categoría funcional e inferencia prudente de motores de bases de datos y mensajería.
- [`backend/app/discovery/cmir_bridge.py`](../backend/app/discovery/cmir_bridge.py):
  - `build_discovery_cmir_and_graph`: Construye el grafo `CMIR` v2 validado y genera los nodos y aristas semánticas (`contains`, `has_interface`, `routes_to`, `listens_on`, `observed_connection`, `inferred_relation`) listos para React Flow.
- [`backend/app/discovery/exporters.py`](../backend/app/discovery/exporters.py):
  - Generadores de reporte técnico en Markdown (`export_discovery_markdown`) y diagrama Mermaid (`export_discovery_mermaid`).
- [`backend/app/discovery/storage.py`](../backend/app/discovery/storage.py):
  - `DiscoverySessionStore`: Caché en memoria y persistencia en disco (`backend/data/discovery_sessions/`, ignorado por Git) indexada por SHA-256 para evitar recargas innecesarias del JSON de 2.3 MB.
- [`backend/app/api/routers/discovery.py`](../backend/app/api/routers/discovery.py):
  - Router FastAPI montado en `/api/v1/discovery`.

### Nuevos módulos en el Frontend (`frontend/src/components/discovery/`)
- [`frontend/src/components/discovery/DiscoveryWorkspace.jsx`](../frontend/src/components/discovery/DiscoveryWorkspace.jsx): Espacio de trabajo principal con barra de control, importación de archivos JSON, selector de sesiones, buscador global, exportación y navegación entre secciones.
- [`frontend/src/components/discovery/DiscoverySections.jsx`](../frontend/src/components/discovery/DiscoverySections.jsx): Secciones jerárquicas y desplegables (`Summary`, `Hardware`, `Software`, `Network`, `Runtime`, `Databases`, `Assessment`) con filtros en servidor/cliente y tablas paginadas.
- [`frontend/src/components/discovery/DiscoveryDiagramCanvas.jsx`](../frontend/src/components/discovery/DiscoveryDiagramCanvas.jsx): Lienzo interactivo `@xyflow/react` con 5 modos de vista, filtros por capa/estado epistémico, controles de zoom/fit, minimapa, leyenda semántica y cajón lateral de inspección profunda.
- [`frontend/src/components/discovery/ExplanationCard.jsx`](../frontend/src/components/discovery/ExplanationCard.jsx): Tarjeta desplegable reutilizable que presenta las 9 dimensiones explicativas y la insignia epistémica (`OBSERVED`, `DERIVED`, `INFERRED`, `UNAVAILABLE`, `ERROR`).

---

## 3. Endpoints REST (`/api/v1/discovery`)

| Método | Ruta | Descripción |
| :--- | :--- | :--- |
| `GET` | `/api/v1/discovery/collectors` | Lista los recolectores soportados (`osquery`, `open-audit`) y las especificaciones de bases de datos (`PostgreSQL`, `MySQL`, `SQLServer`). |
| `GET` | `/api/v1/discovery/sessions` | Lista las sesiones de discovery almacenadas en caché/disco. |
| `GET` | `/api/v1/discovery/latest` | Obtiene la sesión más reciente o importa automáticamente `docs/cloudmove-osquery-inventory.json` si está disponible (`auto_import_default=true`). |
| `POST` | `/api/v1/discovery/import-local` | Importa un archivo JSON desde una ruta local permitida dentro del repositorio. |
| `POST` | `/api/v1/discovery/import` | Importa un inventario mediante subida `multipart/form-data` o cuerpo JSON directo (`cloudmove.discovery.v1` o re-importación de `cloudmove.normalized.v1`). |
| `GET` | `/api/v1/discovery/sessions/{session_id}` | Devuelve el análisis completo de la sesión (`summary`, `hardware`, `software`, `network`, `runtime`, `databases`, `assessment`, `diagram`, `cmir`). |
| `GET` | `/api/v1/discovery/sessions/{session_id}/packages` | Consulta paginada y filtrada (`search`, `category`, `arch`, `page`, `page_size`) de paquetes instalados. |
| `GET` | `/api/v1/discovery/sessions/{session_id}/processes` | Consulta paginada y filtrada (`search`, `category`, `state`, `page`, `page_size`) de procesos observados. |
| `GET` | `/api/v1/discovery/sessions/{session_id}/services` | Consulta paginada y filtrada (`search`, `status`, `user`, `page`, `page_size`) de unidades `systemd`. |
| `GET` | `/api/v1/discovery/sessions/{session_id}/export` | Exporta la sesión en formato `normalized_json`, `cmir`, `markdown` o `mermaid`. |

---

## 4. Cómo Ejecutar y Probar

### 1. Levantar el Backend (FastAPI)
```bash
PYTHONPATH=backend uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Levantar el Frontend (React + Vite)
```bash
npm --prefix frontend run dev
```
En la barra superior de CloudMove, selecciona el modo **`Osquery Discovery`** para abrir el analizador e inspeccionar tanto las secciones desplegables como el diagrama interactivo.

### 3. Ejecutar las Pruebas Automatizadas
```bash
PYTHONPATH=backend python3 -m pytest backend/tests -v
npm --prefix frontend run build
```

---

## 5. Privacidad y Seguridad
- El archivo real `docs/cloudmove-osquery-inventory.json`, cualquier variante `*osquery-inventory*.json` y el directorio de sesiones `backend/data/discovery_sessions/` están excluidos en [`.gitignore`](../.gitignore).
- El inventario original permanece intacto y de solo lectura.
