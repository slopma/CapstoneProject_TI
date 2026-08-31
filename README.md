# CloudMove

Plataforma de abstracción semántica y migración selectiva de infraestructura multicloud. Descubre infraestructura on-premise y cloud, la normaliza en un modelo intermedio neutral (**CMIR**), permite seleccionar subgrafos de arquitectura y genera automáticamente infraestructura como código (**Terraform**) y configuración de estado (**Puppet**).

> Capstone Project in IT · Universidad EAFIT · 2026-2

## Estado del proyecto

**Sprint 0 · Propuesta** — problema, referentes, alternativas y arquitectura conceptual definidos. Aún sin código de producto.

## El problema

Migrar infraestructura entre proveedores hoy exige traducción rígida 1-a-1 y mover cargas de trabajo completas en bloque. No existe un modelo intermedio neutral que permita seleccionar y migrar solo una parte de la arquitectura resolviendo automáticamente sus dependencias.

## Qué hace CloudMove

1. **Discovery Engine** — descubre infraestructura on-premise, AWS y Azure vía APIs y agentes agentless.
2. **CMIR (CloudMove Intermediate Representation)** — normaliza los recursos descubiertos en un modelo semántico neutral.
3. **Architecture Graph** — visualiza la arquitectura como grafo y permite seleccionar subgrafos con resolución automática de dependencias.
4. **IaC Generator** — exporta el subgrafo seleccionado como Terraform + manifiestos Kubernetes + recetas Puppet.

Caso de uso ancla del MVP: conversión **EKS → AKS** (EBS CSI → Azure Disk PVC, IAM/IRSA → Entra ID Workload Identity, ALB Ingress → AGIC).

## Equipo

| Integrante | Rol |
|---|---|
| Sara López Marín | Problema y diseño conceptual (CMIR, grafo, marco de referencia) |
| Luis Alejandro Castrillón Pulgarín | Viabilidad técnica y validación (requisitos, MVP, IaC) |

## Estructura del repositorio

```
docs/
  sprint0/          # Documento de propuesta y evidencias (tablero, capturas)
  adr/              # Architecture Decision Records
src/
  discovery/        # Discovery Engine
  cmir/             # Modelo y motor de normalización semántica
  graph/            # Grafo interactivo y selección de subgrafos
  generator/        # Generador de Terraform y recetas Puppet
```

## Stack

Terraform · Puppet · Kubernetes (EKS/AKS) · APIs de AWS y Azure


## Licencia

🔹 *Definir (ej. MIT) según lineamientos del curso.*
