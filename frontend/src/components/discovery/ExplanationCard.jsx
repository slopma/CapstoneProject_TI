import React, { useState } from "react";

const STATE_BADGE_META = {
  observed: {
    label: "Observado (osquery)",
    className: "disc-state-badge is-observed",
    description: "Dato obtenido directamente de una tabla de osquery sin transformación especulativa.",
  },
  derived: {
    label: "Derivado (Determinista)",
    className: "disc-state-badge is-derived",
    description: "Valor calculado matemáticamente a partir de campos observados (ej. bloques × tamaño de bloque, o IP + máscara → CIDR).",
  },
  inferred: {
    label: "Inferido (Con hipótesis)",
    className: "disc-state-badge is-inferred",
    description: "Interpretación sustentada en indicios que requiere confirmación adicional.",
  },
  unavailable: {
    label: "No disponible / No recopilado",
    className: "disc-state-badge is-unavailable",
    description: "Dato ausente en el inventario o que requiere un recolector específico.",
  },
  error: {
    label: "Error de recolección",
    className: "disc-state-badge is-error",
    description: "Falló la consulta o la interpretación del campo.",
  },
};

export function StateBadge({ state }) {
  const key = String(state || "observed").toLowerCase();
  const meta = STATE_BADGE_META[key] || STATE_BADGE_META.observed;
  return (
    <span className={meta.className} title={meta.description}>
      {meta.label}
    </span>
  );
}

export default function ExplanationCard({ explanation, defaultExpanded = false, compact = false }) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (!explanation) return null;

  const detectedStr =
    typeof explanation.detected_value === "object" && explanation.detected_value !== null
      ? JSON.stringify(explanation.detected_value)
      : String(explanation.detected_value ?? "No disponible");

  return (
    <div className={`disc-explanation-card ${compact ? "is-compact" : ""}`}>
      <div className="disc-exp-header">
        <div className="disc-exp-title-group">
          <h4 className="disc-exp-title">{explanation.label}</h4>
          {explanation.formatted_value && (
            <span className="disc-exp-value-pill">{explanation.formatted_value}</span>
          )}
        </div>
        <div className="disc-exp-actions">
          <StateBadge state={explanation.state} />
          <button
            type="button"
            className="disc-exp-toggle-btn"
            onClick={() => setExpanded((prev) => !prev)}
            aria-expanded={expanded}
          >
            {expanded ? "Ocultar análisis" : "Ver análisis y migración"}
          </button>
        </div>
      </div>

      <p className="disc-exp-summary-line">
        <strong>Interpretación:</strong> {explanation.interpretation}
      </p>

      {expanded && (
        <div className="disc-exp-grid">
          <div className="disc-exp-item">
            <span className="disc-exp-key">Qué es</span>
            <p className="disc-exp-text">{explanation.what_is}</p>
          </div>

          <div className="disc-exp-item">
            <span className="disc-exp-key">Valor detectado (Bruto)</span>
            <code className="disc-exp-code">{detectedStr}</code>
          </div>

          <div className="disc-exp-item">
            <span className="disc-exp-key">Por qué importa</span>
            <p className="disc-exp-text">{explanation.why_it_matters}</p>
          </div>

          <div className="disc-exp-item is-highlight">
            <span className="disc-exp-key">Importancia para migración a AWS</span>
            <p className="disc-exp-text">{explanation.migration_relevance}</p>
          </div>

          <div className="disc-exp-item">
            <span className="disc-exp-key">Limitaciones del dato</span>
            <p className="disc-exp-text">{explanation.limitations}</p>
          </div>

          <div className="disc-exp-item">
            <span className="disc-exp-key">Acción sugerida</span>
            <p className="disc-exp-text">{explanation.suggested_action}</p>
          </div>

          <div className="disc-exp-item is-full">
            <span className="disc-exp-key">Procedencia y trazabilidad</span>
            <code className="disc-exp-code">{explanation.provenance}</code>
          </div>
        </div>
      )}
    </div>
  );
}
