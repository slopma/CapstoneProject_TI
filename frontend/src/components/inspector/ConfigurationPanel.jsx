import React from "react";

function ConfigurationPanel({ node }) {
  return (
    <div className="inspector-tab-content">
      <div className="tech-prop-grid">
        <div className="prop-row">
          <span className="prop-key">Motor / Runtime</span>
          <span className="prop-val mono">{node.engine || node.platform || "Estándar"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Subred de Red</span>
          <span className="prop-val mono">{node.network?.subnet_cidr || node.cidr_block || "192.168.10.0/24"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Aislamiento de Red</span>
          <span className="prop-val">{node.security?.private_only ? "Solo Red Privada" : "Subred Estándar"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Cifrado en Reposo</span>
          <span className="prop-val">{node.security?.encryption_at_rest ? "Activo (AES-256)" : "Predeterminado"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Transporte TLS</span>
          <span className="prop-val">Forzado (TLS 1.3)</span>
        </div>
      </div>
    </div>
  );
}

export default ConfigurationPanel;
