import React, { useMemo, useState, useCallback, useEffect } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Handle,
  Position,
  useReactFlow,
  ReactFlowProvider,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ResourceIcon } from "../architecture/TechnicalIcons";
import ExplanationCard, { StateBadge } from "./ExplanationCard";

const CATEGORY_META = {
  asset: { label: "Activo Raíz", accent: "#0f172a", bg: "#f1f5f9", border: "#334155", angle: 0 },
  hardware: { label: "Hardware & CPU", accent: "#1d4ed8", bg: "#eff6ff", border: "#93c5fd", column: 0, row: 0 },
  storage: { label: "Almacenamiento", accent: "#0f766e", bg: "#f0fdfa", border: "#5eead4", column: 0, row: 1 },
  software: { label: "SO & Software", accent: "#4338ca", bg: "#eef2ff", border: "#a5b4fc", column: 0, row: 2 },
  services: { label: "Servicios Systemd", accent: "#0369a1", bg: "#f0f9ff", border: "#7dd3fc", column: 2, row: 0 },
  processes: { label: "Procesos Runtime", accent: "#334155", bg: "#f8fafc", border: "#cbd5e1", column: 2, row: 0 },
  runtime: { label: "Runtime & Servicios", accent: "#0369a1", bg: "#f0f9ff", border: "#7dd3fc", column: 2, row: 0 },
  network: { label: "Interfaces & Subredes", accent: "#15803d", bg: "#f0fdf4", border: "#86efac", column: 2, row: 1 },
  listeners: { label: "Puertos en Escucha", accent: "#b45309", bg: "#fffbeb", border: "#fcd34d", column: 2, row: 2 },
  remote_endpoints: { label: "Endpoints Remotos", accent: "#b91c1c", bg: "#fef2f2", border: "#fca5a5", column: 3, row: 1 },
};

const EDGE_STYLE_BY_TYPE = {
  contains: {
    stroke: "#64748b",
    strokeWidth: 1.5,
    strokeDasharray: undefined,
    label: "Contains",
  },
  has_interface: {
    stroke: "#15803d",
    strokeWidth: 1.8,
    strokeDasharray: undefined,
    label: "Has Interface",
  },
  routes_to: {
    stroke: "#0369a1",
    strokeWidth: 1.8,
    strokeDasharray: "6 3",
    label: "Routes To",
  },
  listens_on: {
    stroke: "#b45309",
    strokeWidth: 1.8,
    strokeDasharray: undefined,
    label: "Listens On (PID)",
  },
  observed_connection: {
    stroke: "#b91c1c",
    strokeWidth: 1.7,
    strokeDasharray: "4 4",
    label: "Observed Socket",
  },
  inferred_relation: {
    stroke: "#0f766e",
    strokeWidth: 1.6,
    strokeDasharray: "2 4",
    label: "Derived / Inferred",
  },
};

