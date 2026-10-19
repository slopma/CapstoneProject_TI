# Documento de Rediseño Visual de Diagrama y Modularización IaC de CloudMove

## 1. Resumen Ejecutivo y Objetivos Alcanzados

Este documento detalla el rediseño integral de la interfaz de usuario de **CloudMove**, la transformación del canvas de arquitectura a un **Diagrama Horizontal de Izquierda a Derecha (LR)** con auto-dimensionamiento dinámico de contenedores padre y la **modularización de la generación de código de Infraestructura como Código (IaC / Terraform)**.

El rediseño fue guiado por los principios visuales de los sistemas de diseño de nivel empresarial (tales como Refero y Airtable), logrando una interfaz editorial sobria, limpia, espaciosa y altamente legible, eliminando elementos de simulación tipo demo de IA, neones o glassmorphism.

---

## 2. Rediseño del Diagrama de Arquitectura Horizontal (LR)

### 2.1 Orientación Horizontal y Disposición de Niveles (L1-L8)
Se convirtió el layout jerárquico a una disposición estricta de **Izquierda a Derecha (LR)**:
- **Flujo Físico y Lógico**:
  - `Level 1` (Datacenter / Cloud Provider)
  - `Level 2` (VPC / Virtual Network)
  - `Level 3` (Subnets / Availability Zones)
  - `Level 4` (Clusters EKS/AKS)
  - `Level 5` (Namespaces / Resource Groups)
  - `Level 6` (Aplicaciones / Microservicios)
  - `Level 7` (Workloads / Deployments / Pods)
  - `Level 8` (Recursos Atómicos / DBs / S3 / Instancias)
- **Conectores Ortogonales (`smoothstep`)**:
  - Las aristas del grafo se configuran como curvas cuadradas u ortogonales tipo diagrama de arquitectura profesional (`smoothstep`).
  - Los handles de entrada (`Position.Left`) y salida (`Position.Right`) en los nodos garantizan un trazado limpio entre capas sin cruces desordenados de líneas.

### 2.2 Auto-Dimensionamiento Dinámico de Contenedores Padre
- **Cálculo de Bounding Boxes**:
  - En `graphLayout.js`, el algoritmo recorre recursivamente los nodos de nivel superior (padres) y calcula la caja envolvente que encierra a todos sus nodos hijos desplegados (`minX`, `maxX`, `minY`, `maxY`).
  - Se añade un padding uniforme de 28px alrededor de los contenidos internos.
  - Los estilos de los nodos padre se inyectan dinámicamente mediante `computedStyle: { minWidth, minHeight }`, asegurando que el marco de un Datacenter, VPC o Cluster se expanda suavemente cuando se despliegan sus hijos sin solapamientos ni recortes de texto.

### 2.3 Eliminación del Filtro Fijo de Niveles (L1-L8)
- **Navegación Intuitiva Jerárquica**:
  - Se removió el grupo de botones fijos `All (L1-L8)` de la barra superior.
  - La exploración se realiza de forma natural mediante:
    1. **Botones Discretos de Expansión `[+]` y `[-]`** en las tarjetas de nodos padre.
    2. **Breadcrumb / Miga de Pan** en la barra superior que rastrea la jerarquía desde la raíz hasta el nodo enfocado.
    3. **Zoom y Pan Continuo** controlado por React Flow con botones de control integrados.
    4. **Acciones Globales de Despliegue**: Botones "Desplegar Todo" y "Colapsar a Raíz".

---

## 3. Sistema de Diseño y Escala Tipográfica Enterprise

### 3.1 Escala Tipográfica (Basada en Refero / Airtable)
Se implementó una jerarquía tipográfica uniforme y altamente legible basada en la fuente `Inter` y `JetBrains Mono` para identificadores técnicos:
- **Título de Página / Header**: `28px` (`font-weight: 800`)
- **Título de Sección / Modal**: `20px` (`font-weight: 700`)
- **Título de Nodo / Tarjeta**: `16px` (`font-weight: 600`)
- **Cuerpo de Texto / Metadatos**: `15px` (`font-weight: 400`)
- **Etiquetas de Estado / Tipos**: `13px` (`font-weight: 600`)
- **Micro-indicadores / Badges**: `12px` (`font-weight: 700`, monospaced)

### 3.2 Paleta de Colores y Superficies Sobrias
- **Fondo Base del Canvas**: `#F8FAFC` (Slate ligero), libre de patrones oscuros o rejillas fosforescentes.
- **Superficies y Tarjetas**: `#FFFFFF` sólido con bordes sutiles en `#E2E8F0` y sombras difusas minimalistas (`0 1px 3px rgba(15, 23, 42, 0.06)`).
- **Cero Emojis y Cero Glassmorphism**: Se sustituyeron emojis genéricos por badges técnicos y códigos de color institucional por proveedor (AWS, Azure, K8s).

---

## 4. Modularización de la Generación de Infraestructura como Código (IaC)

### 4.1 Estructura Archivo por Archivo (`backend/app/generators/terraform.py`)
En lugar de retornar un único bloque de texto gigante, el generador backend produce una estructura multi-archivo estándar de producción:

```json
{
  "provider.tf": "terraform {\n  required_providers {\n...",
  "variables.tf": "variable \"aws_region\" {\n...",
  "main.tf": "resource \"aws_vpc\" \"main\" {\n...",
  "outputs.tf": "output \"vpc_id\" {\n..."
}
```

### 4.2 Lógica de Formateo `terraform fmt`
- El backend intenta ejecutar la utilidad oficial `terraform fmt` mediante subproceso cuando el CLI de Terraform está disponible en el entorno del sistema.
- En caso de no contar con la herramienta externa instalada, el backend utiliza un formateador de sintaxis basado en normalización de indentación y saltos de línea sin interrumpir la ejecución API.

### 4.3 Visualizador Multi-Pestañas en el Frontend (`IaCViewer.jsx`)
- El componente de previsualización de código (`IaCViewer.jsx`) cuenta con una barra superior de pestañas dinámicas (`main.tf`, `variables.tf`, `outputs.tf`, `provider.tf`, `k8s-manifests.yaml`).
- Cada pestaña incluye resaltado de sintaxis, numeración de líneas y botón dedicado de **Copiar al Portapapeles** e **Imprimir/Descargar**.

---

## 5. Verificación y Resultados de Pruebas

### 5.1 Suite de Pruebas Automatizadas Backend (Pytest)
Se ejecutaron los tests unitarios e integrados del backend resultando en **100% de éxito**:
```bash
PYTHONPATH=backend python3 -m pytest backend/tests
============================== 10 passed in 0.63s ==============================
```
Pruebas verificadas:
- `test_adapters.py`: Traducción de modelos CMIR a AWS, Azure y Kubernetes.
- `test_cmir.py`: Normalización de inventarios JSON.
- `test_dependencies.py`: Motor de resolución de dependencias topológicas.
- `test_graph.py`: Construcción del subgrafo y preservación de jerarquía.
- `test_iac.py`: Generación modular de archivos Terraform y Kubernetes + formateo sintáctico.

### 5.2 Compilación del Frontend (Vite Production Build)
Se ejecutó la compilación de producción del cliente web:
```bash
npm run build
✓ built in 397ms
dist/index.html                   0.45 kB
dist/assets/index-D07Yg42c.css   33.11 kB
dist/assets/index-BpYYJxCo.js   435.79 kB
```
La aplicación compila sin errores ni advertencias de sintaxis.
