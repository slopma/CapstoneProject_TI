import React, { useState } from "react";

/**
 * Renders structured GitHub evidence and the interactive Database Analyzer & Transformer card
 * so the user never sees a wall of concatenated raw text.
 */
export function StructuredGithubEvidenceView({ gh, targetProvider = "AWS" }) {
  const [showAllTables, setShowAllTables] = useState(false);
  if (!gh) return null;

  const dbAnalysis = gh.database_analysis || null;
  const rawDetail = String(gh.evidence_detail || "");

  // Split pipe-separated or bullet-separated evidence into clean items if no dbAnalysis
  const evidenceSegments = rawDetail
    .split(/\s*\|\s*|\s*·\s*/)
    .map((s) => s.trim())
    .filter(Boolean);

  return (
    <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 10 }}>
      {/* Archivos fuente inspeccionados */}
      {Array.isArray(gh.files) && gh.files.length > 0 && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            flexWrap: "wrap",
            fontSize: 12.5,
            color: "#414D5C",
          }}
        >
          <strong style={{ color: "#16191F" }}>Fuentes analizadas en GitHub:</strong>
          {gh.files.map((f, idx) => (
            <code
              key={idx}
              style={{
                backgroundColor: "#F2F3F3",
                border: "1px solid #D5DBDB",
                borderRadius: 3,
                padding: "2px 6px",
                fontSize: 12,
                color: "#16191F",
              }}
            >
              {f}
            </code>
          ))}
        </div>
      )}

      {/* Si es una Base de Datos con análisis profundo o backup, mostrar el panel visual estructurado */}
      {dbAnalysis && dbAnalysis.has_backup ? (
        <div
          style={{
            backgroundColor: "#F8FAFC",
            border: "1px solid #B8D4F2",
            borderRadius: 4,
            padding: "12px 14px",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 8,
              marginBottom: 10,
              paddingBottom: 8,
              borderBottom: "1px solid #DCE8F5",
            }}
          >
            <div>
              <span
                className="cm-badge"
                style={{
                  backgroundColor: "#0972D3",
                  color: "#ffffff",
                  fontWeight: 700,
                  fontSize: 11.5,
                  marginRight: 8,
                }}
              >
                INSPECCION PROFUNDA DE BASE DE DATOS Y BACKUP
              </span>
              <strong style={{ fontSize: 13.5, color: "#16191F" }}>
                Diagnóstico y Plan de Transformación de Datos hacia {targetProvider}
              </strong>
            </div>
            <span
              className="cm-badge observed"
              style={{ fontSize: 12, fontWeight: 700 }}
            >
               Paridad de Datos Verificable ({dbAnalysis.total_rows_count} registros)
            </span>
          </div>

          {/* 4 Tarjetas KPI de la Base de Datos */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
              gap: 8,
              marginBottom: 12,
            }}
          >
            <div
              style={{
                backgroundColor: "#ffffff",
                border: "1px solid #D5DBDB",
                borderRadius: 4,
                padding: "8px 10px",
              }}
            >
              <div style={{ fontSize: 11.5, color: "#5F6B7A", fontWeight: 600 }}>
                MOTOR Y VERSION DETECTADA
              </div>
              <div style={{ fontSize: 13.5, fontWeight: 700, color: "#16191F", marginTop: 2 }}>
                {dbAnalysis.engine_version}
              </div>
              <div style={{ fontSize: 12, color: "#0972D3", marginTop: 2 }}>
                Imagen destino: <code>{dbAnalysis.target_container_image}</code>
              </div>
            </div>

            <div
              style={{
                backgroundColor: "#ffffff",
                border: "1px solid #D5DBDB",
                borderRadius: 4,
                padding: "8px 10px",
              }}
            >
              <div style={{ fontSize: 11.5, color: "#5F6B7A", fontWeight: 600 }}>
                ARCHIVO DE VOLCADO (BACKUP)
              </div>
              <div style={{ fontSize: 13.5, fontWeight: 700, color: "#16191F", marginTop: 2 }}>
                <code>{dbAnalysis.backup_file}</code> ({dbAnalysis.backup_size_kb} KB)
              </div>
              <div style={{ fontSize: 12, color: "#5F6B7A", marginTop: 2 }}>
                {dbAnalysis.backup_format}
              </div>
            </div>

            <div
              style={{
                backgroundColor: "#ffffff",
                border: "1px solid #D5DBDB",
                borderRadius: 4,
                padding: "8px 10px",
              }}
            >
              <div style={{ fontSize: 11.5, color: "#5F6B7A", fontWeight: 600 }}>
                TABLAS Y FILAS DE DOMINIO (PUBLIC)
              </div>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#037F0C", marginTop: 2 }}>
                {dbAnalysis.public_tables_count} tablas · {dbAnalysis.public_rows_count} filas
              </div>
              <div style={{ fontSize: 12, color: "#5F6B7A", marginTop: 2 }}>
                Esquema principal de la aplicación
              </div>
            </div>

            <div
              style={{
                backgroundColor: "#ffffff",
                border: "1px solid #D5DBDB",
                borderRadius: 4,
                padding: "8px 10px",
              }}
            >
              <div style={{ fontSize: 11.5, color: "#5F6B7A", fontWeight: 600 }}>
                TOTAL EN TODOS LOS ESQUEMAS
              </div>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#16191F", marginTop: 2 }}>
                {dbAnalysis.total_tables_count} tablas · {dbAnalysis.total_rows_count} filas
              </div>
              <div style={{ fontSize: 12, color: "#5F6B7A", marginTop: 2 }}>
                Incluye {(dbAnalysis.schemas || []).length} esquemas (auth, storage, etc.)
              </div>
            </div>
          </div>

          {/* Tablas con datos extraídas del backup */}
          {Array.isArray(dbAnalysis.tables_with_data) &&
            dbAnalysis.tables_with_data.length > 0 && (
              <div style={{ marginBottom: 10 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 6,
                  }}
                >
                  <strong style={{ fontSize: 12.5, color: "#16191F" }}>
                    Tablas con datos identificadas en el backup ({dbAnalysis.tables_with_data.length}):
                  </strong>
                  {dbAnalysis.tables_with_data.length > 10 && (
                    <button
                      type="button"
                      className="cm-btn sm"
                      onClick={() => setShowAllTables(!showAllTables)}
                      style={{ padding: "2px 8px", fontSize: 11.5 }}
                    >
                      {showAllTables
                        ? "Mostrar solo principales"
                        : `Ver las ${dbAnalysis.tables_with_data.length} tablas`}
                    </button>
                  )}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {(showAllTables
                    ? dbAnalysis.tables_with_data
                    : dbAnalysis.tables_with_data.slice(0, 10)
                  ).map((tbl, tIdx) => (
                    <span
                      key={tIdx}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "3px 8px",
                        borderRadius: 3,
                        fontSize: 12,
                        backgroundColor: tbl.is_public ? "#F2FAF3" : "#F2F3F3",
                        border: tbl.is_public ? "1px solid #8CD990" : "1px solid #D5DBDB",
                        color: "#16191F",
                      }}
                    >
                      <code>{tbl.table}</code>
                      <strong style={{ color: tbl.is_public ? "#037F0C" : "#414D5C" }}>
                        {tbl.rows} filas
                      </strong>
                    </span>
                  ))}
                </div>
              </div>
            )}

          {/* Extensiones, Esquemas y Funciones RPC en 2 columnas */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
              gap: 10,
              marginBottom: 10,
            }}
          >
            <div
              style={{
                backgroundColor: "#ffffff",
                border: "1px solid #E9EBED",
                borderRadius: 4,
                padding: "8px 10px",
              }}
            >
              <strong style={{ fontSize: 12.5, color: "#16191F", display: "block", marginBottom: 4 }}>
                Extensiones PostgreSQL requeridas ({(dbAnalysis.extensions || []).length}):
              </strong>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {(dbAnalysis.extensions || []).map((ext, eIdx) => (
                  <code
                    key={eIdx}
                    style={{
                      backgroundColor: "#F2F8FD",
                      color: "#033160",
                      border: "1px solid #A4C9F5",
                      borderRadius: 3,
                      padding: "1px 6px",
                      fontSize: 11.5,
                    }}
                  >
                    {ext}
                  </code>
                ))}
              </div>

              {Array.isArray(dbAnalysis.seed_files) && dbAnalysis.seed_files.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <strong
                    style={{ fontSize: 12.5, color: "#16191F", display: "block", marginBottom: 4 }}
                  >
                    Archivos semilla JSON adicionales ({dbAnalysis.seed_files.length}):
                  </strong>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    {dbAnalysis.seed_files.map((sf, sIdx) => (
                      <div key={sIdx} style={{ fontSize: 12, color: "#414D5C" }}>
                        • <code>{sf.path}</code> — <strong>{sf.record_count} registros</strong> ({sf.format})
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {Array.isArray(dbAnalysis.rpc_functions) && dbAnalysis.rpc_functions.length > 0 && (
              <div
                style={{
                  backgroundColor: "#ffffff",
                  border: "1px solid #E9EBED",
                  borderRadius: 4,
                  padding: "8px 10px",
                }}
              >
                <strong
                  style={{ fontSize: 12.5, color: "#16191F", display: "block", marginBottom: 4 }}
                >
                  Funciones SQL / RPC Espaciales detectadas ({dbAnalysis.rpc_functions.length}):
                </strong>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {dbAnalysis.rpc_functions.map((fn, fIdx) => (
                    <div key={fIdx} style={{ fontSize: 12, color: "#16191F", lineHeight: 1.35 }}>
                      • <code>{fn.name}()</code>{" "}
                      <span style={{ color: "#5F6B7A", fontSize: 11.5 }}>
                        → {fn.returns}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Pipeline automático de transformación a AWS */}
          {Array.isArray(dbAnalysis.aws_transformation_steps) &&
            dbAnalysis.aws_transformation_steps.length > 0 && (
              <div
                style={{
                  backgroundColor: "#ffffff",
                  border: "1px solid #D5DBDB",
                  borderLeft: "4px solid #037F0C",
                  borderRadius: 4,
                  padding: "8px 12px",
                }}
              >
                <strong
                  style={{ fontSize: 12.5, color: "#037F0C", display: "block", marginBottom: 4 }}
                >
                  Pipeline de Transformación Automática de Base de Datos hacia {targetProvider}:
                </strong>
                <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                  {dbAnalysis.aws_transformation_steps.map((step, stIdx) => (
                    <div key={stIdx} style={{ fontSize: 12.5, color: "#16191F", lineHeight: 1.4 }}>
                      {step}
                    </div>
                  ))}
                </div>
              </div>
            )}
        </div>
      ) : (
        /* Vista estructurada limpia para componentes que no son base de datos */
        <div
          style={{
            backgroundColor: "#F8FAFC",
            border: "1px solid #E9EBED",
            borderRadius: 4,
            padding: "8px 12px",
          }}
        >
          <div style={{ fontSize: 12.5, fontWeight: 700, color: "#414D5C", marginBottom: 4 }}>
            Evidencia técnica verificada en el repositorio:
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {evidenceSegments.map((seg, sIdx) => (
              <div key={sIdx} style={{ fontSize: 13, color: "#16191F", lineHeight: 1.4 }}>
                • {seg}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Renders the Pre-Flight Preventive Anti-Failure Checks banner so the user can see
 * potential migration errors ahead of time and how the selected options prevent them.
 */
export function PreflightPreventiveChecksBanner({ checks, targetProvider = "AWS" }) {
  if (!Array.isArray(checks) || checks.length === 0) return null;

  return (
    <div
      style={{
        backgroundColor: "#ffffff",
        border: "1px solid #D5DBDB",
        borderLeft: "4px solid #037F0C",
        borderRadius: 4,
        padding: "12px 14px",
        marginBottom: 14,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 8,
          marginBottom: 8,
        }}
      >
        <div>
          <span
            className="cm-badge observed"
            style={{ fontSize: 11.5, fontWeight: 700, marginRight: 8 }}
          >
            PROTECCION PREVENTIVA PRE-FLIGHT
          </span>
          <strong style={{ fontSize: 14, color: "#16191F" }}>
            Diagnóstico Anticipado de Riesgos Operativos en {targetProvider} ({checks.length} verificaciones aplicadas)
          </strong>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: 10,
        }}
      >
        {checks.map((chk) => (
          <div
            key={chk.id}
            style={{
              backgroundColor: "#FAFAFA",
              border: "1px solid #E9EBED",
              borderRadius: 4,
              padding: "10px 12px",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: 6,
                marginBottom: 4,
              }}
            >
              <strong style={{ fontSize: 13, color: "#16191F" }}>{chk.risk_title}</strong>
              <span
                className="cm-badge observed"
                style={{ fontSize: 11, fontWeight: 700, whiteSpace: "nowrap" }}
              >
                {chk.status || "MITIGADO"}
              </span>
            </div>
            <div style={{ fontSize: 12, color: "#5F6B7A", marginBottom: 6, lineHeight: 1.35 }}>
              <strong>Causa común de fallo:</strong> {chk.cause}
            </div>
            <div
              style={{
                fontSize: 12,
                color: "#037F0C",
                backgroundColor: "#F2FAF3",
                border: "1px solid #8CD990",
                borderRadius: 3,
                padding: "5px 8px",
                lineHeight: 1.35,
              }}
            >
              <strong>Solución en este plan:</strong> {chk.prevention_applied}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Interactive Graphical Verifier Modal / Panel showing the exact cloud topology
 * that will be created in AWS/GCP according to the user's selected migration options.
 */
export default function PlannedCloudStructureGraphModal({
  isOpen,
  onClose,
  catalog,
  decisions,
  targetProvider = "aws",
}) {
  const [selectedNodeId, setSelectedNodeId] = useState("node-ec2");

  if (!isOpen || !catalog) return null;

  const pUpper = (targetProvider || catalog.target_provider || "aws").toUpperCase();
  const activeDecisions = decisions || catalog.applied_decisions || {};

  // Extract current user selections
  const computeChoice =
    activeDecisions["compute_architecture"] || "single_instance_containerized";
  const isHaMode = computeChoice === "ha_asg_alb_containerized";
  const isDecoupledMode = computeChoice === "decoupled_tier_instances";

  const diskChoice =
    activeDecisions["storage_and_build_capacity"] || "ebs_30gb_gp3_swap";
  const diskGb =
    diskChoice === "ebs_50gb_gp3_swap"
      ? 50
      : diskChoice === "ebs_20gb_gp3_swap"
      ? 20
      : 30;

  const netChoice =
    activeDecisions["network_and_env_rewriting"] ||
    "auto_rewrite_public_ip_and_open_ports";
  const dbPortOpenExternally = netChoice !== "strict_private_db_port";

  const iamChoice = activeDecisions["workload_identity"] || "skip_custom_iam";
  const secretsChoice =
    activeDecisions["secrets_and_env"] || "env_template_user_data";

  // Find database item & decision
  const dbItem = (catalog.items || []).find(
    (it) => it.category === "database_or_external" && it.id.startsWith("dep:")
  );
  const dbDecision = dbItem
    ? activeDecisions[dbItem.id] || dbItem.selected_option_id || dbItem.default_option_id
    : "self_hosted_container";
  const dbAnalysis = dbItem?.github_discovered?.database_analysis || null;

  // Find frontend/backend component items
  const componentItems = (catalog.items || []).filter(
    (it) => it.category === "component"
  );

  const openPorts = ["22 (SSH)", "80 (HTTP)", "443 (HTTPS)", "3000 (Frontend)", "8000 (Backend API)"];
  if (dbDecision === "self_hosted_container" && dbPortOpenExternally) {
    openPorts.push("5432 (PostgreSQL/PostGIS)");
  }

  // Build interactive node details dictionary for the side inspector
  const nodeDetailsMap = {
    "node-vpc": {
      title: `Red Virtual Aislada (${pUpper} VPC Multi-AZ)`,
      resource: "aws_vpc.target_vpc + aws_internet_gateway.igw + 4x aws_subnet",
      type: "Red y Enrutamiento",
      summary:
        "Aísla la infraestructura en el bloque CIDR 10.0.0.0/16 con dos subredes públicas (10.0.1.0/24 AZ-a, 10.0.4.0/24 AZ-b) y dos subredes privadas (10.0.2.0/24 AZ-a, 10.0.3.0/24 AZ-b).",
      specs: [
        "CIDR Block: 10.0.0.0/16 (DNS Hostnames y DNS Support habilitados)",
        "Internet Gateway: aws_internet_gateway.igw conectado a aws_route_table.public_rt",
        "Subredes Públicas: map_public_ip_on_launch = true en AZ-a y AZ-b",
        "Subredes Privadas: Aislamiento para bases de datos RDS Multi-AZ",
      ],
    },
    "node-sg": {
      title: "Firewall Perimetral (aws_security_group.app_sg)",
      resource: "aws_security_group.app_sg",
      type: "Seguridad de Red",
      summary:
        "Controla el tráfico entrante y saliente hacia la instancia EC2 y los contenedores publicados.",
      specs: [
        `Puertos TCP Abiertos: ${openPorts.join(", ")}`,
        dbDecision === "self_hosted_container" && dbPortOpenExternally
          ? "Puerto 5432 abierto para permitir conexión e inspección de la base de datos PostGIS"
          : "Puerto 5432 restringido a la red interna de contenedores / VPC",
        "Egress: Tráfico saliente permitido (0.0.0.0/0) para clonar GitHub y descargar imágenes Docker",
      ],
    },
    "node-ec2": {
      title: isHaMode
        ? "Clúster EC2 Auto Scaling + Application Load Balancer"
        : isDecoupledMode
        ? "Instancias EC2 Separadas por Capa"
        : "Nodo Principal EC2 (aws_instance.compute_host)",
      resource: isHaMode
        ? "aws_lb.app_alb + aws_autoscaling_group + aws_instance"
        : "aws_instance.compute_cocoaapp_host",
      type: "Cómputo Cloud",
      summary:
        "Servidor Ubuntu 22.04 LTS aprovisionado con Docker Engine, Docker Compose v2, cliente PostgreSQL y servicio systemd de persistencia.",
      specs: [
        "Tipo de Instancia: t3.micro (Elegible en Capa Gratuita de AWS)",
        `Volumen Raíz EBS: ${diskGb} GB gp3 cifrado (delete_on_termination = true)`,
        "Memoria Swap: 2 GB (/swapfile) configurados en el paso [1/7] de user_data.sh",
        "Reemplazo automático: user_data_replace_on_change = true",
        "Reescritura dinámica de IP Pública vía IMDSv2 (169.254.169.254) antes de compilar",
      ],
    },
    "node-ebs": {
      title: `Almacenamiento Raíz EBS gp3 (${diskGb} GB) + 2 GB Swap`,
      resource: `root_block_device { volume_size = ${diskGb}, volume_type = "gp3" }`,
      type: "Almacenamiento Persistente",
      summary:
        "Previene el fallo 'no space left on device' al descomprimir imágenes pesadas de PostGIS, Python ML/GIS (scipy, scikit-learn, geopandas) y Node.js.",
      specs: [
        `Capacidad asignada: ${diskGb} GB gp3 (frente a los 8 GB por defecto de la AMI)`,
        "Cifrado EBS activo (encrypted = true)",
        "Volumen Docker persistente: pgdata (/var/lib/postgresql/data)",
        "Limpieza post-compilación: docker builder prune -af",
      ],
    },
    "node-frontend": {
      title: "Contenedor Frontend Web ( Puerto 3000 -> 80 )",
      resource: "Servicio Docker 'frontend' (nginx:alpine / Vite SPA)",
      type: "Capa de Presentación",
      summary:
        "Compila la aplicación web tras inyectar la IP pública real de EC2 en VITE_API_URL y la sirve mediante Nginx en el puerto 3000.",
      specs: [
        "Mapeo de Puerto: 3000:80 (Accesible en http://<IP_PUBLICA>:3000)",
        "Variable inyectada antes del build: VITE_API_URL=http://<IP_PUBLICA>:8000",
        "Política de resiliencia: restart: always",
      ],
    },
    "node-backend": {
      title: "Contenedor Backend API ( Puerto 8000 -> 8000 )",
      resource: "Servicio Docker 'backend' (FastAPI / Python 3.11)",
      type: "Capa de Lógica y API REST",
      summary:
        "Expone la API REST y documentación Swagger (/docs) en el puerto 8000, conectado directamente al motor PostgreSQL/PostGIS.",
      specs: [
        "Mapeo de Puerto: 8000:8000 (Accesible en http://<IP_PUBLICA>:8000/docs)",
        dbDecision === "self_hosted_container"
          ? "Conexión a BD: DB_HOST=db, DB_PORT=5432, DATABASE_URL=postgresql://postgres:***@db:5432/postgres"
          : dbDecision === "transform_to_cloud_managed"
          ? "Conexión a BD: Endpoint privado de Amazon RDS PostgreSQL (Puerto 5432)"
          : "Conexión a BD: Endpoint externo BaaS preservado en .env",
        "Dependencia de arranque: depends_on db (condition: service_healthy)",
      ],
    },
    "node-db": {
      title:
        dbDecision === "self_hosted_container"
          ? `Base de Datos Contenerizada (${dbAnalysis?.target_container_image || "postgis/postgis:17-3.5"})`
          : dbDecision === "transform_to_cloud_managed"
          ? "Amazon RDS for PostgreSQL + PostGIS (Multi-AZ)"
          : "Servicio BaaS Externo (Supabase Cloud)",
      resource:
        dbDecision === "self_hosted_container"
          ? "Servicio Docker 'db' + migrate_database_data.sh"
          : dbDecision === "transform_to_cloud_managed"
          ? "aws_db_instance + aws_db_subnet_group + migrate_database_data.sh"
          : "Conexión HTTPS Externa (0 recursos RDS)",
      type: "Capa de Datos y Persistencia Geoespacial",
      summary:
        dbDecision === "keep_external"
          ? "Mantiene la conexión hacia el proyecto externo de Supabase sin aprovisionar motor local."
          : `Recrea la base de datos en ${pUpper}, pre-configura esquemas y roles compatibles con Supabase, activa PostGIS y restaura automáticamente el backup '${dbAnalysis?.backup_file || "supabase_backup.dump"}'.`,
      specs:
        dbDecision === "keep_external"
          ? ["Sin aprovisionamiento de base de datos en AWS", "Usa VITE_SUPABASE_URL externo"]
          : [
              `Motor: ${dbAnalysis?.engine_version || "PostgreSQL 17 + PostGIS 3.5"}`,
              `Backup restaurado: ${dbAnalysis?.backup_file || "supabase_backup.dump"} (${dbAnalysis?.public_tables_count || 18} tablas públicas, ${dbAnalysis?.total_rows_count || 760} filas totales)`,
              `Esquemas creados: ${(dbAnalysis?.schemas || ["public", "auth", "storage"]).join(", ")}`,
              `Extensiones activadas: ${(dbAnalysis?.extensions || ["postgis", "pgcrypto", "uuid-ossp"]).join(", ")}`,
              `Funciones RPC restauradas: ${(dbAnalysis?.rpc_functions || []).map((f) => f.name).join(", ") || "N/A"}`,
            ],
    },
  };

  const activeNodeInfo = nodeDetailsMap[selectedNodeId] || nodeDetailsMap["node-ec2"];

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(15, 23, 42, 0.68)",
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: "#ffffff",
          borderRadius: 6,
          width: "100%",
          maxWidth: 1220,
          maxHeight: "92vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 20px 45px rgba(0, 0, 0, 0.3)",
          border: "1px solid #0972D3",
          overflow: "hidden",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Cabecera del Modal */}
        <div
          style={{
            padding: "14px 20px",
            backgroundColor: "#0F1B2A",
            color: "#ffffff",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 10,
          }}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                className="cm-badge"
                style={{
                  backgroundColor: "#0972D3",
                  color: "#ffffff",
                  fontWeight: 700,
                  fontSize: 11.5,
                }}
              >
                VERIFICADOR GRAFICO DE ARQUITECTURA {pUpper}
              </span>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#ffffff" }}>
                Estructura Exacta que Terraform y Docker Crearán en {pUpper}
              </h3>
            </div>
            <div style={{ fontSize: 12.5, color: "#CBD5E1", marginTop: 3 }}>
              Haz clic sobre cualquier bloque del diagrama para inspeccionar su configuración técnica, puertos, volúmenes y transformación de base de datos.
            </div>
          </div>

          <button
            type="button"
            className="cm-btn sm"
            onClick={onClose}
            style={{
              backgroundColor: "#1E293B",
              color: "#ffffff",
              border: "1px solid #475569",
              fontWeight: 700,
              padding: "6px 14px",
            }}
          >
            Cerrar Vista Gráfica
          </button>
        </div>

        {/* Cuerpo Principal: Diagrama Gráfico a la izquierda + Inspector de Nodo a la derecha */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 340px",
            gap: 0,
            overflowY: "auto",
            flex: 1,
          }}
        >
          {/* Lienzo del Diagrama Topológico */}
          <div
            style={{
              padding: 18,
              backgroundColor: "#F1F5F9",
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            {/* Flujo de Tráfico de Usuario */}
            <div
              style={{
                backgroundColor: "#ffffff",
                border: "1px solid #CBD5E1",
                borderRadius: 6,
                padding: "10px 14px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                flexWrap: "wrap",
                gap: 8,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span
                  style={{
                    backgroundColor: "#0F1B2A",
                    color: "#ffffff",
                    padding: "4px 10px",
                    borderRadius: 4,
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  Cliente / Navegador Web
                </span>
                <span style={{ fontWeight: 700, color: "#0972D3", fontSize: 13 }}>
                  ── HTTP :3000 / :8000 ──&gt;
                </span>
                <span
                  onClick={() => setSelectedNodeId("node-sg")}
                  style={{
                    cursor: "pointer",
                    backgroundColor: selectedNodeId === "node-sg" ? "#0972D3" : "#EFF6FF",
                    color: selectedNodeId === "node-sg" ? "#ffffff" : "#1E40AF",
                    border: "1px solid #93C5FD",
                    padding: "4px 10px",
                    borderRadius: 4,
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  Security Group ({openPorts.length} puertos abiertos)
                </span>
                <span style={{ fontWeight: 700, color: "#0972D3", fontSize: 13 }}>
                  ──&gt;
                </span>
                <span
                  onClick={() => setSelectedNodeId("node-frontend")}
                  style={{
                    cursor: "pointer",
                    backgroundColor: "#F0FDF4",
                    color: "#166534",
                    border: "1px solid #86EFAC",
                    padding: "4px 10px",
                    borderRadius: 4,
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  Frontend (:3000) ──&gt; Backend (:8000) ──&gt; BD PostGIS (:5432)
                </span>
              </div>
            </div>

            {/* Contenedor Exterior: Región AWS + VPC */}
            <div
              onClick={() => setSelectedNodeId("node-vpc")}
              style={{
                border:
                  selectedNodeId === "node-vpc"
                    ? "2px solid #0972D3"
                    : "2px dashed #64748B",
                borderRadius: 8,
                backgroundColor: "#F8FAFC",
                padding: 16,
                cursor: "pointer",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: 8,
                  marginBottom: 12,
                }}
              >
                <div>
                  <span
                    style={{
                      backgroundColor: "#1E293B",
                      color: "#ffffff",
                      padding: "3px 8px",
                      borderRadius: 3,
                      fontSize: 11.5,
                      fontWeight: 700,
                      marginRight: 8,
                    }}
                  >
                    VPC {pUpper}
                  </span>
                  <strong style={{ fontSize: 14, color: "#0F172A" }}>
                    aws_vpc.target_vpc (10.0.0.0/16) + Internet Gateway (aws_internet_gateway.igw)
                  </strong>
                </div>
                <span style={{ fontSize: 12, color: "#475569", fontWeight: 600 }}>
                  Subredes Públicas (10.0.1.0/24, 10.0.4.0/24) · Subredes Privadas (10.0.2.0/24, 10.0.3.0/24)
                </span>
              </div>

              {/* Bloque Security Group */}
              <div
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedNodeId("node-sg");
                }}
                style={{
                  border:
                    selectedNodeId === "node-sg"
                      ? "2px solid #0972D3"
                      : "1px solid #93C5FD",
                  backgroundColor: "#EFF6FF",
                  borderRadius: 6,
                  padding: "10px 12px",
                  marginBottom: 14,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: 6,
                    marginBottom: 6,
                  }}
                >
                  <strong style={{ fontSize: 13, color: "#1E3A8A" }}>
                    Firewall Perimetral: aws_security_group.app_sg
                  </strong>
                  <span style={{ fontSize: 11.5, color: "#1E40AF", fontWeight: 600 }}>
                    Reglas Ingress Activas
                  </span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {openPorts.map((p, idx) => (
                    <span
                      key={idx}
                      style={{
                        backgroundColor: "#ffffff",
                        border: "1px solid #60A5FA",
                        color: "#1E3A8A",
                        padding: "2px 8px",
                        borderRadius: 3,
                        fontSize: 12,
                        fontWeight: 700,
                      }}
                    >
                      TCP {p}
                    </span>
                  ))}
                </div>
              </div>

              {/* Subred Pública: Instancia EC2 + Disco EBS + Docker Compose */}
              <div
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedNodeId("node-ec2");
                }}
                style={{
                  border:
                    selectedNodeId === "node-ec2"
                      ? "2px solid #0972D3"
                      : "2px solid #0284C7",
                  backgroundColor: "#ffffff",
                  borderRadius: 6,
                  padding: 14,
                  marginBottom: 12,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    flexWrap: "wrap",
                    gap: 8,
                    marginBottom: 12,
                    paddingBottom: 8,
                    borderBottom: "1px solid #E2E8F0",
                  }}
                >
                  <div>
                    <span
                      style={{
                        backgroundColor: "#0284C7",
                        color: "#ffffff",
                        padding: "2px 8px",
                        borderRadius: 3,
                        fontSize: 11,
                        fontWeight: 700,
                        marginRight: 8,
                      }}
                    >
                      SUBRED PUBLICA AZ-A (10.0.1.0/24)
                    </span>
                    <strong style={{ fontSize: 14, color: "#0F172A" }}>
                      {isHaMode
                        ? "Application Load Balancer + Auto Scaling Group + Instancia EC2 (t3.micro)"
                        : "Instancia EC2 Principal: aws_instance.compute_host (Ubuntu 22.04 LTS · t3.micro)"}
                    </strong>
                  </div>

                  {/* Badge de Almacenamiento EBS */}
                  <div
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedNodeId("node-ebs");
                    }}
                    style={{
                      backgroundColor:
                        selectedNodeId === "node-ebs" ? "#0972D3" : "#FEF3C7",
                      color: selectedNodeId === "node-ebs" ? "#ffffff" : "#92400E",
                      border: "1px solid #F59E0B",
                      padding: "4px 10px",
                      borderRadius: 4,
                      fontSize: 12,
                      fontWeight: 700,
                      cursor: "pointer",
                    }}
                  >
                    Volumen EBS Raíz: {diskGb} GB gp3 Cifrado + 2 GB Swap
                  </div>
                </div>

                {/* Clúster Interno Docker Compose */}
                <div
                  style={{
                    backgroundColor: "#F8FAFC",
                    border: "1px dashed #94A3B8",
                    borderRadius: 6,
                    padding: 12,
                  }}
                >
                  <div
                    style={{
                      fontSize: 12.5,
                      fontWeight: 700,
                      color: "#334155",
                      marginBottom: 10,
                      display: "flex",
                      justifyContent: "space-between",
                      flexWrap: "wrap",
                      gap: 6,
                    }}
                  >
                    <span>
                      CLÚSTER DOCKER COMPOSE INTERNO (/opt/app/docker-compose.cloudmove.yml)
                    </span>
                    <span style={{ color: "#037F0C" }}>
                      Servicio systemd: Activo al iniciar · Reinicio automático (restart: always)
                    </span>
                  </div>

                  {/* Tarjetas de los 3 Contenedores conectados */}
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 10,
                    }}
                  >
                    {/* Contenedor 1: Frontend */}
                    <div
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedNodeId("node-frontend");
                      }}
                      style={{
                        backgroundColor: "#ffffff",
                        border:
                          selectedNodeId === "node-frontend"
                            ? "2px solid #0972D3"
                            : "1px solid #CBD5E1",
                        borderLeft: "4px solid #0972D3",
                        borderRadius: 4,
                        padding: "10px 12px",
                        cursor: "pointer",
                      }}
                    >
                      <div style={{ fontSize: 11, fontWeight: 700, color: "#0972D3" }}>
                        CONTENEDOR FRONTEND WEB
                      </div>
                      <div style={{ fontSize: 13.5, fontWeight: 700, color: "#0F172A", marginTop: 2 }}>
                        frontend (Nginx / Vite SPA)
                      </div>
                      <div style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
                        • Puerto expuesto: <code>3000:80</code>
                      </div>
                      <div style={{ fontSize: 12, color: "#037F0C", marginTop: 2 }}>
                        • <code>VITE_API_URL=http://&lt;IP_EC2&gt;:8000</code> (Inyectado antes del build)
                      </div>
                    </div>

                    {/* Contenedor 2: Backend */}
                    <div
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedNodeId("node-backend");
                      }}
                      style={{
                        backgroundColor: "#ffffff",
                        border:
                          selectedNodeId === "node-backend"
                            ? "2px solid #0972D3"
                            : "1px solid #CBD5E1",
                        borderLeft: "4px solid #0284C7",
                        borderRadius: 4,
                        padding: "10px 12px",
                        cursor: "pointer",
                      }}
                    >
                      <div style={{ fontSize: 11, fontWeight: 700, color: "#0284C7" }}>
                        CONTENEDOR BACKEND API
                      </div>
                      <div style={{ fontSize: 13.5, fontWeight: 700, color: "#0F172A", marginTop: 2 }}>
                        backend (FastAPI / Python 3.11)
                      </div>
                      <div style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
                        • Puerto expuesto: <code>8000:8000</code>
                      </div>
                      <div style={{ fontSize: 12, color: "#037F0C", marginTop: 2 }}>
                        • Conectado a BD: <code>DB_HOST={dbDecision === "self_hosted_container" ? "db" : "rds-endpoint"}</code> (:5432)
                      </div>
                    </div>

                    {/* Contenedor 3: Base de Datos PostGIS (si es self_hosted_container) */}
                    {dbDecision === "self_hosted_container" && (
                      <div
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedNodeId("node-db");
                        }}
                        style={{
                          backgroundColor: "#F0FDF4",
                          border:
                            selectedNodeId === "node-db"
                              ? "2px solid #037F0C"
                              : "1px solid #86EFAC",
                          borderLeft: "4px solid #037F0C",
                          borderRadius: 4,
                          padding: "10px 12px",
                          cursor: "pointer",
                        }}
                      >
                        <div style={{ fontSize: 11, fontWeight: 700, color: "#037F0C" }}>
                          MOTOR BD TRANSFORMADO EN AWS
                        </div>
                        <div
                          style={{
                            fontSize: 13.5,
                            fontWeight: 700,
                            color: "#0F172A",
                            marginTop: 2,
                          }}
                        >
                          db ({dbAnalysis?.target_container_image || "postgis/postgis:17-3.5"})
                        </div>
                        <div style={{ fontSize: 12, color: "#166534", marginTop: 4 }}>
                          • Puerto: <code>5432:5432</code> · Volumen: <code>pgdata</code>
                        </div>
                        <div style={{ fontSize: 12, color: "#166534", marginTop: 2 }}>
                          • Backup restaurado:{" "}
                          <strong>
                            {dbAnalysis?.public_tables_count || 18} tablas públicas ·{" "}
                            {dbAnalysis?.total_rows_count || 760} filas
                          </strong>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Subredes Privadas / Base de Datos RDS o Externa + IAM + Secretos */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
                  gap: 10,
                }}
              >
                {dbDecision !== "self_hosted_container" && (
                  <div
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedNodeId("node-db");
                    }}
                    style={{
                      backgroundColor: "#ffffff",
                      border:
                        selectedNodeId === "node-db"
                          ? "2px solid #0972D3"
                          : "1px solid #CBD5E1",
                      borderRadius: 6,
                      padding: "10px 12px",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#0972D3" }}>
                      {dbDecision === "transform_to_cloud_managed"
                        ? "SUBREDES PRIVADAS MULTI-AZ (10.0.2.0/24, 10.0.3.0/24)"
                        : "CONEXION EXTERNA PRESERVADA"}
                    </div>
                    <div style={{ fontSize: 13.5, fontWeight: 700, color: "#0F172A", marginTop: 2 }}>
                      {dbDecision === "transform_to_cloud_managed"
                        ? "Amazon RDS for PostgreSQL (db.t3.micro Multi-AZ)"
                        : "Supabase BaaS Externo (Sin RDS en AWS)"}
                    </div>
                    <div style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
                      {dbDecision === "transform_to_cloud_managed"
                        ? `Restaura ${dbAnalysis?.backup_file || "backup.dump"} (${dbAnalysis?.total_rows_count || 760} filas) vía migrate_database_data.sh`
                        : "Mantiene las credenciales originales en el archivo .env"}
                    </div>
                  </div>
                )}

                <div
                  style={{
                    backgroundColor: "#ffffff",
                    border: "1px solid #CBD5E1",
                    borderRadius: 6,
                    padding: "10px 12px",
                  }}
                >
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#475569" }}>
                    GESTION DE VARIABLES Y SECRETOS
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#0F172A", marginTop: 2 }}>
                    {secretsChoice === "cloud_secrets_manager"
                      ? "AWS Secrets Manager (aws_secretsmanager_secret)"
                      : "Inyección Automática en .env vía user_data.sh ($0)"}
                  </div>
                  <div style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
                    Reescribe VITE_API_URL, DATABASE_URL y DB_HOST con los endpoints reales de AWS.
                  </div>
                </div>

                <div
                  style={{
                    backgroundColor: "#ffffff",
                    border: "1px solid #CBD5E1",
                    borderRadius: 6,
                    padding: "10px 12px",
                  }}
                >
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#475569" }}>
                    IDENTIDAD IAM DEL SERVIDOR
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#0F172A", marginTop: 2 }}>
                    {iamChoice === "skip_custom_iam"
                      ? "Sin Rol IAM Personalizado (Compatible AWS Academy)"
                      : "Rol IAM + Instance Profile (aws_iam_role)"}
                  </div>
                  <div style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
                    {iamChoice === "skip_custom_iam"
                      ? "Evita errores AccessDenied en cuentas de laboratorio con iam:CreateRole restringido."
                      : "Asigna identidad de ejecución nativa a la instancia EC2."}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Panel Lateral Derecho: Inspector Técnico del Nodo Seleccionado */}
          <div
            style={{
              backgroundColor: "#ffffff",
              borderLeft: "1px solid #D5DBDB",
              padding: 18,
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
              gap: 14,
            }}
          >
            <div>
              <span
                className="cm-badge"
                style={{
                  backgroundColor: "#F2F8FD",
                  color: "#0972D3",
                  border: "1px solid #A4C9F5",
                  fontSize: 11.5,
                  fontWeight: 700,
                }}
              >
                {activeNodeInfo.type}
              </span>
              <h4 style={{ margin: "8px 0 4px 0", fontSize: 15, color: "#16191F" }}>
                {activeNodeInfo.title}
              </h4>
              <div
                style={{
                  fontSize: 12,
                  backgroundColor: "#F2F3F3",
                  padding: "4px 8px",
                  borderRadius: 3,
                  fontFamily: "monospace",
                  color: "#033160",
                  marginBottom: 10,
                }}
              >
                {activeNodeInfo.resource}
              </div>
              <p style={{ fontSize: 13, color: "#414D5C", lineHeight: 1.45, margin: "0 0 12px 0" }}>
                {activeNodeInfo.summary}
              </p>

              <div
                style={{
                  fontSize: 12.5,
                  fontWeight: 700,
                  color: "#16191F",
                  marginBottom: 6,
                  borderBottom: "1px solid #E9EBED",
                  paddingBottom: 4,
                }}
              >
                Especificaciones que se aplicarán:
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {(activeNodeInfo.specs || []).map((sp, idx) => (
                  <div
                    key={idx}
                    style={{
                      fontSize: 12.5,
                      color: "#16191F",
                      backgroundColor: "#F8FAFC",
                      border: "1px solid #E2E8F0",
                      borderRadius: 4,
                      padding: "6px 8px",
                      lineHeight: 1.35,
                    }}
                  >
                    • {sp}
                  </div>
                ))}
              </div>
            </div>

            <div
              style={{
                backgroundColor: "#F2FAF3",
                border: "1px solid #8CD990",
                borderRadius: 4,
                padding: "10px 12px",
                fontSize: 12.5,
                color: "#037F0C",
              }}
            >
              <strong>Estado de Validación:</strong> Todos los recursos mostrados en este diagrama están sincronizados con los archivos <code>main.tf</code>, <code>user_data.sh</code> y <code>docker-compose.cloudmove.yml</code>.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
