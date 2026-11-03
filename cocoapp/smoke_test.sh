#!/usr/bin/env bash
set -euo pipefail
echo "[CloudMove Smoke & Health Test] Verificando aplicación 'CocoaApp' en AWS..."
for port in 80 3000 8000; do
  echo " -> Comprobando puerto TCP $port..."
  nc -z -w 3 127.0.0.1 "$port" || { echo "ERROR: Puerto $port no responde"; exit 1; }
done
echo " -> Comprobando endpoint de salud HTTP http://127.0.0.1:80/health..."
curl -fsS "http://127.0.0.1:80/health" >/dev/null
echo "[OK] Servicio arrancado, puertos activos y endpoint de salud verificado."
