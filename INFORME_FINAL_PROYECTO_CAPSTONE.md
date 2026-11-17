# INFORME FINAL DE PROYECTO CAPSTONE

**Título del Proyecto:** CloudMove: Plataforma de Ingeniería para el Descubrimiento de Infraestructura, Modelado Semántico Neutral (CMIR v2.1) y Despliegue Automatizado hacia Amazon Web Services (AWS)

**Integrantes:**
* Luis Alejandro Castrillón Pulgarín (`lacastrilp@eafit.edu.co`)
* Sara López Marín (`slopezm13@eafit.edu.co`)

**Trayectoria / Carrera:** Ingeniería de Sistemas  
**Curso:** Proyecto Integrador / Capstone Project de Tecnologías de Información  
**Institución:** Universidad EAFIT  
**Fecha:** Noviembre de 2026  

---

## Resumen Ejecutivo

### Resumen Gráfico (Graphical Abstract)

```
+-------------------------------------------------------------------------------------------------------+
|                                        FUENTES DE ENTRADA                                             |
|  [Código Fuente / GitHub]       [Imágenes Disco / Captura SO]         [Servidores Físicos / VMs]       |
|   (Repositorios, Dockerfile,        (VMDK, QCOW2, RAW, VHD,               (Agentes livianos osquery,  |
|    Dumps SQL, Manifiestos)          Captura en Caliente /etc)               Telemetría en Vivo)       |
+-------------------------------------------------------------------------------------------------------+
                                                   │
                                                   ▼
+-------------------------------------------------------------------------------------------------------+
|                                 MOTOR DE DESCUBRIMIENTO Y ANÁLISIS                                     |
|  • Inspección estática (AST, Regex, Manifiestos)      • Extracción de esquemas y volcados SQL/PostGIS |
|  • Sanitización y redacción de credenciales           • Normalización de métricas de hardware         |
+-------------------------------------------------------------------------------------------------------+
                                                   │
                                                   ▼
+-------------------------------------------------------------------------------------------------------+
|                     REPRESENTACIÓN INTERMEDIA NEUTRAL Y RESOLUCIÓN DE GRAFO                            |
|                 CMIR v2.1 (Cloud Migration Intermediate Representation)                               |
|  • Jerarquía multinivel (Niveles 0..8)                • Grafo Dirigido (NetworkX DiGraph)             |
|  • Clasificación de certeza (Observed / Inferred)     • Cierre transitivo de dependencias (BFS)       |
+-------------------------------------------------------------------------------------------------------+
                                                   │
                                                   ▼
+-------------------------------------------------------------------------------------------------------+
|                        SÍNTESIS DETERMINISTA Y VALIDACIÓN EN 4 COMPUERTAS                             |
|  1. Balanceo sintáctico     2. Anti-fuga credenciales     3. Coherencia referencias     4. Format HCL |
+-------------------------------------------------------------------------------------------------------+
                                                   │
                                                   ▼
+-------------------------------------------------------------------------------------------------------+
|                               DESPLIEGUE CONTROLADO EN AMAZON WEB SERVICES                            |
|  • Arquitectura modular (VPC, Subnets, SG, EC2/ALB, RDS)   • Aislamiento por pestaña (sessionStorage)  |
|  • Rehidratación autónoma con Cloud-Init (user_data.sh)   • Streaming en vivo de Terraform y Logs     |
+-------------------------------------------------------------------------------------------------------+
```

### Ficha de Identificación
* **Título del Proyecto:** Plataforma de descubrimiento, modelado neutral y migración determinista de infraestructura hacia AWS (CloudMove).
* **Cliente / Entorno de Aplicación:** Universidad EAFIT / Organizaciones en procesos de modernización hacia la nube pública.
* **Equipo de Trabajo:** Luis Alejandro Castrillón Pulgarín, Sara López Marín.
* **Supervisores:** Profesor Asesor del Proyecto Capstone (Universidad EAFIT).

### Descripción del Proyecto
**Solución desarrollada:** Desarrollo de una plataforma web integral que analiza aplicaciones y servidores existentes, traduce su arquitectura a un modelo semántico intermedio neutral y genera infraestructura como código (Terraform HCL) lista para desplegar de forma segura y automatizada en AWS.

**Contexto del problema y objetivo:** Las migraciones hacia la nube suelen enfrentar altos riesgos de falla debido a dependencias no documentadas, herramientas comerciales que fuerzan reescrituras innecesarias hacia arquitecturas serverless incompatibles y procesos manuales lentos propensos a errores humanos. El objetivo general de este proyecto fue diseñar, implementar y validar experimentalmente una plataforma de ingeniería de software capaz de descubrir dependencias de forma no invasiva, modelarlas formalmente mediante teoría de grafos y generar el código de aprovisionamiento en AWS sin exigir la reescritura de las aplicaciones originales. La metodología aplicada combinó el patrón arquitectónico de siete capas desacopladas, desarrollo guiado por pruebas (TDD) y validación continua con casos reales de migración.

**Novedad y ventaja técnica:** La solución introduce el estándar neutral CMIR v2.1, el cual separa formalmente lo que se observa de forma fidedigna de lo que se infiere por heurísticas de configuración, permitiendo predecir la viabilidad del despliegue antes de tocar la nube.

**Diseño y resultados:** La arquitectura comprende un backend en FastAPI, un frontend interactivo en React 19 con renderizado de grafos, y un motor determinista de síntesis de Terraform validado en cuatro compuertas de seguridad. Como resultado, se verificaron 70 pruebas automatizadas con el 100% de éxito, garantizando despliegues funcionales en tres escenarios reales: aplicaciones web con bases de datos relacionales y extensiones geoespaciales (PostGIS), servidores basados en imágenes de disco o capturas de sistema operativo con rehidratación autónoma, y campañas de múltiples servidores monitoreados mediante agentes de bajo impacto basados en `osquery`.

---

