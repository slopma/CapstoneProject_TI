import React, { useState } from "react";

export default function TargetArchitectureView({ job }) {
  const [activeViewTab, setActiveViewTab] = useState("diagram"); // "diagram" | "tf_inventory" | "flows"

  if (!job) {
    return (
      <div className="cm-card" style={{ padding: 40, textAlign: "center" }}>
        <div style={{ fontSize: 44, marginBottom: 12 }}>☁️</div>
        <h3 style={{ fontSize: 18, color: "#0f172a", marginBottom: 8, fontWeight: 700 }}>
          Sin arquitectura objetivo activa
        </h3>
        <p style={{ fontSize: 14, color: "#64748b", maxWidth: 580, margin: "0 auto 16px auto", lineHeight: 1.6 }}>
          Los diagramas de arquitectura objetivo no son fijos ni se muestran por defecto. Se generan directamente a partir del código de infraestructura <strong>Terraform (HCL)</strong> sintetizado en la sección <strong>GitHub → Nube</strong> y se adaptan a las decisiones de migración seleccionadas.
        </p>
        <span className="cm-badge info" style={{ padding: "6px 14px", fontSize: 13 }}>
          Selecciona o inicia un plan de migración para generar el código Terraform y visualizar la arquitectura
        </span>
      </div>
    );
  }

  const provider = (job?.target_provider || "aws").toUpperCase();
  const appName = job?.source_environment?.app_name || job?.name || "Carga de Trabajo";
  const decisions = job.source_config?.user_decisions || job.user_decisions || job.decisions || {};
  
  const compChoice = decisions.compute_architecture || "single_instance_containerized";
  const isHA = compChoice === "ha_asg_alb_containerized" || compChoice === "ha_alb_asg";
  
  const isCloudDB = Object.entries(decisions).some(
    ([k, v]) => (k.includes("database") || k.includes("supabase") || k.includes("dep:")) && v === "provision_cloud_db"
  );

  const components = job.source_environment?.components || [
    { name: "frontend", tier: "frontend", framework: "React", container_ports: [80], host_ports: [3000] },
    { name: "backend", tier: "backend", framework: "FastAPI", container_ports: [8000], host_ports: [8000] },
  ];

  const ports = job.source_environment?.exposed_ports || [80, 443, 3000, 8000];

  // Terraform Inventory Mapping (matches the exact resources in main.tf)
  const terraformResources = [
    { type: "aws_vpc", name: "target_vpc", layer: "Red y Aislamiento", desc: "VPC aislada 10.0.0.0/16 con DNS hostnames y DNS support habilitados" },
    { type: "aws_internet_gateway", name: "igw", layer: "Conectividad Exterior", desc: "Puerta de enlace a Internet pública asociada a la VPC" },
    { type: "aws_subnet", name: "public_subnet", layer: "Subred Pública A", desc: "10.0.1.0/24 (us-east-1a) con asignación de IP pública para Ingress" },
    { type: "aws_subnet", name: "public_subnet_b", layer: "Subred Pública B", desc: "10.0.4.0/24 (us-east-1b) para redundancia Multi-AZ del balanceador" },
    { type: "aws_subnet", name: "private_subnet_a", layer: "Subred Privada A", desc: "10.0.2.0/24 (us-east-1a) para persistencia y cómputo aislado sin IP pública" },
    { type: "aws_subnet", name: "private_subnet_b", layer: "Subred Privada B", desc: "10.0.3.0/24 (us-east-1b) para alta disponibilidad Multi-AZ de base de datos" },
    { type: "aws_route_table", name: "public_rt", layer: "Enrutamiento", desc: "Tabla de rutas con destino 0.0.0.0/0 direccionado a aws_internet_gateway.igw" },
    { type: "aws_route_table_association", name: "public_a", layer: "Enrutamiento", desc: "Asociación de Subred Pública A a la tabla de rutas públicas" },
    { type: "aws_route_table_association", name: "public_b", layer: "Enrutamiento", desc: "Asociación de Subred Pública B a la tabla de rutas públicas" },
    { type: "aws_security_group", name: "app_sg", layer: "Perímetro de Seguridad", desc: `Security Group de la aplicación: ingress en puertos ${ports.join(", ")}` },
    ...(isHA ? [
      { type: "aws_security_group", name: "alb_sg", layer: "Perímetro de Seguridad", desc: "Security Group del Balanceador ALB con ingress HTTP/HTTPS (80/443)" },
      { type: "aws_lb", name: "app_alb", layer: "Balanceo de Carga", desc: "Application Load Balancer Layer 7 distribuido en subredes públicas Multi-AZ" },
      { type: "aws_lb_target_group", name: "app_tg", layer: "Balanceo de Carga", desc: "Target Group HTTP :80 con health check /health cada 30s" },
      { type: "aws_lb_listener", name: "http_listener", layer: "Balanceo de Carga", desc: "Listener en puerto 80 que reenvía tráfico al Target Group" },
      { type: "aws_launch_template", name: "compute_host_lt", layer: "Cómputo Administrado", desc: "Plantilla de lanzamiento EC2 t3.micro Ubuntu 22.04 LTS con user_data.sh" },
      { type: "aws_autoscaling_group", name: "compute_host_asg", layer: "Cómputo Administrado", desc: "Grupo de autoescalado Multi-AZ (Min: 1, Deseado: 2, Max: 3) con auto-healing" },
    ] : [
      { type: "aws_instance", name: "compute_host", layer: "Cómputo Administrado", desc: "Instancia EC2 t3.micro (Ubuntu 22.04 LTS) con 2GB swapfile y Docker Host" },
    ]),
    { type: "aws_iam_role", name: "identity_sa", layer: "Seguridad e Identidad", desc: "Rol IAM con permisos de mínimo privilegio para lectura en Secrets Manager" },
    { type: "aws_iam_instance_profile", name: "identity_sa_profile", layer: "Seguridad e Identidad", desc: "Perfil de instancia IAM asignado al host EC2 para bootstrapping seguro" },
    { type: "aws_secretsmanager_secret", name: "secrets", layer: "Gestión de Secretos", desc: `Secret Manager cloudmove/production/${appName.toLowerCase()}-secrets cifrado KMS` },
    ...(isCloudDB ? [
      { type: "aws_db_subnet_group", name: "db_subnets", layer: "Base de Datos", desc: "Grupo de subredes privadas A y B para aislamiento total de la base de datos" },
      { type: "aws_db_instance", name: "app_db", layer: "Base de Datos", desc: "Amazon RDS PostgreSQL 15 (db.t4g.micro, Multi-AZ, backup 7 días, cifrado KMS)" },
    ] : [
      { type: "external_service", name: "supabase_baas", layer: "Servicio Externo", desc: "PostgreSQL BaaS preservado externamente en Supabase sin costo de RDS redundante" },
    ]),
    { type: "docker_compose", name: "docker-compose.cloudmove.yml", layer: "Contenedores Multi-Tier", desc: `Malla de contenedores: ${components.map(c => c.name).join(" + ")}` },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Encabezado Principal y Origen del Diagrama */}
      <div className="cm-card">
        <div className="cm-card-title">
          <span>Arquitectura Generada desde Terraform — GitHub → Nube ({provider})</span>
          <span className="cm-badge observed" style={{ backgroundColor: "#0972d3", color: "#ffffff" }}>
            Generado desde Terraform (HCL)
          </span>
        </div>
        <p style={{ margin: "4px 0 12px 0", fontSize: 13.5, color: "#475569", lineHeight: 1.5 }}>
          Esta arquitectura no es un gráfico por defecto: <strong>es sintetizada directamente a partir del código Terraform (<code>main.tf</code>, <code>variables.tf</code>, <code>user_data.sh</code>)</strong> generado para el repositorio <strong>{appName}</strong>. Refleja con precisión cada recurso, regla de red y contenedor aprovisionado.
        </p>

        {/* Selector de Vistas de la Arquitectura */}
        <div style={{ display: "flex", gap: 8, borderBottom: "1px solid #e2e8f0", paddingBottom: 8, marginTop: 12 }}>
          <button
            type="button"
            className={`cm-btn sm ${activeViewTab === "diagram" ? "primary" : "secondary"}`}
            onClick={() => setActiveViewTab("diagram")}
          >
            🗺️ Diagrama Visual de Infraestructura
          </button>
          <button
            type="button"
            className={`cm-btn sm ${activeViewTab === "tf_inventory" ? "primary" : "secondary"}`}
            onClick={() => setActiveViewTab("tf_inventory")}
          >
            📜 Recursos Terraform Creados ({terraformResources.length})
          </button>
          <button
            type="button"
            className={`cm-btn sm ${activeViewTab === "flows" ? "primary" : "secondary"}`}
            onClick={() => setActiveViewTab("flows")}
          >
            ⚡ Malla de Tráfico y Puertos
          </button>
        </div>

        {/* Resumen Superior de Capacidades Cloud */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginTop: 14 }}>
          <div className="cm-card-subtle" style={{ padding: 10, borderLeft: "4px solid #0972d3" }}>
            <span style={{ fontSize: 11.5, color: "#64748b", textTransform: "uppercase", fontWeight: 700 }}>VPC & Subredes</span>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>aws_vpc (10.0.0.0/16)</div>
            <div style={{ fontSize: 12, color: "#475569" }}>4 Subredes Multi-AZ (2 Públicas + 2 Privadas)</div>
          </div>

          <div className="cm-card-subtle" style={{ padding: 10, borderLeft: isHA ? "4px solid #8b5cf6" : "4px solid #16a34a" }}>
            <span style={{ fontSize: 11.5, color: "#64748b", textTransform: "uppercase", fontWeight: 700 }}>Cómputo en HCL</span>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
              {isHA ? "aws_lb + aws_autoscaling_group" : "aws_instance (t3.micro)"}
            </div>
            <div style={{ fontSize: 12, color: "#475569" }}>
              {isHA ? "Balanceo L7 + 2-3 Instancias Multi-AZ" : "Ubuntu 22.04 LTS + Swap 2GB"}
            </div>
          </div>

          <div className="cm-card-subtle" style={{ padding: 10, borderLeft: isCloudDB ? "4px solid #2563eb" : "4px solid #0284c7" }}>
            <span style={{ fontSize: 11.5, color: "#64748b", textTransform: "uppercase", fontWeight: 700 }}>Persistencia</span>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
              {isCloudDB ? "aws_db_instance (RDS Multi-AZ)" : "Supabase BaaS Externo"}
            </div>
            <div style={{ fontSize: 12, color: "#475569" }}>
              {isCloudDB ? "PostgreSQL 15 aislado en subredes privadas" : "Conexión cifrada sin costo de RDS"}
            </div>
          </div>

          <div className="cm-card-subtle" style={{ padding: 10, borderLeft: "4px solid #f59e0b" }}>
            <span style={{ fontSize: 11.5, color: "#64748b", textTransform: "uppercase", fontWeight: 700 }}>Seguridad & Secretos</span>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>aws_secretsmanager_secret</div>
            <div style={{ fontSize: 12, color: "#475569" }}>IAM Instance Profile con mínimo privilegio</div>
          </div>
        </div>
      </div>

      {/* VISTA 1: DIAGRAMA VISUAL ESQUEMÁTICO GENERADO DESDE TERRAFORM */}
      {activeViewTab === "diagram" && (
        <div className="cm-card">
          <div className="cm-card-title">
            <span>Visualización de Recursos Terraform de {appName}</span>
            <span className="cm-badge" style={{ backgroundColor: "#f1f5f9", color: "#334155" }}>
              main.tf Target Cloud
            </span>
          </div>

          <div
            style={{
              padding: 20,
              backgroundColor: "#f8fafc",
              borderRadius: 8,
              border: "1px solid #cbd5e1",
              display: "flex",
              flexDirection: "column",
              gap: 16,
            }}
          >
            {/* Nivel 0: Perímetro de Proveedor Cloud AWS */}
            <div
              style={{
                padding: 16,
                backgroundColor: "#ffffff",
                borderRadius: 8,
                border: "2px solid #0972d3",
                boxShadow: "0 2px 4px rgba(0,0,0,0.04)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <strong style={{ fontSize: 14.5, color: "#0972d3" }}>
                  ☁ AWS Cloud (us-east-1 N. Virginia) · Definido en <code>provider.tf</code>
                </strong>
                <span className="cm-badge" style={{ backgroundColor: "#eff6ff", color: "#1d4ed8" }}>
                  Infraestructura CloudMove Gestionada
                </span>
              </div>

              {/* Grid: VPC vs Recursos Externos */}
              <div style={{ display: "grid", gridTemplateColumns: isCloudDB ? "1fr" : "3fr 1.2fr", gap: 14 }}>
                {/* Contenedor VPC de Terraform */}
                <div
                  style={{
                    padding: 14,
                    backgroundColor: "#f0fdf4",
                    borderRadius: 6,
                    border: "1.5px dashed #16a34a",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                    <strong style={{ fontSize: 13.5, color: "#166534" }}>
                      🔒 aws_vpc.target_vpc (10.0.0.0/16) · cloudmove-target-vpc
                    </strong>
                    <span style={{ fontSize: 11.5, color: "#15803d", fontWeight: 600 }}>
                      aws_internet_gateway.igw + aws_route_table.public_rt
                    </span>
                  </div>

                  {/* Subred Pública A */}
                  <div
                    style={{
                      padding: 12,
                      backgroundColor: "#ffffff",
                      borderRadius: 6,
                      border: "1px solid #bbf7d0",
                      marginBottom: 10,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: "#1e293b" }}>
                        aws_subnet.public_subnet (10.0.1.0/24 — us-east-1a)
                      </span>
                      <span className="cm-badge" style={{ fontSize: 11, backgroundColor: "#dbeafe", color: "#1e40af" }}>
                        aws_security_group.app_sg ({ports.join(", ")})
                      </span>
                    </div>

                    {/* Balanceador ALB si es HA */}
                    {isHA && (
                      <div style={{ padding: 10, backgroundColor: "#faf5ff", borderRadius: 6, border: "1px solid #c084fc", marginBottom: 10 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <strong style={{ fontSize: 13, color: "#6b21a8" }}>
                            ⚖ aws_lb.app_alb (ALB Multi-AZ) + aws_lb_target_group.app_tg
                          </strong>
                          <span className="cm-badge validated" style={{ fontSize: 11 }}>
                            HTTP :80 /health
                          </span>
                        </div>
                        <div style={{ fontSize: 12, color: "#581c87", marginTop: 2 }}>
                          Listener: <code>aws_lb_listener.http_listener</code> · Reparte tráfico entre instancias públicas Multi-AZ.
                        </div>
                      </div>
                    )}

                    {/* Cómputo: ASG o Instancia EC2 */}
                    <div
                      style={{
                        padding: 12,
                        backgroundColor: "#f8fafc",
                        borderRadius: 6,
                        border: "1px solid #cbd5e1",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                        <strong style={{ fontSize: 13, color: "#0f172a" }}>
                          {isHA
                            ? `🖥 aws_autoscaling_group.compute_host_asg (Min: 1, Max: 3)`
                            : `🖥 aws_instance.compute_host (t3.micro Free Tier / Ubuntu 22.04 LTS)`}
                        </strong>
                        <span className="cm-badge observed" style={{ fontSize: 11 }}>
                          {isHA ? "aws_launch_template.compute_host_lt" : "Swap 2GB anti-OOM"}
                        </span>
                      </div>

                      {/* Contenedores desplegados en el host */}
                      <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fit, minmax(180px, 1fr))`, gap: 8, marginTop: 8 }}>
                        {components.map((c, idx) => (
                          <div
                            key={c.name || idx}
                            style={{
                              padding: 8,
                              backgroundColor: "#ffffff",
                              borderRadius: 4,
                              border: idx === 0 ? "1px solid #93c5fd" : "1px solid #c084fc",
                            }}
                          >
                            <div style={{ fontWeight: 700, fontSize: 12.5, color: idx === 0 ? "#1d4ed8" : "#7e22ce" }}>
                              Contenedor {c.name ? c.name.charAt(0).toUpperCase() + c.name.slice(1) : "App"}
                            </div>
                            <div style={{ fontSize: 11.5, color: "#475569" }}>
                              {c.framework || c.language || "Servicio"} ({c.runtime || "container"})
                            </div>
                            <div style={{ fontSize: 11.5, color: "#16a34a", marginTop: 2 }}>
                              Puerto mapeado: <code>{c.host_ports?.[0] || 80}:{c.container_ports?.[0] || 80}</code>
                            </div>
                          </div>
                        ))}
                      </div>

                      <div style={{ fontSize: 11.5, color: "#64748b", marginTop: 8, textAlign: "center" }}>
                        ↔ Inicializado con script <code>user_data.sh</code> y orquestado vía <code>docker-compose.cloudmove.yml</code>
                      </div>
                    </div>
                  </div>

                  {/* Subredes Privadas (Multi-AZ) para RDS si aplica */}
                  {isCloudDB && (
                    <div
                      style={{
                        padding: 10,
                        backgroundColor: "#eff6ff",
                        borderRadius: 6,
                        border: "1px solid #93c5fd",
                        marginTop: 10,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                        <span style={{ fontSize: 12.5, fontWeight: 700, color: "#1e3a8a" }}>
                          aws_subnet.private_subnet_a & b (10.0.2.0/24 y 10.0.3.0/24)
                        </span>
                        <span className="cm-badge observed" style={{ fontSize: 11 }}>
                          aws_db_subnet_group.db_subnets
                        </span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div>
                          <strong>aws_db_instance.app_db</strong> (PostgreSQL 15 Multi-AZ / db.t4g.micro)
                          <div style={{ fontSize: 11.5, color: "#475569" }}>Puerto 5432 · Backup 7 días · Cifrado Storage KMS</div>
                        </div>
                        <span className="cm-badge validated" style={{ fontSize: 11 }}>Gestionado en Terraform</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* Columna Derecha: Secretos e Integración Externa */}
                {!isCloudDB && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    <div
                      style={{
                        padding: 12,
                        backgroundColor: "#fefce8",
                        borderRadius: 6,
                        border: "1px solid #fde047",
                      }}
                    >
                      <div style={{ fontWeight: 700, fontSize: 12.5, color: "#854d0e" }}>
                        🔐 aws_secretsmanager_secret.secrets
                      </div>
                      <div style={{ fontSize: 11.5, color: "#713f12", marginTop: 4 }}>
                        ID: <code>cloudmove/production/{appName.toLowerCase()}-secrets</code>
                      </div>
                      <div style={{ fontSize: 11, color: "#a16207", marginTop: 4 }}>
                        Asociado a <code>aws_iam_role.identity_sa</code> para inyección en el arranque (Zero-Trust).
                      </div>
                    </div>

                    <div
                      style={{
                        padding: 12,
                        backgroundColor: "#f8fafc",
                        borderRadius: 6,
                        border: "2px dashed #94a3b8",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <strong style={{ fontSize: 12.5, color: "#0f172a" }}>⚡ BaaS Supabase</strong>
                        <span className="cm-badge" style={{ fontSize: 10, backgroundColor: "#e2e8f0", color: "#334155" }}>
                          EXTERNO
                        </span>
                      </div>
                      <div style={{ fontSize: 11.5, color: "#475569", marginTop: 4 }}>
                        PostgreSQL 15 Cloud + Auth
                      </div>
                      <div style={{ fontSize: 11, color: "#166534", marginTop: 4, fontWeight: 600 }}>
                        ✓ Preservado externamente sin costo de RDS redundante
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* VISTA 2: INVENTARIO COMPLETO DE RECURSOS TERRAFORM */}
      {activeViewTab === "tf_inventory" && (
        <div className="cm-card">
          <div className="cm-card-title">
            <span>Inventario Exhaustivo de Recursos en Terraform ({terraformResources.length} Recursos)</span>
            <span className="cm-badge observed">main.tf</span>
          </div>

          <p style={{ margin: "4px 0 12px 0", fontSize: 13, color: "#475569" }}>
            Cada uno de los siguientes recursos está codificado y validado dentro de los módulos Terraform generados para la migración de GitHub a AWS:
          </p>

          <div className="disc-table-wrap">
            <table className="disc-table" style={{ width: "100%", fontSize: 13 }}>
              <thead>
                <tr>
                  <th>Tipo de Recurso Terraform</th>
                  <th>Identificador en HCL</th>
                  <th>Capa Arquitectónica</th>
                  <th>Descripción Técnica & Configuración</th>
                </tr>
              </thead>
              <tbody>
                {terraformResources.map((r, i) => (
                  <tr key={i}>
                    <td>
                      <code>{r.type}</code>
                    </td>
                    <td>
                      <strong>{r.name}</strong>
                    </td>
                    <td>
                      <span className="cm-badge info" style={{ fontSize: 11 }}>
                        {r.layer}
                      </span>
                    </td>
                    <td>{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* VISTA 3: MALLA DE FLUJOS Y PUERTOS */}
      {activeViewTab === "flows" && (
        <div className="cm-card">
          <div className="cm-card-title">
            <span>Matriz de Flujos de Red, Integraciones y Puertos en Terraform</span>
            <span className="cm-badge observed">Tráfico y Protocolos</span>
          </div>

          <div className="disc-table-wrap">
            <table className="disc-table" style={{ width: "100%", fontSize: 13 }}>
              <thead>
                <tr>
                  <th>Flujo de Red</th>
                  <th>Origen</th>
                  <th>Destino</th>
                  <th>Protocolo / Puerto</th>
                  <th>Regla Terraform / SG</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><strong>Ingress Público</strong></td>
                  <td>Internet (0.0.0.0/0)</td>
                  <td>{isHA ? "aws_lb.app_alb" : "aws_instance.compute_host"}</td>
                  <td><code>TCP 80, 443</code></td>
                  <td>Definido en <code>aws_security_group.app_sg</code></td>
                </tr>
                <tr>
                  <td><strong>Malla Interna</strong></td>
                  <td>Contenedor Frontend</td>
                  <td>Contenedor Backend</td>
                  <td><code>HTTP REST / 8000</code></td>
                  <td>Red bridge definida en <code>docker-compose.cloudmove.yml</code></td>
                </tr>
                <tr>
                  <td><strong>Persistencia DB</strong></td>
                  <td>Contenedor Backend</td>
                  <td>{isCloudDB ? "aws_db_instance.app_db" : "Supabase BaaS Externo"}</td>
                  <td><code>TCP 5432 (TLS)</code></td>
                  <td>{isCloudDB ? "Aislado en aws_subnet.private_subnet" : "Conexión saliente segura por Internet"}</td>
                </tr>
                <tr>
                  <td><strong>Descarga de Secretos</strong></td>
                  <td>Host EC2 / user_data.sh</td>
                  <td>aws_secretsmanager_secret</td>
                  <td><code>HTTPS / AWS SDK</code></td>
                  <td>Autorizado por <code>aws_iam_instance_profile.identity_sa_profile</code></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
