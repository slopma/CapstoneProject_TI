#!/bin/bash
set -e

# ==============================================================================
# CloudMove Initialization Script (AWS EC2 / Ubuntu 22.04 LTS)
# ==============================================================================

export DEBIAN_FRONTEND=noninteractive

echo "==> 1. Configurando 4GB de memoria Swap para evitar OOM..."
if [ ! -f /swapfile ]; then
    fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> 2. Actualizando paquetes del sistema..."
apt-get update -y
apt-get install -y ca-certificates curl gnupg lsb-release git unzip htop rsync

echo "==> 3. Instalando Docker oficial y Docker Compose..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Permitir a usuario ubuntu usar docker sin sudo
usermod -aG docker ubuntu
systemctl enable docker
systemctl start docker

echo "==> 4. Preparando directorio de la aplicación..."
mkdir -p /opt/cloudmove
chown -R ubuntu:ubuntu /opt/cloudmove

echo "==> Inicialización completada exitosamente."
