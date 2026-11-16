import React, { useState } from "react";
import PlannedCloudStructureGraphModal, {
  StructuredGithubEvidenceView,
  PreflightPreventiveChecksBanner,
  ContextualTechnicalModal,
  HelpTooltipButton,
} from "./PlannedCloudStructureGraphModal";
import {
  PRIMARY_TRANSFORMATION_IDS,
  summarizeOptionTagline,
} from "./orchestratorConstants";

export default function GithubToCloudTransformationSelector({
  catalog,
  decisions,
  onSelectDecision,
  onApplyToExistingJob = null,
  applyingChanges = false,
  isJobView = false,
}) {
  const [showGraphicalStructureModal, setShowGraphicalStructureModal] = useState(false);
  const [showAdvancedBlocks, setShowAdvancedBlocks] = useState(false);
  const [showHclResources, setShowHclResources] = useState(false);
  const [showSummaryTable, setShowSummaryTable] = useState(false);
  const [showSectionHelp, setShowSectionHelp] = useState(false);

  if (!catalog || !Array.isArray(catalog.items) || catalog.items.length === 0) {
    return null;
  }

  const activeDecisions = decisions || catalog.applied_decisions || {};

  const primaryItems = [];
  const secondaryItems = [];
  catalog.items.forEach((item, idx) => {
    const isPrimary =
      PRIMARY_TRANSFORMATION_IDS.has(item.id) ||
      item.id?.startsWith("dep:") ||
      item.category === "database_or_external" ||
      idx < 3;
    if (isPrimary) primaryItems.push(item);
    else secondaryItems.push(item);
  });

  // Live preview of planned Terraform resources (revealed in accordion)
  const liveResourcesPreview = [
    {
      githubOrigin: "Red Base y Puertos Expuestos",
      decisionLabel: "VPC Multi-AZ aislada + Internet Gateway",
      terraformResource: "aws_vpc.target_vpc + 4x aws_subnet + aws_internet_gateway.igw",
      costEstimate: "$0 USD/mes",
    },
  ];

  catalog.items.forEach((item) => {
    const selectedId = activeDecisions[item.id] || item.selected_option_id || item.default_option_id;
    const chosenOpt =
      (item.options || []).find((o) => o.id === selectedId) || (item.options || [])[0];
    if (chosenOpt) {
      (chosenOpt.cloud_resources_created || []).forEach((resName) => {
        liveResourcesPreview.push({
          githubOrigin: item.github_discovered?.title || item.id,
          decisionLabel: chosenOpt.label,
          terraformResource: resName,
          costEstimate: chosenOpt.cost_estimate || "$0 USD/mes",
        });
      });
    }
  });

  const renderTransformationCard = (item, idx) => {
    const selectedId =
      activeDecisions[item.id] || item.selected_option_id || item.default_option_id;
    const gh = item.github_discovered || {};

    return (
      <div
        key={item.id}
        style={{
          backgroundColor: "#ffffff",
          border: "1px solid #d5dbdb",
          borderRadius: 6,
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
            borderBottom: "1px solid #eaeded",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span className="cm-badge info" style={{ fontSize: 11.5 }}>
              {gh.badge || `Componente #${idx + 1}`}
            </span>
            <strong style={{ fontSize: 14, color: "#000716" }}>
              {gh.title || item.id}
            </strong>
            {gh.subtitle && (
              <span className="cm-hint" style={{ fontSize: 12.5 }}>
                {gh.subtitle}
              </span>
            )}
          </div>

          <StructuredGithubEvidenceView
            gh={gh}
            whyTransformed={item.why_transformed}
            options={item.options}
            selectedOptionId={selectedId}
            itemTitle={gh.title || item.id}
          />
        </div>

        <div className="cm-choice-cards-grid">
          {(item.options || []).map((opt) => {
            const isChosen = selectedId === opt.id;
            const tagline = summarizeOptionTagline(opt.summary || opt.description);
            return (
              <label
                key={opt.id}
                className={`cm-choice-card ${isChosen ? "is-selected" : ""}`}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 6, marginBottom: 6 }}>
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 7 }}>
                      <input
                        type="radio"
                        name={`decision-${isJobView ? "job" : "pre"}-${item.id}`}
                        value={opt.id}
                        checked={isChosen}
                        onChange={() => onSelectDecision(item.id, opt.id)}
                        style={{ marginTop: 3, cursor: "pointer" }}
                      />
                      <strong
                        style={{
                          fontSize: 13.5,
                          color: isChosen ? "#0972d3" : "#000716",
                          lineHeight: 1.35,
                        }}
                      >
                        {opt.label}
                      </strong>
                    </div>
                  </div>

                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginLeft: 20, marginBottom: 6 }}>
                    {opt.badge && (
                      <span className={`cm-badge ${isChosen ? "info" : "neutral"}`} style={{ fontSize: 11 }}>
                        {opt.badge}
                      </span>
                    )}
                    {opt.cost_estimate && (
                      <span
                        className={`cm-badge ${opt.cost_estimate.startsWith("$0") ? "observed" : "warning"}`}
                        style={{ fontSize: 11 }}
                      >
                        {opt.cost_estimate}
                      </span>
                    )}
                  </div>

                  {tagline && (
                    <p
                      style={{
                        margin: "0 0 0 20px",
                        fontSize: 12.5,
                        color: "#545b64",
                        lineHeight: 1.4,
                      }}
                    >
                      {tagline}
                    </p>
                  )}
                </div>

                {showHclResources &&
                  Array.isArray(opt.cloud_resources_created) &&
                  opt.cloud_resources_created.length > 0 && (
                    <div
                      style={{
                        marginLeft: 20,
                        padding: "6px 8px",
                        backgroundColor: isChosen ? "#ffffff" : "#fafafa",
                        borderRadius: 4,
                        border: "1px dashed #cbd5e1",
                        fontSize: 11.5,
                        color: "#0f172a",
                      }}
                    >
                      {opt.cloud_resources_created.slice(0, 3).map((cr, crIdx) => (
                        <div key={crIdx} style={{ lineHeight: 1.35 }}>
                          <code>{cr}</code>
                        </div>
                      ))}
                    </div>
                  )}
              </label>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div
      className="cm-card"
      style={{
        marginTop: 14,
        border: "1px solid #d5dbdb",
        backgroundColor: "#fafafa",
        padding: "14px 16px",
        borderRadius: 6,
      }}
    >
      {/* Compact Executive Toolbar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 10,
          marginBottom: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span className="cm-badge aws">ARQUITECTURA AWS</span>
          <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#000716" }}>
            Decisiones de Despliegue ({catalog.items.length})
          </h4>
          <HelpTooltipButton
            label="¿Cómo funciona?"
            onClick={() => setShowSectionHelp(true)}
          />
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <button
            type="button"
            className="cm-btn sm secondary"
            onClick={() => setShowHclResources((v) => !v)}
          >
            {showHclResources ? "Ocultar bloques HCL" : "Vista HCL avanzada"}
          </button>

          <button
            type="button"
            className="cm-btn sm"
            onClick={() => setShowGraphicalStructureModal(true)}
            style={{
              backgroundColor: "#232f3e",
              color: "#ffffff",
              borderColor: "#232f3e",
            }}
          >
            Ver Diagrama Archify AWS
          </button>

          {isJobView && onApplyToExistingJob && (
            <button
              type="button"
              className="cm-btn primary sm"
              onClick={onApplyToExistingJob}
              disabled={applyingChanges}
            >
              {applyingChanges ? "Regenerando..." : "Aplicar y Regenerar Terraform"}
            </button>
          )}
        </div>
      </div>

      {/* Collapsible Pre-Flight Banner ("N verificaciones aplicadas: Todo OK") */}
      <PreflightPreventiveChecksBanner checks={catalog.preflight_preventive_checks} />

      <ContextualTechnicalModal
        isOpen={showSectionHelp}
        onClose={() => setShowSectionHelp(false)}
        title="Selección de Arquitectura y Recursos AWS"
        badge="Guía CloudMove"
        whyTransformed="Cada tarjeta representa una capa detectada en el repositorio o sistema operativo origen. Al seleccionar tu arquitectura destino (por ejemplo Docker Compose en EC2, Amazon RDS o Instancias Separadas), CloudMove sincroniza automáticamente las variables de entorno, reglas de Security Group y módulos Terraform."
        customSections={[
          {
            heading: "Uso de Vista HCL Avanzada",
            body: "Por defecto las tarjetas muestran costo estimado y propósito operativo sin saturar la pantalla con nombres internos de Terraform (`aws_vpc`, `aws_db_instance`). Activa 'Vista HCL avanzada' arriba o el botón '?' de cada componente si deseas auditar el código exacto.",
          },
        ]}
      />

      {/* Modal Verificador Gráfico Archify AWS */}
      <PlannedCloudStructureGraphModal
        isOpen={showGraphicalStructureModal}
        onClose={() => setShowGraphicalStructureModal(false)}
        catalog={catalog}
        decisions={activeDecisions}
      />

      {/* Primary Architecture Decisions */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 12 }}>
        {primaryItems.map((item, idx) => renderTransformationCard(item, idx))}
      </div>

      {/* Progressive Disclosure Accordion for Secondary / Advanced Config Blocks */}
      {secondaryItems.length > 0 && (
        <div className="cm-accordion-shell" style={{ marginBottom: 12 }}>
          <button
            type="button"
            className="cm-accordion-trigger"
            onClick={() => setShowAdvancedBlocks((v) => !v)}
            aria-expanded={showAdvancedBlocks}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <strong style={{ fontSize: 13.5, color: "#000716" }}>
                Configuración avanzada de red, seguridad e identidad ({secondaryItems.length} bloques)
              </strong>
              <span className="cm-badge observed" style={{ fontSize: 11 }}>
                Valores recomendados preseleccionados
              </span>
            </div>
            <span style={{ fontSize: 12.5, fontWeight: 700, color: "#0972d3" }}>
              {showAdvancedBlocks ? "Ocultar ajustes ▲" : "Personalizar ajustes ▾"}
            </span>
          </button>
          {showAdvancedBlocks && (
            <div className="cm-accordion-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {secondaryItems.map((item, idx) =>
                renderTransformationCard(item, primaryItems.length + idx)
              )}
            </div>
          )}
        </div>
      )}

      {/* Collapsible Advanced Terraform HCL Summary Table */}
      <div className="cm-accordion-shell">
        <button
          type="button"
          className="cm-accordion-trigger"
          onClick={() => setShowSummaryTable((v) => !v)}
          aria-expanded={showSummaryTable}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <strong style={{ fontSize: 13.5, color: "#000716" }}>
              Detalle avanzado de recursos Terraform (main.tf)
            </strong>
            <span className="cm-badge info" style={{ fontSize: 11 }}>
              {liveResourcesPreview.length} recursos sincronizados
            </span>
          </div>
          <span style={{ fontSize: 12.5, fontWeight: 700, color: "#0972d3" }}>
            {showSummaryTable ? "Ocultar tabla HCL ▲" : "Ver recursos HCL generados ▾"}
          </span>
        </button>

        {showSummaryTable && (
          <div className="cm-accordion-body" style={{ padding: 0 }}>
            <div className="cm-table-wrap" style={{ border: "none", borderRadius: 0 }}>
              <table className="cm-table" style={{ margin: 0 }}>
                <thead>
                  <tr>
                    <th>Origen Detectado</th>
                    <th>Estrategia Activa</th>
                    <th>Bloque Terraform AWS</th>
                    <th>Costo Est.</th>
                  </tr>
                </thead>
                <tbody>
                  {liveResourcesPreview.map((row, rIdx) => (
                    <tr key={rIdx}>
                      <td style={{ fontSize: 13 }}><strong>{row.githubOrigin}</strong></td>
                      <td style={{ fontSize: 13 }}>{row.decisionLabel}</td>
                      <td style={{ fontSize: 12.5 }}><code>{row.terraformResource}</code></td>
                      <td style={{ fontSize: 12.5 }}>
                        <span className={`cm-badge ${String(row.costEstimate).startsWith("$0") ? "observed" : "warning"}`}>
                          {row.costEstimate}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

