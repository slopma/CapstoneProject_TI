# ADR-004: Fidelidad y Límites Técnicos en la Migración de Imágenes de Sistema Operativo (Caso de Uso 2)

- **Estado:** Aceptado
- **Fecha:** 2026-10-25
- **Contexto:** Migración de imágenes de máquina (VMDK, VHD/VHDX, QCOW2, RAW, OVA/OVF) hacia AWS EC2 (VM Import/Export / MGN) y GCP Compute Engine.

## Contexto y Problema

Al migrar una máquina virtual o imagen de sistema operativo a la nube (Caso de Uso 2), existe el riesgo de confundir una reconstrucción por paquetes (Caso de Uso 1) con una migración de imagen, o de prometer una transferencia idéntica del estado volátil en memoria RAM y sockets TCP activos entre hipervisores heterogéneos y nubes públicas.

## Decisión

1. **Separación de dimensiones de fidelidad en el evaluador de imágenes (`ImageMigrationService`)**:
   - `disk_content_fidelity`: preservación bloque a bloque / sistema de archivos con verificación SHA-256 en el manifiesto.
   - `persistent_config_fidelity`: preservación de `/etc`, usuarios, unidades `systemd`, `fstab` (requiriendo usar UUIDs en lugar de nombres de dispositivo como `/dev/sda`).
   - `package_and_service_fidelity`: preservación del catálogo de paquetes instalados y demonios habilitados para iniciar en el arranque.
   - `virtual_hardware_and_boot_compatibility`: evaluación explícita de BIOS vs UEFI, arquitectura (`x86_64` vs `arm64` vs `sparc64`), controladores paravirtuales requeridos (AWS ENA + NVMe en `initramfs`; GCP VirtIO-Net + VirtIO-SCSI) y formato de imagen (AWS VM Import admite `OVA`, `VMDK`, `VHD`, `VHDX`, `RAW`; `QCOW2` requiere conversión previa segura con `qemu-img convert -O raw/vmdk`; GCP admite `VMDK`, `VHD`, `VHDX`, `QCOW2`, `RAW`, `OVA`).
   - `volatile_memory_and_active_connections`: documentar y señalar explícitamente como **NO TRANSFERIBLE** en migración fría/tibia de imágenes hacia AWS/GCP; si el usuario solicita continuidad de estado en memoria (`require_live_memory_state=True`), el sistema reporta la limitación técnica y marca la restricción sin ocultarla.
2. **Registro de modificaciones de arranque/controladores**:
   - Cuando una imagen requiere inyección de drivers (`ena`/`nvme` o `virtio`) o ajuste de bootloader/serial console (`ttyS0`), el plan registra la modificación exacta en `boot_adjustments` y conserva el hash SHA-256 original sin alterar jamás la imagen de origen.
