#!/usr/bin/env bash
# ==============================================================================
# CloudMove — Full Live System Disk Snapshot & Bit-by-Bit Clone Tool
# Host: rabbitmq-kali
# Primary Boot Disk: /dev/nvme0n1 (476.94 GiB)
# Root Partition: /dev/nvme0n1p2 (Used: 233.93 GiB / Total: 460.25 GiB)
# ==============================================================================
# Este script ejecuta la captura completa a nivel de bloques del disco o partición raíz.
# Ofrece 3 modos de ejecución:
#   1. ./create_full_raw_disk_clone.sh local   (Genera clon QCOW2 comprimido o RAW.GZ)
#   2. ./create_full_raw_disk_clone.sh s3      (Transmite clon bit a bit directo a AWS S3)
#   3. ./create_full_raw_disk_clone.sh gcs     (Transmite clon bit a bit directo a Google Cloud)
# ==============================================================================
set -euo pipefail

DESTINATION_DIR="${DESTINATION_DIR:-./disk_snapshots}"
S3_BUCKET="${S3_BUCKET:-cloudmove-live-system-snapshots}"
GCS_BUCKET="${GCS_BUCKET:-cloudmove-live-system-snapshots}"
TARGET_DISK="${TARGET_DISK:-/dev/nvme0n1}"
ROOT_PART="${ROOT_PART:-/dev/nvme0n1p2}"

echo "[1/5] Sincronizando búferes del sistema operativo (os.sync)..."
sync

echo "[2/5] Respaldando tabla de particiones GPT/MBR..."
mkdir -p "$DESTINATION_DIR"
if command -v sfdisk >/dev/null 2>&1; then
    sudo sfdisk -d "$TARGET_DISK" > "$DESTINATION_DIR/partition_table_backup.dump"
    echo "  Tabla de particiones guardada en $DESTINATION_DIR/partition_table_backup.dump"
fi

MODE="${1:-local}"

case "$MODE" in
    local)
        echo "[3/5] Creando clon comprimido QCOW2 del disco raíz en $DESTINATION_DIR/rabbitmq-kali-live-os-full.qcow2..."
        if command -v qemu-img >/dev/null 2>&1; then
            sudo qemu-img convert -p -c -f raw -O qcow2 "$ROOT_PART" "$DESTINATION_DIR/rabbitmq-kali-live-os-full.qcow2"
        else
            sudo dd if="$ROOT_PART" bs=4M status=progress | gzip -c > "$DESTINATION_DIR/rabbitmq-kali-live-os-full.raw.gz"
        fi
        echo "[4/5] Calculando firma criptográfica SHA-256..."
        sha256sum "$DESTINATION_DIR/rabbitmq-kali-live-os-full."* > "$DESTINATION_DIR/checksum.sha256"
        echo "[5/5] Clon de disco del sistema operativo completado con éxito."
        ;;
    s3)
        echo "[3/5] Transmitiendo clon bit a bit directamente hacia AWS S3 (s3://$S3_BUCKET/rabbitmq-kali-live-os.raw.gz)..."
        sudo dd if="$ROOT_PART" bs=4M status=progress | gzip -c | aws s3 cp - "s3://$S3_BUCKET/rabbitmq-kali-live-os.raw.gz"
        echo "[4/5] Transmisión hacia S3 completada sin saturar el almacenamiento local."
        ;;
    gcs)
        echo "[3/5] Transmitiendo clon bit a bit directamente hacia GCP Storage (gs://$GCS_BUCKET/rabbitmq-kali-live-os.raw.gz)..."
        sudo dd if="$ROOT_PART" bs=4M status=progress | gzip -c | gcloud storage cp - "gs://$GCS_BUCKET/rabbitmq-kali-live-os.raw.gz"
        echo "[4/5] Transmisión hacia GCP completada sin saturar el almacenamiento local."
        ;;
    *)
        echo "Modo desconocido: $MODE. Usa 'local', 's3' o 'gcs'."
        exit 1
        ;;
esac
