output "instance_id" {
  description = "Identificador de la instancia EC2"
  value       = aws_instance.cloudmove_server.id
}

output "elastic_ip" {
  description = "IP publica estatica asignada (Esta es la IP que debes configurar en Namecheap)"
  value       = aws_eip.cloudmove_ip.public_ip
}

output "ssh_command" {
  description = "Comando para conectarte por SSH al servidor"
  value       = "ssh ubuntu@${aws_eip.cloudmove_ip.public_ip}"
}

output "web_url_ip" {
  description = "URL provisional de acceso directo por IP"
  value       = "http://${aws_eip.cloudmove_ip.public_ip}"
}

output "web_url_domain" {
  description = "URL una vez propagado tu dominio de Namecheap"
  value       = "http://${var.domain_name}"
}

output "namecheap_dns_instructions" {
  description = "Pasos para enlazar el dominio en Namecheap"
  value       = <<EOT

================================================================================
PASOS PARA VINCULAR TU DOMINIO NAMECHEAP CON ESTE SERVIDOR:
================================================================================
1. Inicia sesión en https://www.namecheap.com/ y ve a 'Domain List'.
2. Ubica tu dominio '${var.domain_name}' y haz clic en 'Manage'.
3. Ve a la pestaña 'Advanced DNS'.
4. En la tabla 'Host Records', haz clic en 'Add New Record':
   - Type:  A Record
   - Host:  @
   - Value: ${aws_eip.cloudmove_ip.public_ip}
   - TTL:   1 min (o Automatic)
5. (Opcional para subdominio app o cloudmove):
   - Type:  A Record
   - Host:  app
   - Value: ${aws_eip.cloudmove_ip.public_ip}
   - TTL:   1 min
================================================================================
EOT
}
