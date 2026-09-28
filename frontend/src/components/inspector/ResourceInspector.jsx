import React, { useState } from "react";
import ResourceOverview from "./ResourceOverview";
import DependenciesPanel from "./DependenciesPanel";
import ConfigurationPanel from "./ConfigurationPanel";
import MigrationPanel from "./MigrationPanel";
import { ResourceIcon } from "../architecture/TechnicalIcons";

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

  if (!node) return null;

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

  return (
    <aside className="enterprise-inspector-drawer">
      <header className="drawer-header">
        <div className="drawer-meta-bar">
          <span className="drawer-level-pill">LEVEL {node.level ?? 8}</span>
          <span className="drawer-type-pill">{node.type}</span>
          {node.is_shared && <span className="drawer-shared-pill">SHARED</span>}
        </div>

        <div className="drawer-title-row">
          <ResourceIcon type={node.type} size={20} color="#3b82f6" />
          <h3 className="drawer-title">{node.name}</h3>
        </div>
        <p className="drawer-id-label">ID: <code>{node.id}</code></p>

        <button type="button" className="drawer-close-btn" onClick={onClose} title="Close Inspector">
          &times;
        </button>
      </header>

      <nav className="drawer-nav-tabs">
        <button
          type="button"
          className={activeTab === "overview" ? "active" : ""}
          onClick={() => setActiveTab("overview")}
        >
          Overview
        </button>
        <button
          type="button"
          className={activeTab === "dependencies" ? "active" : ""}
          onClick={() => setActiveTab("dependencies")}
        >
          Dependencies ({directDependencies.length})
        </button>
        <button
          type="button"
          className={activeTab === "config" ? "active" : ""}
          onClick={() => setActiveTab("config")}
        >
          Config & Security
        </button>
        <button
          type="button"
          className={activeTab === "children" ? "active" : ""}
          onClick={() => setActiveTab("children")}
        >
          Children ({children.length})
        </button>
        <button
          type="button"
          className={activeTab === "migration" ? "active" : ""}
          onClick={() => setActiveTab("migration")}
        >
          Migration Scope
        </button>
      </nav>

      <div className="drawer-body-container">
        {activeTab === "overview" && (
          <ResourceOverview node={node} parentNode={parentNode} onSelectNode={onSelectNode} />
        )}
        {activeTab === "dependencies" && (
          <DependenciesPanel
            node={node}
            directDependencies={directDependencies}
            directDependents={directDependents}
            onSelectNode={onSelectNode}
          />
        )}
        {activeTab === "config" && <ConfigurationPanel node={node} />}
        {activeTab === "children" && (
          <div className="inspector-tab-content">
            {children.length === 0 ? (
              <p className="empty-text">No child components contained within this node.</p>
            ) : (
              <>
                <button
                  type="button"
                  className="tech-action-btn-sm"
                  style={{ marginBottom: 12 }}
                  onClick={() => onToggleExpand(node.id)}
                >
                  {isExpanded ? "Collapse Children on Canvas" : "Expand Children on Canvas"}
                </button>
                <ul className="tech-dep-list">
                  {children.map((child) => (
                    <li key={child.id} className="tech-dep-item">
                      <div className="dep-info">
                        <span className="dep-name">{child.name}</span>
                        <span className="dep-meta">L{child.level} · {child.type}</span>
                      </div>
                      <button
                        type="button"
                        className="tech-action-btn-xs"
                        onClick={() => onSelectNode(child.id)}
                      >
                        Select
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
        {activeTab === "migration" && (
          <MigrationPanel node={node} targetProvider={targetProvider} />
        )}
      </div>
    </aside>
  );
}

export default ResourceInspector;
