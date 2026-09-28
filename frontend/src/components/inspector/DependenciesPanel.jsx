import React from "react";

function DependenciesPanel({ node, directDependencies, directDependents, onSelectNode }) {
  return (
    <div className="inspector-tab-content">
      <div className="dep-section">
        <h4 className="dep-section-title">Required Outbound Dependencies ({directDependencies.length})</h4>
        {directDependencies.length === 0 ? (
          <p className="empty-text">No direct outbound dependencies.</p>
        ) : (
          <ul className="tech-dep-list">
            {directDependencies.map((dep) => (
              <li key={dep.id} className="tech-dep-item">
                <div className="dep-info">
                  <span className="dep-name">{dep.name}</span>
                  <span className="dep-meta">L{dep.level} · {dep.type}</span>
                </div>
                <button
                  type="button"
                  className="tech-action-btn-xs"
                  onClick={() => onSelectNode(dep.id)}
                >
                  Inspect
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="dep-section">
        <h4 className="dep-section-title">Inbound Consumer Services ({directDependents.length})</h4>
        {directDependents.length === 0 ? (
          <p className="empty-text">No consumer services depend on this component.</p>
        ) : (
          <ul className="tech-dep-list">
            {directDependents.map((dep) => (
              <li key={dep.id} className="tech-dep-item">
                <div className="dep-info">
                  <span className="dep-name">{dep.name}</span>
                  <span className="dep-meta">L{dep.level} · {dep.type}</span>
                </div>
                <button
                  type="button"
                  className="tech-action-btn-xs"
                  onClick={() => onSelectNode(dep.id)}
                >
                  Inspect
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
