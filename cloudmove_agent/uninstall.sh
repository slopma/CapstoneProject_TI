#!/usr/bin/env bash
# ==============================================================================
# CloudMove Agent — Script Oficial de Desinstalación Limpia
# ==============================================================================
set -euo pipefail

SERVICE_NAME="cloudmove-agent"
INSTALL_DIR="/opt/cloudmove-agent"
CONF_DIR="/etc/cloudmove"
LOG_DIR="/var/log/cloudmove"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Debe ejecutar este script con privilegios de superusuario (root o sudo)."
  exit 1
fi

echo "==> 1. Deteniendo y deshabilitando el servicio systemd '$SERVICE_NAME'..."
if systemctl is-active --quiet "$SERVICE_NAME"; then
  systemctl stop "$SERVICE_NAME"
fi
if systemctl is-enabled --quiet "$SERVICE_NAME"; then
  systemctl disable "$SERVICE_NAME"
fi

echo "==> 2. Eliminando el archivo de unidad systemd..."
rm -f "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload

echo "==> 3. Eliminando archivos de instalación y configuraciones locales..."
rm -rf "$INSTALL_DIR"
rm -rf "$CONF_DIR"

read -p "¿Desea eliminar también los registros de auditoría en $LOG_DIR? (s/N): " -r CONFIRM || CONFIRM="n"
if [[ "$CONFIRM" =~ ^[sS]$ ]]; then
  rm -rf "$LOG_DIR"
  echo "    [✓] Registros eliminados."
fi

echo "==> [OK] Desinstalación del Agente CloudMove completada correctamente."
