terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "availability_zones" {
  description = "Availability zones for the selected AWS region"
  type        = list(string)
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "public_subnet_cidr" {
  description = "CIDR block for the public subnet"
  type        = string
}

variable "private_subnet_a_cidr" {
  description = "CIDR block for the first private subnet"
  type        = string
}

variable "private_subnet_b_cidr" {
  description = "CIDR block for the second private subnet"
  type        = string
}

variable "public_ingress_cidr" {
  description = "Allowed CIDR for public HTTP ingress"
  type        = string
}

variable "egress_cidr" {
  description = "Allowed CIDR for outbound traffic"
  type        = string
}

variable "ami_id" {
  description = "AMI ID for the backend EC2 instance"
  type        = string
}

variable "db_username" {
  description = "PostgreSQL username"
  type        = string
}

variable "db_password" {
  description = "PostgreSQL password"
  type        = string
  sensitive   = true
}

# ------------------------------------------------------------
# Network
# ------------------------------------------------------------

resource "aws_vpc" "cloudmove" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "cloudmove-vpc"
  }
}

resource "aws_internet_gateway" "cloudmove" {
  vpc_id = aws_vpc.cloudmove.id

  tags = {
    Name = "cloudmove-igw"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.cloudmove.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = var.availability_zones[0]
  map_public_ip_on_launch = true

  tags = {
    Name = "cloudmove-public-subnet"
  }
}

resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.cloudmove.id
  cidr_block        = var.private_subnet_a_cidr
  availability_zone = var.availability_zones[0]

  tags = {
    Name = "cloudmove-private-a"
  }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.cloudmove.id
  cidr_block        = var.private_subnet_b_cidr
  availability_zone = var.availability_zones[1]

  tags = {
    Name = "cloudmove-private-b"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.cloudmove.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.cloudmove.id
  }

  tags = {
    Name = "cloudmove-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ------------------------------------------------------------
# Security
# ------------------------------------------------------------

resource "aws_security_group" "backend" {
  name        = "cloudmove-backend-sg"
  description = "Security group for CloudMove backend"
  vpc_id      = aws_vpc.cloudmove.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.public_ingress_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.egress_cidr]
  }

  tags = {
    Name = "cloudmove-backend-sg"
  }
}

resource "aws_security_group" "data" {
  name        = "cloudmove-data-sg"
  description = "Security group for PostgreSQL and Redis"
  vpc_id      = aws_vpc.cloudmove.id

  ingress {
    description     = "PostgreSQL from backend"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.backend.id]
  }

  ingress {
    description     = "Redis from backend"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.backend.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.egress_cidr]
  }

  tags = {
    Name = "cloudmove-data-sg"
  }
}

# ------------------------------------------------------------
# Database subnet groups
# ------------------------------------------------------------

resource "aws_db_subnet_group" "postgres" {
  name = "cloudmove-postgres-subnet-group"

  subnet_ids = [
    aws_subnet.private_a.id,
    aws_subnet.private_b.id
  ]

  tags = {
    Name = "cloudmove-postgres-subnet-group"
  }
}

resource "aws_elasticache_subnet_group" "redis" {
  name = "cloudmove-redis-subnet-group"

  subnet_ids = [
    aws_subnet.private_a.id,
    aws_subnet.private_b.id
  ]
}

# ------------------------------------------------------------
# Backend
# ------------------------------------------------------------

resource "aws_instance" "backend" {
  ami                         = var.ami_id
  instance_type               = "t3.micro"
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.backend.id]
  associate_public_ip_address = true

  tags = {
    Name = "cloudmove-backend"
  }
}

# ------------------------------------------------------------
# PostgreSQL
# ------------------------------------------------------------

resource "aws_db_instance" "postgres" {
  identifier             = "cloudmove-postgres"
  engine                 = "postgres"
  instance_class         = "db.t3.micro"
  allocated_storage      = 20
  username               = var.db_username
  password               = var.db_password
  publicly_accessible    = false
  skip_final_snapshot    = true
  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  vpc_security_group_ids = [aws_security_group.data.id]

  tags = {
    Name = "cloudmove-postgres"
  }
}

# ------------------------------------------------------------
# Redis
# ------------------------------------------------------------

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "cloudmove-redis"
  engine               = "redis"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.redis.name
  security_group_ids   = [aws_security_group.data.id]

  tags = {
    Name = "cloudmove-redis"
  }
}
