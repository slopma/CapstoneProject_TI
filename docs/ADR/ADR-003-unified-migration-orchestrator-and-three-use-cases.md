# ADR-003: Orquestador Unificado de Migraciones y Máquina de Estados Explícita

- **Estado:** Aceptado
- **Fecha:** 2026-10-25
- **Contexto:** Necesidad de un motor común de planificación, validación, dry-run, aprobación, ejecución por etapas y rollback para los 3 casos de uso.

## Contexto y Problema

Antes de esta evolución, el endpoint `POST /api/v1/migration/generate` únicamente traducía un subgrafo CMIR y escribía archivos `.tf` en disco de forma síncrona, sin:
- Estado persistente de una migración.
- Distinción entre generación de artefactos IaC, transferencia de datos/discos y ciclo de vida de la migración.
- Máquina de estados explícita con compuerta de aprobación (`APPROVED`) antes de crear recursos, transferir datos o ejecutar un cutover.
- Soporte integrado para los tres casos de uso (1: Aplicación, 2: Imagen de SO/VM, 3: Campaña de Datacenter).

## Decisión

1. Crear el módulo `backend/app/migration/` (o ampliar el dominio de migración conectado a `/api/v1/migration`) con un **`MigrationOrchestrator`** persistente en disco (`backend/data/migrations_store.json`).
2. Implementar la máquina de estados explícita:
   `DRAFT → DISCOVERING → ASSESSED → PLAN_READY → APPROVED → PREPARING → TESTING → READY_FOR_CUTOVER → COMPLETED`
   más los estados terminales/excepcionales: `FAILED`, `CANCELLED`, `ROLLED_BACK`.
3. Separar estrictamente:
   - **Modo Simulación (`dry_run=True`, por defecto):** evalúa prerrequisitos, genera artefactos (Terraform AWS/GCP, manifiestos de imagen, scripts de importación `aws ec2 import-image` / `gcloud compute images import`, planes de transferencia de datos), simula las etapas e identifica exactamente qué acciones requerirían credenciales cloud reales, marcando claramente `execution_mode="simulated_dry_run"` y **prohibiendo transicionar a `COMPLETED` como si fuera una migración cloud real si solo se ejecutó en simulación o solo se generó Terraform**.
   - **Compuerta de Aprobación Obligatoria (`APPROVED`):** ninguna etapa destructiva o de aprovisionamiento (`PREPARING`, `TESTING`, `READY_FOR_CUTOVER`, `COMPLETED`) puede ejecutarse sin aprobación explícita registrada en auditoría (`approved_by`, `approved_at`).
4. Soportar reintentos por etapa, inyección controlada de fallos parciales, cancelación segura y procedimiento de rollback verificable (conservando intactos los activos de origen).