function DiscoveryGraphNode({ data }) {
  const {
    node,
    selected,
    isGroup,
    isExpanded,
    childCount,
    onSelect,
    onToggleGroup,
  } = data;

  const catKey = node.metadata?.category_group || node.category || "hardware";
  const catMeta = CATEGORY_META[catKey] || CATEGORY_META.hardware;
  const isRoot = node.type === "host";
  const subtitle = node.metadata?.subtitle || node.engine || "";
  const dataState = node.metadata?.data_state || "observed";

  return (
    <div
      className={`disc-flow-node ${isRoot ? "is-root-host" : ""} ${isGroup ? "is-group-node" : "is-item-node"} ${selected ? "is-selected" : ""}`}
      style={{
        "--node-accent": catMeta.accent,
        "--node-bg": catMeta.bg,
        "--node-border": catMeta.border,
      }}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(node);
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          e.stopPropagation();
          onSelect(node);
        }
      }}
    >
      <Handle id="left" type="target" position={Position.Left} className="disc-handle" />
      <Handle id="top" type="target" position={Position.Top} className="disc-handle" />
      <Handle id="right" type="source" position={Position.Right} className="disc-handle" />
      <Handle id="bottom" type="source" position={Position.Bottom} className="disc-handle" />

      <div className="disc-flow-node-top">
        <span
          className="disc-flow-icon"
          style={{ color: isRoot ? "#ffffff" : catMeta.accent, backgroundColor: isRoot ? "#1e293b" : catMeta.bg }}
        >
          <ResourceIcon type={node.type} size={15} color={isRoot ? "#ffffff" : catMeta.accent} />
        </span>

        <div className="disc-flow-title-wrap">
          <div className="disc-flow-title-row">
            <strong className="disc-flow-title" title={node.name}>
              {node.name}
            </strong>
            {isGroup && childCount > 0 && (
              <button
                type="button"
                className="disc-group-expand-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleGroup(node.id);
                }}
                title={isExpanded ? "Contraer grupo" : "Expandir elementos del grupo"}
              >
                {isExpanded ? `− (${childCount})` : `+ (${childCount})`}
              </button>
            )}
          </div>
          {subtitle && (
            <span className="disc-flow-subtitle" title={subtitle}>
              {subtitle}
            </span>
          )}
        </div>
      </div>

      <div className="disc-flow-node-footer">
        <span className="disc-flow-cat-tag">{catMeta.label}</span>
        <span className={`disc-flow-state-dot is-${dataState}`} title={`Estado del dato: ${dataState}`}>
          {dataState}
        </span>
      </div>
    </div>
  );
}

const nodeTypes = {
  discoveryNode: DiscoveryGraphNode,
};

