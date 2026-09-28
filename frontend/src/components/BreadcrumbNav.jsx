import React from "react";

function BreadcrumbNav({ breadcrumbs, onNavigate, onReset }) {
  return (
    <nav className="breadcrumb-nav" aria-label="Navegación jerárquica">
      <button
        type="button"
        className="breadcrumb-item root-btn"
        onClick={onReset}
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
          <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" />
        </svg>
        CloudMove Arch
      </button>

      {breadcrumbs && breadcrumbs.map((item, index) => {
        const isLast = index === breadcrumbs.length - 1;
        return (
          <React.Fragment key={item.id}>
            <span className="breadcrumb-separator">/</span>
            <button
              type="button"
              className={`breadcrumb-item ${isLast ? "active" : ""}`}
              onClick={() => onNavigate(item.id)}
              disabled={isLast}
            >
              <span className="breadcrumb-level-pill">L{item.level}</span>
              <span className="breadcrumb-label">{item.name}</span>
            </button>
          </React.Fragment>
        );
      })}
    </nav>
  );
}

export default BreadcrumbNav;
