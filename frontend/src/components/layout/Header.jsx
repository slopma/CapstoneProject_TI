import React from "react";

export const TAB_LABELS = {
  overview: "Resumen del entorno",
  discovery: "Discovery e inventario",
  campaigns: "Campañas de datacenter",
  architecture: "Grafo de arquitectura",
  migration: "Migraciones y planes",
  "sources-targets": "Orígenes y destinos",
  "executions-audit": "Ejecuciones, IaC y auditoría",
};

export default function Header({
  activeTab,
  setActiveTab,
  searchQuery,
  setSearchQuery,
  selectedCount,
  onPrepareMigration,
  targetProvider = "aws",
  setTargetProvider,
  onToggleMobileNav,
  sidebarCollapsed,
  onToggleSidebarCollapse,
}) {
  return (
    <header className="enterprise-header awsui-top-navigation" role="banner">
      <div className="header-left">
        <button
          type="button"
          className="mobile-nav-toggle"
          onClick={onToggleMobileNav}
          aria-label="Abrir menú de navegación"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>

        {onToggleSidebarCollapse && (
          <button
            type="button"
            className="awsui-top-icon-btn"
            onClick={onToggleSidebarCollapse}
            title={sidebarCollapsed ? "Expandir menú lateral" : "Contraer menú lateral"}
            aria-label="Alternar panel lateral"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
            </svg>
          </button>
        )}

        <button
          type="button"
          className="awsui-brand-identity"
          onClick={() => setActiveTab && setActiveTab("overview")}
          title="Ir al Resumen del entorno de CloudMove Console"
        >
          <span className="awsui-brand-cube" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#FF9900" strokeWidth="2.2">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </span>
          <span className="awsui-brand-title">CloudMove</span>
          <span className="awsui-brand-tag">AWS · GCP Console</span>
        </button>
      </div>

      <div className="awsui-top-center">
        <div className="header-search-box">
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="search-icon"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="search"
            name="architecture-search"
            className="header-search-input"
            aria-label="Buscar recursos, IPs, servicios o planes"
            placeholder="Buscar servicios, recursos o planes..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      <div className="header-right">
        {setTargetProvider && (
          <div className="awsui-top-util-select">
            <select
              aria-label="Proveedor cloud destino activo"
              value={targetProvider}
              onChange={(e) => setTargetProvider(e.target.value)}
              className="awsui-squid-select"
            >
              <option value="aws">AWS · us-east-1</option>
              <option value="gcp">GCP · us-central1</option>
            </select>
          </div>
        )}

        {selectedCount > 0 ? (
          <button
            type="button"
            className="header-action-btn primary"
            onClick={onPrepareMigration}
          >
            Generar IaC ({selectedCount})
          </button>
        ) : (
          <button
            type="button"
            className="header-action-btn primary"
            onClick={() => setActiveTab && setActiveTab("migration")}
          >
            Nueva migración
          </button>
        )}
      </div>
    </header>
  );
}
