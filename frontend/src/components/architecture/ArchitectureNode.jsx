import React, { memo, useCallback } from "react";
import { Handle, Position } from "@xyflow/react";
import { ResourceIcon } from "./TechnicalIcons";
import {
  formatResourceType,
  resolveProviderMeta,
  resolveArchitecturalDomain,
  resolveDomainAccent,
} from "../../utils/graphLayout";

function ChevronIcon({ isExpanded }) {
  return (
    <svg
      className={`arch-chevron-icon ${isExpanded ? "is-expanded" : ""}`}
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M4.5 2.75L7.75 6L4.5 9.25"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MultiDirectionalHandles({ isBoundary }) {
  const cls = `node-handle ${isBoundary ? "is-boundary-handle" : ""}`;
  return (
    <>
      <Handle id="top" type="target" position={Position.Top} className={cls} />
      <Handle id="bottom" type="target" position={Position.Bottom} className={cls} />
      <Handle id="left" type="target" position={Position.Left} className={cls} />
      <Handle id="right" type="target" position={Position.Right} className={cls} />

      <Handle id="top" type="source" position={Position.Top} className={cls} />
      <Handle id="bottom" type="source" position={Position.Bottom} className={cls} />
      <Handle id="left" type="source" position={Position.Left} className={cls} />
      <Handle id="right" type="source" position={Position.Right} className={cls} />
    </>
  );
}

function ArchitectureNode({ data }) {
  const {
    node,
    selected,
    isExpanded,
    hasChildren,
    isCollapsedContainer = false,
    childCount = 0,
    depth = 0,
    staggerIndex = 0,
    isDimmed = false,
    isRelated = false,
    onSelect,
    onToggleExpand,
    onHoverEnter,
    onHoverLeave,
  } = data;

  const provider = resolveProviderMeta(node);
  const domain = resolveArchitecturalDomain(node);
  const badgeTone = resolveDomainAccent(domain, provider);
  const typeLabel = formatResourceType(node.type);
  const technicalDetail =
    node.engine || node.cidr || node.ip || node.platform || node.location || "";
  const childLabel =
    childCount === 1 ? "1 recurso interno" : `${childCount} recursos internos`;

  const staggerDelayMs = Math.min(staggerIndex * 22, 260);

  const handleSelect = useCallback(
    (e) => {
      e.stopPropagation();
      if (onSelect) onSelect(node.id);
    },
    [node.id, onSelect]
  );

  const handleToggle = useCallback(
    (e) => {
      e.stopPropagation();
      if (onToggleExpand) onToggleExpand(node.id);
    },
    [node.id, onToggleExpand]
  );

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        e.stopPropagation();
        if (onSelect) onSelect(node.id);
      } else if (hasChildren && (e.key === "e" || e.key === "E")) {
        e.preventDefault();
        e.stopPropagation();
        if (onToggleExpand) onToggleExpand(node.id);
      }
    },
    [hasChildren, node.id, onSelect, onToggleExpand]
  );

  const stateClasses = [
    "tech-arch-node",
    hasChildren
      ? isCollapsedContainer || !isExpanded
        ? "is-container is-collapsed"
        : "is-container is-expanded"
      : "is-leaf",
    selected ? "is-selected" : "",
    isDimmed ? "is-dimmed" : "",
    isRelated && !selected ? "is-related" : "",
    `provider-${provider.id}`,
    `domain-${domain}`,
  ]
    .filter(Boolean)
    .join(" ");

  const nodeStyle = {
    width: "100%",
    height: "100%",
    "--stagger-delay": `${staggerDelayMs}ms`,
  };

  // 1. Expanded Boundary Container Node
  if (hasChildren && isExpanded && !isCollapsedContainer) {
    return (
      <div
        className={stateClasses}
        style={nodeStyle}
        data-depth={Math.min(depth, 3)}
        data-domain={domain}
        role="button"
        tabIndex={0}
        aria-expanded={true}
        aria-selected={selected}
        aria-label={`${typeLabel}: ${node.name} (${childLabel})`}
        onClick={handleSelect}
        onKeyDown={handleKeyDown}
        onMouseEnter={() => onHoverEnter && onHoverEnter(node.id)}
        onMouseLeave={() => onHoverLeave && onHoverLeave()}
      >
        <MultiDirectionalHandles isBoundary={true} />

        <div className="container-node-header">
          <div className="node-meta">
            <span
              className="container-icon-badge"
              style={{
                color: badgeTone.accent,
                backgroundColor: badgeTone.surface,
              }}
            >
              <ResourceIcon type={node.type} size={14} color={badgeTone.accent} />
            </span>
            <div className="container-title-stack">
              <strong className="container-node-title" title={node.name}>
                {node.name}
              </strong>
              <span className="node-type-label">{typeLabel}</span>
            </div>
          </div>

          <div className="node-status-indicator">
            {node.is_shared && (
              <span
                className="shared-resource-pill"
                title="Recurso compartido entre múltiples dominios"
              >
                Compartido
              </span>
            )}
            <button
              type="button"
              className="expand-toggle-btn expanded"
              title="Contraer contenedor (Atajo: E)"
              aria-label={`Contraer ${node.name}`}
              onClick={handleToggle}
            >
              <ChevronIcon isExpanded={true} />
              <span className="child-count">{childCount}</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // 2. Collapsed Boundary Container Node (Compact Summary Card with Expand Trigger)
  if (hasChildren) {
    return (
      <div
        className={stateClasses}
        style={nodeStyle}
        data-depth={Math.min(depth, 3)}
        data-domain={domain}
        role="button"
        tabIndex={0}
        aria-expanded={false}
        aria-selected={selected}
        aria-label={`${typeLabel} contraído: ${node.name} (${childLabel})`}
        onClick={handleSelect}
        onKeyDown={handleKeyDown}
        onMouseEnter={() => onHoverEnter && onHoverEnter(node.id)}
        onMouseLeave={() => onHoverLeave && onHoverLeave()}
      >
        <MultiDirectionalHandles isBoundary={true} />

        <div className="node-body">
          <span
            className="node-icon-box"
            style={{
              color: badgeTone.accent,
              backgroundColor: badgeTone.surface,
            }}
          >
            <ResourceIcon type={node.type} size={16} color={badgeTone.accent} />
          </span>

          <div className="node-title-group">
            <div className="node-title-row">
              <strong className="node-title" title={node.name}>
                {node.name}
              </strong>
              <button
                type="button"
                className="expand-toggle-btn"
                title={`Desplegar ${childLabel} (Atajo: E)`}
                aria-label={`Desplegar ${node.name} (${childLabel})`}
                onClick={handleToggle}
              >
                <ChevronIcon isExpanded={false} />
                <span className="child-count">{childCount}</span>
              </button>
            </div>

            <div className="node-meta-row">
              <span className="node-type-label">{typeLabel}</span>
              <span className="node-meta-dot" aria-hidden="true">
                ·
              </span>
              <span className="node-provider-inline">{childLabel}</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // 3. Atomic Leaf Workload / Resource Node
  return (
    <div
      className={stateClasses}
      style={nodeStyle}
      data-domain={domain}
      role="button"
      tabIndex={0}
      aria-selected={selected}
      aria-label={`${typeLabel}: ${node.name}`}
      onClick={handleSelect}
      onKeyDown={handleKeyDown}
      onMouseEnter={() => onHoverEnter && onHoverEnter(node.id)}
      onMouseLeave={() => onHoverLeave && onHoverLeave()}
    >
      <MultiDirectionalHandles isBoundary={false} />

      <div className="node-body">
        <span
          className="node-icon-box"
          style={{
            color: badgeTone.accent,
            backgroundColor: badgeTone.surface,
          }}
        >
          <ResourceIcon type={node.type} size={16} color={badgeTone.accent} />
        </span>

        <div className="node-title-group">
          <div className="node-title-row">
            <strong className="node-title" title={node.name}>
              {node.name}
            </strong>
            <span
              className={`status-dot ${node.is_shared ? "warning" : "healthy"}`}
              title={
                node.is_shared
                  ? "Recurso compartido entre servicios"
                  : "Recurso operativo"
              }
              aria-hidden="true"
            />
          </div>

          <div className="node-meta-row">
            <span className="node-type-label">{typeLabel}</span>
            {technicalDetail ? (
              <>
                <span className="node-meta-dot" aria-hidden="true">
                  ·
                </span>
                <small className="node-subtext" title={technicalDetail}>
                  {technicalDetail}
                </small>
              </>
            ) : (
              <>
                <span className="node-meta-dot" aria-hidden="true">
                  ·
                </span>
                <span className="node-provider-inline">{provider.label}</span>
              </>
            )}
          </div>
        </div>
      </div>

      {node.is_shared && (
        <div className="node-footer-bar">
          <span className="shared-resource-pill">Recurso compartido</span>
        </div>
      )}
    </div>
  );
}

export default memo(ArchitectureNode);
