import React, { useState, useRef } from "react";

const TYPE_STYLES = {
  external: {
    stroke: "#64748b",
    badgeBg: "#334155",
    badgeText: "#f8fafc",
    tag: "EXT",
  },
  cloud: {
    stroke: "#0972d3",
    badgeBg: "#0972d3",
    badgeText: "#ffffff",
    tag: "NET",
  },
  security: {
    stroke: "#d97706",
    badgeBg: "#b45309",
    badgeText: "#ffffff",
    tag: "SEC",
  },
  backend: {
    stroke: "#ff9900",
    badgeBg: "#ec7211",
    badgeText: "#000716",
    tag: "EC2",
  },
  database: {
    stroke: "#037f0c",
    badgeBg: "#037f0c",
    badgeText: "#ffffff",
    tag: "DATA",
  },
  messagebus: {
    stroke: "#4f46e5",
    badgeBg: "#4338ca",
    badgeText: "#ffffff",
    tag: "APP",
  },
};

const DOT_COLORS = {
  cyan: "#0972d3",
  emerald: "#037f0c",
  amber: "#ec7211",
};

/**
 * Interactive Archify SVG Architecture & Terraform Diagram Renderer.
 * Renders typed Archify JSON models (boundaries, components, connections, cards)
 * with Dark/Light theme, Live/Still motion, Zoom/Fit controls, node selection, and SVG export.
 */
