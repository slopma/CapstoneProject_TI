import React from "react";

function Breadcrumbs({ breadcrumbs, onNavigate, onReset, onBack }) {
  return (
    <nav className="enterprise-breadcrumbs" aria-label="Architecture navigation path">
      {breadcrumbs && breadcrumbs.length > 1 && (
        <button
          type="button"
          className="back-btn-sm"
          onClick={onBack}
          title="Regresar al nivel anterior"
        >
          &larr; Back
        </button>
      )}

      <button
        type="button"
        className="breadcrumb-node root-node"
        onClick={onReset}
      >
        Root Architecture
      </button>

      {breadcrumbs && breadcrumbs.map((item, idx) => {
        const isLast = idx === breadcrumbs.length - 1;
        return (
          <React.Fragment key={item.id}>
            <span className="breadcrumb-sep">&gt;</span>
            <button
              type="button"
              className={`breadcrumb-node ${isLast ? "active" : ""}`}
              onClick={() => onNavigate(item.id)}
              disabled={isLast}
              title={item.name}
            >
              <span className="level-tag">L{item.level ?? 0}</span>
              <span className="node-title">{item.name}</span>
            </button>
          </React.Fragment>
        );
      })}
    </nav>
  );
}

export default Breadcrumbs;
