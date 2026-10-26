import React from "react";
import { ActionIcon } from "../architecture/TechnicalIcons";

const TAB_LABELS = {
  overview: "Resumen del Entorno",
  discovery: "Discovery e Inventario",
  campaigns: "Campañas de Datacenter",
  architecture: "Grafo de Arquitectura",
  migration: "Migraciones y Planes",
  "sources-targets": "Orígenes y Destinos",
  "executions-audit": "Ejecuciones, IaC y Auditoría",
};

export default function Header({
  activeTab,
  architectureName,
  searchQuery,
  setSearchQuery,
  selectedCount,
  onPrepareMigration,
  targetProvider = "aws",
  setTargetProvider,
  onToggleMobileNav,
}) {
  const areaLabel = TAB_LABELS[activeTab] || "Consola Operativa";

  return (
    <header className="enterprise-header">
      <div className="header-left">
        <button
          type="button"
          className="mobile-nav-toggle"
          onClick={onToggleMobileNav}
          aria-label="Abrir navegación principal"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <div className="header-meta-group">
          <span className="env-badge">{areaLabel}</span>
          <span className="meta-separator" aria-hidden="true">/</span>
          <h1 className="active-arch-title" title={architectureName || "onpremise-datacenter-enterprise"}>
            {architectureName || "onpremise-datacenter-enterprise"}
          </h1>
        </div>
      </div>

      <div className="header-right">
        <div className="header-search-box">
          <svg
            width="14"
            height="14"
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
            aria-label="Buscar activos por nombre, IP o tipo en el grafo"
            placeholder="Buscar recurso, IP, servicio..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        {setTargetProvider && (
          <select
            aria-label="Proveedor cloud destino activo"
            value={targetProvider}
            onChange={(e) => setTargetProvider(e.target.value)}
            className="cm-select"
            style={{ width: "auto", minHeight: 32, padding: "4px 10px", fontSize: 12, fontWeight: 600 }}
          >
            <option value="aws">Destino: AWS</option>
            <option value="gcp">Destino: GCP</option>
          </select>
        )}

        <button
          type="button"
          className="header-action-btn primary"
          disabled={selectedCount === 0}
          onClick={onPrepareMigration}
          title={
            selectedCount === 0
              ? "Selecciona recursos en el Grafo de Arquitectura para analizar dependencias y generar IaC"
              : `Analizar dependencias y generar IaC para ${selectedCount} recurso(s)`
          }
        >
          Preparar Migración ({selectedCount})
        </button>

        <div className="user-profile-badge" title="Arquitecto Cloud / DevOps Senior">
          <span>ARQ</span>
        </div>
      </div>
    </header>
  );
}
