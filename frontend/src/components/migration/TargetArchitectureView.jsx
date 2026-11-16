import React, { useState, useMemo } from "react";
import ArchifyDiagramRenderer from "../architecture/ArchifyDiagramRenderer";
import {
  AwsContainer,
  AwsKeyValuePairs,
  AwsTabs,
  AwsStatusIndicator,
} from "../cloudscape/AwsPrimitives";

function sanitizeWorkloadName(rawName) {
  const s = String(rawName || "").trim();
  if (!s) return "Carga de Trabajo AWS";
  // Mask any underlying Docker container hex ID or internal host reference
  if (/^[0-9a-f]{12}(-live-os)?$/i.test(s) || s.includes("6dbda7b91dcd") || s.includes("60b8ba9903a7") || s.includes("cloudmove-server")) {
    return "Servidor Objetivo (SO / VM)";
  }
  return s;
}

export default function TargetArchitectureView({ job }) {
  const [activeViewTab, setActiveViewTab] = useState("diagram"); // "diagram" | "tf_inventory" | "flows"

  const isVmCase = job?.use_case === "vm_image";
  const srcEnv = job?.source_environment || {};
  const appName = sanitizeWorkloadName(
    srcEnv.app_name || srcEnv.name || job?.name || "Carga de Trabajo AWS"
  );
  const slug = String(appName)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "target_workload";

  const decisions =
    job?.source_config?.user_decisions ||
    srcEnv.user_decisions ||
    srcEnv.transformation_catalog?.applied_decisions ||
    job?.user_decisions ||
    job?.decisions ||
    {};

  const compChoice = decisions.compute_architecture || "single_instance_containerized";
  const vmComputeChoice = decisions.compute_provisioning_mode || "autonomous_cloud_init";
  const isHA = isVmCase
    ? vmComputeChoice === "ha_launch_template_asg"
    : compChoice === "ha_asg_alb_containerized" || compChoice === "ha_alb_asg";

  const ebsChoice = decisions.ebs_storage_sizing || "aws_academy_30gb";
  const rawDiskGib = Number(srcEnv.total_provisioned_gib || srcEnv.disks?.[0]?.size_gib || 50);
  const skipExtraEbs = isVmCase && ebsChoice === "aws_academy_root_only_30gb";
  const provEbsGib =
    ebsChoice === "aws_academy_max_100gb"
      ? Math.min(100, rawDiskGib)
      : ebsChoice === "full_physical_capacity"
      ? rawDiskGib
      : Math.min(30, rawDiskGib);
  const rootVolGib =
    ebsChoice === "aws_academy_max_100gb"
      ? 50
      : ebsChoice === "full_physical_capacity"
      ? Math.min(500, rawDiskGib)
      : 30;

  const sizingProfile = decisions.instance_sizing_profile || "free_tier_t3_micro";
  const vmInstanceType =
    sizingProfile === "balanced_t3_medium"
      ? "t3.medium"
      : sizingProfile === "host_matched_t3_xlarge"
      ? "t3.xlarge"
      : "t3.micro";

  const portsPolicy = decisions.security_group_ports_policy || "curated_deduplicated_ports";

  const isCloudDB = Object.entries(decisions).some(
    ([k, v]) =>
      (k.includes("database") || k.includes("supabase") || k.includes("dep:")) &&
      v === "provision_cloud_db"
  );

  const components = isVmCase
    ? [
        {
          name: "os-portal-service",
          tier: "portal",
          framework: `Portal de SO (${srcEnv.os?.distro || "Linux"})`,
          container_ports: [3000],
          host_ports: [3000],
        },
        {
          name: "os-telemetry-api",
          tier: "api",
          framework: `Servicios systemd (${(srcEnv.running_processes || []).length || 12} procesos)`,
          container_ports: [8000],
          host_ports: [8000],
        },
      ]
    : srcEnv.components || [
        { name: "frontend", tier: "frontend", framework: "React / Nginx", container_ports: [80], host_ports: [3000] },
        { name: "backend", tier: "backend", framework: "FastAPI / Python", container_ports: [8000], host_ports: [8000] },
      ];

  const rawVmPorts = (srcEnv.listening_ports || [80, 443, 3000, 8000]).filter(
    (p) => Number(p) !== 22 && Number(p) < 32768
  );
  const ports = isVmCase
    ? portsPolicy === "strict_web_ssh_only"
      ? [22, 80, 443, 3000, 8000]
      : [22, ...Array.from(new Set([80, 443, 3000, 8000, ...rawVmPorts]))].slice(0, 12)
    : srcEnv.exposed_ports || [80, 443, 3000, 8000];

  const terraformResources = isVmCase
    ? [
        { type: "aws_vpc", name: "target_vpc", layer: "Red y Aislamiento", desc: "VPC aislada 10.0.0.0/16 con DNS hostnames y DNS support habilitados" },
        { type: "aws_internet_gateway", name: "igw", layer: "Conectividad Exterior", desc: "Internet Gateway público asociado a aws_vpc.target_vpc" },
        { type: "aws_subnet", name: "public_subnet", layer: "Subred Pública A", desc: "10.0.1.0/24 (us-east-1a) con asignación de IPv4 pública" },
        { type: "aws_subnet", name: "public_subnet_b", layer: "Subred Pública B", desc: "10.0.4.0/24 (us-east-1b) para redundancia Multi-AZ" },
        { type: "aws_subnet", name: "private_subnet_a", layer: "Subred Privada A", desc: "10.0.2.0/24 (us-east-1a) para aislamiento interno" },
        { type: "aws_subnet", name: "private_subnet_b", layer: "Subred Privada B", desc: "10.0.3.0/24 (us-east-1b) para aislamiento interno" },
        { type: "aws_route_table", name: "public_rt", layer: "Enrutamiento", desc: "Tabla de rutas 0.0.0.0/0 hacia aws_internet_gateway.igw" },
        { type: "aws_security_group", name: "app_sg", layer: "Perímetro de Seguridad", desc: `Security Group deduplicado en puertos TCP: ${ports.join(", ")}` },
        ...(isHA
          ? [
              { type: "aws_lb", name: "app_alb", layer: "Balanceo de Carga", desc: "Application Load Balancer Multi-AZ" },
              { type: "aws_autoscaling_group", name: `vm_${slug}_asg`, layer: "Auto Scaling", desc: `Auto Scaling Group Multi-AZ (${vmInstanceType})` },
            ]
          : []),
        { type: "aws_instance", name: `vm_${slug}`, layer: "Cómputo EC2", desc: `Instancia EC2 (${vmInstanceType} · ${srcEnv.boot_mode || "UEFI"}) con disco raíz ${rootVolGib} GiB gp3 y user_data.sh` },
        ...(!skipExtraEbs
          ? [
              {
                type: "aws_ebs_volume",
                name: `disk_${slug}_1`,
                layer: "Almacenamiento EBS",
                desc: `Volumen EBS gp3 cifrado de ${provEbsGib} GiB adjunto a la instancia`,
              },
            ]
          : []),
      ]
    : [
        { type: "aws_vpc", name: "target_vpc", layer: "Red y Aislamiento", desc: "VPC aislada 10.0.0.0/16 con DNS hostnames y DNS support habilitados" },
        { type: "aws_internet_gateway", name: "igw", layer: "Conectividad Exterior", desc: "Internet Gateway público asociado a la VPC" },
        { type: "aws_subnet", name: "public_subnet", layer: "Subred Pública A", desc: "10.0.1.0/24 (us-east-1a) con IPv4 pública" },
        { type: "aws_subnet", name: "public_subnet_b", layer: "Subred Pública B", desc: "10.0.4.0/24 (us-east-1b) Multi-AZ" },
        { type: "aws_subnet", name: "private_subnet_a", layer: "Subred Privada A", desc: "10.0.2.0/24 (us-east-1a) para capa de datos" },
        { type: "aws_subnet", name: "private_subnet_b", layer: "Subred Privada B", desc: "10.0.3.0/24 (us-east-1b) para alta disponibilidad de datos" },
        { type: "aws_route_table", name: "public_rt", layer: "Enrutamiento", desc: "Tabla de rutas 0.0.0.0/0 hacia aws_internet_gateway.igw" },
        { type: "aws_security_group", name: "app_sg", layer: "Perímetro de Seguridad", desc: `Security Group con reglas ingress: ${ports.join(", ")}` },
        ...(isHA
          ? [
              { type: "aws_lb", name: "app_alb", layer: "Balanceo de Carga", desc: "Application Load Balancer Layer 7 Multi-AZ" },
              { type: "aws_autoscaling_group", name: "compute_host_asg", layer: "Cómputo Administrado", desc: "Auto Scaling Group Multi-AZ (Min: 1, Max: 3)" },
            ]
          : [
              { type: "aws_instance", name: "compute_host", layer: "Cómputo Administrado", desc: "Instancia EC2 Ubuntu 22.04 LTS con Docker Compose y Swap 2GB" },
            ]),
        { type: "aws_secretsmanager_secret", name: "secrets", layer: "Gestión de Secretos", desc: `Secret Manager cifrado KMS para ${appName}` },
        ...(isCloudDB
          ? [
              { type: "aws_db_instance", name: "app_db", layer: "Base de Datos", desc: "Amazon RDS PostgreSQL 15 (db.t4g.micro, Multi-AZ, cifrado KMS)" },
            ]
          : [
              { type: "external_service", name: "external_db", layer: "Persistencia", desc: "Base de datos PostgreSQL / PostGIS en contenedor o servicio externo" },
            ]),
      ];

  // Dynamic Archify Diagram Model built from selected Terraform decisions
  const archifyModel = useMemo(() => {
    const computeLabel = isHA
      ? isVmCase
        ? `aws_autoscaling_group.vm_${slug}`
        : "aws_autoscaling_group.compute"
      : isVmCase
      ? `aws_instance.vm_${slug}`
      : "aws_instance.compute_host";

    const computeSub = isHA
      ? `ALB + ASG Multi-AZ (${isVmCase ? vmInstanceType : "t3.micro"})`
      : isVmCase
      ? `${vmInstanceType} · Raíz ${rootVolGib} GiB gp3`
      : "t3.micro · Ubuntu 22.04 + Docker";

    const storageNode = isVmCase
      ? {
          id: "storage_node",
          type: "database",
          label: skipExtraEbs ? "root_block_device (gp3)" : `aws_ebs_volume.disk_1`,
          sublabel: skipExtraEbs
            ? `Solo Raíz ${rootVolGib} GiB gp3 Cifrado`
            : `Volumen EBS ${provEbsGib} GiB gp3 Cifrado`,
          pos: [565, 345],
          size: [176, 62],
        }
      : {
          id: "storage_node",
          type: "database",
          label: isCloudDB ? "aws_db_instance.app_db" : "Contenedor PostGIS / DB",
          sublabel: isCloudDB
            ? "RDS PostgreSQL 15 Multi-AZ :5432"
            : "PostgreSQL / PostGIS :5432",
          pos: [565, 345],
          size: [176, 62],
        };

    const securityAuxNode = isHA
      ? {
          id: "aux_node",
          type: "cloud",
          label: "aws_lb.app_alb",
          sublabel: "ALB Layer 7 Multi-AZ :80/:443",
          pos: [290, 345],
          size: [164, 62],
        }
      : {
          id: "aux_node",
          type: "security",
          label: isVmCase ? "cloud_init (user_data)" : "aws_secretsmanager",
          sublabel: isVmCase ? "Rehidratación systemd y red" : "Secretos KMS + IAM Profile",
          pos: [290, 345],
          size: [164, 62],
        };

    const comps = [
      {
        id: "clients",
        type: "external",
        label: "Usuarios y Operadores",
        sublabel: `HTTP :3000 / API :8000 / SSH :22`,
        pos: [36, 205],
        size: [158, 62],
      },
      {
        id: "igw",
        type: "cloud",
        label: "aws_internet_gateway.igw",
        sublabel: "public_rt 0.0.0.0/0",
        pos: [290, 65],
        size: [164, 62],
      },
      {
        id: "sg",
        type: "security",
        label: "aws_security_group.app_sg",
        sublabel: `Puertos: ${ports.slice(0, 5).join(", ")}`,
        pos: [290, 205],
        size: [164, 62],
      },
      securityAuxNode,
      {
        id: "subnet_net",
        type: "cloud",
        label: "aws_subnet.public_subnet",
        sublabel: "10.0.1.0/24 (us-east-1a/1b)",
        pos: [565, 65],
        size: [176, 62],
      },
      {
        id: "compute_main",
        type: "backend",
        label: computeLabel,
        sublabel: computeSub,
        pos: [565, 205],
        size: [176, 62],
      },
      storageNode,
      {
        id: "workload_tier",
        type: "messagebus",
        label: components[0]?.name || "frontend-service",
        sublabel: `${components[0]?.framework || "Web"} :${components[0]?.host_ports?.[0] || 3000}`,
        pos: [845, 135],
        size: [172, 62],
      },
      {
        id: "api_tier",
        type: "messagebus",
        label: components[1]?.name || "backend-api",
        sublabel: `${components[1]?.framework || "API"} :${components[1]?.host_ports?.[0] || 8000}`,
        pos: [845, 275],
        size: [172, 62],
      },
    ];

    return {
      schema_version: 1,
      diagram_type: "architecture",
      meta: {
        title: `Visualización de Recursos Terraform de ${appName} · main.tf Target Cloud (AWS)`,
        locale: "es",
        quality_profile: "showcase",
      },
      components: comps,
      boundaries: [
        {
          kind: "region",
          label: "aws_vpc.target_vpc (10.0.0.0/16 · AWS us-east-1)",
          wraps: [
            "igw",
            "sg",
            "aux_node",
            "subnet_net",
            "compute_main",
            "storage_node",
            "workload_tier",
            "api_tier",
          ],
          pad: 22,
        },
        {
          kind: "security-group",
          label: isHA
            ? "Grupo Multi-AZ (us-east-1a / us-east-1b · Alta Disponibilidad)"
            : "Zona de Cómputo y Persistencia Aislada (us-east-1a)",
          wraps: ["subnet_net", "compute_main", "storage_node", "workload_tier", "api_tier"],
          pad: 14,
        },
      ],
      connections: [
        { from: "clients", to: "sg", label: `TCP :${ports.slice(0, 3).join("/")}`, variant: "emphasis" },
        { from: "igw", to: "sg", label: "Ruta IGW" },
        { from: "sg", to: "compute_main", label: "Ingress SG", variant: "security" },
        { from: "aux_node", to: "compute_main", label: isHA ? "ALB Target" : "Bootstrap", variant: "dashed" },
        { from: "subnet_net", to: "compute_main", label: "IP Pública" },
        { from: "compute_main", to: "storage_node", label: isVmCase ? "EBS gp3" : "SQL :5432", variant: "security" },
        { from: "compute_main", to: "workload_tier", label: "HTTP :3000", variant: "emphasis" },
        { from: "compute_main", to: "api_tier", label: "API :8000", variant: "emphasis" },
      ],
      cards: [
        {
          dot: "cyan",
          title: "1. Red y Perímetro en main.tf",
          items: [
            "aws_vpc.target_vpc (10.0.0.0/16) con DNS hostnames y soporte Multi-AZ",
            "aws_internet_gateway.igw y tabla de rutas aws_route_table.public_rt",
            `aws_security_group.app_sg con ${ports.length} puertos autorizados`,
          ],
        },
        {
          dot: "emerald",
          title: "2. Cómputo y Servicios Seleccionados",
          items: [
            isHA
              ? `Alta disponibilidad con aws_lb.app_alb y Auto Scaling Group`
              : `Instancia ${computeLabel} (${computeSub})`,
            `Servicios activos: ${components.map((c) => c.name).join(" + ")}`,
            "Sincronización automática de IP pública vía IMDSv2 en cada arranque",
          ],
        },
        {
          dot: "amber",
          title: "3. Almacenamiento y Persistencia",
          items: [
            isVmCase
              ? skipExtraEbs
                ? `Disco raíz unificado de ${rootVolGib} GiB gp3 cifrado`
                : `Disco raíz ${rootVolGib} GiB + aws_ebs_volume de ${provEbsGib} GiB gp3`
              : isCloudDB
              ? "Base de datos gestionada aws_db_instance (Amazon RDS PostgreSQL 15)"
              : "Persistencia PostgreSQL / PostGIS integrada con volumen persistente",
            `Total de recursos declarados en HCL: ${terraformResources.length}`,
          ],
        },
      ],
    };
  }, [
    appName,
    slug,
    isHA,
    isVmCase,
    vmInstanceType,
    rootVolGib,
    skipExtraEbs,
    provEbsGib,
    isCloudDB,
    ports,
    components,
    terraformResources.length,
  ]);

  if (!job) {
    return (
      <AwsContainer
        title="Sin arquitectura objetivo activa"
        description="Selecciona o inicia un plan de migración para sintetizar el código Terraform HCL y renderizar el diagrama de arquitectura con Archify."
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <AwsContainer
        title={`Visualización de Recursos Terraform de ${appName}`}
        description="Diagrama interactivo generado con Archify a partir de los recursos declarados en main.tf, variables.tf y user_data.sh según tu selección de arquitectura."
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span className="cm-badge aws">main.tf Target Cloud · AWS</span>
            <span className="cm-badge observed">{terraformResources.length} recursos HCL</span>
          </div>
        }
      >
        <AwsKeyValuePairs
          columns={4}
          items={[
            {
              label: "VPC y Subredes (main.tf)",
              value: "aws_vpc (10.0.0.0/16)",
              subtext: "4 subredes Multi-AZ (2 públicas + 2 privadas)",
            },
            {
              label: "Arquitectura de cómputo",
              value: isHA
                ? "ALB + Auto Scaling"
                : isVmCase
                ? `aws_instance (${vmInstanceType})`
                : "aws_instance (t3.micro)",
              subtext: isHA
                ? "Balanceador Layer 7 + 1-3 instancias"
                : `Raíz ${rootVolGib} GiB gp3 + user_data.sh`,
            },
            {
              label: isVmCase ? "Almacenamiento EBS" : "Capa de base de datos",
              value: isVmCase
                ? skipExtraEbs
                  ? `Raíz ${rootVolGib} GiB gp3`
                  : `aws_ebs_volume (${provEbsGib} GiB)`
                : isCloudDB
                ? "Amazon RDS Multi-AZ"
                : "PostgreSQL / PostGIS",
              subtext: "Cifrado habilitado y compatible con cuota AWS Academy",
            },
            {
              label: "Seguridad y puertos",
              value: `app_sg (${ports.length} puertos)`,
              subtext: `TCP: ${ports.slice(0, 6).join(", ")}`,
            },
          ]}
        />

        <AwsTabs
          activeTabId={activeViewTab}
          onTabChange={setActiveViewTab}
          tabs={[
            {
              id: "diagram",
              label: "Diagrama de arquitectura (Archify)",
              badge: "Interactivo",
            },
            {
              id: "tf_inventory",
              label: "Inventario de recursos Terraform",
              count: terraformResources.length,
            },
            {
              id: "flows",
              label: "Malla de tráfico y puertos",
              count: ports.length,
            },
          ]}
        />

        {activeViewTab === "diagram" && (
          <ArchifyDiagramRenderer
            model={archifyModel}
            showStandaloneLink={true}
            standaloneUrl="/archify-aws-cmir.html"
          />
        )}

        {activeViewTab === "tf_inventory" && (
          <div className="cm-table-wrap">
            <table className="cm-table">
              <thead>
                <tr>
                  <th>Tipo de recurso HCL</th>
                  <th>Identificador en main.tf</th>
                  <th>Capa de arquitectura</th>
                  <th>Configuración sintetizada</th>
                </tr>
              </thead>
              <tbody>
                {terraformResources.map((r, idx) => (
                  <tr key={`${r.type}.${r.name}.${idx}`}>
                    <td>
                      <code>{r.type}</code>
                    </td>
                    <td>
                      <strong>{r.name}</strong>
                    </td>
                    <td>
                      <span className="cm-badge info">{r.layer}</span>
                    </td>
                    <td>{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {activeViewTab === "flows" && (
          <div className="cm-table-wrap">
            <table className="cm-table">
              <thead>
                <tr>
                  <th>Origen</th>
                  <th>Destino</th>
                  <th>Protocolo y puerto</th>
                  <th>Regla de seguridad en Terraform</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Internet (0.0.0.0/0)</td>
                  <td>
                    <code>{isHA ? "aws_lb.app_alb" : "aws_instance"}</code>
                  </td>
                  <td>
                    <strong>TCP :80 / :443 / :3000</strong>
                  </td>
                  <td>
                    <AwsStatusIndicator type="success">
                      Ingress permitido en aws_security_group.app_sg
                    </AwsStatusIndicator>
                  </td>
                </tr>
                <tr>
                  <td>Frontend Web (:3000)</td>
                  <td>Backend API (:8000)</td>
                  <td>
                    <strong>HTTP / REST :8000</strong>
                  </td>
                  <td>
                    <AwsStatusIndicator type="success">
                      Sincronizado vía IMDSv2 (sync_public_ip.sh)
                    </AwsStatusIndicator>
                  </td>
                </tr>
                <tr>
                  <td>Backend API (:8000)</td>
                  <td>
                    <code>{isCloudDB ? "aws_db_instance.app_db" : "PostgreSQL / EBS"}</code>
                  </td>
                  <td>
                    <strong>{isVmCase ? "NVMe Block I/O" : "TCP :5432"}</strong>
                  </td>
                  <td>
                    <AwsStatusIndicator type="success">
                      Tráfico interno dentro de aws_vpc.target_vpc
                    </AwsStatusIndicator>
                  </td>
                </tr>
                <tr>
                  <td>Operador SSH</td>
                  <td>
                    <code>aws_instance</code>
                  </td>
                  <td>
                    <strong>SSH TCP :22</strong>
                  </td>
                  <td>
                    <AwsStatusIndicator type="info">
                      Regla única deduplicada en aws_security_group.app_sg
                    </AwsStatusIndicator>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </AwsContainer>
    </div>
  );
}
