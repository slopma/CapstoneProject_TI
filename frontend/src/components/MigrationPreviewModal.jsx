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
  const optionalDeps = dependencies?.optional_dependencies || [];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-container" onClick={(e) => e.stopPropagation()}>
        <header className="modal-header">
          <div>
            <span className="step-pill">Migration Scope Preview</span>
            <h2>Vista Previa de la Migración Granular</h2>
          </div>
          <button type="button" className="close-panel-btn" onClick={onClose}>
            ✕
          </button>
        </header>

        <div className="modal-body">
          <div className="scope-metrics">
            <div className="metric-box">
              <span>Seleccionados</span>
              <strong>{selectedNodes.length}</strong>
            </div>
            <div className="metric-box">
              <span>Dep. Directas</span>
              <strong>{directDeps.length}</strong>
            </div>
            <div className="metric-box">
              <span>Dep. Transitivas</span>
              <strong>{transitiveDeps.length}</strong>
            </div>
            <div className="metric-box warning">
              <span>Dep. Compartidas</span>
              <strong>{sharedDeps.length}</strong>
            </div>
          </div>

          {sharedDeps.length > 0 && (
            <div className="alert alert-warning">
              <strong>Recursos Compartidos Detectados:</strong>
              <p>Los siguientes recursos son consumidos por otros componentes fuera de la selección:</p>
              <ul>
                {sharedDeps.map((id) => (
                  <li key={id}><code>{id}</code></li>
                ))}
              </ul>
              <small>CloudMove mantendrá o clonará las reglas de conectividad para evitar interrumpir las otras cargas de trabajo.</small>
            </div>
          )}

          <div className="target-selection-section">
            <h3>Seleccionar Proveedor de Destino IaC</h3>
            <div className="provider-options">
              <button
                type="button"
                className={`provider-card ${targetProvider === "aws" ? "selected" : ""}`}
                onClick={() => setTargetProvider("aws")}
              >
                <strong>AWS</strong>
                <span>Terraform HCL · Amazon Web Services</span>
              </button>
              <button
                type="button"
                className={`provider-card ${targetProvider === "azure" ? "selected" : ""}`}
                onClick={() => setTargetProvider("azure")}
              >
                <strong>Azure</strong>
                <span>Terraform HCL · Microsoft Azure</span>
              </button>
              <button
                type="button"
                className={`provider-card ${targetProvider === "kubernetes" ? "selected" : ""}`}
                onClick={() => setTargetProvider("kubernetes")}
              >
                <strong>Kubernetes</strong>
                <span>YAML Manifests · Cloud Native</span>
              </button>
            </div>
          </div>

          {generationResult && (
            <div className="alert alert-success">
              <h4>¡Generación Completada Con Éxito!</h4>
              <p><strong>Archivo Generado:</strong> <code>{generationResult.output_path || generationResult.output}</code></p>
              <p><strong>Recursos Totales Creados:</strong> {generationResult.resources_generated?.length}</p>
              <details>
                <summary>Ver Código IaC Generado ({targetProvider.toUpperCase()})</summary>
                <pre className="code-block">
                  <code>{generationResult.iac_code || generationResult.terraform}</code>
                </pre>
              </details>
            </div>
          )}
        </div>

        <footer className="modal-footer">
          <button type="button" className="secondary-btn" onClick={onClose}>
            Cancelar / Volver
          </button>
          <button
            type="button"
            className="primary-btn"
            onClick={onConfirmGenerate}
            disabled={generating || selectedNodes.length === 0}
          >
            {generating ? "Generando Código IaC..." : `Generar Infraestructura (${targetProvider.toUpperCase()})`}
          </button>
        </footer>
      </div>
    </div>
  );
}

export default MigrationPreviewModal;