export default function ArchifyDiagramRenderer({
  model,
  selectedIds = [],
  onSelectComponent = null,
  showStandaloneLink = true,
  standaloneUrl = "/archify-aws-cmir.html",
}) {
  const [theme, setTheme] = useState("dark"); // "dark" | "light"
  const [liveMotion, setLiveMotion] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [hoveredId, setHoveredId] = useState(null);
  const svgRef = useRef(null);

  if (!model || !model.components) return null;

  const isDark = theme === "dark";
  const bgCanvas = isDark ? "#0d1117" : "#f8fafc";
  const gridColor = isDark ? "rgba(148, 163, 184, 0.08)" : "rgba(15, 23, 42, 0.06)";
  const nodeBg = isDark ? "#161b22" : "#ffffff";
  const nodeText = isDark ? "#f0f6fc" : "#000716";
  const nodeSubtext = isDark ? "#8b949e" : "#545b64";
  const edgeDefault = isDark ? "#58a6ff" : "#0972d3";
  const edgeSecurity = isDark ? "#f59e0b" : "#b45309";
  const edgeEmphasis = isDark ? "#ff9900" : "#ec7211";

  const compMap = {};
  model.components.forEach((c) => {
    compMap[c.id] = c;
  });

  // Compute bounding boxes for boundaries based on wrapped components
  const computedBoundaries = (model.boundaries || []).map((b, idx) => {
    const wrapped = (b.wraps || [])
      .map((id) => compMap[id])
      .filter(Boolean);
    if (wrapped.length === 0) return null;
    const pad = b.pad || 20;
    const minX = Math.min(...wrapped.map((c) => c.pos[0])) - pad;
    const minY = Math.min(...wrapped.map((c) => c.pos[1])) - (pad + 18);
    const maxX = Math.max(...wrapped.map((c) => c.pos[0] + (c.size?.[0] || 168))) + pad;
    const maxY = Math.max(...wrapped.map((c) => c.pos[1] + (c.size?.[1] || 64))) + pad;
    return {
      key: `${b.kind}-${idx}`,
      kind: b.kind,
      label: b.label,
      x: minX,
      y: minY,
      width: maxX - minX,
      height: maxY - minY,
    };
  }).filter(Boolean);

  const handleExportSvg = () => {
    if (!svgRef.current) return;
    const serializer = new XMLSerializer();
    const source = serializer.serializeToString(svgRef.current);
    const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `archify-aws-architecture.svg`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      className="archify-viewer-shell"
      style={{
        border: "1px solid #d5dbdb",
        borderRadius: 8,
        overflow: "hidden",
        backgroundColor: "#ffffff",
      }}
    >
      {/* Top Archify Control Bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 10,
          padding: "10px 16px",
          backgroundColor: "#232f3e",
          color: "#ffffff",
          borderBottom: "1px solid #414d5c",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span
            style={{
              backgroundColor: "#ff9900",
              color: "#000716",
              fontWeight: 700,
              fontSize: 11.5,
              padding: "2px 8px",
              borderRadius: 4,
            }}
          >
            ARCHIFY v3.1
          </span>
          <strong style={{ fontSize: 13.5, color: "#ffffff" }}>
            {model.meta?.title || "Arquitectura AWS · Modelo CMIR y Recursos Terraform"}
          </strong>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <button
            type="button"
            className="awsui-top-util-btn"
            style={{ height: 28, fontSize: 12 }}
            onClick={() => setLiveMotion((prev) => !prev)}
          >
            Flujo: {liveMotion ? "Activo (Live)" : "Estático (Still)"}
          </button>
          <button
            type="button"
            className="awsui-top-util-btn"
            style={{ height: 28, fontSize: 12 }}
            onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
          >
            Tema: {isDark ? "Oscuro" : "Claro"}
          </button>
          <button
            type="button"
            className="awsui-top-util-btn"
            style={{ height: 28, fontSize: 12 }}
            onClick={() => setZoom((z) => Math.max(0.7, +(z - 0.1).toFixed(2)))}
            aria-label="Reducir zoom"
          >
            −
          </button>
          <button
            type="button"
            className="awsui-top-util-btn"
            style={{ height: 28, fontSize: 12 }}
            onClick={() => setZoom(1)}
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            type="button"
            className="awsui-top-util-btn"
            style={{ height: 28, fontSize: 12 }}
            onClick={() => setZoom((z) => Math.min(1.4, +(z + 0.1).toFixed(2)))}
            aria-label="Aumentar zoom"
          >
            +
          </button>
          <button
            type="button"
            className="awsui-top-util-btn"
            style={{ height: 28, fontSize: 12 }}
            onClick={handleExportSvg}
          >
            Exportar SVG
          </button>
          {showStandaloneLink && (
            <a
              href={standaloneUrl}
              target="_blank"
              rel="noreferrer"
              className="awsui-top-util-btn"
              style={{ height: 28, fontSize: 12, textDecoration: "none" }}
            >
              Visor completo ↗
            </a>
          )}
        </div>
      </div>

      {/* Interactive SVG Canvas */}
      <div
        style={{
          width: "100%",
          overflowX: "auto",
          backgroundColor: bgCanvas,
          backgroundImage: `radial-gradient(${gridColor} 1px, transparent 1px)`,
          backgroundSize: "18px 18px",
          padding: "16px 0",
        }}
      >
        <svg
          ref={svgRef}
          viewBox="0 0 1060 460"
          style={{
            width: `${Math.round(100 * zoom)}%`,
            minWidth: 780,
            maxHeight: 500,
            display: "block",
            margin: "0 auto",
            fontFamily: "var(--font-sans)",
          }}
        >
          <defs>
            <marker
              id="archify-arrow-default"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill={edgeDefault} />
            </marker>
            <marker
              id="archify-arrow-security"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill={edgeSecurity} />
            </marker>
            <marker
              id="archify-arrow-emphasis"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill={edgeEmphasis} />
            </marker>
          </defs>

          {liveMotion && (
            <style>{`
              @keyframes archifyDashFlow {
                to { stroke-dashoffset: -24; }
              }
              .archify-live-edge {
                stroke-dasharray: 6 6;
                animation: archifyDashFlow 1.1s linear infinite;
              }
            `}</style>
          )}

          {/* 1. Render Boundaries (VPC & Subnets) */}
          {computedBoundaries.map((b) => {
            const isRegion = b.kind === "region";
            const borderCol = isRegion
              ? isDark
                ? "#0972d3"
                : "#0972d3"
              : isDark
              ? "#2ea043"
              : "#037f0c";
            const fillCol = isRegion
              ? isDark
                ? "rgba(9, 114, 211, 0.06)"
                : "rgba(9, 114, 211, 0.03)"
              : isDark
              ? "rgba(46, 160, 67, 0.06)"
              : "rgba(3, 127, 12, 0.03)";

            return (
              <g key={b.key}>
                <rect
                  x={b.x}
                  y={b.y}
                  width={b.width}
                  height={b.height}
                  rx={8}
                  fill={fillCol}
                  stroke={borderCol}
                  strokeWidth={isRegion ? 1.8 : 1.3}
                  strokeDasharray={isRegion ? "none" : "6 4"}
                />
                <text
                  x={b.x + 12}
                  y={b.y + 18}
                  fill={isDark ? "#e6edf3" : "#000716"}
                  fontSize="11.5"
                  fontWeight="700"
                >
                  {b.label}
                </text>
              </g>
            );
          })}

          {/* 2. Render Connections */}
          {(model.connections || []).map((conn, idx) => {
            const src = compMap[conn.from];
            const dst = compMap[conn.to];
            if (!src || !dst) return null;

            const sw = src.size?.[0] || 168;
            const sh = src.size?.[1] || 64;
            const dw = dst.size?.[0] || 168;
            const dh = dst.size?.[1] || 64;

            const sx = src.pos[0] + sw / 2;
            const sy = src.pos[1] + sh / 2;
            const dx = dst.pos[0] + dw / 2;
            const dy = dst.pos[1] + dh / 2;

            let x1 = sx;
            let y1 = sy;
            let x2 = dx;
            let y2 = dy;

            if (Math.abs(dx - sx) > Math.abs(dy - sy)) {
              x1 = dx > sx ? src.pos[0] + sw : src.pos[0];
              x2 = dx > sx ? dst.pos[0] : dst.pos[0] + dw;
            } else {
              y1 = dy > sy ? src.pos[1] + sh : src.pos[1];
              y2 = dy > sy ? dst.pos[1] : dst.pos[1] + dh;
            }

            const strokeCol =
              conn.variant === "security"
                ? edgeSecurity
                : conn.variant === "emphasis"
                ? edgeEmphasis
                : edgeDefault;
            const markerId =
              conn.variant === "security"
                ? "url(#archify-arrow-security)"
                : conn.variant === "emphasis"
                ? "url(#archify-arrow-emphasis)"
                : "url(#archify-arrow-default)";

            const midX = (x1 + x2) / 2;
            const midY = (y1 + y2) / 2;

            return (
              <g key={`${conn.from}-${conn.to}-${idx}`}>
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={strokeCol}
                  strokeWidth="2"
                  className={liveMotion ? "archify-live-edge" : ""}
                  strokeDasharray={conn.variant === "dashed" ? "4 4" : undefined}
                  markerEnd={markerId}
                />
                {conn.label && (
                  <g transform={`translate(${midX}, ${midY})`}>
                    <rect
                      x={-48}
                      y={-10}
                      width={96}
                      height={19}
                      rx={4}
                      fill={isDark ? "#0d1117" : "#ffffff"}
                      stroke={strokeCol}
                      strokeWidth="1"
                    />
                    <text
                      x={0}
                      y={3}
                      textAnchor="middle"
                      fill={isDark ? "#f0f6fc" : "#000716"}
                      fontSize="10"
                      fontWeight="600"
                      fontFamily="var(--font-mono)"
                    >
                      {conn.label}
                    </text>
                  </g>
                )}
              </g>
            );
          })}

          {/* 3. Render Components */}
          {model.components.map((comp) => {
            const w = comp.size?.[0] || 168;
            const h = comp.size?.[1] || 64;
            const styleMeta = TYPE_STYLES[comp.type] || TYPE_STYLES.cloud;
            const isSelected = selectedIds.includes(comp.id);
            const isHovered = hoveredId === comp.id;

            return (
              <g
                key={comp.id}
                transform={`translate(${comp.pos[0]}, ${comp.pos[1]})`}
                style={{ cursor: onSelectComponent ? "pointer" : "default" }}
                onMouseEnter={() => setHoveredId(comp.id)}
                onMouseLeave={() => setHoveredId(null)}
                onClick={() => onSelectComponent && onSelectComponent(comp)}
              >
                <rect
                  x={0}
                  y={0}
                  width={w}
                  height={h}
                  rx={6}
                  fill={nodeBg}
                  stroke={isSelected ? "#ff9900" : isHovered ? "#58a6ff" : styleMeta.stroke}
                  strokeWidth={isSelected || isHovered ? 2.4 : 1.5}
                />
                <rect
                  x={8}
                  y={10}
                  width={34}
                  height={18}
                  rx={3}
                  fill={styleMeta.badgeBg}
                />
                <text
                  x={25}
                  y={22}
                  textAnchor="middle"
                  fill={styleMeta.badgeText}
                  fontSize="9.5"
                  fontWeight="800"
                >
                  {styleMeta.tag}
                </text>
                <text
                  x={48}
                  y={23}
                  fill={nodeText}
                  fontSize="11.5"
                  fontWeight="700"
                >
                  {comp.label.length > 20 ? `${comp.label.slice(0, 19)}…` : comp.label}
                </text>
                <text
                  x={10}
                  y={45}
                  fill={nodeSubtext}
                  fontSize="10.5"
                  fontFamily="var(--font-mono)"
                >
                  {(comp.sublabel || "").length > 26
                    ? `${comp.sublabel.slice(0, 25)}…`
                    : comp.sublabel}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Archify Bottom Architectural Summary Cards */}
      {model.cards && model.cards.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: 12,
            padding: 16,
            backgroundColor: "#fafafa",
            borderTop: "1px solid #e9ebed",
          }}
        >
          {model.cards.map((card, idx) => (
            <div
              key={card.title || idx}
              style={{
                backgroundColor: "#ffffff",
                border: "1px solid #e9ebed",
                borderTop: `3px solid ${DOT_COLORS[card.dot] || "#0972d3"}`,
                borderRadius: 6,
                padding: "12px 14px",
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 13, color: "#000716", marginBottom: 6 }}>
                {card.title}
              </div>
              <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: "#545b64", lineHeight: 1.45 }}>
                {(card.items || []).map((it, i) => (
                  <li key={i} style={{ marginBottom: 4 }}>
                    {it}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
