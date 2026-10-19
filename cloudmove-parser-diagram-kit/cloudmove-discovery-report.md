# CloudMove — informe de discovery osquery

- **Activo:** rabbitmq-kali
- **Fecha de recolección (UTC):** 2026-10-19T17:45:34+00:00
- **Fuente:** osquery / osqueryi version 5.23.1
- **Sistema operativo:** Kali GNU/Linux 2026.3 (x86_64)
- **Modelo:** LENOVO IdeaPad Gaming 3 15IAH7
- **CPU:** 12th Gen Intel(R) Core(TM) i7-12650H; 10 núcleos físicos / 16 lógicos
- **RAM total:** 15.35 GiB; disponible en la instantánea: 8.55 GiB
- **Consultas osquery:** 16/16 exitosas; errores: 0

> **Alcance:** este archivo describe una instantánea del portátil donde se ejecutó osquery. No es un inventario de todo el rack ni evidencia por sí sola de qué cargas deben migrarse.

## Interfaces de red

| Interfaz | Dirección/CIDR | Subred inferida |
|---|---|---|
| lo | 127.0.0.1/8 | 127.0.0.0/8 |
| wlan0 | 10.10.37.219/23 | 10.10.36.0/23 |
| docker0 | 172.17.0.1/16 | 172.17.0.0/16 |
| lo | ::1 | — |
| wlan0 | fe80::f59:e31d:f797:6f70%wlan0 | — |

**Puerta(s) de enlace por defecto:** 10.10.36.1

## Discos y sistemas de archivos

| Dispositivo | Tamaño estimado | Modelo |
|---|---:|---|
| /dev/nvme0n1 | 476.9 GiB | UMIS RPJTJ512MGE1QDY |
| /dev/nvme0n1p1 | no calculado | UMIS RPJTJ512MGE1QDY |
| /dev/nvme0n1p2 | no calculado | UMIS RPJTJ512MGE1QDY |
| /dev/nvme0n1p3 | no calculado | UMIS RPJTJ512MGE1QDY |

| Punto de montaje | Sistema de archivos | Total estimado | Disponible estimado |
|---|---|---:|---:|
| / | ext4 | 452.0 GiB | 240.8 GiB |
| /boot/efi | vfat | 974.1 MiB | 965.8 MiB |

## Servicios en escucha observados

| Proceso | Dirección | Protocolo/puerto | Exposición |
|---|---|---|---|
| sshd | 0.0.0.0 | TCP/22 | all_interfaces_or_unspecified |
| sshd | :: | TCP/22 | all_interfaces_or_unspecified |
| NetworkManager | :: | PROTO 255/58 | all_interfaces_or_unspecified |
| avahi-daemon | 0.0.0.0 | UDP/5353 | all_interfaces_or_unspecified |
| avahi-daemon | :: | UDP/5353 | all_interfaces_or_unspecified |
| ollama | 127.0.0.1 | TCP/11434 | loopback_only |
| agy | 127.0.0.1 | TCP/33535 | loopback_only |
| code | 127.0.0.1 | TCP/33843 | loopback_only |
| agy | 127.0.0.1 | TCP/37559 | loopback_only |
| code | 127.0.0.1 | TCP/38889 | loopback_only |
| containerd | 127.0.0.1 | TCP/42161 | loopback_only |
| code | 127.0.0.1 | TCP/46441 | loopback_only |
| next-server (v1 | 127.0.0.1 | TCP/54112 | loopback_only |
| code | 127.0.0.1 | TCP/54113 | loopback_only |

## Conexiones remotas observadas en esta instantánea

Estas observaciones son evidencia de sockets vistos en el momento de la recolección; no deben etiquetarse automáticamente como dependencias de aplicación confirmadas.

| IP remota | Protocolo/puerto | Observaciones | Procesos asociados | IP pública según parser |
|---|---|---:|---|---|
| 104.18.39.21 | TCP/443 | 4 | firefox-esr | Sí |
| 104.18.32.47 | TCP/443 | 2 | codex, firefox-esr | Sí |
| 172.64.155.209 | TCP/443 | 1 | firefox-esr | Sí |
| 138.91.182.224 | TCP/443 | 1 | code | Sí |
| 172.217.113.4 | TCP/443 | 1 | agy | Sí |
| 34.107.243.93 | TCP/443 | 1 | firefox-esr | Sí |
| 34.54.84.110 | TCP/443 | 1 | agy | Sí |
| 140.82.113.26 | TCP/443 | 1 | firefox-esr | Sí |
| 20.42.73.27 | TCP/443 | 1 | code | Sí |
| 10.10.36.2 | UDP/67 | 1 | NetworkManager | No |

## Conteos de inventario

- Procesos: 358
- Registros de sockets consultados: 980
- Paquetes Debian instalados: 4297
- Unidades systemd: 379
- Módulos del kernel: 227
- Interfaces: 5
- Rutas: 14
- Servicios en escucha: 14
- Endpoints remotos únicos: 10

## Advertencias e interpretación

- **HOSTNAME_FIELD_MISMATCH** — system_info.hostname='localhost' differs from computer_name='rabbitmq-kali'; CloudMove uses computer_name/asset.hostname='rabbitmq-kali'.
- **NON_SERVER_TEST_ASSET** — The current discovery source identifies this asset as a laptop. Treat it as a collector validation sample, not as a rack server workload.
- **NETWORK_SNAPSHOT_NOT_DEPENDENCY_PROOF** — Remote socket observations are a point-in-time snapshot. They do not by themselves prove an application dependency or capture every short-lived connection.
- This is a snapshot of one host, not network-wide discovery.
- Current processes and socket observations do not constitute historical performance telemetry.
- Observed remote endpoints are not asserted to be confirmed application dependencies.
- Disk byte values are estimates and should be checked against lsblk/df before cloud right-sizing.

## Siguiente paso para CloudMove

1. Importar el JSON normalizado y conservar fuente/fecha de cada observación.
2. En los servidores reales autorizados, ejecutar osquery en cada host o desplegar un gestor de flota.
3. Recolectar métricas históricas de CPU, memoria y disco para dimensionamiento; esta instantánea no las ofrece.
4. Confirmar dependencias con recolección repetida/telemetría y validación por los responsables de la aplicación.
5. Añadir metadatos de motores de base de datos con consultas de catálogo de solo lectura.
