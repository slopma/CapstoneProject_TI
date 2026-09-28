import React from "react";
import { Handle, Position } from "@xyflow/react";
import { ResourceIcon } from "./TechnicalIcons";

const LEVEL_COLORS = {
  0: "#475569",
  1: "#38bdf8",
  2: "#818cf8",
  3: "#a78bfa",
  4: "#c084fc",
  5: "#f472b6",
  6: "#fb923c",
  7: "#34d399",
  8: "#94a3b8",
};

function ArchitectureNode({ data }) {
  const { node, selected, isExpanded, hasChildren, childCount, onSelect, onToggleExpand } = data;
  const levelColor = LEVEL_COLORS[node.level ?? 8] || "#94a3b8";
  const subtext = node.engine || node.platform || node.location || node.category || "";

  return (
    <div
      className={`tech-arch-node ${selected ? "is-selected" : ""}`}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(node.id);
      }}
    >
      <Handle type="target" position={Position.Top} className="node-handle" style={{ background: levelColor }} />

      <div className="node-tech-header">
        <div className="node-meta">
          <span className="node-level-tag" style={{ borderLeftColor: levelColor }}>
            L{node.level ?? 8}
          </span>
          <span className="node-type-label">{node.type}</span>
        </div>
        <div className="node-status-indicator">
          <span className={`status-dot ${node.is_shared ? "warning" : "healthy"}`}></span>
          <span className="status-text">{node.is_shared ? "Shared" : "Healthy"}</span>
        </div>
      </div>

      <div className="node-body">
        <span className="node-icon-box">
          <ResourceIcon type={node.type} size={16} color={levelColor} />
        </span>
        <div className="node-title-group">
          <strong className="node-title">{node.name}</strong>
          {subtext && <small className="node-subtext">{subtext}</small>}
        </div>
      </div>

      {hasChildren && (
        <div className="node-expansion-footer">
          <span className="child-count">{childCount} sub-items</span>
          <button
            type="button"
            className={`expand-toggle-btn ${isExpanded ? "expanded" : ""}`}
            onClick={(e) => {
              e.stopPropagation();
              onToggleExpand(node.id);
            }}
          >
            {isExpanded ? "Collapse" : "Expand"}
          </button>
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="node-handle" style={{ background: levelColor }} />
    </div>
  );
}

export default ArchitectureNode;