function computeDiscoveryLayout(rawNodes, rawEdges, expandedGroups, hiddenCategories, searchQuery, relNatureFilter) {
  const q = (searchQuery || "").trim().toLowerCase();

  // Count children per group
  const childCountByGroup = {};
  rawNodes.forEach((n) => {
    if (n.parent_id) {
      childCountByGroup[n.parent_id] = (childCountByGroup[n.parent_id] || 0) + 1;
    }
  });

  // Determine visible nodes
  const visibleNodes = rawNodes.filter((n) => {
    const cat = n.metadata?.category_group || n.category || "hardware";
    if (hiddenCategories.includes(cat) && n.type !== "host") return false;
    if (n.parent_id && !expandedGroups.includes(n.parent_id) && !q) {
      return false;
    }
    if (q) {
      const hay = `${n.name} ${n.type} ${n.metadata?.subtitle || ""} ${cat}`.toLowerCase();
      if (n.type !== "host" && !hay.includes(q)) {
        return false;
      }
    }
    return true;
  });

  const visibleIds = new Set(visibleNodes.map((n) => n.id));

  // Position nodes cleanly around central root host:
  // Left columns: Hardware, Storage, Software & OS
  // Center column: Root Host (`host-{hostname}`)
  // Right columns: Runtime/Services/Processes, Network/Subnets/Gateway, Listening Ports, Remote Endpoints
  const LEFT_GROUPS = ["grp-hardware", "grp-storage", "grp-software"];
  const RIGHT_GROUPS = ["grp-runtime", "grp-network", "grp-listeners", "grp-remote-peers"];

  const positions = {};
  const rootNode = visibleNodes.find((n) => n.type === "host");
  if (rootNode) {
    positions[rootNode.id] = { x: 760, y: 380 };
  }

  // Layout Left Groups & their children
  let leftCursorY = 40;
  LEFT_GROUPS.forEach((gid) => {
    const gNode = visibleNodes.find((n) => n.id === gid);
    const children = visibleNodes.filter((n) => n.parent_id === gid);
    if (!gNode && children.length === 0) return;

    const blockHeight = Math.max(110, children.length * 102);
    const groupY = leftCursorY + (children.length > 1 ? ((children.length - 1) * 102) / 2 : 0);

    if (gNode) {
      positions[gNode.id] = { x: 400, y: groupY };
    }
    children.forEach((ch, idx) => {
      // Sub-level indentation for partitions vs disks vs mounts
      const levelShift = ch.level >= 5 ? -340 : ch.level === 4 ? -170 : 0;
      positions[ch.id] = {
        x: 40 + levelShift,
        y: leftCursorY + idx * 102,
      };
    });

    leftCursorY += blockHeight + 56;
  });

  // Layout Right Groups & their children
  let rightCursorY = 40;
  RIGHT_GROUPS.forEach((gid) => {
    const gNode = visibleNodes.find((n) => n.id === gid);
    const children = visibleNodes.filter((n) => n.parent_id === gid);
    if (!gNode && children.length === 0) return;

    const isPeers = gid === "grp-remote-peers";
    const cols = children.length > 6 ? 2 : 1;
    const rowsCount = Math.ceil(children.length / cols);
    const blockHeight = Math.max(110, rowsCount * 100);
    const groupY = rightCursorY + (rowsCount > 1 ? ((rowsCount - 1) * 100) / 2 : 0);

    if (gNode) {
      positions[gNode.id] = { x: isPeers ? 1480 : 1120, y: groupY };
    }
    children.forEach((ch, idx) => {
      const colIdx = idx % cols;
      const rowIdx = Math.floor(idx / cols);
      const baseX = isPeers ? 1820 : 1480;
      positions[ch.id] = {
        x: baseX + colIdx * 310,
        y: rightCursorY + rowIdx * 100,
      };
    });

    rightCursorY += blockHeight + 56;
  });

  // Fallback position for any unpositioned visible node
  visibleNodes.forEach((n, idx) => {
    if (!positions[n.id]) {
      positions[n.id] = { x: 760 + (idx % 3) * 280, y: 620 + Math.floor(idx / 3) * 110 };
    }
  });

  // Format edges
  const flowEdges = [];
  rawEdges.forEach((e) => {
    if (!visibleIds.has(e.source) || !visibleIds.has(e.target)) return;
    const nature = e.metadata?.nature || "confirmed";
    if (relNatureFilter !== "all" && nature !== relNatureFilter) return;

    const styleMeta = EDGE_STYLE_BY_TYPE[e.type] || EDGE_STYLE_BY_TYPE.contains;
    const srcPos = positions[e.source] || { x: 0, y: 0 };
    const tgtPos = positions[e.target] || { x: 0, y: 0 };
    const sourceHandle = tgtPos.x < srcPos.x ? "left" : "right";
    const targetHandle = tgtPos.x < srcPos.x ? "right" : "left";

    flowEdges.push({
      id: e.id || `${e.source}-${e.target}-${e.type}`,
      source: e.source,
      target: e.target,
      sourceHandle,
      targetHandle,
      type: "smoothstep",
      animated: e.type === "observed_connection",
      label: e.type === "contains" ? undefined : styleMeta.label,
      labelStyle: { fontSize: 10, fontWeight: 600, fill: "#334155" },
      labelBgStyle: { fill: "#ffffff", fillOpacity: 0.9, rx: 4, ry: 4 },
      labelBgPadding: [4, 2],
      style: {
        stroke: styleMeta.stroke,
        strokeWidth: styleMeta.strokeWidth,
        strokeDasharray: styleMeta.strokeDasharray,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 14,
        height: 14,
        color: styleMeta.stroke,
      },
      data: e,
    });
  });

  return {
    visibleNodes,
    positions,
    flowEdges,
    childCountByGroup,
  };
}