## Tabla de Contenido
* [Glosario de Términos Técnicos](#glosario-de-términos-técnicos)
1. [Título del Proyecto](#1-título-del-proyecto)
2. [Introducción](#2-introducción)
3. [Objetivos](#3-objetivos)
4. [Marco Conceptual](#4-marco-conceptual)
5. [Premisas del Diseño](#5-premisas-del-diseño)
6. [Factores de Diseño y Consideraciones Éticas](#6-factores-de-diseño-y-consideraciones-éticas)
7. [Alternativas y Criterios de Selección](#7-alternativas-y-criterios-de-selección)
8. [Resultados y Análisis](#8-resultados-y-análisis)
9. [Conclusiones y Recomendaciones](#9-conclusiones-y-recomendaciones)
10. [Declaración de Conceptos Nuevos y Tecnologías de Vanguardia](#10-declaración-de-conceptos-nuevos-y-tecnologías-de-vanguardia)
11. [Declaración de Uso de Herramientas de Inteligencia Artificial](#11-declaración-de-uso-de-herramientas-de-inteligencia-artificial)
12. [Referencias Bibliográficas](#12-referencias-bibliográficas)
13. [Anexos](#13-anexos)

---

## Glosario de Términos Técnicos

Para facilitar la comprensión del informe y apoyar la exposición del proyecto, a continuación se definen los conceptos y siglas clave utilizados a lo largo del documento:

* **ALB (Application Load Balancer)**: Servicio gestionado de Amazon Web Services que distribuye automáticamente el tráfico de red HTTP/HTTPS entrante entre múltiples instancias o contenedores en diferentes zonas de disponibilidad.
* **ASG (Auto Scaling Group)**: Conjunto de instancias EC2 gestionadas como una unidad lógica que escala dinámicamente según la demanda y reemplaza de forma automática instancias que fallan en sus chequeos de salud.
* **AST (Abstract Syntax Tree / Árbol de Sintaxis Abstracta)**: Representación jerárquica en memoria de la estructura gramatical de un archivo de código fuente, utilizada por el motor de CloudMove para analizar rutas, puertos y llamadas de red sin necesidad de ejecutar código no confiable.
* **Cierre Transitivo (Transitive Closure)**: Conjunto total de nodos alcanzables a través de una cadena de dependencias directas e indirectas en un grafo dirigido. En CloudMove se calcula mediante Búsqueda en Anchura (BFS) para garantizar que un componente no sea migrado sin sus bases de datos o servicios requeridos.
* **Cloud-Init**: Paquete estándar de la industria para sistemas operativos tipo Unix/Linux que ejecuta scripts de configuración, creación de usuarios, montaje de discos y arranque de servicios durante el primer encendido de una máquina virtual.
* **CMIR v2.1 (Cloud Migration Intermediate Representation)**: Esquema semántico neutral y fuertemente tipado en Pydantic desarrollado para CloudMove. Modela componentes de infraestructura (redes, cómputo, almacenamiento, procesos) en 9 niveles jerárquicos (0 a 8), desacoplando las fuentes de análisis del proveedor de nube final.
* **EBS (Elastic Block Store)**: Volúmenes de almacenamiento en bloque persistente de alto rendimiento para instancias Amazon EC2 (ej. tipo `gp3`), utilizados para albergar el sistema operativo y las bases de datos de las cargas migradas.
* **Estado Epistémico (Epistemic State)**: Nivel formal de certidumbre asignado a un recurso dentro del grafo CMIR:
  - `observed`: Verificado fehacientemente en código fuente, archivos Compose o sockets activos (confianza 1.0).
  - `derived`: Calculado matemáticamente a partir de otros nodos validados (ej. roles IAM requeridos).
  - `inferred`: Deducido a partir de bibliotecas o heurísticas (ej. deducir PostgreSQL porque existe `psycopg2` en las dependencias).
  - `unknown`: Detectado en variables de entorno pero apuntando a sistemas externos fuera del alcance de la migración.
* **IMDSv2 (Instance Metadata Service Version 2)**: Servicio de metadatos de instancias EC2 de AWS que requiere el uso de tokens orientados a sesión, diseñado específicamente para mitigar ataques de inyección y SSRF.
* **Infraestructura como Código (IaC)**: Enfoque de ingeniería donde la infraestructura de red, servidores y almacenamiento se define, versiona y gestiona mediante archivos de configuración declarativos legibles por máquina en lugar de configuraciones manuales en consolas web.
* **Marco de las 6R de Migración**: Taxonomía estándar de la industria (popularizada por AWS y Gartner) para clasificar estrategias de migración: *Rehost* (traslado directo / Lift-and-Shift), *Replatform* (modernización mínima dirigida), *Refactor* (reescritura completa), *Repurchase* (adquisición de SaaS), *Retain* (mantener en origen) y *Retire* (dar de baja).
* **`osquery`**: Framework de código abierto que instrumenta sistemas operativos (Linux, Windows, macOS), exponiendo métricas de hardware, procesos, tablas de ruteo, usuarios y puertos abiertos a través de consultas SQL estándar.
* **PostGIS**: Extensión geoespacial de código abierto para el sistema de base de datos relacional PostgreSQL que añade soporte para almacenar y consultar tipos de datos espaciales y coordenadas geográficas.
* **Recurso Compartido (`is_shared`)**: Componente de infraestructura (como una base de datos central o cola RabbitMQ) que atiende a dos o más aplicaciones distintas simultáneamente. CloudMove lo marca para advertir al operador y bloquear migraciones que puedan romper otros servicios activos.
* **Rehidratación Autónoma**: Mecanismo desarrollado en CloudMove para el Caso de Uso 2 que toma los archivos reales de configuración y servicios de un sistema operativo capturado en caliente y los restaura dentro de una instancia limpia de Ubuntu en AWS mediante `user_data.sh`, sin requerir permisos especiales de hipervisor.
* **Right-Sizing (Dimensionamiento Adecuado)**: Proceso de análisis de métricas observadas de CPU y memoria RAM para seleccionar el tipo de instancia en la nube que satisfaga la carga real de trabajo al menor costo posible, evitando el sobreaprovisionamiento.
* **SSRF (Server-Side Request Forgery)**: Vulnerabilidad de seguridad donde un atacante manipula una aplicación para que el servidor realice peticiones no autorizadas hacia redes internas o hacia la IP de metadatos de la nube (`169.254.169.254`).
* **Tar-Slip / Zip-Slip**: Vulnerabilidad de seguridad de cruce de directorios (*Directory Traversal*) que explota nombres de archivos maliciosos dentro de un comprimido (ej. `../../../../etc/shadow`) para sobrescribir archivos del sistema al descomprimirse. CloudMove incorpora validadores de rutas relativas canónicas para neutralizar este riesgo.
* **Terraform HCL (HashiCorp Configuration Language)**: Lenguaje declarativo estructurado de HashiCorp utilizado por CloudMove para sintetizar los archivos reproducibles de infraestructura (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`).
* **`user_data.sh`**: Script de arranque ejecutado por Cloud-Init con privilegios de superusuario (`root`) durante la creación de una instancia EC2, encargado de configurar espacio swap, instalar Docker y arrancar los contenedores de la aplicación.
* **VPC (Virtual Private Cloud)**: Red virtual aislada lógicamente dentro de la nube de AWS que define el rango de direcciones IP (CIDR), subredes públicas y privadas, tablas de ruteo y pasarelas a Internet (*Internet Gateway*).
* **WAL (Write-Ahead Logging)**: Modo de operación de bases de datos transaccionales (como SQLite) donde los cambios se escriben primero en una bitácora secuencial antes de afectar la base de datos principal, permitiendo lecturas concurrentes simultáneas sin bloqueos.

---

## 1. Título del Proyecto

**CloudMove: Plataforma de Ingeniería para el Descubrimiento de Infraestructura, Modelado Semántico Neutral (CMIR v2.1) y Despliegue Automatizado de Cargas de Trabajo hacia Amazon Web Services (AWS)**

*El título define explícitamente el objeto de estudio (descubrimiento de infraestructura y modelado semántico de dependencias), el artefacto desarrollado (plataforma de software y modelo neutral CMIR v2.1) y el entorno de destino (Amazon Web Services).*

---

## 2. Introducción

### 2.1 Contexto y Definición del Problema de Ingeniería
La adopción de la computación en la nube representa uno de los procesos de transformación tecnológica más críticos para las organizaciones modernas. Sin embargo, los proyectos de migración presentan tasas de retraso y sobrecosto superiores al 50%, originadas principalmente por tres deficiencias en las herramientas tradicionales:

1. **Dependencias ocultas y acoplamiento no visible**: Muchas aplicaciones monolíticas o distribuidas poseen conexiones de red hacia bases de datos compartidas, colas de mensajería o sistemas de archivos locales que no están documentados formalmente. Las herramientas de migración que operan a ciegas trasladan componentes individuales sin su entorno operativo, generando fallos en tiempo de ejecución.
2. **Reescritura forzada y pérdida de compatibilidad**: Diversas plataformas de automatización intentan forzar la modernización inmediata hacia servicios *serverless* (como AWS Lambda o AWS App Runner). Esto ocasiona fallos catastróficos en aplicaciones que mantienen estado en disco local, que utilizan librerías binarias pesadas (como `geopandas`, `scikit-learn` o extensiones C de Python) o que requieren exponer múltiples puertos TCP simultáneamente.
3. **Falta de reproducibilidad y riesgos de seguridad**: Los procedimientos manuales o basados en consolas web conducen a configuraciones inconsistentes (*configuration drift*), exposición involuntaria de credenciales en repositorios y falta de aislamiento entre operadores.

Este escenario constituye un **problema complejo de ingeniería** debido a la heterogeneidad de los sistemas origen (código fuente en múltiples lenguajes, imágenes binarias de disco, servidores físicos y virtuales), la necesidad de garantizar compatibilidad funcional sin acceso invasivo a las máquinas de producción, y el cumplimiento estricto de restricciones de costo y seguridad en la nube de destino.

### 2.2 Variables, Criterios y Restricciones
* **Variables técnicas**: Tipos de arquitecturas de CPU (x86_64, ARM64), requerimientos de memoria RAM y vCPU, puertos de red escuchando, extensiones de base de datos (ej. PostGIS), formatos de empaquetado (Docker Compose, systemd, binarios VMDK/QCOW2).
* **Variables económicas**: Selección de tipos de instancia elegibles dentro de la capa gratuita o presupuestos restringidos (ej. familias `t3.micro`, `t3a.medium`), dimensionamiento de volúmenes EBS gp3.
* **Restricciones normativas y de seguridad**: Aislamiento total de credenciales de AWS por sesión de usuario, prohibición de usar roles IAM del servidor anfitrión (`ALLOW_SERVER_AWS_FALLBACK=false`), mitigación de ataques SSRF hacia el servicio de metadatos IMDSv2, protección contra cruce de directorios (*Tar-Slip/Zip-Slip*) al descomprimir artefactos.
* **Restricciones operativas de laboratorio**: Compatibilidad con cuentas académicas restringidas (AWS Academy Learner Lab / Vocareum), donde la creación de roles IAM como `vmimport` y el uso de volúmenes EBS mayores a 100 GB están prohibidos.

### 2.3 Contexto de Impacto
* **Impacto Económico**: Reduce drásticamente las horas de consultoría especializada necesarias para auditar y migrar cargas de trabajo, disminuyendo el tiempo de preparación de semanas a minutos y optimizando el costo mensual en la nube mediante recomendaciones de dimensionamiento adecuado (*right-sizing*).
* **Impacto Social y Laboral**: Disminuye el estrés operativo y las ventanas de mantenimiento nocturnas de los equipos de infraestructura y desarrollo, automatizando tareas repetitivas de verificación de red y despliegue.
* **Impacto Ambiental**: Facilita la transición desde centros de datos locales ineficientes y servidores sobredimensionados hacia centros de datos hiperscalares con mejor eficiencia en el uso de energía (PUE) y apagado programado de recursos ociosos.

### 2.4 Alcance del Proyecto
* **Lo que sí aborda**:
  - Descubrimiento no invasivo en tres casos de uso: 1) Código fuente y repositorios Git (`app_source`), 2) Imágenes de disco y capturas de sistema operativo en caliente (`vm_image`), y 3) Múltiples servidores mediante telemetría liviana con `osquery` (`datacenter_campaign`).
  - Modelado formal de infraestructura en un grafo semántico intermedio neutro (CMIR v2.1).
  - Algoritmo de resolución de dependencias directas y transitivas con detección de recursos compartidos.
  - Síntesis determinista de Infraestructura como Código en Terraform HCL validado en 4 etapas.
  - Orquestación transaccional con máquina de estados y consola de despliegue en tiempo real hacia AWS.
* **Lo que no aborda**:
  - No reescribe la lógica interna de negocio de las aplicaciones a lenguajes diferentes.
  - No proporciona soporte de despliegue automatizado hacia proveedores distintos a Amazon Web Services (manteniendo el modelado intermedio neutral, pero el adaptador de salida concentrado exclusivamente en AWS).

*(Alineado con el criterio de evaluación ABET SO1-PO1-1: Definición de problemas complejos de ingeniería).*

---

## 3. Objetivos

### 3.1 Objetivo General
Diseñar, implementar y validar experimentalmente una plataforma web modular de ingeniería de software que automatice el descubrimiento de dependencias, la representación neutral de arquitecturas y la síntesis determinista de Infraestructura como Código (Terraform HCL) para la migración de aplicaciones y servidores hacia Amazon Web Services (AWS), garantizando la integridad operativa sin requerir reescritura de código.

### 3.2 Objetivos Específicos
1. **Modelado y Formulación Matemática**: Modelar formalmente la topología de dependencias de software y hardware mediante teoría de grafos dirigidos ($G = (V, E)$), implementando algoritmos de cierre transitivo en anchura (BFS) y un esquema semántico neutral (CMIR v2.1) que cuantifique el nivel de certeza de cada componente mediante puntuaciones de confianza epistémica.
2. **Síntesis Determinista y Validación de Infraestructura**: Desarrollar un motor modular de generación de código Terraform HCL estructurado en cuatro archivos principales (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`) acoplado a un sistema de validación estática de cuatro compuertas (análisis léxico de llaves, verificación anti-fuga de credenciales, coherencia de referencias cruzadas y formateo canónico).
3. **Orquestación Transaccional y Seguridad Operativa**: Construir una arquitectura de orquestación desacoplada basada en una máquina de estados de doce fases transaccionales sobre una base de datos ACID con registro previo (SQLite WAL), garantizando el aislamiento estricto de credenciales por pestaña de navegador y la protección del plano de control contra ataques de falsificación de peticiones del lado del servidor (SSRF).
4. **Validación y Verificación Experimental**: Validar la efectividad, resiliencia y desempeño de la plataforma mediante la ejecución automatizada de un banco de 70 pruebas unitarias y de integración, evaluando experimentalmente tres escenarios reales de migración hacia AWS (aplicación web completa con base de datos geoespacial PostGIS, servidor capturado en caliente con rehidratación Cloud-Init e inventario multi-nodo basado en `osquery`).

*(Alineado con los criterios de evaluación ABET SO1-PO1-1, SO1-PO1-2 y SO6-PO6-1).*

---

## 4. Marco Conceptual

### 4.1 Fundamentos Teóricos y Modelos Matemáticos

#### A. Teoría de Grafos y Cierre Transitivo de Dependencias
La infraestructura de una aplicación se modela formalmente como un grafo dirigido $G = (V, E)$, donde:
* $V = \{v_1, v_2, \dots, v_n\}$ representa el conjunto de nodos o recursos de infraestructura (redes, subredes, instancias de cómputo, servicios, bases de datos, volúmenes de almacenamiento).
* $E = \{(u, v) \mid u, v \in V\}$ representa el conjunto de aristas dirigidas que indican dependencias funcionales (ej. $u \xrightarrow{\text{reads\_from}} v$ o $u \xrightarrow{\text{runs\_on}} v$).

Para asegurar que ningún componente sea migrado sin sus prerrequisitos operativos, se implementa el cálculo del cierre transitivo mediante el algoritmo de Búsqueda en Anchura (BFS), cuya complejidad computacional temporal es $O(|V| + |E|)$. Si un nodo $u$ requiere un recurso $v$, y este a su vez depende de $w$, el subgrafo de migración induce:
$$\text{Dep}(u) = \{x \in V \mid \exists \text{ camino dirigido de } u \text{ hacia } x \text{ en } G\}$$

Adicionalmente, se define la función booleana de compartición $\text{is\_shared}(v)$:
$$\text{is\_shared}(v) = \begin{cases} \text{Verdadero} & \text{si } \text{deg}^-(v) > 1 \text{ con orígenes en aplicaciones distintas} \\ \text{Falso} & \text{en caso contrario} \end{cases}$$
Un recurso compartido bloquea la migración aislada de un solo componente para evitar desconectar servicios existentes.

#### B. Integridad de Bloques e Idempotencia Criptográfica
Para asegurar que los artefactos copiados en staging y las identidades de los nodos de infraestructura no colisionen ni se corrompan, se utiliza la función criptográfica de dispersión SHA-256:
$$H(M) = \text{SHA-256}(M) \in \{0, 1\}^{256}$$
Las identidades deterministas de los nodos en CMIR v2.1 se generan mediante la combinación de atributos canónicos estables (tipo, nombre, máquina origen, puerto), garantizando que la reevaluación de una misma fuente produzca exactamente la misma topología (idempotencia).

#### C. Transaccionalidad y Consistencia de Estados (ACID en SQLite WAL)
El estado de la migración se gestiona mediante un motor relacional en modo WAL (*Write-Ahead Logging*). En este esquema, las modificaciones se escriben secuencialmente en un archivo de bitácora temporal antes de fusionarse en la base de datos principal, lo que permite lecturas concurrentes sin bloqueo mientras se ejecuta una escritura, garantizando las propiedades de Atomicidad, Consistencia, Aislamiento y Durabilidad.

### 4.2 Metodologías y Patrones de Diseño
* **Patrón de Arquitectura en 7 Capas**: Estructura modular estrictamente unidireccional que desacopla la captura de datos, la representación intermedia, la lógica de grafos, el proveedor de destino, la generación de código, la máquina de estados y la ejecución en la nube.
* **Estrategias de Migración (Marco 6R de AWS)**: La plataforma implementa de forma prioritaria las estrategias *Rehost* (traslado directo de máquina virtual o contenedor a EC2) y *Replatform* (modernización mínima dirigida, como transformar un contenedor PostgreSQL local a una instancia gestionada en Amazon RDS).
* **Principio de Mínimo Privilegio (Least Privilege)**: Las plantillas de infraestructura generan roles IAM con políticas restringidas exclusivamente a los servicios necesarios para la carga de trabajo.

### 4.3 Normas Técnicas y Estándares de la Industria
* **ISO/IEC 25010**: Modelo de calidad del producto software, enfatizando la mantenibilidad, confiabilidad, seguridad y portabilidad.
* **RFC 7231 / RFC 7519**: Estándares de comunicación para la API REST del backend y la manipulación segura de tokens de autenticación.
* **AWS IMDSv2**: Especificación del servicio de metadatos de instancia de AWS orientada a mitigar vulnerabilidades de inyección y SSRF mediante tokens de sesión orientados a conexión.
* **HashiCorp HCL2**: Gramática estándar para la definición declarativa de Infraestructura como Código.

### 4.4 Tecnologías y Herramientas Nuevas Incorporadas
* **`osquery`**: Motor de instrumentación de sistemas operativos que expone métricas de hardware, procesos, tablas de ruteo y puertos abiertos a través de consultas SQL estándar.
* **CMIR v2.1 (Cloud Migration Intermediate Representation)**: Formato de esquema JSON fuertemente tipado desarrollado para este proyecto, que desacopla la fuente de análisis del código final de Terraform.
* **Cloud-Init (`user_data.sh`)**: Estándar multiplataforma para la inicialización y configuración desatendida de instancias virtuales durante el primer arranque.
* **`@xyflow/react`**: Biblioteca de alto rendimiento para React 19 utilizada para visualizar, interactuar y editar el grafo de dependencias de la arquitectura en el navegador.

*(Alineado con los criterios de evaluación ABET SO1-PO1-2, SO7-PO7-1, SO7-PO7-2 y SO2-PO2-1).*

---

## 5. Premisas del Diseño

### 5.1 Requerimientos Funcionales (RF)
* **RF1 - Ingesta Multi-Fuente**: El sistema debe admitir repositorios Git (públicos y privados), carpetas locales de código, imágenes de disco (`VMDK`, `QCOW2`, `RAW`, `VHD`, `OVA`) y datos de telemetría emitidos por agentes `osquery`.
* **RF2 - Detección Estática y Análisis de Código**: El motor debe extraer componentes, rutas, variables de entorno y volcados de bases de datos relacionales (incluyendo tipos binarios `PGDMP` y scripts `.sql`) sin ejecutar código arbitrario del usuario.
* **RF3 - Generación de Modelo Neutral (CMIR v2.1)**: Todos los datos descubiertos deben transformarse en un grafo formal con clasificación de certidumbre (`observed`, `derived`, `inferred`, `unknown`) y jerarquía de niveles del 0 al 8.
* **RF4 - Síntesis Modular de Terraform HCL**: La plataforma debe emitir cuatro archivos HCL (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`) y un script de inicialización (`user_data.sh`) totalmente configurado.
* **RF5 - Validación en Cuatro Compuertas**: Antes de presentar o ejecutar el plan, el código generado debe someterse a validación de balanceo sintáctico, filtros anti-fuga de secretos, integridad de referencias cruzadas y formateo con `terraform fmt`.
* **RF6 - Consola de Despliegue Transaccional**: El usuario debe contar con una interfaz interactiva para revisar el plan de ejecución (`terraform plan`), autorizar explícitamente el cambio (`APPROVED`) y monitorear el despliegue en tiempo real (`terraform apply`).

### 5.2 Requerimientos No Funcionales y de Desempeño
* **Desempeño temporal**: El análisis estático de un repositorio promedio (< 100 MB) debe completarse en menos de 10 segundos. La síntesis de código Terraform debe tardar menos de 3 segundos.
* **Consumo de recursos**: El agente de recolección en servidores origen debe consumir menos de 50 MB de memoria RAM y no superar el 2% de uso sostenido de CPU.
* **Compatibilidad de costos (AWS Free Tier y Academy)**: Por defecto, los planes deben seleccionar instancias elegibles de capa gratuita (`t3.micro`), volúmenes EBS de hasta 30 GB (con un tope estricto de 100 GB para no infringir políticas de AWS Academy) y prescindir de roles especiales como `vmimport` si el entorno es restringido.
* **Seguridad y Confidencialidad**: Ninguna credencial de nube debe almacenarse en el disco del servidor de CloudMove. Las peticiones deben usar credenciales aisladas en memoria y transmitidas por sesión (`sessionStorage`).

---

## 6. Factores de Diseño y Consideraciones Éticas

A continuación se presenta la tabla obligatoria de factores aplicados en el diseño de ingeniería del proyecto:

| Tipo de Factor | Consideración Aplicada en el Proyecto | Justificación Técnica de la Decisión | Impacto Ético Asociado |
| :--- | :--- | :--- | :--- |
| **Técnico** | Generación determinista de Terraform HCL validada en 4 niveles y basada en un modelo semántico neutro (CMIR v2.1). | Evita la corrupción de código, elimina configuraciones a ciegas y asegura que la infraestructura creada sea idéntica y reproducible en cualquier despliegue. | Responsabilidad profesional de entregar sistemas confiables que no provoquen caídas en los servicios críticos de los usuarios. |
| **Económico** | Selección de instancias dentro de la Capa Gratuita (`t3.micro`), limitación de volúmenes EBS y advertencias de sobredimensionamiento (*right-sizing*). | Permite a empresas emergentes, estudiantes y organizaciones migrar sin incurrir en facturaciones inesperadas o deudas técnicas de alto costo. | Justicia distributiva y transparencia económica, previniendo gastos desmedidos en plataformas de computación en la nube. |
| **Ambiental** | Empaquetamiento de servicios en contenedores ligeros sobre una única instancia EC2 y consolidación de servidores ociosos. | Maximiza la tasa de utilización del hardware virtual asignado, reduciendo el desperdicio energético derivado de múltiples servidores subutilizados. | Compromiso con la sostenibilidad ambiental mediante la reducción de la huella de carbono digital en los centros de datos. |
| **Social** | Asistente web paso a paso con explicaciones claras de riesgos, dependencias detectadas y visualización en grafos. | Democratiza el acceso a la computación en la nube para desarrolladores que no son especialistas en DevOps ni en sintaxis compleja de Terraform. | Inclusión tecnológica y reducción de barreras de entrada técnicas para pequeñas y medianas organizaciones. |
| **Seguridad y Salud Pública** | Aislamiento de credenciales en `sessionStorage`, redacción activa de secretos y bloqueo de acceso a credenciales del servidor anfitrión (`ALLOW_SERVER_AWS_FALLBACK=false`). | Previene la suplantación de identidad, la fuga de llaves maestras y ataques de desplazamiento lateral hacia redes internas o metadatos de la nube. | Protección del derecho a la privacidad y salvaguarda de los datos sensibles y la confidencialidad de la información de los usuarios. |
| **Contexto Global** | Uso de estándares abiertos internacionales (Terraform, Docker, Cloud-Init, Linux) e independencia de proveedor en el modelo CMIR v2.1. | Garantiza que las organizaciones no queden atadas a contratos cerrados ni a tecnologías propietarias que limiten su soberanía tecnológica. | Promoción de estándares abiertos y libre competencia en el ecosistema global de tecnologías de la información. |

*(Alineado con los criterios de evaluación ABET SO2-PO2-2, SO2-PO2-3, SO4-PO4-1, SO4-PO4-2 y SO4-PO4-3).*

---

## 7. Alternativas y Criterios de Selección

### 7.1 Descripción de Alternativas Evaluadas

* **Alternativa A: Migración Manual y Reescritura Forzada a Serverless**
  - *Principio de funcionamiento*: Un equipo de ingenieros audita manualmente el código, reescribe los endpoints de la aplicación para ejecutarse en funciones efímeras (AWS Lambda) y configura la red a través de la consola web de AWS.
  - *Complejidad*: Muy alta. Requiere semanas de refactorización de código y pruebas individuales.
  - *Ventajas*: Uso nativo de servicios gestionados bajo demanda.
  - *Limitaciones*: Incompatible con librerías pesadas (>250 MB), incompatibilidad con aplicaciones que gestionan estado en disco local, altos tiempos de respuesta en arranques en frío (*cold starts*) y alto riesgo de errores manuales en seguridad.

* **Alternativa B: Herramientas Comerciales Propietarias de Replicación de Bloques (ej. AWS MGN)**
  - *Principio de funcionamiento*: Instalación de un agente propietario en el sistema operativo en caliente que replica de manera continua cada bloque del disco hacia volúmenes EBS en la nube.
  - *Complejidad*: Media.
  - *Ventajas*: Mínimo tiempo de inactividad durante el corte final (*cutover*).
  - *Limitaciones*: Exige permisos de administración completos (`root`/`SYSTEM`) en los servidores origen, no funciona sobre repositorios de código fuente ni archivos de disco fuera de línea, genera costos adicionales de replicación y queda completamente bloqueada en entornos de laboratorio o cuentas académicas por falta de permisos IAM avanzados.

* **Alternativa C (Seleccionada): Plataforma Basada en Modelo Neutral CMIR v2.1 y Síntesis Modular de Terraform (CloudMove)**
  - *Principio de funcionamiento*: Análisis estático no invasivo de la aplicación o servidor, construcción de un grafo formal de dependencias desacoplado, evaluación de viabilidad antes del despliegue y síntesis automatizada de código Terraform HCL respaldado por Docker Compose y Cloud-Init.
  - *Complejidad*: Equilibrada. El usuario opera a través de un asistente guiado que automatiza la complejidad subyacente.
  - *Ventajas*: No requiere modificar el código de la aplicación, soporta los tres casos de uso (Git, imágenes de disco y servidores activos), previene fugas de seguridad, funciona dentro de las restricciones de cuentas académicas y entrega código de infraestructura auditable.
  - *Limitaciones*: El despliegue de servidores completos mediante rehidratación requiere un tiempo de arranque inicial mientras Cloud-Init aprovisiona el entorno.

### 7.2 Matriz Multicriterio Ponderada

Para la evaluación objetiva se asignaron ponderaciones de 1 a 5 a cada criterio y se calificaron las alternativas en una escala de 1 a 5 (donde 5 representa el desempeño óptimo):

| Criterio de Selección | Peso (%) | Alternativa A (Manual / Serverless) | Alternativa B (Comercial / AWS MGN) | Alternativa C (CloudMove - Seleccionada) |
| :--- | :---: | :---: | :---: | :---: |
| **Viabilidad técnica y no reescritura** | 25% | 2.0 (0.50) | 3.5 (0.87) | **4.8 (1.20)** |
| **Costo y optimización de recursos** | 20% | 3.0 (0.60) | 2.5 (0.50) | **4.7 (0.94)** |
| **Seguridad, aislamiento y soberanía** | 20% | 2.5 (0.50) | 3.5 (0.70) | **4.9 (0.98)** |
| **Compatibilidad con laboratorios y Free Tier** | 15% | 3.0 (0.45) | 1.0 (0.15) | **5.0 (0.75)** |
| **Facilidad de uso y experiencia de usuario** | 10% | 1.5 (0.15) | 3.0 (0.30) | **4.5 (0.45)** |
| **Eficiencia energética y ambiental** | 10% | 4.0 (0.40) | 3.0 (0.30) | **4.5 (0.45)** |
| **Puntaje Total Ponderado** | **100%** | **2.60 / 5.00** | **2.82 / 5.00** | **4.77 / 5.00** |

### 7.3 Justificación Rigurosa de la Elección
La **Alternativa C (CloudMove)** superó ampliamente a las demás opciones al obtener un puntaje de **4.77 sobre 5.00**. La decisión técnica se fundamenta en su capacidad única para realizar migraciones viables sin romper el código original del usuario, su compatibilidad con entornos de infraestructura restringidos y la entrega de artefactos de Terraform abiertos y reproducibles.

*(Alineado con los criterios de evaluación ABET SO2-PO2-1, SO2-PO2-2, SO2-PO2-3, SO4-PO4-1, SO4-PO4-2 y SO4-PO4-3).*

---

## 8. Resultados y Análisis

### 8.1 Resultados de la Suite Automatizada de Pruebas
La validación del sistema se condujo mediante una batería exhaustiva de pruebas unitarias, de integración y de seguridad en el backend. Los resultados numéricos se detallan a continuación:

* **Total de pruebas ejecutadas:** 70 pruebas.
* **Pruebas aprobadas exitosamente:** 70 pruebas (100% de efectividad).
* **Pruebas fallidas o con error:** 0 pruebas.
* **Tiempo total de ejecución de la suite:** 21.61 segundos.

```
============================= Detalle de Pruebas =============================
backend/tests/test_cmir.py                        PASSED [ 2 pruebas]
backend/tests/test_dependencies.py                PASSED [ 1 prueba ]
backend/tests/test_graph.py                       PASSED [ 1 prueba ]
backend/tests/test_iac.py                         PASSED [ 7 pruebas]
backend/tests/test_adapters.py                    PASSED [ 1 prueba ]
backend/tests/test_agents.py                      PASSED [ 3 pruebas]
backend/tests/test_discovery.py                   PASSED [15 pruebas]
backend/tests/test_evolution_use_cases.py         PASSED [ 8 pruebas]
backend/tests/test_github_connector.py            PASSED [ 6 pruebas]
backend/tests/test_reliability_and_discovery.py   PASSED [ 9 pruebas]
backend/tests/test_security_and_audit_fixes.py    PASSED [13 pruebas]
backend/tests/test_uc2_file_staging.py            PASSED [ 4 pruebas]
------------------------------------------------------------------------------
Resultado Consolidado: 70 passed in 21.61s
```

### 8.2 Validación frente a los Tres Casos de Uso del Proyecto

#### A. Caso de Uso 1: Aplicación desde Código Fuente (`app_source`)
* Se probó la ingesta de repositorios complejos conteniendo frontend en React/Vite, backend en FastAPI y persistencia en PostgreSQL con la extensión espacial PostGIS.
* El escáner estático analizó el árbol de archivos en 1.8 segundos, fijó el commit SHA para evitar ataques de carrera (*branch drift*) y extrajo las variables requeridas sin exponer secretos.
* Descompiló e inspeccionó volcados binarios de PostgreSQL (`PGDMP`), extrayendo el listado de tablas, conteo de filas y esquemas, generando el script de restauración `migrate_database_data.sh`.
* Generó el módulo de Terraform con una VPC personalizada, subredes públicas y privadas, grupo de seguridad con reglas acotadas y un script `user_data.sh` con 2 GB de espacio swap para evitar caídas por falta de memoria (*Out of Memory*) durante la instalación de paquetes.

#### B. Caso de Uso 2: Servidores desde Imágenes de Disco y Captura en Vivo (`vm_image`)
* Se validaron transferencias de imágenes de disco con verificación criptográfica SHA-256 en el área de staging, asegurando la no alteración del archivo original (`source_untouched = True`).
* Se ejecutó el análisis de particiones y drivers de arranque (`ena`, `nvme`) y verificación del archivo `/etc/fstab`.
* Ante la restricción de cuentas académicas que carecen de permisos para el rol `vmimport`, el sistema activó automáticamente el modo de **Rehidratación Autónoma con Cloud-Init**, levantando una instancia base limpia y reconstruyendo los archivos de configuración y servicios mediante `user_data.sh`, permitiendo monitorear la salud del servidor a través de un portal web de telemetría en vivo.

#### C. Caso de Uso 3: Campañas de Data Center Multi-Servidor (`datacenter_campaign`)
* Se procesaron inventarios reales y sintéticos generados por el agente `osquery`.
* El motor unificó correctamente servidores duplicados bajo identificadores canónicos únicos (`machine_id` + MAC primaria + hostname), resolvió dependencias transitivas mediante el grafo `networkx` y discriminó componentes compartidos para su migración ordenada por fases (*waves*).

### 8.3 Análisis de Incertidumbre y Fidelidad Epistémica
Una innovación clave validada en los resultados fue el clasificador de certeza epistémica. En las pruebas de importación local, el sistema clasificó correctamente:
* Dependencias confirmadas (`observed`, confianza 1.0): Puertos escuchando activamente y contenedores definidos en `docker-compose.yml`.
* Dependencias inferidas (`inferred`, confianza 0.65): Motores de bases de datos detectados en `requirements.txt` (ej. `psycopg2` y `SQLAlchemy`) pero sin contenedor local, infiriendo la necesidad de aprovisionar un servicio en la nube.
* Conexiones externas desconocidas (`unknown`, confianza 0.50): URLs leídas en archivos `.env` (ej. `VITE_API_URL` apuntando a hosts remotos), advirtiendo al operador sobre endpoints fuera del alcance del despliegue.

*(Alineado con los criterios de evaluación ABET SO1-PO1-3, SO6-PO6-1 y SO6-PO6-2).*

---

## 9. Conclusiones y Recomendaciones

### 9.1 Conclusiones
1. **Cumplimiento Integral de Objetivos**: Se construyó y verificó una solución de ingeniería que automatiza el ciclo completo de migración cloud en tres casos de uso representativos, logrando un 100% de éxito en la suite de 70 pruebas automatizadas.
2. **Eficiencia y Viabilidad sin Reescritura**: La plataforma demostró experimentalmente que es viable migrar aplicaciones tradicionales con estado y librerías científicas pesadas hacia la nube sin forzar reescrituras hacia arquitecturas serverless, garantizando disponibilidad y reduciendo los tiempos de despliegue a pocos minutos.
3. **Independencia Arquitectónica Mediante CMIR v2.1**: La introducción del modelo semántico neutral permitió desacoplar totalmente las fuentes de recolección de los generadores de infraestructura, evitando dependencias propietarias y garantizando la trazabilidad de cada recurso aprovisionado.
4. **Seguridad y Resiliencia en la Nube**: El diseño satisfizo rigurosamente los requerimientos de seguridad multi-usuario, aislando credenciales en el cliente web, previniendo ataques de SSRF y habilitando despliegues exitosos incluso en entornos con permisos severamente restringidos como AWS Academy.

### 9.2 Recomendaciones Técnicas
1. **Ampliación de Adaptadores de Destino**: Si bien el modelo CMIR v2.1 es neutro, el adaptador de salida actual se enfoca en AWS. Se recomienda implementar a futuro adaptadores para Google Cloud Platform (GCP) y Microsoft Azure reutilizando el mismo grafo semántico.
2. **Integración con Sistemas de CI/CD**: Incorporar conectores mediante Webhooks de GitHub Actions o GitLab CI para que la generación y auditoría del plan de infraestructura se ejecute automáticamente ante cambios en la rama principal de los repositorios.
3. **Optimización de Tiempos de Arranque en Rehidratación**: Para imágenes de disco de gran tamaño en el Caso 2, se recomienda explorar la compresión por bloques diferenciales con Zstandard para acelerar el tiempo de transferencia hacia las instancias EC2.

*(Alineado con el criterio de evaluación ABET SO6-PO6-3: Emisión de conclusiones basadas en juicio de ingeniería).*

---

## 10. Declaración de Conceptos Nuevos y Tecnologías de Vanguardia

Durante el desarrollo del proyecto se investigaron e incorporaron conceptos técnicos y herramientas de vanguardia no cubiertas en cursos previos:
* **Instrumentación de Sistemas Operativos con `osquery`**: Transformación de la telemetría del sistema operativo en tablas relacionales consultables mediante SQL estándar.
* **Modelo Semántico CMIR v2.1**: Diseño de una gramática intermedia en Pydantic con niveles jerárquicos de infraestructura y metadatos de proveniencia epistémica.
* **Análisis Sintáctico Estático (AST Parsing)**: Inspección de árboles de sintaxis abstracta en Python y código JavaScript para deducir rutas, puertos y dependencias de red sin ejecutar código no confiable.
* **Validación de Infraestructura en Cuatro Compuertas**: Sistema de auditoría previa que previene errores de sintaxis en Terraform y fugas de credenciales antes del aprovisionamiento.
* **Rehidratación Autónoma con Cloud-Init**: Mecanismo para reconstruir la configuración de un sistema operativo capturado en caliente dentro de una instancia limpia de EC2 sin requerir roles restringidos de hipervisor.

---

## 11. Declaración de Uso de Herramientas de Inteligencia Artificial

De conformidad con las políticas académicas del curso de Proyecto Integrador de la Universidad EAFIT, el equipo declara de forma transparente y honesta que utilizó herramientas de Inteligencia Artificial Generativa durante el ciclo de vida del proyecto.

### 11.1 Propósito y Alcance del Uso
Las herramientas de IA se utilizaron exclusivamente como asistentes de productividad técnica en los siguientes aspectos:
* Apoyo en la redacción inicial de documentación técnica y verificación de coherencia gramatical.
* Generación de esqueletos de expresiones regulares (*Regex*) para la detección estática de dependencias en archivos de código fuente.
* Asistencia en la formulación de esquemas tipados con Pydantic y plantillas base de Terraform HCL.
* Sugerencias de optimización para consultas y formateo visual de grafos en React.

En ningún momento se delegó a la inteligencia artificial la toma de decisiones de diseño arquitectónico, la lógica transaccional de la máquina de estados, el modelo formal de teoría de grafos ni la resolución de problemas de seguridad. Todo el código generado o sugerido fue analizado críticamente, modificado manualmente y sometido a pruebas automatizadas estrictas.

### 11.2 Prompts de Ejemplo Reales Utilizados en el Proyecto

A continuación se presentan ejemplos sinceros de los requerimientos y consultas formuladas a las herramientas de IA:

* **Prompt 1 (Construcción de expresiones regulares para escaneo de bases de datos):**
  > *"Necesito una expresión regular en Python para identificar si un archivo de volcado de base de datos de PostgreSQL está en formato binario custom (PGDMP) o si es un script SQL de texto plano que incluye instrucciones para habilitar la extensión postgis y definir tablas. Debe ser eficiente y no cargar archivos de varios gigabytes completamente en memoria."*

* **Prompt 2 (Estructuración de plantillas de Terraform seguras):**
  > *"Dame un ejemplo de cómo estructurar un archivo main.tf de Terraform para AWS que cree una VPC con subredes públicas y un grupo de seguridad que parametrice el puerto 22 a través de una variable ssh_ingress_cidr, asegurándome de que no incluya credenciales en texto plano y que sea compatible con la versión 5 del proveedor de AWS."*

* **Prompt 3 (Depuración de pruebas en pytest):**
  > *"Al ejecutar pytest en un módulo que importa boto3 en un entorno donde la librería aún no está instalada globalmente, la suite se interrumpe en la fase de recolección. ¿Cómo puedo envolver de forma limpia la importación en replication_and_import.py y cloud_live_discovery.py usando bloques try/except para que las pruebas unitarias que no usan la nube real puedan ejecutarse sin fallar?"*

* **Prompt 4 (Redacción y estilo):**
  > *"Revisa este párrafo técnico que describe el cierre transitivo de dependencias con BFS y ayúdame a redactarlo de forma clara y formal en español técnico para ingenieros, eliminando cualquier fraseología de relleno o tono de asistente virtual."*

### 11.3 Criterio y Juicio de Ingeniería Aplicado
Cada una de las respuestas obtenidas fue evaluada mediante juicio crítico de ingeniería. Las sugerencias fueron adaptadas al contexto específico de CloudMove, ajustando nombres de recursos, endureciendo políticas de seguridad y validando el comportamiento mediante las 70 pruebas unitarias documentadas en este informe.

---

## 12. Referencias Bibliográficas

*[Formato de citación IEEE]*

* [1] HashiCorp, "Terraform Documentation and HCL2 Language Specification," HashiCorp Developer Documentation, 2024. [En línea]. Disponible en: `https://developer.hashicorp.com/terraform/docs`
* [2] Amazon Web Services, "AWS Well-Architected Framework: Reliability, Security, and Cost Optimization Pillars," AWS Whitepapers, 2023. [En línea]. Disponible en: `https://aws.amazon.com/architecture/well-architected/`
* [3] Facebook / The Linux Foundation, "osquery: An Operating System Instrumentation Framework," osquery Open Source Project, 2024. [En línea]. Disponible en: `https://osquery.io/`
* [4] T. H. Cormen, C. E. Leiserson, R. L. Rivest, y C. Stein, *Introduction to Algorithms*, 4ta ed. Cambridge, MA: The MIT Press, 2022.
* [5] Canonical Ltd., "Cloud-Init: The Standard for Customizing Cloud Instances," Canonical Documentation, 2024. [En línea]. Disponible en: `https://cloudinit.readthedocs.io/`
* [6] International Organization for Standardization, "ISO/IEC 25010: Systems and software engineering — Systems and software Quality Requirements and Evaluation (SQuaRE) — Product quality model," ISO/IEC Standard, 2023.
* [7] S. Chacon y B. Straub, *Pro Git*, 2da ed. Nueva York: Apress, 2014.
* [8] M. Fowler, *Patterns of Enterprise Application Architecture*. Boston, MA: Addison-Wesley, 2002.
* [9] SQLite Development Team, "Write-Ahead Logging (WAL) in SQLite," SQLite Official Documentation, 2024. [En línea]. Disponible en: `https://www.sqlite.org/wal.html`
* [10] M. Nygard, *Release It!: Design and Deploy Production-Ready Software*, 2da ed. Raleigh, NC: Pragmatic Bookshelf, 2018.

---

## 13. Anexos

### Anexo 1: Estructura del Repositorio y Arquitectura del Código
El proyecto se encuentra organizado en una jerarquía clara y mantenible:
* `backend/app/api/`: Enrutadores de la API REST de FastAPI (`discovery.py`, `migration.py`, `architecture.py`, `agents.py`).
* `backend/app/cmir/`: Modelos Pydantic del esquema neutral CMIR v2.1 y constructores de jerarquía.
* `backend/app/dependencies/`: Algoritmos de resolución de dependencias directas y transitivas con `networkx`.
* `backend/app/adapters/`: Adaptador especializado para recursos de AWS (`aws_adapter.py`).
* `backend/app/generators/`: Motores de síntesis de código Terraform y scripts de inicialización.
* `backend/app/persistence/`: Base de datos transaccional SQLite WAL con soporte de concurrencia optimista.
* `backend/tests/`: Suite automatizada compuesta por 12 archivos de prueba y 70 casos de verificación.
* `frontend/src/`: Aplicación web moderna construida con React 19, Vite y `@xyflow/react`.
* `cloudmove_agent/`: Agente ligero de recolección multiplataforma con instaladores automáticos.

### Anexo 2: Resumen del Banco de Pruebas Automatizadas
Las 70 pruebas cubren la totalidad de los flujos críticos:
1. Pruebas de modelos y jerarquías CMIR v2.1 (`test_cmir.py`).
2. Pruebas de clasificación de motores de bases de datos y dependencias (`test_dependencies.py`).
3. Pruebas de construcción y validación de grafos dirigidos (`test_graph.py`).
4. Pruebas de síntesis modular de Terraform HCL y formateo (`test_iac.py`).
5. Pruebas de traducción de recursos hacia AWS (`test_adapters.py`).
6. Pruebas de gestión y catálogo de agentes (`test_agents.py`).
7. Pruebas de ingesta y parseo de telemetría `osquery` (`test_discovery.py`).
8. Pruebas de los tres casos de uso evolutivos (`test_evolution_use_cases.py`).
9. Pruebas de clonación y seguridad del conector de GitHub (`test_github_connector.py`).
10. Pruebas de confiabilidad y resiliencia en descubrimiento (`test_reliability_and_discovery.py`).
11. Pruebas de mitigación SSRF, saneamiento y auditoría de seguridad (`test_security_and_audit_fixes.py`).
12. Pruebas de copias en staging e integridad de imágenes de disco (`test_uc2_file_staging.py`).

### Anexo 3: Ejemplo de Artefactos de Infraestructura Generados
* `provider.tf`: Configuración del proveedor `aws` con versionado restringido (`~> 5.0`).
* `variables.tf`: Definición tipada de parámetros (`environment`, `instance_type`, `ssh_ingress_cidr`, `db_ingress_cidr`).
* `main.tf`: Declaración de VPC, subredes públicas y privadas, Internet Gateway, grupos de seguridad, instancias EC2 con disco gp3 y recursos RDS PostgreSQL opcionales.
* `outputs.tf`: Exportación limpia de identificadores de recursos, direcciones IP públicas y puntos de enlace (*endpoints*).
* `user_data.sh`: Script ejecutable por Cloud-Init que configura 2 GB de swap, instala Docker Engine / Docker Compose y levanta los contenedores con reinicio automático.

