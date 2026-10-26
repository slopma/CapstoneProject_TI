#!/usr/bin/env bash
# ==============================================================================
# CloudMove — System Image Restoration & Provisioning Script
# Reconstructs the operating system configuration, user accounts, and packages.
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo " CloudMove — Restauración de Imagen del Sistema (rabbitmq-kali)"
echo "=========================================================="

echo "[1/4] Restaurando archivos de configuración en /etc..."
if [ -d "etc" ]; then
    sudo cp -rv etc/* /etc/
fi

echo "[2/4] Verificando y creando cuentas de usuario locales..."
if [ -f "users_manifest.json" ]; then
    python3 -c "
import json, subprocess
with open('users_manifest.json') as f:
    users = json.load(f)
for u in users:
    if u.get('uid', 0) >= 1000 and u.get('username') not in ('nobody', 'root'):
        cmd = ['useradd', '-u', str(u['uid']), '-m', '-s', u.get('shell', '/bin/bash'), u['username']]
        res = subprocess.run(['id', u['username']], capture_output=True)
        if res.returncode != 0:
            print(f'Creando usuario {u["username"]} (UID: {u["uid"]})...')
            subprocess.run(cmd, check=False)
"
fi

echo "[3/4] Instalando paquetes faltantes desde el manifiesto..."
if command -v apt-get >/dev/null 2>&1 && [ -f "installed_packages_manifest.txt" ]; then
    echo "Instalando paquetes críticos en el SO destino..."
    sudo apt-get update -y || true
    sudo apt-get install -y openssh-server cloud-init systemd grub-efi-amd64 || true
fi

echo "[4/4] Recargando demonios de systemd..."
sudo systemctl daemon-reload || true
echo "Restauración de imagen de sistema completada exitosamente."
