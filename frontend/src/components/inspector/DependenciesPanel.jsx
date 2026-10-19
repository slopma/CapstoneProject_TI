import React from "react";
import { formatResourceType } from "../../utils/graphLayout";

function DependenciesPanel({ directDependencies, directDependents, onSelectNode }) {
  return (
    <div className="inspector-tab-content">
      <div className="dep-section">
        <h4 className="dep-section-title">
          Dependencias salientes requeridas ({directDependencies.length})
        </h4>
        {directDependencies.length === 0 ? (
          <p className="empty-text">Sin dependencias directas salientes.</p>
        ) : (
          <ul className="tech-dep-list">
            {directDependencies.map((dep) => (
              <li key={dep.id} className="tech-dep-item">
                <div className="dep-info">
                  <span className="dep-name">{dep.name}</span>
                  <span className="dep-meta">{formatResourceType(dep.type)}</span>
                </div>
                <button
                  type="button"
                  className="tech-action-btn-xs"
                  onClick={() => onSelectNode(dep.id)}
                >
                  Inspeccionar
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="dep-section">
        <h4 className="dep-section-title">
          Servicios consumidores entrantes ({directDependents.length})
        </h4>
        {directDependents.length === 0 ? (
          <p className="empty-text">Ningún otro servicio depende directamente de este recurso.</p>
        ) : (
          <ul className="tech-dep-list">
            {directDependents.map((dep) => (
              <li key={dep.id} className="tech-dep-item">
                <div className="dep-info">
                  <span className="dep-name">{dep.name}</span>
                  <span className="dep-meta">{formatResourceType(dep.type)}</span>
                </div>
                <button
                  type="button"
                  className="tech-action-btn-xs"
                  onClick={() => onSelectNode(dep.id)}
                >
                  Inspeccionar
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default DependenciesPanel;
