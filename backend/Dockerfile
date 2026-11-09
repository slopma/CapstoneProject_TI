FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema requeridas (incluyendo util-linux y qemu-utils para Caso 2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    unzip \
    qemu-utils \
    util-linux \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Instalar Terraform CLI oficial para despliegues automatizados
RUN curl -fsSL https://releases.hashicorp.com/terraform/1.7.5/terraform_1.7.5_linux_amd64.zip -o terraform.zip \
    && unzip terraform.zip \
    && mv terraform /usr/local/bin/ \
    && rm terraform.zip

# Instalar AWS CLI v2 oficial para verificación STS y gestión cloud
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
    && unzip -q awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
