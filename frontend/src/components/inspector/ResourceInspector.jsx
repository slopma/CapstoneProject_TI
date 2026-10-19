import React, { useState, useEffect, useCallback } from "react";
import ResourceOverview from "./ResourceOverview";
import DependenciesPanel from "./DependenciesPanel";
import ConfigurationPanel from "./ConfigurationPanel";
import MigrationPanel from "./MigrationPanel";
import { ResourceIcon } from "../architecture/TechnicalIcons";
import { formatResourceType, resolveProviderMeta } from "../../utils/graphLayout";

function ResourceInspector({
  node,
  allNodes,
  edges,
  onClose,
  onSelectNode,
  targetProvider,
  onToggleExpand,
  isExpanded,
}) {
  const [activeTab, setActiveTab] = useState("overview");
  const [drawerWidth, setDrawerWidth] = useState(420);
  const [isResizing, setIsResizing] = useState(false);

  const handleMouseDown = useCallback((e) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!isResizing) return;
      const newWidth = window.innerWidth - e.clientX - 16;
      if (newWidth >= 340 && newWidth <= 800) {
        setDrawerWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    if (isResizing) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    }
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing]);

  if (!node) return null;

  const provider = resolveProviderMeta(node);
  const typeLabel = formatResourceType(node.type);

  const directDependencies = edges
    .filter((e) => e.source === node.id && !e.is_hierarchy)
    .map((e) => allNodes.find((n) => n.id === e.target))
    .filter(Boolean);

  const directDependents = edges
    .filter((e) => e.target === node.id && !e.is_hierarchy)
    .map((e) => allNodes.find((n) => n.id === e.source))
    .filter(Boolean);

  const children = allNodes.filter((n) => n.parent_id === node.id);
  const parentNode = allNodes.find((n) => n.id === node.parent_id);

  const totalDeps = directDependencies.length + directDependents.length;
  const hasChildren = children.length > 0;
  const hasConfig = Boolean(
    (node.configuration && Object.keys(node.configuration).length > 0) ||
      (node.security && Object.keys(node.security).length > 0) ||
      (node.network && Object.keys(node.network).length > 0) ||
      (node.storage && Object.keys(node.storage).length > 0) ||
      (node.env_vars && Object.keys(node.env_vars).length > 0) ||
      node.engine ||
      node.platform ||
      node.cidr_block ||
      node.port ||
      node.image
  );

  const availableTabs = [
    { id: "overview", label: "Resumen" },
    totalDeps > 0 ? { id: "dependencies", label: `Relaciones (${totalDeps})` } : null,
    hasConfig ? { id: "config", label: "Configuración" } : null,
    hasChildren ? { id: "children", label: `Internos (${children.length})` } : null,
    { id: "migration", label: "Migración" },
  ].filter(Boolean);

  const validTabIds = availableTabs.map((t) => t.id);
  const currentTab = validTabIds.includes(activeTab) ? activeTab : "overview";

  const toggleExpandDrawer = () => {
    setDrawerWidth((prev) => (prev >= 580 ? 420 : 620));
  };

  return (
    <aside
      className={`enterprise-inspector-drawer ${isResizing ? "is-resizing" : ""}`}
      style={{ width: `${drawerWidth}px` }}
      aria-label={`Inspector de recurso: ${node.name}`}
    >
      <div
        className="drawer-resize-handle"
        onMouseDown={handleMouseDown}
        title="Arrastra para ajustar el ancho del panel"
      />

      <header className="drawer-header">
        <div className="drawer-title-row">
          <span
            className="container-icon-badge"
            style={{
              color: provider.accent,
              backgroundColor: provider.surface,
            }}
          >
            <ResourceIcon type={node.type} size={16} color={provider.accent} />
          </span>
          <h3 className="drawer-title">{node.name}</h3>
        </div>

        <p className="drawer-subtitle-line">
          <span>{typeLabel}</span>
          <span className="node-meta-dot" aria-hidden="true">·</span>
          <code>{node.id}</code>
          {node.is_shared && (
            <>
              <span className="node-meta-dot" aria-hidden="true">·</span>
              <span className="drawer-shared-pill">Compartido</span>
            </>
          )}
        </p>

        <div className="drawer-header-actions">
          <button
            type="button"
            className="drawer-resize-toggle-btn"
            onClick={toggleExpandDrawer}
            title={drawerWidth >= 580 ? "Reducir panel" : "Ampliar panel"}
          >
            {drawerWidth >= 580 ? "Compactar" : "Ampliar"}
          </button>
          <button
            type="button"
            className="drawer-close-btn"
            onClick={onClose}
            title="Cerrar inspector"
            aria-label="Cerrar inspector"
          >
            &times;
          </button>
        </div>
      </header>

      <nav className="drawer-nav-tabs" aria-label="Secciones del inspector">
        {availableTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={currentTab === tab.id ? "active" : ""}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <div className="drawer-body-container">
        {currentTab === "overview" && (
          <ResourceOverview node={node} parentNode={parentNode} onSelectNode={onSelectNode} />
        )}
        {currentTab === "dependencies" && (
          <DependenciesPanel
            directDependencies={directDependencies}
            directDependents={directDependents}
            onSelectNode={onSelectNode}
          />
        )}
        {currentTab === "config" && <ConfigurationPanel node={node} />}
        {currentTab === "children" && (
          <div className="inspector-tab-content">
            <button
              type="button"
              className="toolbar-btn"
              style={{ marginBottom: 12 }}
              onClick={() => onToggleExpand(node.id)}
            >
              {isExpanded ? "Contraer recursos en el lienzo" : "Desplegar recursos en el lienzo"}
            </button>
            <ul className="tech-dep-list">
              {children.map((child) => (
                <li key={child.id} className="tech-dep-item">
                  <div className="dep-info">
                    <span className="dep-name">{child.name}</span>
                    <span className="dep-meta">{formatResourceType(child.type)}</span>
                  </div>
                  <button
                    type="button"
                    className="tech-action-btn-xs"
                    onClick={() => onSelectNode(child.id)}
                  >
                    Inspeccionar
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {currentTab === "migration" && (
          <MigrationPanel node={node} targetProvider={targetProvider} />
        )}
      </div>
    </aside>
  );
}

export default ResourceInspector;
