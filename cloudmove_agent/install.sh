#!/usr/bin/env bash
# ==============================================================================
# CloudMove Agent — Script de Instalación Oficial para Linux (systemd)
# Compatible con Debian, Ubuntu, RHEL, Rocky Linux, AlmaLinux y derivados.
# ==============================================================================
set -euo pipefail

SERVER_URL="http://localhost:8000"
ENROLLMENT_TOKEN=""
INSTALL_DIR="/opt/cloudmove-agent"
SERVICE_NAME="cloudmove-agent"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token)
      ENROLLMENT_TOKEN="$2"
      shift 2
      ;;
    --server)
      SERVER_URL="$2"
      shift 2
      ;;
    *)
      echo "Opción desconocida: $1"
      echo "Uso: $0 --token <ENROLLMENT_TOKEN> [--server <URL>]"
      exit 1
      ;;
  esac
done

if [[ -z "$ENROLLMENT_TOKEN" ]]; then
  echo "ERROR: Debe proporcionar un token de inscripción válido con --token <TOKEN>"
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Este script debe ejecutarse como root o con sudo para registrar el servicio systemd."
  exit 1
fi

echo "==> 1. Verificando dependencias locales (Python 3.8+ y curl)..."
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 no está instalado."; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl no está instalado."; exit 1; }

echo "==> 2. Preparando directorios en $INSTALL_DIR y /etc/cloudmove..."
mkdir -p "$INSTALL_DIR"
mkdir -p /etc/cloudmove
mkdir -p /var/log/cloudmove

echo "==> 3. Enrolando agente en $SERVER_URL..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH="$SCRIPT_DIR/..:$SCRIPT_DIR" python3 -m cloudmove_agent.installer \
  --server "$SERVER_URL" \
  --token "$ENROLLMENT_TOKEN" \
  --config /etc/cloudmove/agent.conf \
  --no-service

echo "==> 4. Copiando archivos de agente a $INSTALL_DIR..."
cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"

echo "==> 5. Configurando e iniciando el servicio systemd ($SERVICE_NAME)..."
cp "$SCRIPT_DIR/cloudmove-agent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "==> [OK] Agente CloudMove instalado y activo como servicio de sistema."
systemctl status "$SERVICE_NAME" --no-pager || true
