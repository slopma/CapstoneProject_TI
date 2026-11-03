import React from "react";

function ResourceOverview({ node, parentNode, onSelectNode }) {
  return (
    <div className="inspector-tab-content">
      <div className="tech-prop-grid">
        <div className="prop-row">
          <span className="prop-key">Proveedor</span>
          <span className="prop-val">{node.provider || "on-premise"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Ubicación / Región</span>
          <span className="prop-val">{node.location || "Datacenter A"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Entorno</span>
          <span className="prop-val">{node.environment || "production"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Categoría</span>
          <span className="prop-val">{node.category || "resource"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Estado de Migración</span>
          <span className={`status-badge ${node.status?.toLowerCase()}`}>{node.status || "DISCOVERED"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Contenedor Padre</span>
          {parentNode ? (
            <button
              type="button"
              className="tech-link-btn"
              onClick={() => onSelectNode(parentNode.id)}
            >
              {parentNode.name} (L{parentNode.level})
            </button>
          ) : (
            <span className="prop-val muted">Ámbito Raíz (Nivel 0)</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default ResourceOverview;
