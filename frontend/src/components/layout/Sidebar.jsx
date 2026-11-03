import React from "react";
import { NavIcon } from "../architecture/TechnicalIcons";

export const CLOUDMOVE_NAV_GROUPS = [
  {
    group: "Descubrimiento y topología",
    items: [
      {
        id: "overview",
        label: "Resumen del entorno",
        hint: "Panel general, métricas y accesos rápidos",
        icon: "architecture",
      },
      {
        id: "discovery",
        label: "Discovery e inventario",
        hint: "Agente osquery, procesos, red y bases de datos",
        icon: "discovery",
      },
      {
        id: "campaigns",
        label: "Campañas de datacenter",
        hint: "Descubrimiento masivo y oleadas por sitio",
        icon: "dependencies",
      },
      {
        id: "architecture",
        label: "Grafo de arquitectura",
        hint: "Topología CMIR v2.1 y análisis de alcance",
        icon: "architecture",
      },
    ],
  },
  {
    group: "Migración y gobernanza",
    items: [
      {
        id: "migration",
        label: "Migraciones y planes",
        hint: "Casos 1 (App/GitHub), 2 (Imagen VM) y 3 (Datacenter)",
        icon: "migration",
      },
      {
        id: "sources-targets",
        label: "Orígenes y destinos",
        hint: "Conectores, agentes y compatibilidad AWS/GCP",
        icon: "settings",
      },
      {
        id: "executions-audit",
        label: "Auditoría y Terraform",
        hint: "Terraform HCL, pruebas pre/post y bitácora ACID",
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
  collapsed = false,
  onToggleCollapse,
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
        className={`enterprise-sidebar awsui-side-navigation ${mobileOpen ? "mobile-open" : ""} ${
          collapsed ? "is-collapsed" : ""
        }`}
        aria-label="Navegación de servicios de CloudMove"
      >
        <div className="sidebar-brand">
          {!collapsed && (
            <div className="sidebar-brand-group">
              <div>
                <span className="brand-name">Migration Hub</span>
              </div>
            </div>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: collapsed ? "auto" : 0, marginRight: collapsed ? "auto" : 0 }}>
            {onToggleCollapse && (
              <button
                type="button"
                className="awsui-side-collapse-btn"
                onClick={onToggleCollapse}
                title={collapsed ? "Expandir navegación lateral" : "Contraer navegación lateral"}
                aria-label={collapsed ? "Expandir navegación lateral" : "Contraer navegación lateral"}
              >
                {collapsed ? "»" : "«"}
              </button>
            )}
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
        </div>

        <nav className="sidebar-nav" aria-label="Secciones de la consola">
          {CLOUDMOVE_NAV_GROUPS.map((group, idx) => (
            <div key={group.group} className="awsui-nav-section">
              {idx > 0 && <div className="awsui-nav-divider" />}
              {!collapsed && (
                <div className="sidebar-group-label">{group.group}</div>
              )}
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
                    title={item.hint}
                  >
                    <span className="nav-icon-wrapper" aria-hidden="true">
                      <NavIcon type={item.icon} />
                    </span>
                    {!collapsed && (
                      <span className="sidebar-nav-meta">
                        <span className="sidebar-nav-label">{item.label}</span>
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        {!collapsed && (
          <div className="sidebar-footer">
            <div className="system-status-indicator">
              <span className="status-dot healthy" aria-hidden="true" />
              <span>CMIR v2.1 · AWS / GCP</span>
            </div>
            {typeof systemStats.jobsCount === "number" && (
              <div className="sidebar-footer-sub">
                {systemStats.jobsCount} planes registrados
              </div>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
