import React from "react";

function ResourceOverview({ node, parentNode, onSelectNode }) {
  return (
    <div className="inspector-tab-content">
      <div className="tech-prop-grid">
        <div className="prop-row">
          <span className="prop-key">Provider</span>
          <span className="prop-val">{node.provider || "on-premise"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Location / Region</span>
          <span className="prop-val">{node.location || "Datacenter A"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Environment</span>
          <span className="prop-val">{node.environment || "production"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Category</span>
          <span className="prop-val">{node.category || "resource"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Migration Status</span>
          <span className={`status-badge ${node.status?.toLowerCase()}`}>{node.status || "DISCOVERED"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-key">Parent Component</span>
          {parentNode ? (
            <button
              type="button"
              className="tech-link-btn"
              onClick={() => onSelectNode(parentNode.id)}
            >
              {parentNode.name} (L{parentNode.level})
            </button>
          ) : (
            <span className="prop-val muted">Root Scope (Level 0)</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default ResourceOverview;
