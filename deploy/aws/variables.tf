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
  description = "Dominio o subdominio registrado en Namecheap que apuntará a esta instancia"
  type        = string
  default     = "digitalcafeluna.store"
}
