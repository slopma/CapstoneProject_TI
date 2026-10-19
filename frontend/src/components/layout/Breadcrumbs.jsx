import React from "react";

function Breadcrumbs({ breadcrumbs, onNavigate, onReset, onBack }) {
  return (
    <nav className="enterprise-breadcrumbs" aria-label="Ruta de navegación de arquitectura">
      {breadcrumbs && breadcrumbs.length > 1 && (
        <button
          type="button"
          className="back-btn-sm"
          onClick={onBack}
          title="Regresar al contenedor superior"
        >
          &larr; Nivel anterior
        </button>
      )}

      <button
        type="button"
        className="breadcrumb-node root-node"
        onClick={onReset}
      >
        Arquitectura raíz
      </button>

      {breadcrumbs &&
        breadcrumbs.map((item, idx) => {
          const isLast = idx === breadcrumbs.length - 1;
          return (
            <React.Fragment key={item.id}>
              <span className="breadcrumb-sep" aria-hidden="true">/</span>
              <button
                type="button"
                className={`breadcrumb-node ${isLast ? "active" : ""}`}
                onClick={() => onNavigate(item.id)}
                disabled={isLast}
                title={item.name}
              >
                <span className="node-title">{item.name}</span>
              </button>
            </React.Fragment>
          );
        })}
    </nav>
  );
}

export default Breadcrumbs;
