import React from "react";
import { NavIcon } from "../architecture/TechnicalIcons";

export const CLOUDMOVE_NAV_GROUPS = [
  {
    group: "Visibilidad y Descubrimiento",
    items: [
      {
        id: "overview",
        label: "Resumen del Entorno",
        hint: "Salud global, inventario y accesos",
        icon: "architecture",
      },
      {
        id: "discovery",
        label: "Discovery e Inventario",
        hint: "Agente osquery, procesos, red y BDs",
        icon: "discovery",
      },
      {
        id: "campaigns",
        label: "Campañas de Datacenter",
        hint: "Descubrimiento masivo y oleadas",
        icon: "dependencies",
      },
      {
        id: "architecture",
        label: "Grafo de Arquitectura",
        hint: "Topología CMIR v2.1 y dependencias",
        icon: "architecture",
      },
    ],
  },
  {
    group: "Planificación y Ejecución Cloud",
    items: [
      {
        id: "migration",
        label: "Migraciones y Planes",
        hint: "Casos 1 (App), 2 (Imagen) y 3 (DC)",
        icon: "migration",
      },
      {
        id: "sources-targets",
        label: "Orígenes y Destinos",
        hint: "Conectores, AWS/GCP y compatibilidad",
        icon: "settings",
      },
      {
        id: "executions-audit",
        label: "Ejecuciones, IaC y Auditoría",
        hint: "Terraform HCL, checkpoints y trazas",
        icon: "audit",
      },
    ],
  },
];

export default function Sidebar({
  activeTab,
  setActiveTab,
  mobileOpen = false,
  onCloseMobile,
  systemStats = {},
}) {
  const handleSelect = (id) => {
    setActiveTab(id);
    if (onCloseMobile) onCloseMobile();
  };

  return (
    <>
      <div
        className={`sidebar-backdrop ${mobileOpen ? "visible" : ""}`}
        onClick={onCloseMobile}
        aria-hidden="true"
      />
      <aside
        className={`enterprise-sidebar ${mobileOpen ? "mobile-open" : ""}`}
        aria-label="Navegación principal de CloudMove"
      >
        <div className="sidebar-brand">
          <div className="sidebar-brand-group">
            <div className="brand-logo-mark" aria-hidden="true">
              CM
            </div>
            <div>
              <span className="brand-name">CLOUDMOVE</span>
              <span className="brand-subtitle">On-Premise → AWS · GCP</span>
            </div>
          </div>
          {onCloseMobile && (
            <button
              type="button"
              className="sidebar-close-btn"
              onClick={onCloseMobile}
              aria-label="Cerrar menú de navegación"
            >
              ×
            </button>
          )}
        </div>

        <nav className="sidebar-nav" aria-label="Áreas operativas">
          {CLOUDMOVE_NAV_GROUPS.map((group) => (
            <React.Fragment key={group.group}>
              <div className="sidebar-group-label">{group.group}</div>
              {group.items.map((item) => {
                const isActive = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => handleSelect(item.id)}
                    className={`sidebar-nav-btn ${isActive ? "active" : ""}`}
                    aria-current={isActive ? "page" : undefined}
                    data-nav-id={item.id}
                  >
                    <span className="nav-icon-wrapper" aria-hidden="true">
                      <NavIcon type={item.icon} />
                    </span>
                    <span className="sidebar-nav-meta">
                      <span className="sidebar-nav-label">{item.label}</span>
                      <span className="sidebar-nav-hint">{item.hint}</span>
                    </span>
                  </button>
                );
              })}
            </React.Fragment>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="system-status-indicator">
            <span className="status-dot healthy" aria-hidden="true" />
            <span>CMIR v2.1 · Motor Activo</span>
          </div>
          <div className="sidebar-footer-sub">
            Destinos: <strong>AWS · GCP</strong> (Azure excluido ADR-001)
            {typeof systemStats.jobsCount === "number" && (
              <> · {systemStats.jobsCount} planes</>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
