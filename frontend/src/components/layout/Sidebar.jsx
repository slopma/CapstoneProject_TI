import React from "react";
import { NavIcon } from "../architecture/TechnicalIcons";

const NAV_ITEMS = [
  { id: "architecture", label: "Architecture", icon: "architecture" },
  { id: "discovery", label: "Discovery", icon: "discovery" },
  { id: "dependencies", label: "Dependencies", icon: "dependencies" },
  { id: "migration", label: "Migration", icon: "migration" },
  { id: "iac", label: "IaC Generator", icon: "iac" },
  { id: "audit", label: "Activity / Audit", icon: "audit" },
  { id: "settings", label: "Settings", icon: "settings" },
];

function Sidebar({ activeTab, onSelectTab }) {
  return (
    <aside className="enterprise-sidebar">
      <div className="sidebar-brand">
        <span className="brand-logo-mark">CM</span>
        <span className="brand-name">CLOUDMOVE</span>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className={`sidebar-nav-btn ${isActive ? "active" : ""}`}
              onClick={() => onSelectTab(item.id)}
              title={item.label}
            >
              <span className="nav-icon-wrapper">
                <NavIcon name={item.icon} size={16} />
              </span>
              <span className="nav-label">{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <div className="system-status-indicator">
          <span className="status-dot healthy"></span>
          <span className="system-label">CMIR Engine v2.0</span>
        </div>
      </div>
    </aside>
  );
}

export default Sidebar;
