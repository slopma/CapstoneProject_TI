import React from "react";
import IaCViewer from "./IaCViewer";

function MigrationPreviewModal({
  selectedNodes,
  dependencies,
  targetProvider,
  setTargetProvider,
  onConfirmGenerate,
  onClose,
  generating,
  generationResult,
}) {
  const directDeps = dependencies?.required_direct || [];
  const transitiveDeps = dependencies?.required_transitive || [];
  const sharedDeps = dependencies?.shared_dependencies || [];

  const filenameMap = {
    aws: "main.tf",
    azure: "main.tf",
    kubernetes: "manifests.yaml",
  };

  return (
    <div className="enterprise-modal-overlay" onClick={onClose}>
      <div className="enterprise-modal-card" onClick={(e) => e.stopPropagation()}>
        <header className="modal-top-header">
          <div className="modal-title-meta">
            <span className="modal-scope-tag">MIGRATION SCOPE PREVIEW</span>
            <h2 className="modal-heading">Granular Subgraph Migration & Target Translation</h2>
          </div>
          <button type="button" className="modal-close-x" onClick={onClose}>
            &times;
          </button>
        </header>

        <div className="modal-scrollable-body">
          <div className="tech-metric-bar">
            <div className="metric-cell">
              <span className="m-label">Selected Scope</span>
              <span className="m-val">{selectedNodes.length}</span>
            </div>
            <div className="metric-cell">
              <span className="m-label">Direct Dependencies</span>
              <span className="m-val">{directDeps.length}</span>
            </div>
            <div className="metric-cell">
              <span className="m-label">Transitive Dependencies</span>
              <span className="m-val">{transitiveDeps.length}</span>
            </div>
            <div className="metric-cell warning">
              <span className="m-label">Shared Dependencies</span>
              <span className="m-val">{sharedDeps.length}</span>
            </div>
          </div>

          {sharedDeps.length > 0 && (
            <div className="tech-alert warning">
              <strong>Shared Resource Isolation Warning:</strong>
              <p>The following shared components are referenced by external services outside the migration scope:</p>
              <ul className="alert-code-list">
                {sharedDeps.map((id) => (
                  <li key={id}><code>{id}</code></li>
                ))}
              </ul>
              <small>CloudMove target adapters will maintain connectivity rules to prevent breaking unmigrated workloads.</small>
            </div>
          )}

          <div className="target-provider-selector-block">
            <h4 className="selector-title">Target Provider & Infrastructure Adapter</h4>
            <div className="provider-grid">
              <button
                type="button"
                className={`provider-card-btn ${targetProvider === "aws" ? "active" : ""}`}
                onClick={() => setTargetProvider("aws")}
              >
                <div className="provider-info">
                  <strong>AWS (Amazon Web Services)</strong>
                  <span>Terraform HCL · AWSAdapter</span>
                </div>
              </button>
              <button
                type="button"
                className={`provider-card-btn ${targetProvider === "azure" ? "active" : ""}`}
                onClick={() => setTargetProvider("azure")}
              >
                <div className="provider-info">
                  <strong>Microsoft Azure</strong>
                  <span>Terraform HCL · AzureAdapter</span>
                </div>
              </button>
              <button
                type="button"
                className={`provider-card-btn ${targetProvider === "kubernetes" ? "active" : ""}`}
                onClick={() => setTargetProvider("kubernetes")}
              >
                <div className="provider-info">
                  <strong>Kubernetes (Cloud Native)</strong>
                  <span>YAML Manifests · K8sAdapter</span>
                </div>
              </button>
            </div>
          </div>

          {generationResult && (
            <div className="iac-result-section">
              <div className="tech-alert success">
                <strong>IaC Generation Succeeded!</strong>
                <p>Output file written to: <code>{generationResult.output_path || generationResult.output}</code></p>
              </div>
              <IaCViewer
                code={generationResult.iac_code || generationResult.terraform}
                language={targetProvider === "kubernetes" ? "yaml" : "hcl"}
                filename={filenameMap[targetProvider] || "main.tf"}
              />
            </div>
          )}
        </div>

        <footer className="modal-bottom-footer">
          <button type="button" className="tech-btn secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="tech-btn primary"
            onClick={onConfirmGenerate}
            disabled={generating || selectedNodes.length === 0}
          >
            {generating ? "Translating & Generating..." : `Generate ${targetProvider.toUpperCase()} Infrastructure`}
          </button>
        </footer>
      </div>
    </div>
  );
}

export default MigrationPreviewModal;