function InnerDiscoveryDiagram({
  graphData,
  onNavigateToSection,
}) {
  const { fitView, setCenter } = useReactFlow();
  const rawNodes = useMemo(() => graphData?.nodes || [], [graphData?.nodes]);
  const rawEdges = useMemo(() => graphData?.edges || [], [graphData?.edges]);

  const allGroupIds = useMemo(
    () => rawNodes.filter((n) => n.type === "discovery_group").map((n) => n.id),
    [rawNodes]
  );

  // Start with core groups expanded; keep large secondary groups collapsible
  const [expandedGroups, setExpandedGroups] = useState(() => [
    "grp-hardware",
    "grp-storage",
    "grp-software",
    "grp-runtime",
    "grp-network",
    "grp-listeners",
  ]);
  const [hiddenCategories, setHiddenCategories] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [relNatureFilter, setRelNatureFilter] = useState("all");
  const [selectedNode, setSelectedNode] = useState(null);
  const [showLegend, setShowLegend] = useState(true);

  const handleToggleGroup = useCallback((groupId) => {
    setExpandedGroups((prev) =>
      prev.includes(groupId) ? prev.filter((id) => id !== groupId) : [...prev, groupId]
    );
  }, []);

  const handleExpandAll = useCallback(() => {
    setExpandedGroups(allGroupIds);
  }, [allGroupIds]);

  const handleCollapseAll = useCallback(() => {
    setExpandedGroups([]);
  }, []);

  const handleToggleCategory = useCallback((catId) => {
    setHiddenCategories((prev) =>
      prev.includes(catId) ? prev.filter((c) => c !== catId) : [...prev, catId]
    );
  }, []);

  const { visibleNodes, positions, flowEdges, childCountByGroup } = useMemo(
    () =>
      computeDiscoveryLayout(
        rawNodes,
        rawEdges,
        expandedGroups,
        hiddenCategories,
        searchQuery,
        relNatureFilter
      ),
    [rawNodes, rawEdges, expandedGroups, hiddenCategories, searchQuery, relNatureFilter]
  );

  const flowNodes = useMemo(() => {
    return visibleNodes.map((n) => {
      const isGroup = n.type === "discovery_group";
      return {
        id: n.id,
        type: "discoveryNode",
        position: positions[n.id] || { x: 0, y: 0 },
        data: {
          node: n,
          selected: selectedNode?.id === n.id,
          isGroup,
          isExpanded: expandedGroups.includes(n.id),
          childCount: childCountByGroup[n.id] || 0,
          onSelect: setSelectedNode,
          onToggleGroup: handleToggleGroup,
        },
      };
    });
  }, [visibleNodes, positions, selectedNode, expandedGroups, childCountByGroup, handleToggleGroup]);

  const handleCenterRoot = useCallback(() => {
    const rootPos = positions[graphData?.root_node_id];
    if (rootPos) {
      setCenter(rootPos.x + 140, rootPos.y + 45, { zoom: 0.85, duration: 240 });
    } else {
      fitView({ padding: 0.14, duration: 240 });
    }
  }, [positions, graphData?.root_node_id, setCenter, fitView]);

  const handleFitScreen = useCallback(() => {
    fitView({ padding: 0.14, duration: 240 });
  }, [fitView]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fitView({ padding: 0.14, duration: 200 });
    }, 60);
    return () => clearTimeout(timer);
  }, [graphData?.root_node_id, fitView]);

  // Related edges for selected node in side drawer
  const selectedNodeEdges = useMemo(() => {
    if (!selectedNode) return [];
    return rawEdges.filter((e) => e.source === selectedNode.id || e.target === selectedNode.id);
  }, [selectedNode, rawEdges]);

  return (
    <div className="disc-diagram-container">
      {/* Diagram Controls & Filter Toolbar */}
      <div className="disc-diagram-toolbar" role="toolbar" aria-label="Controles del diagrama de discovery">
        <div className="disc-toolbar-row">
          <div className="disc-search-input-wrap">
            <input
              type="search"
              className="disc-search-input"
              placeholder="Buscar nodo por nombre, IP, puerto, proceso o paquete..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button
                type="button"
                className="disc-clear-btn"
                onClick={() => setSearchQuery("")}
              >
                Limpiar
              </button>
            )}
          </div>

          <div className="disc-btn-group">
            <button type="button" className="toolbar-btn" onClick={handleFitScreen}>
              Ajustar a pantalla
            </button>
            <button type="button" className="toolbar-btn" onClick={handleCenterRoot}>
              Centrar en activo raíz
            </button>
            <button type="button" className="toolbar-btn" onClick={handleExpandAll}>
              Expandir grupos ({allGroupIds.length})
            </button>
            <button type="button" className="toolbar-btn" onClick={handleCollapseAll}>
              Contraer a grupos
            </button>
            <button
              type="button"
              className={`toolbar-btn ${showLegend ? "active" : ""}`}
              onClick={() => setShowLegend((v) => !v)}
            >
              {showLegend ? "Ocultar leyenda" : "Mostrar leyenda"}
            </button>
          </div>

          <div className="disc-rel-filter">
            <label htmlFor="rel-nature-select" className="toolbar-label">
              Relaciones:
            </label>
            <select
              id="rel-nature-select"
              className="disc-select"
              value={relNatureFilter}
              onChange={(e) => setRelNatureFilter(e.target.value)}
            >
              <option value="all">Todas las relaciones</option>
              <option value="confirmed">Solo confirmadas (Estructura / PID)</option>
              <option value="observed">Observadas directas (Interfaces / Rutas)</option>
              <option value="observed_snapshot">Observadas en instantánea (Sockets)</option>
              <option value="inferred">Derivadas / Inferidas (Subredes / Montajes)</option>
            </select>
          </div>
        </div>

        {/* Category Visibility Filter Chips */}
        <div className="disc-category-chips" role="group" aria-label="Mostrar u ocultar categorías de recursos">
          <span className="toolbar-label">Categorías:</span>
          {(graphData?.categories || []).map((cat) => {
            if (cat.id === "asset") return null;
            const isHidden = hiddenCategories.includes(cat.id);
            return (
              <button
                key={cat.id}
                type="button"
                className={`disc-cat-chip ${isHidden ? "is-hidden" : "is-visible"}`}
                onClick={() => handleToggleCategory(cat.id)}
                aria-pressed={!isHidden}
              >
                <span>{cat.label}</span>
                <span className="disc-cat-count">{cat.count}</span>
              </button>
            );
          })}
          {hiddenCategories.length > 0 && (
            <button
              type="button"
              className="disc-reset-cats-btn"
              onClick={() => setHiddenCategories([])}
            >
              Mostrar todas
            </button>
          )}
        </div>
      </div>

      {/* Main Stage + Legend + Node Inspector Drawer */}
      <div className="disc-stage-wrap">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          fitView
          minZoom={0.15}
          maxZoom={1.75}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} color="#cbd4e1" gap={22} size={1.2} />
          <Controls showInteractive={false} className="arch-flow-controls" />
          <MiniMap
            pannable
            zoomable
            className="arch-flow-minimap"
            nodeBorderRadius={6}
            nodeColor={(n) => {
              const nodeObj = n.data?.node;
              if (!nodeObj) return "#94a3b8";
              if (nodeObj.type === "host") return "#0f172a";
              const cat = nodeObj.metadata?.category_group || nodeObj.category;
              return CATEGORY_META[cat]?.accent || "#64748b";
            }}
          />
        </ReactFlow>

        {/* Floating Legend */}
        {showLegend && (
          <aside className="disc-diagram-legend" aria-label="Leyenda semántica del grafo">
            <div className="disc-legend-header">
              <strong>Leyenda Semántica y Evidencia</strong>
              <button type="button" onClick={() => setShowLegend(false)} aria-label="Cerrar leyenda">
                &times;
              </button>
            </div>
            <div className="disc-legend-section">
              <span className="disc-legend-subtitle">Tipos de relación</span>
              <ul className="disc-legend-list">
                <li>
                  <span className="disc-line-sample is-solid-slate" />
                  <span><strong>Contains:</strong> Pertenencia estructural confirmada</span>
                </li>
                <li>
                  <span className="disc-line-sample is-solid-green" />
                  <span><strong>Has interface:</strong> Interfaz de red observada</span>
                </li>
                <li>
                  <span className="disc-line-sample is-dashed-blue" />
                  <span><strong>Routes to:</strong> Ruta en tabla de encaminamiento</span>
                </li>
                <li>
                  <span className="disc-line-sample is-solid-amber" />
                  <span><strong>Listens on:</strong> Proceso ↔ Puerto confirmado por PID</span>
                </li>
                <li>
                  <span className="disc-line-sample is-dashed-red" />
                  <span><strong>Observed connection:</strong> Socket puntual (No confirma dependencia)</span>
                </li>
                <li>
                  <span className="disc-line-sample is-dotted-teal" />
                  <span><strong>Inferred / Derived:</strong> Subred por máscara o montaje</span>
                </li>
              </ul>
            </div>
            <div className="disc-legend-footer">
              <span>Nodos visibles: <strong>{visibleNodes.length}</strong> / {rawNodes.length}</span>
              <span>Aristas: <strong>{flowEdges.length}</strong></span>
            </div>
          </aside>
        )}

        {/* Selected Node Side Panel */}
        {selectedNode && (
          <aside className="disc-node-drawer" aria-label={`Detalle del nodo ${selectedNode.name}`}>
            <div className="disc-drawer-header">
              <div>
                <span className="disc-drawer-type-badge">
                  {selectedNode.type.toUpperCase()} · Nivel {selectedNode.level}
                </span>
                <h3 className="disc-drawer-title">{selectedNode.name}</h3>
              </div>
              <button
                type="button"
                className="drawer-close-btn"
                onClick={() => setSelectedNode(null)}
                aria-label="Cerrar detalle"
              >
                &times;
              </button>
            </div>

            <div className="disc-drawer-body">
              <div className="disc-drawer-actions-bar">
                <StateBadge state={selectedNode.metadata?.data_state || "observed"} />
                {selectedNode.metadata?.section_target && (
                  <button
                    type="button"
                    className="tech-btn primary"
                    onClick={() =>
                      onNavigateToSection(
                        selectedNode.metadata.section_target,
                        selectedNode.metadata.subsection_target
                      )
                    }
                  >
                    Ir a sección detallada ({selectedNode.metadata.section_target.toUpperCase()}) &rarr;
                  </button>
                )}
              </div>

              {selectedNode.metadata?.explanation && (
                <ExplanationCard
                  explanation={selectedNode.metadata.explanation}
                  defaultExpanded={true}
                  compact={true}
                />
              )}

              {selectedNode.metadata?.details &&
                Object.keys(selectedNode.metadata.details).length > 0 && (
                  <div className="disc-drawer-box">
                    <h4>Atributos reales observados</h4>
                    <div className="disc-kv-list">
                      {Object.entries(selectedNode.metadata.details).map(([k, v]) => {
                        if (v === null || v === undefined || k === "explanation") return null;
                        const valStr =
                          typeof v === "object" ? JSON.stringify(v) : String(v);
                        return (
                          <div key={k} className="disc-kv-row">
                            <span className="disc-kv-key">{k}</span>
                            <code className="disc-kv-val">{valStr}</code>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

              <div className="disc-drawer-box">
                <h4>Relaciones y evidencia ({selectedNodeEdges.length})</h4>
                <ul className="disc-edge-evidence-list">
                  {selectedNodeEdges.map((edge) => {
                    const isOutgoing = edge.source === selectedNode.id;
                    const peerId = isOutgoing ? edge.target : edge.source;
                    const peerNode = rawNodes.find((n) => n.id === peerId);
                    return (
                      <li key={edge.id} className="disc-edge-evidence-item">
                        <div className="disc-edge-ev-top">
                          <span className={`disc-rel-pill is-${edge.metadata?.nature || "confirmed"}`}>
                            {edge.type}
                          </span>
                          <span className="disc-edge-ev-badge">{edge.metadata?.badge}</span>
                        </div>
                        <div className="disc-edge-ev-peer">
                          {isOutgoing ? "Hacia: " : "Desde: "}
                          <button
                            type="button"
                            className="tech-link-btn"
                            onClick={() => peerNode && setSelectedNode(peerNode)}
                          >
                            {peerNode ? peerNode.name : peerId}
                          </button>
                        </div>
                        <p className="disc-edge-ev-text">{edge.metadata?.evidence}</p>
                        {edge.metadata?.uncertainty_note && (
                          <p className="disc-edge-ev-warn">
                            Nota: {edge.metadata.uncertainty_note}
                          </p>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

export default function DiscoveryDiagramCanvas(props) {
  return (
    <ReactFlowProvider>
      <InnerDiscoveryDiagram {...props} />
    </ReactFlowProvider>
  );
}
