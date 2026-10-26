# ADR-002: Extensión Retrocompatible del Esquema CMIR v2.1 y Trazabilidad de Evidencias

- **Estado:** Aceptado
- **Fecha:** 2026-10-25
- **Contexto:** Representación unificada para los tres casos de uso (Aplicación, Imagen de SO/VM y Datacenter Completo).

## Contexto y Problema

El modelo `CMIR` v2.0 (`backend/app/cmir/models.py`) definía `CMIRNode` y `CMIRRelationship` con niveles jerárquicos `0-8`, pero carecía de:
1. Campos formales y tipados de **evidencia, fuente, fecha de descubrimiento, confianza/estado epistémico (`observed`, `derived`, `inferred`, `unknown`) y mapeo al recurso destino (`target_mapping`)** directamente en los nodos y relaciones.
2. Tipos semánticos completos para representar la jerarquía física y lógica de los tres casos de uso: `datacenter`, `physical_host`, `hypervisor`, `virtual_machine`, `machine_image`, `disk_image`, `operating_system`, `application`, `application_component`, `process`, `system_service`, `port`, `network_connection`, `container`, `workload`, `database`, `database_instance`, `database_schema`, `volume`, `disk`, `filesystem`, `file_share`, `network`, `subnet`, `connectivity_rule`, `identity`, `target_aws_resource`, `target_gcp_resource`.
3. Relaciones semánticas expresivas: `runs_on`, `hosts`, `depends_on`, `communicates_with`, `connects_to`, `reads_from`, `writes_to`, `mounts`, `exposes`, `requires_identity`, `migrates_to`.
4. Mecanismo de migración de versión de esquema (`2.0` → `2.1`) para inventarios y sesiones persistidas en `backend/data/` e `inventory/`.

## Decisión

1. **Extender `CMIRNode` y `CMIRRelationship` en `backend/app/cmir/models.py` sin romper campos existentes** (manteniendo valores por defecto compatibles con v2.0):
   - Añadir `canonical_id`, `epistemic_state` (`observed | derived | inferred | unknown`), `confidence` (`float` 0.0–1.0 o etiqueta), `source_connector`, `discovered_at`, `evidence_items` (`List[CMIREvidence]`) y `target_mapping` (`Dict[str, Any]`).
2. **Prohibir tratar relaciones inferidas como confirmadas**:
   - En `CMIRRelationship`, distinguir `epistemic_state="observed"` / `"confirmed"` frente a `"inferred"` o `"unknown"`.
   - En `resolve_dependencies`, devolver por separado las dependencias confirmadas (`required_direct`, `required_transitive`), las dependencias inferidas (`inferred_dependencies`) y las dependencias compartidas (`shared_dependencies`), impidiendo que una dependencia compartida se modifique o migre sin validación explícita.
3. **Versionado y migración automática (`migrate_cmir_schema`)**:
   - Soportar lectura transparente de documentos CMIR `1.0` y `2.0` actualizándolos a `2.1` con preservación íntegra de nodos y relaciones.
