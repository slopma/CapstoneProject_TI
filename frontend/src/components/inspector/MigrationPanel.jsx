import React from "react";

function MigrationPanel({ node, targetProvider }) {
  return (
    <div className="inspector-tab-content">
      <div className="tech-box">
        <h4 className="tech-box-title">Granular Migration Scope Readiness</h4>
        <div className="prop-row">
          <span className="prop-key">Target Ecosystem</span>
          <span className="prop-val highlight">{(targetProvider || "AWS").toUpperCase()}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">CMIR Model Neutrality</span>
          <span className="prop-val">100% Compatible</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Target Adapter</span>
          <span className="prop-val mono">
            {targetProvider === "azure" ? "AzureAdapter (azurerm)" : targetProvider === "kubernetes" ? "KubernetesAdapter (YAML)" : "AWSAdapter (hashicorp/aws)"}
          </span>
        </div>

        {node.is_shared && (
          <div className="tech-alert warning">
            <strong>Shared Dependency Detected:</strong>
            <p>This component is referenced by external services outside the current scope. Connectivity rules will be preserved or duplicated in the target IaC.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default MigrationPanel;
