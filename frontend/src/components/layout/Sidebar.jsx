import React from "react";
import { NavIcon } from "../architecture/TechnicalIcons";

export const CLOUDMOVE_NAV_GROUPS = [
  {
    group: "Consola principal",
    items: [
      {
        id: "overview",
        label: "Console Home (Inicio)",
        hint: "Panel principal, widgets de estado y lanzamiento rápido",
        icon: "architecture",
      },
    ],
  },
  {
    group: "Casos de migración",
    items: [
      {
        id: "case-1-nav",
        tab: "migration",
        useCase: "app_source",
        label: "Caso 1 · Aplicación (GitHub)",
        hint: "Repositorio o código fuente → Contenedores en AWS/GCP",
        icon: "migration",
      },
      {
        id: "case-2-nav",
        tab: "migration",
        useCase: "vm_image",
        label: "Caso 2 · Imagen de SO / VM",
        hint: "Agente en vivo o disco VMDK/QCOW2 → Máquina virtual",
        icon: "discovery",
      },
      {
        id: "migration",
        label: "Planes de migración",
        hint: "Orquestador completo, etapas y despliegue Terraform",
        icon: "dependencies",
      },
    ],
  },
  {
    group: "Descubrimiento y topología",
    items: [
      {
        id: "discovery",
        label: "Discovery e inventario",
        hint: "Telemetría osquery, procesos, red y bases de datos",
        icon: "discovery",
      },
      {
        id: "architecture",
        label: "Grafo de arquitectura CMIR",
        hint: "Topología jerárquica Nivel 0-5 y dependencias",
        icon: "architecture",
      },
      {
        id: "sources-targets",
        label: "Orígenes, agentes y destinos",
        hint: "Inscripción de agentes remotos y conectores AWS/GCP",
        icon: "settings",
      },
    ],
  },
  {
    group: "Gobernanza y operaciones",
    items: [
      {
        id: "executions-audit",
        label: "Auditoría AWS y Terraform",
        hint: "Recursos activos en AWS, cuotas EBS y bitácora ACID",
        icon: "audit",
      },
    ],
  },
];

export default function Sidebar({
  activeTab,
  activeUseCase = "app_source",
  setActiveTab,
  onQuickStartUseCase,
  mobileOpen = false,
  onCloseMobile,
  collapsed = false,
  onToggleCollapse,
  systemStats = {},
}) {
  const handleSelect = (item) => {
    if (item.useCase && onQuickStartUseCase) {
      onQuickStartUseCase(item.useCase);
    } else {
      setActiveTab(item.tab || item.id);
    }
    if (onCloseMobile) onCloseMobile();
  };

  const isItemActive = (item) => {
    if (item.id === "case-1-nav") {
      return activeTab === "migration" && activeUseCase === "app_source";
    }
    if (item.id === "case-2-nav") {
      return activeTab === "migration" && activeUseCase === "vm_image";
    }
    if (item.id === "migration") {
      return false; // Highlighted via specific active case above
    }
    return activeTab === item.id;
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
                <span className="brand-name">AWS Migration Hub</span>
                <span style={{ display: "block", fontSize: 11.5, color: "#545b64", fontWeight: 500 }}>
                  CloudMove v2.1
                </span>
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
                const isActive = isItemActive(item);
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => handleSelect(item)}
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
              <span>CMIR v2.1 · Casos 1 y 2</span>
            </div>
            {typeof systemStats.jobsCount === "number" && (
              <div className="sidebar-footer-sub">
                {systemStats.jobsCount} plan(es) en base de datos ACID
              </div>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
