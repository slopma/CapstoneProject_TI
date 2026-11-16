import React, { useState, useMemo } from "react";
import ArchifyDiagramRenderer from "../architecture/ArchifyDiagramRenderer";
import { AwsStatusIndicator } from "../cloudscape/AwsPrimitives";

/**
 * Reusable Contextual Help Trigger (`?`) & Deep Technical Detail Modal.
 * Keeps the main flow executive, scannable, and clutter-free until the user asks for depth.
 */
export function HelpTooltipButton({ label = "Detalle técnico", onClick, ariaLabel }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="cm-help-pill-btn"
      aria-label={ariaLabel || label}
      title={label}
    >
      <span className="cm-help-circle" aria-hidden="true">?</span>
      <span>{label}</span>
    </button>
  );
}

export function ContextualTechnicalModal({
  isOpen,
  onClose,
  title,
  badge,
  whyTransformed,
  ghEvidence,
  options = [],
  selectedOptionId,
  customSections = [],
}) {
  if (!isOpen) return null;

  const dbAnalysis = ghEvidence?.database_analysis || null;
  const rawDetail = String(ghEvidence?.evidence_detail || "");
  const evidenceSegments = rawDetail
    .split(/\s*\|\s*|\s*·\s*/)
    .map((s) => s.trim())
    .filter(Boolean);

  return (
    <div
      className="cm-modal-overlay"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="cm-modal-surface"
        style={{ maxWidth: 740 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cm-modal-dark-header">
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            {badge && <span className="cm-badge aws">{badge}</span>}
            <h3 style={{ margin: 0, fontSize: 15.5, fontWeight: 700, color: "#ffffff" }}>
              {title || "Detalle técnico y arquitectura AWS"}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="cm-modal-close-dark"
            aria-label="Cerrar detalle técnico"
          >
            Cerrar
          </button>
        </div>

        <div className="cm-modal-body-stack">
          {whyTransformed && (
            <div className="cm-card-subtle" style={{ backgroundColor: "#f2f8fd", borderColor: "#a4c9f5" }}>
              <div style={{ fontSize: 12.5, fontWeight: 700, color: "#033160", marginBottom: 4 }}>
                ¿Por qué se transforma hacia AWS?
              </div>
              <div style={{ fontSize: 13, color: "#0f172a", lineHeight: 1.5 }}>{whyTransformed}</div>
            </div>
          )}

          {customSections.map((sec, idx) => (
            <div key={idx} className="cm-card-subtle">
              <div style={{ fontSize: 13, fontWeight: 700, color: "#000716", marginBottom: 4 }}>
                {sec.heading}
              </div>
              <div style={{ fontSize: 13, color: "#414d5c", lineHeight: 1.5 }}>{sec.body}</div>
            </div>
          ))}

          {Array.isArray(ghEvidence?.files) && ghEvidence.files.length > 0 && (
            <div>
              <div style={{ fontSize: 12.5, fontWeight: 700, color: "#16191f", marginBottom: 6 }}>
                Fuentes y manifiestos analizados:
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {ghEvidence.files.map((f, idx) => (
                  <code
                    key={idx}
                    style={{
                      backgroundColor: "#f2f3f3",
                      border: "1px solid #d5dbdb",
                      borderRadius: 4,
                      padding: "2px 6px",
                      fontSize: 12,
                    }}
                  >
                    {f}
                  </code>
                ))}
              </div>
            </div>
          )}

          {dbAnalysis && dbAnalysis.has_backup ? (
            <div className="cm-card-subtle">
              <div style={{ fontWeight: 700, fontSize: 13, color: "#000716", marginBottom: 8 }}>
                Diagnóstico de Base de Datos y Volcado ({dbAnalysis.engine_version})
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                  gap: 8,
                  marginBottom: 10,
                }}
              >
                <div className="cm-card-subtle" style={{ padding: "6px 10px", backgroundColor: "#ffffff" }}>
                  <div className="cm-hint">Archivo Backup</div>
                  <strong><code>{dbAnalysis.backup_file}</code></strong>
                </div>
                <div className="cm-card-subtle" style={{ padding: "6px 10px", backgroundColor: "#ffffff" }}>
                  <div className="cm-hint">Esquema Público</div>
                  <strong>{dbAnalysis.public_tables_count} tablas · {dbAnalysis.public_rows_count} filas</strong>
                </div>
                <div className="cm-card-subtle" style={{ padding: "6px 10px", backgroundColor: "#ffffff" }}>
                  <div className="cm-hint">Total Registros</div>
                  <strong>{dbAnalysis.total_tables_count} tablas · {dbAnalysis.total_rows_count} filas</strong>
                </div>
              </div>
              {Array.isArray(dbAnalysis.extensions) && dbAnalysis.extensions.length > 0 && (
                <div style={{ fontSize: 12.5, color: "#414d5c" }}>
                  <strong>Extensiones requeridas:</strong>{" "}
                  <code>{dbAnalysis.extensions.join(", ")}</code>
                </div>
              )}
            </div>
          ) : (
            evidenceSegments.length > 0 && (
              <div className="cm-card-subtle">
                <div style={{ fontSize: 12.5, fontWeight: 700, color: "#16191f", marginBottom: 6 }}>
                  Evidencia técnica detectada:
                </div>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: "#414d5c", lineHeight: 1.5 }}>
                  {evidenceSegments.map((seg, idx) => (
                    <li key={idx}>{seg}</li>
                  ))}
                </ul>
              </div>
            )
          )}

          {options.length > 0 && (
            <div>
              <div style={{ fontSize: 12.5, fontWeight: 700, color: "#16191f", marginBottom: 6 }}>
                Recursos Terraform HCL por estrategia:
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {options.map((opt) => {
                  const isSelected = opt.id === selectedOptionId;
                  return (
                    <div
                      key={opt.id}
                      style={{
                        padding: "10px 12px",
                        borderRadius: 6,
                        border: isSelected ? "1.5px solid #0972d3" : "1px solid #d5dbdb",
                        backgroundColor: isSelected ? "#f2f8fd" : "#ffffff",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
                        <strong style={{ fontSize: 13, color: "#000716" }}>
                          {opt.label} {isSelected ? "· Activa" : ""}
                        </strong>
                        {opt.cost_estimate && (
                          <span className="cm-badge info" style={{ fontSize: 11.5 }}>
                            {opt.cost_estimate}
                          </span>
                        )}
                      </div>
                      <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#414d5c", lineHeight: 1.45 }}>
                        {opt.description}
                      </p>
                      {Array.isArray(opt.cloud_resources_created) &&
                        opt.cloud_resources_created.length > 0 && (
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                            {opt.cloud_resources_created.map((res, rIdx) => (
                              <code
                                key={rIdx}
                                style={{
                                  fontSize: 11.5,
                                  backgroundColor: "#f8fafc",
                                  border: "1px solid #cbd5e1",
                                  padding: "2px 6px",
                                  borderRadius: 3,
                                  color: "#0f172a",
                                }}
                              >
                                {res}
                              </code>
                            ))}
                          </div>
                        )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Compact executive evidence strip paired with a `?` button for full technical justification.
 */
export function StructuredGithubEvidenceView({
  gh,
  whyTransformed,
  options,
  selectedOptionId,
  itemTitle,
}) {
  const [modalOpen, setModalOpen] = useState(false);
  if (!gh && !whyTransformed) return null;

  const dbAnalysis = gh?.database_analysis || null;
  const filesCount = Array.isArray(gh?.files) ? gh.files.length : 0;

  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 8,
          marginTop: 4,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {dbAnalysis && dbAnalysis.has_backup ? (
            <>
              <span className="cm-badge info" style={{ fontSize: 11.5 }}>
                {dbAnalysis.engine_version}
              </span>
              <span className="cm-badge observed" style={{ fontSize: 11.5 }}>
                {dbAnalysis.public_tables_count} tablas · {dbAnalysis.total_rows_count} registros
              </span>
            </>
          ) : (
            filesCount > 0 && (
              <span className="cm-badge simulated" style={{ fontSize: 11.5 }}>
                {filesCount} fuente(s): {gh.files.slice(0, 2).join(", ")}
                {filesCount > 2 ? "..." : ""}
              </span>
            )
          )}
        </div>

        <HelpTooltipButton
          label="¿Por qué se transforma?"
          ariaLabel={`Ver detalle técnico de ${gh?.title || itemTitle || "componente"}`}
          onClick={() => setModalOpen(true)}
        />
      </div>

      <ContextualTechnicalModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        title={gh?.title || itemTitle}
        badge={gh?.badge || "Detalle Técnico"}
        whyTransformed={whyTransformed}
        ghEvidence={gh}
        options={options}
        selectedOptionId={selectedOptionId}
      />
    </>
  );
}

/**
 * Collapsible Pre-Flight Preventive Checks Accordion.
 * Default collapsed: "N verificaciones aplicadas: Todo OK" with expandable diagnostic cards.
 */
export function PreflightPreventiveChecksBanner({ checks }) {
  const [expanded, setExpanded] = useState(false);

  if (!Array.isArray(checks) || checks.length === 0) return null;

  return (
    <div
      style={{
        backgroundColor: "#ffffff",
        border: "1px solid #d5dbdb",
        borderRadius: 6,
        marginBottom: 12,
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        style={{
          width: "100%",
          background: "transparent",
          border: "none",
          padding: "10px 14px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 8,
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <AwsStatusIndicator type="success">
            <strong>{checks.length} verificaciones aplicadas: Todo OK</strong>
          </AwsStatusIndicator>
          <span style={{ fontSize: 12.5, color: "#545b64" }}>
            Controles preventivos de cuota EBS, puertos e IAM en AWS
          </span>
        </div>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#0972d3" }}>
          {expanded ? "Ocultar detalle ▲" : "Expandir diagnóstico ▾"}
        </span>
      </button>

      {expanded && (
        <div
          style={{
            padding: "10px 14px 12px 14px",
            borderTop: "1px solid #eaeded",
            backgroundColor: "#fafafa",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
            gap: 8,
          }}
        >
          {checks.map((chk) => (
            <div
              key={chk.id}
              style={{
                backgroundColor: "#ffffff",
                border: "1px solid #e9ebed",
                borderRadius: 4,
                padding: "8px 10px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 6, marginBottom: 4 }}>
                <strong style={{ fontSize: 12.5, color: "#16191f" }}>{chk.risk_title}</strong>
                <span className="cm-badge observed" style={{ fontSize: 10.5 }}>
                  {chk.status || "OK"}
                </span>
              </div>
              <div style={{ fontSize: 12, color: "#037f0c", lineHeight: 1.4 }}>
                {chk.prevention_applied}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Interactive Graphical Verifier Modal powered by ArchifyDiagramRenderer.
 */
export default function PlannedCloudStructureGraphModal({
  isOpen,
  onClose,
  catalog,
  decisions,
}) {
  const archifyModel = useMemo(() => {
    if (!catalog) return null;
    const activeDecisions = decisions || catalog.applied_decisions || {};
    const computeChoice =
      activeDecisions["compute_architecture"] ||
      activeDecisions["compute_provisioning_mode"] ||
      "single_instance_containerized";
    const isHaMode =
      computeChoice === "ha_asg_alb_containerized" ||
      computeChoice === "ha_launch_template_asg";
    const isDecoupled = computeChoice === "decoupled_tier_instances";

    const diskChoice =
      activeDecisions["storage_and_build_capacity"] ||
      activeDecisions["ebs_storage_sizing"] ||
      "ebs_30gb_gp3_swap";
    const diskGb = diskChoice.includes("100")
      ? 100
      : diskChoice.includes("50")
      ? 50
      : 30;

    const dbItem = (catalog.items || []).find(
      (it) => it.category === "database_or_external" && it.id.startsWith("dep:")
    );
    const dbDecision = dbItem
      ? activeDecisions[dbItem.id] || dbItem.selected_option_id || dbItem.default_option_id
      : "self_hosted_container";

    const computeTitle = isHaMode
      ? "ALB + EC2 Auto Scaling"
      : isDecoupled
      ? "Instancias EC2 Separadas"
      : "aws_instance.compute_host";
    const dbTitle =
      dbDecision === "transform_to_cloud_managed" || dbDecision === "provision_cloud_db"
        ? "aws_db_instance.app_db (RDS)"
        : dbDecision === "keep_external"
        ? "Servicio BaaS Externo"
        : "PostgreSQL / EBS gp3";

    return {
      schema_version: 1,
      diagram_type: "architecture",
      meta: {
        title: "Topología Objetivo en Amazon Web Services (AWS · main.tf)",
        locale: "es",
        quality_profile: "showcase",
      },
      components: [
        {
          id: "users",
          type: "external",
          label: "Usuarios / Clientes",
          sublabel: "HTTP :3000 / API :8000 / SSH :22",
          pos: [40, 190],
          size: [160, 62],
        },
        {
          id: "igw",
          type: "cloud",
          label: "aws_internet_gateway.igw",
          sublabel: "public_rt 0.0.0.0/0",
          pos: [290, 65],
          size: [170, 62],
        },
        {
          id: "sg",
          type: "security",
          label: "aws_security_group.app_sg",
          sublabel: "Ingress :22, :80, :3000, :8000",
          pos: [290, 190],
          size: [170, 62],
        },
        {
          id: "iam",
          type: "security",
          label: "Secretos y Bootstrap",
          sublabel: "user_data.sh + IMDSv2",
          pos: [290, 315],
          size: [170, 62],
        },
        {
          id: "compute",
          type: "backend",
          label: computeTitle,
          sublabel: isHaMode ? "Multi-AZ ALB + ASG" : `EC2 Ubuntu · ${diskGb} GiB gp3`,
          pos: [565, 130],
          size: [185, 68],
        },
        {
          id: "ebs",
          type: "database",
          label: `Amazon EBS (${diskGb} GiB gp3)`,
          sublabel: "Volumen Cifrado + Swap",
          pos: [565, 275],
          size: [185, 62],
        },
        {
          id: "db",
          type: "messagebus",
          label: dbTitle,
          sublabel:
            dbDecision === "transform_to_cloud_managed" || dbDecision === "provision_cloud_db"
              ? "Subred Privada Multi-AZ :5432"
              : "Datos y Backups Restaurados",
          pos: [835, 190],
          size: [175, 66],
        },
      ],
      boundaries: [
        {
          kind: "region",
          label: "AWS us-east-1 · aws_vpc.target_vpc (10.0.0.0/16)",
          wraps: ["igw", "sg", "iam", "compute", "ebs", "db"],
          pad: 22,
        },
        {
          kind: "security-group",
          label: "Subredes Públicas y Privadas (AZ-a / AZ-b)",
          wraps: ["compute", "ebs", "db"],
          pad: 14,
        },
      ],
      connections: [
        { from: "users", to: "sg", label: "HTTPS / HTTP", variant: "emphasis" },
        { from: "igw", to: "sg", label: "Enrutamiento" },
        { from: "sg", to: "compute", label: "Allow TCP", variant: "security" },
        { from: "iam", to: "compute", label: "User Data", variant: "dashed" },
        { from: "compute", to: "ebs", label: "Block I/O", variant: "security" },
        { from: "compute", to: "db", label: "TCP :5432", variant: "emphasis" },
      ],
      cards: [
        {
          dot: "cyan",
          title: "1. Red y Seguridad AWS",
          items: [
            "aws_vpc.target_vpc (10.0.0.0/16) Multi-AZ",
            "aws_security_group.app_sg con reglas deduplicadas",
          ],
        },
        {
          dot: "emerald",
          title: "2. Cómputo Seleccionado",
          items: [computeTitle, "Sincronización de IP pública vía IMDSv2"],
        },
        {
          dot: "amber",
          title: "3. Almacenamiento y Datos",
          items: [`EBS ${diskGb} GiB gp3 cifrado`, dbTitle],
        },
      ],
    };
  }, [catalog, decisions]);

  if (!isOpen || !catalog || !archifyModel) return null;

  return (
    <div className="cm-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div
        className="cm-modal-surface"
        style={{ maxWidth: 1140 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cm-modal-dark-header">
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span className="cm-badge aws">ARCHIFY AWS TOPOLOGY</span>
            <h3 style={{ margin: 0, fontSize: 15.5, fontWeight: 700, color: "#ffffff" }}>
              Diagrama Interactivo de Recursos Terraform en AWS
            </h3>
          </div>
          <button
            type="button"
            className="cm-modal-close-dark"
            onClick={onClose}
          >
            Cerrar
          </button>
        </div>

        <div style={{ padding: 16, overflowY: "auto", backgroundColor: "#f2f3f3" }}>
          <ArchifyDiagramRenderer
            model={archifyModel}
            defaultTheme="light"
            showStandaloneLink={true}
            standaloneUrl="/archify-aws-cmir.html"
          />
        </div>
      </div>
    </div>
  );
}
