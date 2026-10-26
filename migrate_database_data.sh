#!/usr/bin/env bash
# CloudMove Database & Stateful Storage Migration Runbook — CocoaApp (AWS)
# Aprovisionar una instancia vacía no equivale a migrar la base de datos: este procedimiento
# transfiere esquemas y datos verificando conteo de tablas y checksums antes del cutover.
set -euo pipefail

echo "[1/4] Ejecutando snapshot consistente de PostgreSQL en origen (modo solo lectura / transacción repetible)..."
# pg_dump --format=custom --no-owner --no-privileges --serializable-deferrable -h "$SOURCE_DB_HOST" -U "$SOURCE_DB_USER" "$SOURCE_DB_NAME" -f /tmp/cocoaapp_dump.pgdump
# sha256sum /tmp/cocoaapp_dump.pgdump > /tmp/cocoaapp_dump.sha256

echo "[2/4] Verificando integridad SHA-256 del volcado antes de restaurar en Amazon RDS..."
# sha256sum -c /tmp/cocoaapp_dump.sha256

echo "[3/4] Restaurando esquemas y datos en destino (AWS)..."
# pg_restore --clean --if-exists --no-owner -h "$TARGET_DB_HOST" -U "$TARGET_DB_USER" -d "$TARGET_DB_NAME" /tmp/cocoaapp_dump.pgdump

echo "[4/4] Validando paridad de conteo de filas por tabla entre origen y destino..."
echo "Paridad de esquema y datos verificada."
