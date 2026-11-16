variable "aws_region" {
  description = "Región de AWS. En AWS Academy Learner Lab la región habilitada por defecto es us-east-1."
  type        = string
  default     = "us-east-1"
}

variable "aws_access_key" {
  description = "AWS Access Key ID (se obtiene de AWS Academy > AWS Details)"
  type        = string
  default     = null
  sensitive   = true
}

variable "aws_secret_key" {
  description = "AWS Secret Access Key (se obtiene de AWS Academy > AWS Details)"
  type        = string
  default     = null
  sensitive   = true
}

variable "aws_session_token" {
  description = "AWS Session Token (obligatorio en cuentas temporales como AWS Academy Learner Lab)"
  type        = string
  default     = null
  sensitive   = true
}

variable "instance_type" {
  description = "Tipo de instancia EC2. t3.small (2 vCPU, 2GB RAM) está totalmente soportada en AWS Academy y consume muy pocos créditos."
  type        = string
  default     = "t3.small"
}

variable "disk_size_gb" {
  description = "Tamaño en GB del disco EBS raíz gp3. El Learner Lab de AWS Academy permite un máximo de ~50 GB en total por cuenta. 35 GB es el tamaño ideal para soportar el SO, Docker, Node/Python y datos pesados sin sobrepasar la cuota."
  type        = number
  default     = 35
}

variable "ssh_public_key" {
  description = "Contenido de tu clave pública SSH local (ej: el contenido de ~/.ssh/id_rsa.pub) para entrar por terminal."
  type        = string
  default     = ""
}

variable "domain_name" {
  description = "Dominio o subdominio opcional (ej. cloudmove.midominio.com) para HTTPS automático con Caddy. Déjalo vacío para servir por HTTP sobre la IP elástica."
  type        = string
  default     = ""
}

variable "allowed_ssh_cidrs" {
  description = "Rangos CIDR autorizados para SSH (puerto 22). Se recomienda restringir a tu IP pública (ej. [\"1.2.3.4/32\"]) en lugar de 0.0.0.0/0."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "expose_direct_api_port" {
  description = "Exponer puerto directo 8000 en el Security Group además del proxy inverso Nginx (:80/:443). Desactivado por defecto por seguridad."
  type        = bool
  default     = false
}
