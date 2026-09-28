import React from "react";

function ConfigurationPanel({ node }) {
  return (
    <div className="inspector-tab-content">
      <div className="tech-prop-grid">
        <div className="prop-row">
          <span className="prop-key">Engine / Runtime</span>
          <span className="prop-val mono">{node.engine || node.platform || "Standard"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Network Subnet</span>
          <span className="prop-val mono">{node.network?.subnet_cidr || "192.168.10.0/24"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Network Isolation</span>
          <span className="prop-val">{node.security?.private_only ? "Private Network Only" : "Standard Subnet"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Encryption at Rest</span>
          <span className="prop-val">{node.security?.encryption_at_rest ? "Enabled (AES-256)" : "Default"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">TLS Transport</span>
          <span className="prop-val">Enforced (TLS 1.3)</span>
        </div>
      </div>
    </div>
  );
}

export default ConfigurationPanel;
