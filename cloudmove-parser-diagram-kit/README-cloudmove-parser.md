# CloudMove osquery parser y diagrama

## Archivos generados

- `cloudmove_osquery_parser.py`: parser reutilizable para el esquema `cloudmove.discovery.v1`.
- `cloudmove-normalized-inventory.json`: inventario normalizado a `cloudmove.normalized.v1`.
- `cloudmove-discovery-diagram.png` y `.svg`: diagrama renderizado del host y sus conexiones observadas.
- `cloudmove-discovery-diagram.dot`: fuente Graphviz editable.
- `cloudmove-discovery-diagram.mmd`: diagrama fuente Mermaid.
- `cloudmove-discovery-report.md`: resumen y advertencias del inventario.

## Ejecutarlo en Kali

Ubica el archivo original `cloudmove-osquery-inventory.json` (el export generado por osquery) y copia el parser al proyecto. Ejemplo:

```bash
PROJECT="$HOME/Documentos/Semestre 2026-2/CapstoneProject_TI"
python3 "$PROJECT/cloudmove_osquery_parser.py" \
  --input "$PROJECT/docs/cloudmove-osquery-inventory.json" \
  --output-dir "$PROJECT/docs/cloudmove-parsed"
```

Requiere Python 3.10+ y solo usa la biblioteca estándar. Si `dot` de Graphviz está instalado, renderiza automáticamente PNG y SVG; sin Graphviz todavía genera JSON normalizado, DOT, Mermaid y Markdown.

## Interpretación de esta muestra

- Host: `rabbitmq-kali`, Kali GNU/Linux Rolling 2026.3.
- Recolector: osquery 5.23.1; consultas reportadas: 16/16 exitosas, 0 errores.
- Recurso detectado: Lenovo IdeaPad Gaming 3 15IAH7, 10 núcleos físicos, 16 lógicos y ~15.35 GiB RAM.
- Interfaz principal observada: `wlan0`, `10.10.37.219/23`, subred inferida `10.10.36.0/23`, puerta de enlace `10.10.36.1`.
- El snapshot tiene procesos, interfaces, rutas, puertos escuchando, paquetes y sockets.

**Advertencias:** el activo observado es un portátil, no un servidor de rack. Las conexiones remotas son sockets vistos en una sola instantánea; no se deben tratar automáticamente como dependencias confirmadas. Los datos de disco son aproximaciones derivadas de columnas de osquery y deben contrastarse con `lsblk`/`df` antes de dimensionar AWS. El inventario contiene información sensible de sistema y red; no lo publiques en repositorios abiertos.
