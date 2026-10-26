# ADR-001: Proveedores Destino Exclusivos AWS y GCP (Retiro Funcional de Azure)

- **Estado:** Aceptado
- **Fecha:** 2026-10-25
- **Contexto:** Evolución de CloudMove v2.1 hacia plataforma unificada de migración On-Premise → Cloud (Aplicaciones, Imágenes de VM y Datacenters).

## Contexto y Problema

En la iteración inicial del proyecto (Sprint 0 y MVP v2.0), CloudMove exploró adaptadores para AWS, Microsoft Azure (`AzureAdapter`) y manifiestos Kubernetes (`KubernetesAdapter`), mientras que el soporte para Google Cloud Platform (`backend/app/translators/gcp.py`) consistía únicamente en un diccionario estático de 16 líneas con tres tipos de recursos (`compute`, `database`, `cache`) sin adaptador `BaseProviderAdapter`, sin generador de Terraform HCL ni integración en los routers o en la interfaz gráfica.

La nueva dirección funcional del producto establece que **los únicos proveedores nube de destino admitidos son Amazon Web Services (AWS) y Google Cloud Platform (GCP)**. Azure queda fuera del alcance funcional de la nueva versión.

Sin embargo, eliminar abruptamente los archivos `backend/app/adapters/azure_adapter.py` o `generate_azure_terraform_files` rompería pruebas unitarias históricas (`backend/tests/test_adapters.py`, `backend/tests/test_iac.py`).

## Clasificación de Referencias Existentes a Azure / AKS

| Ubicación | Tipo | Decisión de Transición |
|---|---|---|
| `backend/app/adapters/azure_adapter.py` | Código legado + pruebas históricas | Conservar clase `AzureAdapter` marcada como `DEPRECATED / LEGACY` para no romper `test_adapters.py` ni `test_iac.py`. No exponer como destino elegible en nuevos flujos. |
| `backend/app/generators/terraform.py` (`generate_azure_terraform*`) | Código legado + pruebas históricas | Conservar funciones para compatibilidad de tests unitarios; incorporar `generate_gcp_terraform_files` y `generate_gcp_terraform`. |
| `backend/app/api/routers/migration.py` | Ruta funcional API | Priorizar `aws` y `gcp` como proveedores oficiales. Rechazar `azure` en los nuevos flujos del orquestador (`/api/v1/migration/plans`, `/api/v1/migration/use-cases/*`). |
| `frontend/src/components/migration/MigrationPreviewModal.jsx`, `MigrationPanel.jsx`, `DetailPanel.jsx` | Interfaz de usuario activa | Retirar los botones y selectores de Microsoft Azure; reemplazar por **AWS (Amazon Web Services)** y **GCP (Google Cloud Platform)**. |
| `docs/PROJECT_AUDIT.md`, `docs/CLOUDMOVE_INTERNAL_ARCHITECTURE.md` | Documentación histórica | Conservar trazabilidad histórica y añadir nota explícita de superación por el alcance v2.1 (AWS/GCP). |

## Decisión

1. Implementar soporte completo de primer nivel para **AWS** (`AWSAdapter`) y **GCP** (`GCPAdapter`) con contratos simétricos en `BaseProviderAdapter`: validación de configuración, verificación de permisos/prerrequisitos, traducción CMIR, generación modular de Terraform (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`), validación sintáctica de artefactos y simulación/ejecución por etapas.
2. Retirar Azure de todos los flujos de usuario en el frontend y del nuevo `MigrationOrchestrator`.
3. Mantener los módulos legados de Azure aislados exclusivamente para retrocompatibilidad de pruebas históricas.
