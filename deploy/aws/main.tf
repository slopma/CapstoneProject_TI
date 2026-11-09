# Obtener la VPC por defecto existente en AWS Academy
data "aws_vpc" "default" {
  default = true
}

# Obtener subredes públicas de la VPC por defecto
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# AMI oficial de Ubuntu 22.04 LTS Server x86_64
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Security Group con reglas de acceso para CloudMove
resource "aws_security_group" "cloudmove_sg" {
  name        = "cloudmove-platform-sg"
  description = "Reglas de red para la plataforma CloudMove (SSH, HTTP, HTTPS, API)"
  vpc_id      = data.aws_vpc.default.id

  # SSH
  ingress {
    description = "Acceso SSH administrativo"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTP (Frontend / Web)
  ingress {
    description = "Trafico web HTTP estandar"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS (Trafico seguro SSL)
  ingress {
    description = "Trafico web HTTPS seguro"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Puerto directo Backend FastAPI (opcional para pruebas de API)
  ingress {
    description = "API FastAPI directa"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Salida libre hacia internet
  egress {
    description      = "Salida libre a internet para descargas y paquetes"
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = {
    Name    = "cloudmove-platform-sg"
    Project = "CloudMove-Capstone"
  }
}

# Clave SSH opcional si se proporciona en las variables
resource "aws_key_pair" "cloudmove_key" {
  count      = var.ssh_public_key != "" ? 1 : 0
  key_name   = "cloudmove-deploy-key"
  public_key = var.ssh_public_key
}

# Instancia EC2 adaptada al presupuesto y cuotas de AWS Academy
resource "aws_instance" "cloudmove_server" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = var.instance_type
  subnet_id     = data.aws_subnets.default.ids[0]

  vpc_security_group_ids = [aws_security_group.cloudmove_sg.id]
  key_name               = var.ssh_public_key != "" ? aws_key_pair.cloudmove_key[0].key_name : null

  # Almacenamiento EBS adaptado al límite estricto de AWS Academy (~50 GB max por lab)
  root_block_device {
    volume_size           = var.disk_size_gb
    volume_type           = "gp3"
    delete_on_termination = true

    tags = {
      Name    = "cloudmove-root-disk"
      Project = "CloudMove-Capstone"
    }
  }

  user_data = file("${path.module}/user_data.sh")

  tags = {
    Name    = "cloudmove-server"
    Project = "CloudMove-Capstone"
  }
}

# Asignar una IP Elastica fija (EIP) para no perder el registro DNS de Namecheap
resource "aws_eip" "cloudmove_ip" {
  instance = aws_instance.cloudmove_server.id
  domain   = "vpc"

  tags = {
    Name    = "cloudmove-static-ip"
    Project = "CloudMove-Capstone"
  }
}
