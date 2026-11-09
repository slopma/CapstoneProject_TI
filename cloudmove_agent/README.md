# CloudMove Agent — Informe Técnico Detallado de Arquitectura, Mensajería, Operación Interna y Desinstalación

Este documento explica en detalle cómo funciona el **Agente de CloudMove** ([`cloudmove_agent/`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent)): cómo se instala y autentica contra la plataforma central, cómo funciona su protocolo de mensajería (peticiones, respuestas, cabeceras criptográficas y *polling* de tareas), qué hace exactamente dentro del computador local o servidor remoto, qué archivos crea en el sistema operativo y cómo se revoca y desinstala sin dejar rastro.

---

## Tabla de Contenidos

1. [Visión General y los 2 Modos de Operación del Agente](#1-visión-general-y-los-2-modos-de-operación-del-agente)
2. [Instalación y Enrolamiento Paso a Paso: ¿Cómo Conecta el Computador con CloudMove?](#2-instalación-y-enrolamiento-paso-a-paso-cómo-conecta-el-computador-con-cloudmove)
   - [2.1 Fase 1: Generación del Token Efímero de Inscripción (`cmat_...`)](#21-fase-1-generación-del-token-efímero-de-inscripción-cmat_)
   - [2.2 Fase 2: Descarga y Ejecución del Instalador (`install.sh` / `install.ps1` / `installer.py`)](#22-fase-2-descarga-y-ejecución-del-instalador-installsh--installps1--installerpy)
   - [2.3 Fase 3: Cálculo de la Identidad Hardware Estable (`machine_id`) y Canje por la `Bearer API Key` (`cma_...`)](#23-fase-3-cálculo-de-la-identidad-hardware-estable-machine_id-y-canje-por-la-bearer-api-key-cma_)
   - [2.4 Fase 4: Persistencia Segura (`chmod 600`) y Registro del Demonio `systemd`](#24-fase-4-persistencia-segura-chmod-600-y-registro-del-demonio-systemd)
3. [Protocolo de Mensajería: Peticiones, Respuestas, Cabeceras y Ciclo de Vida de Tareas](#3-protocolo-de-mensajería-peticiones-respuestas-cabeceras-y-ciclo-de-vida-de-tareas)
   - [3.1 Arquitectura de Comunicación 100% Saliente (*Outbound-Only*)](#31-arquitectura-de-comunicación-100-saliente-outbound-only)
   - [3.2 Cabeceras HTTP de Autenticación y Protección Anti-Replay](#32-cabeceras-http-de-autenticación-y-protección-anti-replay)
   - [3.3 Flujo Completo de Mensajes (Diagrama de Secuencia)](#33-flujo-completo-de-mensajes-diagrama-de-secuencia)
   - [3.4 Detalle de Todas las Peticiones y Respuestas JSON](#34-detalle-de-todas-las-peticiones-y-respuestas-json)
4. [¿Qué Hace Exactamente el Agente Dentro del Computador?](#4-qué-hace-exactamente-el-agente-dentro-del-computador)
   - [4.1 Sondeo Nativo de Hardware, Red, Discos, Servicios y Bases de Datos (`system_collector.py`)](#41-sondeo-nativo-de-hardware-red-discos-servicios-y-bases-de-datos-system_collectorpy)
   - [4.2 Auto-Instalación Portable de `osquery` en Espacio de Usuario y las 16 Consultas SQL (`osquery_installer.py`)](#42-auto-instalación-portable-de-osquery-en-espacio-de-usuario-y-las-16-consultas-sql-osquery_installerpy)
   - [4.3 Lista Blanca de Tareas Autorizadas (`_execute_single_task`) y Bloqueo de Shell Arbitrario](#43-lista-blanca-de-tareas-autorizadas-_execute_single_task-y-bloqueo-de-shell-arbitrario)
5. [Mapa Completo de Archivos, Directorios, Logs y Servicios que Crea en el Computador](#5-mapa-completo-de-archivos-directorios-logs-y-servicios-que-crea-en-el-computador)
6. [¿Cómo se Elimina y Desinstala el Agente por Completo?](#6-cómo-se-elimina-y-desinstala-el-agente-por-completo)
   - [6.1 Paso 1: Revocación de Credenciales desde el Servidor CloudMove](#61-paso-1-revocación-de-credenciales-desde-el-servidor-cloudmove)
   - [6.2 Paso 2: Desinstalación Automática en Linux (`uninstall.sh`)](#62-paso-2-desinstalación-automática-en-linux-uninstallsh)
   - [6.3 Paso 3: Limpieza del Motor Portable `osquery` en Espacio de Usuario (Sin Root)](#63-paso-3-limpieza-del-motor-portable-osquery-en-espacio-de-usuario-sin-root)
   - [6.4 Paso 4: Desinstalación Automática en Windows (`uninstall.ps1`)](#64-paso-4-desinstalación-automática-en-windows-uninstallps1)
   - [6.5 Paso 5: Verificación Forense Post-Desinstalación](#65-paso-5-verificación-forense-post-desinstalación)

---

## 1. Visión General y los 2 Modos de Operación del Agente

Un navegador web, por restricciones de aislamiento (*sandbox*) de seguridad, no tiene acceso directo a la tabla de particiones físicas, sockets del kernel, procesos del sistema ni demonios locales de una máquina. El paquete **[`cloudmove_agent/`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent)** resuelve esto actuando como un **puente local auditado, de solo lectura y con capacidades acotadas por lista blanca** entre el computador/servidor de origen y el backend de CloudMove.

El paquete del agente está diseñado para operar en **dos modos complementarios** según la necesidad del usuario:

| Característica | Modo 1: Demonio de Producción (`agent_daemon.py`) | Modo 2: Puente Local Interactivo + `osquery` Portable (`app.py`) |
| :--- | :--- | :--- |
| **Propósito Principal** | Monitoreo continuo de servidores on-premise/VMs, envío periódico de *heartbeats* de salud y ejecución de órdenes remotas de migración (Caso 2 y Caso 3). | Descubrimiento inmediato del PC local desde el asistente web de CloudMove sin necesidad de permisos `root`/`sudo`. |
| **Archivo Principal** | [`cloudmove_agent/agent_daemon.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/agent_daemon.py) y [`cloudmove_agent/installer.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/installer.py) | [`cloudmove_agent/app.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/app.py), [`cloudmove_agent/osquery_installer.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/osquery_installer.py) y [`cloudmove_osquery_export.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_osquery_export.py) |
| **Cómo se Ejecuta** | Como servicio de sistema en segundo plano (`systemd`: `cloudmove-agent.service`) o proceso continuo `python3 -m cloudmove_agent.agent_daemon`. | Como microservicio local en el puerto `8001` (`uvicorn cloudmove_agent.app:app --port 8001`) o script CLI. |
| **Dirección de Red** | **100% Saliente (*Outbound-Only*)**: el agente inicia todas las conexiones HTTP/HTTPS hacia `/api/v1/agents/*` cada 20 segundos. No abre ningún puerto entrante. | Escucha localmente en `127.0.0.1:8001` (con CORS restringido a `localhost`) y sube el inventario a `/api/v1/discovery/osquery`. |
| **Privilegios Requeridos** | `root` / `sudo` (para registrar `systemd` e inspeccionar dispositivos de bloque físicos). Soportado también en modo usuario (`--no-service`). | **No requiere `root` ni `sudo`**: descarga `osquery` portable en `~/.local/share/cloudmove/osquery` y ejecuta con `--allow-non-root`. |

---

## 2. Instalación y Enrolamiento Paso a Paso: ¿Cómo Conecta el Computador con CloudMove?

El proceso de conexión entre el computador local y el backend de CloudMove utiliza un **esquema de autenticación en dos etapas** (implementado en [`backend/app/api/routers/agents.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/api/routers/agents.py) y [`backend/app/persistence/transactional_db.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py#L1208-L1389)):
1. Un **Token de Inscripción Efímero (`cmat_...`)** de tiempo y número de usos limitados para autorizar el alta inicial.
2. Una **Llave de API Permanente por Agente (`cma_...`)** emitida únicamente tras validar el token de inscripción y vinculada al identificador de hardware (`machine_id`) del equipo.

### 2.1 Fase 1: Generación del Token Efímero de Inscripción (`cmat_...`)

1. El operador solicita en la interfaz de CloudMove (o mediante `POST /api/v1/agents/enrollment-tokens`) un nuevo token de inscripción.
2. El método [`TransactionalDatabase.create_enrollment_token()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py#L1208-L1255) genera un secreto criptográfico de 32 bytes de entropía:
   ```text
   cmat_<secrets.token_urlsafe(32)>
   ```
3. **Seguridad en Base de Datos**: El servidor **nunca guarda el token en texto plano**. Calcula inmediatamente su digest `SHA-256` (`token_hash`) y guarda en la tabla `agent_enrollment_tokens`:
   - `token_id` (ej. `tok-8f4a2c91b3e0`)
   - `token_hash` (el hash SHA-256 de 64 caracteres hexadecimales)
   - `token_prefix` (los primeros 12 caracteres `cmat_xxxxxxx...` solo para identificación visual en la UI)
   - `expires_at` (por defecto 24 horas: `86400` segundos)
   - `max_uses` (por defecto `1`, es decir, de **un solo uso**) y `uses_count = 0`
4. El endpoint devuelve al operador el comando exacto de instalación para Linux y para Windows:
   - **Linux**:
     ```bash
     curl -sSL http://<SERVIDOR>:8000/api/v1/agents/install.sh | sudo bash -s -- --token cmat_... --server http://<SERVIDOR>:8000
     ```
   - **Windows (PowerShell Administrador)**:
     ```powershell
     Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('http://<SERVIDOR>:8000/api/v1/agents/install.ps1')) -Server 'http://<SERVIDOR>:8000' -Token 'cmat_...'
     ```

---

### 2.2 Fase 2: Descarga y Ejecución del Instalador (`install.sh` / `install.ps1` / `installer.py`)

Cuando el usuario ejecuta el comando en su computador Linux ([`download_linux_installer()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/api/routers/agents.py#L241-L390) o [`cloudmove_agent/install.sh`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/install.sh)):

1. **Verificación de Entorno**: Comprueba que se esté ejecutando con permisos `root` (`$EUID -eq 0`) y que existan los binarios `python3`, `curl` y `tar`.
2. **Creación de Estructura de Directorios**:
   - `/opt/cloudmove-agent`: donde residirá el código Python del agente.
   - `/etc/cloudmove`: donde se almacenará la credencial privada (`agent.conf`).
   - `/var/log/cloudmove`: donde se escribirá la bitácora local (`agent.log`).
3. **Descarga en Vivo del Paquete (`GET /api/v1/agents/bundle.tar.gz`)**:
   El servidor empaqueta al vuelo en memoria (`io.BytesIO` + `tarfile`) todos los módulos `.py`, `.sh` y `.service` del directorio [`cloudmove_agent/`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent) y el script los extrae en `/opt/cloudmove-agent/cloudmove_agent`.

---

### 2.3 Fase 3: Cálculo de la Identidad Hardware Estable (`machine_id`) y Canje por la `Bearer API Key` (`cma_...`)

Antes de conectarse al endpoint de enrolamiento, el instalador determina la **identidad única e inmutable de la máquina** ([`get_stable_machine_id()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/system_collector.py#L37-L67)):
1. En **Linux**, lee en orden de prioridad:
   - `/etc/machine-id` (identificador de 128 bits generado en la instalación del SO).
   - `/var/lib/dbus/machine-id`.
   - `/sys/class/dmi/id/product_uuid` (UUID físico de la placa base / SMBIOS del hipervisor).
2. En **Windows**, lee la llave criptográfica del registro:
   - `HKLM:\SOFTWARE\Microsoft\Cryptography -> MachineGuid`.
3. Si ninguno está disponible, construye un identificador determinista a partir de la dirección MAC física (`uuid.getnode()`).

Con estos datos, el instalador envía `POST /api/v1/agents/enroll`. El backend ejecuta [`verify_and_consume_enrollment_token()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py#L1276-L1304) y [`enroll_agent()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py#L1306-L1373):
- Verifica que el `SHA-256` del `enrollment_token` exista, no esté revocado (`revoked = 0`), no haya expirado (`expires_at > now`) y que `uses_count < max_uses`.
- Incrementa `uses_count`. Si alcanzó `max_uses`, marca automáticamente el token de inscripción como `revoked = 1` para que **nadie más pueda reutilizarlo**.
- Calcula el `agent_id` de forma determinista:
  ```python
  agent_id = f"agent-{hashlib.sha256((machine_id + hostname).encode()).hexdigest()[:16]}"
  ```
  *(Esto garantiza que si un mismo computador se reinstala o reconecta, conserve su mismo `agent_id` en el inventario de CloudMove sin duplicar máquinas).*
- Genera la **API Key exclusiva del agente**: `cma_<secrets.token_urlsafe(32)>`, guarda solo su hash `SHA-256` en la columna `auth_token_hash` de la tabla `agents`, y se la devuelve por única vez al instalador.

---

### 2.4 Fase 4: Persistencia Segura (`chmod 600`) y Registro del Demonio `systemd`

Con el `agent_id` y la `agent_api_key` recibidos:
1. Escribe el archivo `/etc/cloudmove/agent.conf` ([`write_agent_config()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/installer.py#L121-L143)):
   ```ini
   [agent]
   server_url = http://localhost:8000
   agent_id = agent-4b92e10a8c7d3f12
   api_key = cma_9xK2mP...
   heartbeat_interval = 20
   enrolled_at = 2026-11-09T19:30:00+00:00
   ```
2. Aplica permisos **`chmod 600 /etc/cloudmove/agent.conf`** (`0o600`), de modo que ningún otro usuario no privilegiado del computador pueda leer la llave `cma_...`.
3. Crea la unidad `/etc/systemd/system/cloudmove-agent.service` con directivas de aislamiento de seguridad (`NoNewPrivileges=true` y `ProtectSystem=full`), ejecuta `systemctl daemon-reload`, `systemctl enable cloudmove-agent` y `systemctl restart cloudmove-agent`.

---

## 3. Protocolo de Mensajería: Peticiones, Respuestas, Cabeceras y Ciclo de Vida de Tareas

### 3.1 Arquitectura de Comunicación 100% Saliente (*Outbound-Only*)

El demonio [`CloudMoveAgentDaemon`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/agent_daemon.py#L77-L370) nunca abre un socket `LISTEN` en la red del computador donde se instala. Toda la mensajería sigue un modelo **Pull / Outbound-Polling** sobre HTTP/HTTPS:
- Esto permite que el agente funcione detrás de firewalls corporativos, routers domésticos con NAT o subredes privadas sin necesidad de abrir puertos entrantes ni configurar redirección de puertos.
- El bucle principal ([`run_forever()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/agent_daemon.py#L344-L366)) ejecuta un escaneo inicial de inventario al arrancar y luego, cada **20 segundos** (`heartbeat_interval`), envía un *heartbeat* y consulta si existen tareas pendientes para él.

---

### 3.2 Cabeceras HTTP de Autenticación y Protección Anti-Replay

Cada petición HTTP enviada por el agente mediante [`_http_request()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/agent_daemon.py#L121-L156) incluye **5 cabeceras de seguridad**:

```http
User-Agent: CloudMove-Agent/2.1
Content-Type: application/json
Accept: application/json
Authorization: Bearer cma_9xK2mP8vL4nQ1wR7tY5uI0oP3aS6dF8gH1jK4lZ7xC
X-Agent-ID: agent-4b92e10a8c7d3f12
X-Agent-Timestamp: 2026-11-09T19:45:12.401823+00:00
X-Agent-Nonce: 7f8c9a12b4e64d109c3a8b5e2f1d0a4c
```

**¿Cómo valida el servidor cada mensaje entrante?**
1. **Verificación Criptográfica de la API Key ([`_verify_agent_auth`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/api/routers/agents.py#L104-L118) y [`authenticate_agent`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py#L1375-L1389))**:
   Extrae el token del header `Authorization: Bearer <api_key>`, calcula su hash `SHA-256` y verifica en la tabla `agents` que coincida exactamente con `auth_token_hash` para ese `agent_id` y que su estado no sea `REVOKED`. Si no coincide o fue revocado, responde inmediatamente con `HTTP 401 Unauthorized` o `HTTP 403 Forbidden`.
2. **Ventana Anti-Replay de 300 Segundos ([`record_agent_heartbeat`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py#L1402-L1412))**:
   El servidor compara `X-Agent-Timestamp` con el reloj UTC actual:
   ```python
   diff = abs((curr_dt - ts_dt).total_seconds())
   if diff > 300:
       raise ValueError(f"Heartbeat timestamp skew out of tolerance ({diff:.1f}s > 300s). Replay rejected.")
   ```
   Si un atacante interceptara un paquete en tránsito e intentara reenviarlo minutos después, el backend lo rechaza con `HTTP 400 Bad Request`.

---

### 3.3 Flujo Completo de Mensajes (Diagrama de Secuencia)

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operador (UI / API)
    participant Srv as Backend CloudMove (/api/v1/agents)
    participant DB as SQLite WAL (transactional_db.py)
    participant Daemon as Agente en el Computador (agent_daemon.py)

    Note over Op,DB: 1. Fase de Autorización e Inscripción
    Op->>Srv: POST /api/v1/agents/enrollment-tokens (ttl=86400, max_uses=1)
    Srv->>DB: Guarda SHA-256(cmat_...) en agent_enrollment_tokens
    Srv-->>Op: Devuelve cmat_... + comando install.sh / install.ps1

    Op->>Daemon: Ejecuta install.sh --token cmat_...
    Daemon->>Srv: POST /api/v1/agents/enroll (enrollment_token, hostname, machine_id, os_info)
    Srv->>DB: Consume token cmat_... (uses_count++) y registra agente con SHA-256(cma_...)
    Srv-->>Daemon: HTTP 200 {agent_id, agent_api_key: "cma_...", heartbeat_interval_seconds: 20}
    Daemon->>Daemon: Guarda /etc/cloudmove/agent.conf (chmod 600) e inicia systemd

    Note over Daemon,DB: 2. Escaneo Inicial Automático al Arrancar
    Daemon->>Daemon: Ejecuta collect_system_inventory() (CPU, RAM, Discos, Red, Puertos, Servicios, DBs)
    Daemon->>Srv: POST /api/v1/agents/{agent_id}/inventory (Bearer cma_...)
    Srv->>DB: upsert_asset(asset-agent-..., canonical_key="host:<machine_id>")
    Srv-->>Daemon: HTTP 200 {"status": "ingested", "asset_id": "asset-agent-..."}

    Note over Op,Daemon: 3. Bucle Continuo de Heartbeat y Despacho de Tareas (Cada 20s)
    Op->>Srv: POST /api/v1/agents/{agent_id}/dispatch-task {"action": "inspect_disk"}
    Srv->>DB: Valida Whitelist e inserta en agent_tasks con status = 'PENDING'
    Srv-->>Op: HTTP 200 {"task_id": "task-a1b2c3", "status": "PENDING"}

    Daemon->>Srv: POST /api/v1/agents/{agent_id}/heartbeat (CPU %, RAM %, Load, Nonce, Timestamp)
    Srv->>DB: Verifica Timestamp (<300s), actualiza status='ONLINE' y cuenta tareas PENDING
    Srv-->>Daemon: HTTP 200 {"status": "ONLINE", "pending_tasks_count": 1}

    Daemon->>Srv: GET /api/v1/agents/{agent_id}/tasks (Bearer cma_...)
    Srv->>DB: Selecciona tareas PENDING y las actualiza atómicamente a status = 'DISPATCHED'
    Srv-->>Daemon: HTTP 200 {"tasks": [{"task_id": "task-a1b2c3", "action": "inspect_disk", ...}]}

    Daemon->>Daemon: Ejecuta _execute_single_task("inspect_disk") localmente
    Daemon->>Srv: POST /api/v1/agents/{agent_id}/tasks/task-a1b2c3/result {"status": "COMPLETED", "result": {...}}
    Srv->>DB: Actualiza agent_tasks SET status = 'COMPLETED', result_json = ...
    Srv-->>Daemon: HTTP 200 {"task_id": "task-a1b2c3", "status": "COMPLETED"}
```

---

### 3.4 Detalle de Todas las Peticiones y Respuestas JSON

A continuación se documenta el contrato exacto de cada endpoint que utiliza el agente:

#### 1. Enrolamiento del Computador (`POST /api/v1/agents/enroll`)
- **Petición enviada por el instalador del agente**:
  ```json
  {
    "enrollment_token": "cmat_8f9d2a1b4c6e7f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c",
    "hostname": "prod-db-01.empresa.local",
    "ip_address": "192.168.1.50",
    "os_family": "linux",
    "os_name": "Linux",
    "os_version": "#45-Ubuntu SMP PREEMPT_DYNAMIC",
    "architecture": "x86_64",
    "machine_id": "9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c",
    "version": "2.1.0",
    "capabilities": [
      "discovery",
      "advanced_inspection",
      "disk_snapshot",
      "native_tool_install",
      "config_modification",
      "service_control",
      "cutover_revert"
    ]
  }
  ```
- **Respuesta del servidor CloudMove (`200 OK`)**:
  ```json
  {
    "status": "ONLINE",
    "agent_id": "agent-4b92e10a8c7d3f12",
    "agent_api_key": "cma_9xK2mP8vL4nQ1wR7tY5uI0oP3aS6dF8gH1jK4lZ7xC",
    "hostname": "prod-db-01.empresa.local",
    "capabilities": [
      "discovery",
      "advanced_inspection",
      "disk_snapshot",
      "native_tool_install",
      "config_modification",
      "service_control",
      "cutover_revert"
    ],
    "enrolled_at": "2026-11-09T19:30:00.123456+00:00",
    "server_version": "2.1.0",
    "heartbeat_interval_seconds": 20
  }
  ```

#### 2. Latido de Salud Periódico (`POST /api/v1/agents/{agent_id}/heartbeat`)
- **Petición enviada por el agente cada 20 segundos**:
  ```json
  {
    "health_metrics": {
      "cpu_percent": 14.2,
      "ram_percent": 41.8,
      "ram_used_mb": 6688,
      "ram_total_mb": 16000,
      "load_average": {
        "1m": 0.56,
        "5m": 0.42,
        "15m": 0.38
      },
      "status": "HEALTHY",
      "uptime_seconds": 84520.4
    },
    "nonce": "7f8c9a12b4e64d109c3a8b5e2f1d0a4c",
    "timestamp": "2026-11-09T19:30:20.000000+00:00"
  }
  ```
- **Respuesta del servidor CloudMove (`200 OK`)**:
  ```json
  {
    "agent_id": "agent-4b92e10a8c7d3f12",
    "status": "ONLINE",
    "last_heartbeat_at": "2026-11-09T19:30:20.014210+00:00",
    "pending_tasks_count": 1
  }
  ```
  > **Detección Automática de Desconexión (`OFFLINE`)**: Cuando cualquier usuario consulta la lista de agentes (`GET /api/v1/agents`), [`TransactionalDatabase.list_agents()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py#L1458-L1464) calcula `now_ts - last_heartbeat_at`. Si han transcurrido **más de 60 segundos** (3 latidos perdidos) sin recibir un *heartbeat*, el estado del agente cambia dinámicamente de `ONLINE` a `OFFLINE`.

#### 3. Consulta de Tareas Pendientes (`GET /api/v1/agents/{agent_id}/tasks`)
- **Respuesta del servidor CloudMove (`200 OK`)**:
  Al responder esta llamada, el backend cambia atómicamente el estado de cada tarea entregada de `PENDING` a `DISPATCHED` para que no se ejecute dos veces:
  ```json
  {
    "tasks": [
      {
        "task_id": "task-9d8e7f6a5b4c",
        "agent_id": "agent-4b92e10a8c7d3f12",
        "action": "check_mgn_prerequisites",
        "parameters": {
          "region": "us-east-1"
        },
        "status": "DISPATCHED",
        "created_at": "2026-11-09T19:30:15.000000+00:00",
        "timeout_seconds": 300
      }
    ]
  }
  ```

#### 4. Entrega del Resultado de una Tarea (`POST /api/v1/agents/{agent_id}/tasks/{task_id}/result`)
- **Petición enviada por el agente al terminar la tarea**:
  ```json
  {
    "status": "COMPLETED",
    "result": {
      "service": "aws_mgn",
      "region": "us-east-1",
      "mgn_endpoint": "mgn.us-east-1.amazonaws.com",
      "tcp_443_outbound": true,
      "python_installed": true,
      "ready_for_mgn_agent": true
    },
    "error": null
  }
  ```

#### 5. Ingesta del Inventario Completo del Computador (`POST /api/v1/agents/{agent_id}/inventory`)
- **Petición enviada por el agente (`collect_system_inventory()`)**:
  Envía el documento JSON con CPU, memoria, discos/particiones (`lsblk` + `statvfs`), interfaces de red (`ip -j addr`), puertos en escucha (`ss -tulpn`), servicios `systemd`, runtimes (`python3`, `node`, `java`, `go`, `docker`) y motores de bases de datos detectados localmente.
- **Respuesta del servidor CloudMove (`200 OK`)**:
  Reconcilia el servidor en la tabla transaccional `assets` bajo la llave única `host:<machine_id>`:
  ```json
  {
    "status": "ingested",
    "agent_id": "agent-4b92e10a8c7d3f12",
    "asset_id": "asset-agent-4b92e10a8c7d3f12",
    "canonical_key": "host:9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c",
    "hostname": "prod-db-01.empresa.local",
    "ingested_at": "2026-11-09T19:30:05.512000+00:00"
  }
  ```

---

## 4. ¿Qué Hace Exactamente el Agente Dentro del Computador?

El agente opera bajo un principio estricto: **inspección de solo lectura y ejecución exclusiva de primitivas de migración autorizadas**. A continuación se detalla qué módulos internos se ejecutan en el computador y cómo obtienen la información.

### 4.1 Sondeo Nativo de Hardware, Red, Discos, Servicios y Bases de Datos (`system_collector.py`)

El módulo [`cloudmove_agent/system_collector.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/system_collector.py) recolecta la radiografía del computador sin depender de librerías externas pesadas:

1. **Procesador y Carga (`collect_cpu_info`)**:
   - Lee `/proc/cpuinfo` para extraer el nombre exacto del procesador (`model name`), cuenta los núcleos con `os.cpu_count()` y consulta la carga del kernel (`1m`, `5m`, `15m`) con `os.getloadavg()`.
2. **Memoria Física y Swap (`collect_memory_info`)**:
   - Parsea `/proc/meminfo` (`MemTotal`, `MemAvailable`, `MemFree`, `SwapTotal`, `SwapFree`) calculando al megabyte la memoria usada y el porcentaje real de ocupación.
3. **Discos Físicos, Particiones y Puntos de Montaje (`collect_disks_and_mounts`)**:
   - Lee `/proc/mounts` filtrando sistemas de archivos reales (`ext4`, `xfs`, `btrfs`, `vfat`, `ntfs`, `zfs`, `nfs`, `cifs`, `overlay`) e invoca `os.statvfs(mountpoint)` sobre cada uno para obtener el tamaño total, usado y libre en MB/GB.
   - Ejecuta `lsblk -J -b -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,UUID,ROTA` para obtener el árbol jerárquico de discos físicos y sus particiones hijas, incluyendo el `UUID` de cada partición y si es disco mecánico rotacional (`rota == "1"`) o SSD/NVMe.
4. **Interfaces de Red, MACs y Direcciones IP (`collect_network_interfaces`)**:
   - Lee `/sys/class/net/<iface>/address` y `/operstate`, y ejecuta `ip -j addr` para obtener todas las direcciones IPv4 e IPv6 asignadas y sus máscaras de prefijo (`prefixlen`).
5. **Puertos TCP/UDP en Escucha (`collect_listening_ports`)**:
   - Ejecuta `ss -tulpn` para identificar todos los sockets abiertos y el proceso asociado.
   - Si `ss` no está disponible, incluye un **parser directo del kernel sobre `/proc/net/tcp` y `/proc/net/tcp6`** que filtra las líneas cuyo estado hexadecimal es `0A` (`TCP_LISTEN`) y convierte el puerto hexadecimal (`int(port_hex, 16)`) a decimal.
6. **Servicios del Sistema (`collect_system_services`)**:
   - Ejecuta `systemctl list-units --type=service --all --no-pager --no-legend` para listar las unidades `.service`, su estado de carga (`loaded`), estado de activación (`active`/`inactive`) y descripción.
7. **Detección No Intrusiva de Bases de Datos Locales (`detect_local_databases`)**:
   - Verifica puertos en escucha y sockets Unix locales (`/var/run/postgresql`, `/var/run/redis`, `/var/run/mysqld`) para detectar instancias activas de **PostgreSQL** (`5432`), **MySQL/MariaDB** (`3306`), **Redis** (`6379`) y **RabbitMQ** (`5672`).
   - **Privacidad de Datos**: El recolector **jamás abre conexiones SQL ni lee tablas de negocio**; únicamente registra la presencia del motor, marca `is_shared = True` y señala si requiere sincronización de disco (`requires_quiescing = True`).

---

### 4.2 Auto-Instalación Portable de `osquery` en Espacio de Usuario y las 16 Consultas SQL (`osquery_installer.py`)

Cuando el usuario utiliza el modo de descubrimiento profundo con `osquery` ([`cloudmove_agent/app.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/app.py) + [`cloudmove_agent/osquery_installer.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/osquery_installer.py) + [`cloudmove_osquery_export.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_osquery_export.py)), el agente realiza un flujo completamente automatizado:

1. **Detección del Equipo y Selección del Paquete Portable (`select_asset_for_current_pc`)**:
   - Detecta el sistema operativo (`linux`, `windows`, `darwin`) y la arquitectura (`x86_64`, `aarch64`).
   - Consulta la API de lanzamientos de GitHub de `osquery` (o su catálogo local verificado `FALLBACK_RELEASE_ASSETS` para la versión `5.23.1`) y selecciona prioritariamente el paquete **portable (`.tar.gz` o `.zip`)** que puede extraerse en espacio de usuario **sin pedir contraseña de `sudo` ni permisos de Administrador**.
2. **Verificación Criptográfica `SHA-256` y Extracción Anti-Path-Traversal (`_extract_archive_safely`)**:
   - Descarga el paquete en un directorio temporal, calcula su hash `SHA-256` y lo compara con el digest oficial (`expected_sha256`). Si difiere en un solo bit, aborta la instalación.
   - Inspecciona cada miembro y enlace simbólico del archivo `.tar.gz` antes de extraerlo para garantizar que ninguna ruta contenga `..` ni apunte fuera del directorio de destino, reescribiendo enlaces absolutos internos (`/opt/osquery/bin/osqueryd`) a enlaces relativos seguros dentro de `~/.local/share/cloudmove/osquery`.
   - Crea el enlace ejecutable en `~/.local/bin/osqueryi` (en Linux/macOS) o `%LOCALAPPDATA%\CloudMove\bin\osqueryi.exe` (en Windows).
3. **Prueba Funcional (*Smoke Test*) y Ejecución de las 16 Consultas SQL**:
   - Ejecuta `osqueryi --json "SELECT version, build_platform, build_distro FROM osquery_info LIMIT 1;"` para certificar que el binario funciona en el computador.
   - A continuación, [`cloudmove_osquery_export.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_osquery_export.py#L31-L54) ejecuta las **16 consultas SQL de solo lectura** contra las tablas virtuales del sistema operativo:
     `system_info`, `os_version`, `platform_info`, `cpu_info`, `memory_info`, `uptime`, `interface_addresses`, `routes`, `mounts`, `block_devices`, `listening_ports`, `processes`, `process_open_sockets`, `deb_packages`, `systemd_units` y `kernel_modules`.
   - Guarda el resultado en [`docs/cloudmove-osquery-agent-inventory.json`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/docs/cloudmove-osquery-agent-inventory.json) y lo sube automáticamente al backend de CloudMove (`POST /api/v1/discovery/osquery`).

---

### 4.3 Lista Blanca de Tareas Autorizadas (`_execute_single_task`) y Bloqueo de Shell Arbitrario

Por diseño de seguridad, **el Agente de CloudMove NO permite la ejecución remota de comandos arbitrarios (RCE)**. Ni el backend ([`TransactionalDatabase.create_agent_task()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py#L1524-L1537)) ni el demonio local ([`CloudMoveAgentDaemon._execute_single_task()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/agent_daemon.py#L194-L217)) aceptan cadenas de comandos bash/powershell libres.

Únicamente pueden ejecutarse las siguientes **acciones cerradas en lista blanca**:

| Nombre de la Acción (`action`) | Qué Ejecuta Internamente el Agente en el Computador |
| :--- | :--- |
| **`collect_inventory`** | Ejecuta `collect_system_inventory()` y sube el inventario completo actualizado a `POST /api/v1/agents/{agent_id}/inventory`. |
| **`inspect_disk`** | Ejecuta `collect_disks_and_mounts()` para devolver la geometría actual de discos, tablas de particiones, puntos de montaje, UUIDs y espacio libre. |
| **`check_mgn_prerequisites`** | Comprueba desde el computador local si existe salida TCP en el puerto `443` hacia el endpoint regional de **AWS Application Migration Service** (`mgn.<region>.amazonaws.com`) y valida el soporte de Python para el agente de replicación de bloques de AWS. |
| **`check_gcp_migrate_prerequisites`** | Comprueba desde el computador local la conectividad TCP saliente en el puerto `443` hacia **Google Cloud Migrate to Virtual Machines** (`vmmigration.googleapis.com`). |
| **`quiesce_database` / `unquiesce_database`** | Invoca directamente a la librería C del sistema (`ctypes.CDLL("libc.so.6").sync()`) para volcar todos los buffers de memoria del kernel a los discos físicos antes de tomar un snapshot de bloque consistente. |
| **`capture_live_os` / `create_disk_image`** | Invoca a [`capture_live_operating_system()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/migration/image_migrator.py#L774-L1085) para capturar el estado del sistema operativo en vivo, empaquetar los manifiestos y generar la imagen virtual en staging con su hash SHA-256. |

Si cualquier petición intenta despachar una acción fuera de esta lista (por ejemplo, `action: "run_shell"`), el agente lanza inmediatamente un `ValueError("Acción rechazada por la política de seguridad del agente. Ejecución arbitraria no autorizada.")` y reporta la tarea como `FAILED`.

---

## 5. Mapa Completo de Archivos, Directorios, Logs y Servicios que Crea en el Computador

Para total transparencia, esta tabla enumera **todos los archivos y directorios** que el agente crea en el computador según el sistema operativo y el modo de instalación:

| Sistema / Modo | Ruta Exacta en el Computador | Qué Contiene / Para Qué Sirve |
| :--- | :--- | :--- |
| **Linux (Servicio `systemd` con `sudo`)** | `/opt/cloudmove-agent/` | Código fuente Python del demonio (`agent_daemon.py`, `system_collector.py`, `installer.py`, `uninstall.sh`). |
| **Linux (Servicio `systemd` con `sudo`)** | `/etc/cloudmove/agent.conf` | Configuración privada del agente (`server_url`, `agent_id`, `api_key`). Protegido con permisos **`0600`** (solo `root`). |
| **Linux (Servicio `systemd` con `sudo`)** | `/etc/systemd/system/cloudmove-agent.service` | Unidad de servicio `systemd` que mantiene el agente activo en segundo plano. |
| **Linux (Servicio `systemd` con `sudo`)** | `/var/log/cloudmove/agent.log` | Archivo de registro de auditoría local donde el agente escribe cada *heartbeat* y cada tarea ejecutada. |
| **Linux / macOS (Modo Usuario sin `sudo`)** | `~/.cloudmove/agent.conf` y `~/.cloudmove/agent.log` | Configuración y logs de respaldo cuando el agente se ejecuta sin permisos de superusuario. |
| **Linux / macOS (`osquery` Portable sin `sudo`)** | `~/.local/share/cloudmove/osquery/` | Árbol de archivos del binario portable oficial de `osquery v5.23.1` descargado en espacio de usuario. |
| **Linux / macOS (`osquery` Portable sin `sudo`)** | `~/.local/bin/osqueryi` | Enlace simbólico hacia el ejecutable `osqueryd`/`osqueryi` extraído localmente. |
| **Windows (PowerShell Administrador)** | `C:\Program Files\CloudMove\agent.conf` y `\logs` | Directorio de instalación, configuración y bitácora del agente en Windows. |
| **Windows (`osquery` Portable Usuario)** | `%LOCALAPPDATA%\CloudMove\osquery\` y `\bin\osqueryi.exe` | Instalación portable de `osquery` en el perfil local del usuario de Windows. |

---

## 6. ¿Cómo se Elimina y Desinstala el Agente por Completo?

Una vez finalizada la migración o el descubrimiento del computador, puedes desconectar y eliminar por completo el agente tanto del **servidor de CloudMove** (revocación criptográfica) como del **computador local** (eliminación de servicios, binarios, credenciales y logs).

### 6.1 Paso 1: Revocación de Credenciales desde el Servidor CloudMove

Antes o después de desinstalar el agente en la máquina, el operador puede invalidar permanentemente su llave de acceso en el backend de CloudMove:

- **Desde la API o Interfaz Web**:
  ```bash
  curl -X POST http://localhost:8000/api/v1/agents/<AGENT_ID>/revoke \
    -H "Content-Type: application/json" \
    -d '{
      "reason": "Migración completada - Desmantelamiento de agente local",
      "operator_id": "admin@cloudmove.local"
    }'
  ```
- **¿Qué hace esto en el backend?**:
  Ejecuta [`TransactionalDatabase.revoke_agent()`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/backend/app/persistence/transactional_db.py#L1481-L1509), cambiando el estado del agente a `REVOKED`, registrando la fecha exacta (`revoked_at`), el motivo (`revocation_reason`) y escribiendo un evento inmutable `REVOKE_AGENT` en `audit_events`. A partir de ese milisegundo, cualquier intento de usar esa `agent_api_key` recibe `HTTP 403 Forbidden`.

---

### 6.2 Paso 2: Desinstalación Automática en Linux (`uninstall.sh`)

El paquete incluye el script oficial [`cloudmove_agent/uninstall.sh`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/uninstall.sh). Para ejecutarlo en el computador donde se instaló el servicio:

```bash
sudo bash /opt/cloudmove-agent/uninstall.sh
```
*(O desde el repositorio local: `sudo bash cloudmove_agent/uninstall.sh`)*.

**¿Qué hace exactamente `uninstall.sh` paso a paso dentro del computador?**
1. **Detiene el proceso en ejecución**: Comprueba si `cloudmove-agent.service` está activo (`systemctl is-active --quiet cloudmove-agent`) y ejecuta `systemctl stop cloudmove-agent`.
2. **Deshabilita el arranque automático**: Ejecuta `systemctl disable cloudmove-agent` para eliminar los enlaces simbólicos en `/etc/systemd/system/multi-user.target.wants/`.
3. **Elimina la unidad de `systemd` y recarga el demonio**: Borra `/etc/systemd/system/cloudmove-agent.service` y ejecuta `systemctl daemon-reload`.
4. **Borra el código y las credenciales**: Elimina recursivamente `/opt/cloudmove-agent` y `/etc/cloudmove` (incluyendo `/etc/cloudmove/agent.conf` con la `api_key`).
5. **Limpieza opcional de logs de auditoría**: Pregunta interactivamente si deseas eliminar también `/var/log/cloudmove` (`s/N`) y, si confirmas con `s`, borra por completo el directorio de registros.

---

### 6.3 Paso 3: Limpieza del Motor Portable `osquery` en Espacio de Usuario (Sin Root)

Si además utilizaste el modo de descubrimiento local sin root ([`osquery_installer.py`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/osquery_installer.py)), que instala el binario portable de `osquery` dentro de la carpeta personal del usuario (`~/.local`), puedes eliminarlo con un solo comando sin necesitar `sudo`:

```bash
rm -rf ~/.local/share/cloudmove ~/.local/bin/osqueryi ~/.cloudmove
```

---

### 6.4 Paso 4: Desinstalación Automática en Windows (`uninstall.ps1`)

En sistemas Windows, abre una consola de **PowerShell como Administrador** y ejecuta el script oficial [`cloudmove_agent/uninstall.ps1`](file:///home/lacastrilp/Documentos/Semestre_2026_2/CapstoneProject_TI/cloudmove_agent/uninstall.ps1):

```powershell
.\cloudmove_agent\uninstall.ps1
# Y si se utilizó osquery portable en el perfil del usuario:
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\CloudMove" -ErrorAction SilentlyContinue
```

Esto elimina por completo `C:\Program Files\CloudMove` (junto con `agent.conf` y la carpeta `logs`) y cualquier binario portable de `osqueryi.exe` alojado en `%LOCALAPPDATA%\CloudMove`.

---

### 6.5 Paso 5: Verificación Forense Post-Desinstalación

Para comprobar con total certeza que el agente fue eliminado del computador Linux y que no queda ningún proceso, servicio ni archivo de configuración activo, puedes ejecutar los siguientes 3 comandos de verificación:

```bash
# 1. Verificar que el servicio systemd ya no existe (debe indicar "Unit cloudmove-agent.service could not be found")
systemctl status cloudmove-agent

# 2. Verificar que no hay ningún proceso de Python ejecutando cloudmove_agent
ps aux | grep -i cloudmove_agent

# 3. Verificar que los directorios de instalación y credenciales fueron eliminados
ls -la /opt/cloudmove-agent /etc/cloudmove ~/.local/share/cloudmove
```
