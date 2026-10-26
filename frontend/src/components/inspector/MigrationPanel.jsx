import React from "react";

function MigrationPanel({ node, targetProvider }) {
  const provider = (targetProvider || "aws").toLowerCase() === "gcp" ? "gcp" : "aws";
  const epistemic = node.epistemic_state || node.metadata?.data_state || "observed";
  const confidence = typeof node.confidence === "number" ? `${Math.round(node.confidence * 100)}%` : "100%";

  return (
    <div className="inspector-tab-content">
      <div className="tech-box">
        <h4 className="tech-box-title">Preparación de Migración CMIR v2.1</h4>
        <div className="prop-row">
          <span className="prop-key">Proveedor Destino</span>
          <span className="prop-val highlight">{provider.toUpperCase()}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Estado de Evidencia</span>
          <span className="prop-val mono">{epistemic.toUpperCase()} ({confidence})</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">ID Canónico</span>
          <span className="prop-val mono">{node.canonical_id || node.id}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Adaptador Destino</span>
          <span className="prop-val mono">
            {provider === "gcp" ? "GCPAdapter (hashicorp/google)" : "AWSAdapter (hashicorp/aws)"}
          </span>
        </div>

        {node.is_shared && (
          <div className="tech-alert warning">
            <strong>Dependencia Compartida Protegida:</strong>
            <p>
              Este componente es utilizado por múltiples cargas fuera de la selección actual. No se migrará automáticamente sin validación explícita.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default MigrationPanel;
