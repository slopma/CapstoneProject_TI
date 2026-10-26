import React, { useMemo, useCallback, useEffect, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useReactFlow,
  ReactFlowProvider,
  SelectionMode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import ArchitectureNode from "./ArchitectureNode";
import {
  computeHierarchicalLayout,
  projectVisibleEdges,
} from "../../utils/graphLayout";

const nodeTypes = {
  techNode: ArchitectureNode,
};

function prefersReducedMotion() {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function InnerCanvas({
  nodes = [],
  edges = [],
  allNodes,
  allEdges,
  selectedNodes = [],
  expandedNodeIds = [],
  onNodeClick,
  onToggleExpand,
  zoomTargetId,
  highlightDeps = true,
  showLegend = true,
  onCloseLegend,
}) {
  const { fitView, fitBounds } = useReactFlow();
  const [hoveredNodeId, setHoveredNodeId] = useState(null);
  const [isMoving, setIsMoving] = useState(false);

  const canonicalNodes = allNodes && allNodes.length > 0 ? allNodes : nodes;
  const canonicalEdges = allEdges && allEdges.length > 0 ? allEdges : edges;

  const { allNodesMap, totalChildCountMap } = useMemo(() => {
    const nMap = {};
    const countMap = {};

    canonicalNodes.forEach((n) => {
      nMap[n.id] = n;
      if (Array.isArray(n.children_ids) && n.children_ids.length > 0) {
        countMap[n.id] = n.children_ids.length;
      }
    });

    canonicalNodes.forEach((n) => {
      const pId = n.parent_id || n.parent;
      if (pId) {
        countMap[pId] = Math.max(
          countMap[pId] || 0,
          canonicalNodes.filter((item) => (item.parent_id || item.parent) === pId).length
        );
      }
    });

    return { allNodesMap: nMap, totalChildCountMap: countMap };
  }, [canonicalNodes]);

  const visibleNodeIds = useMemo(
    () => new Set(nodes.map((n) => n.id)),
    [nodes]
  );

  const effectiveEdges = useMemo(() => {
    return projectVisibleEdges(canonicalEdges, visibleNodeIds, allNodesMap);
  }, [canonicalEdges, visibleNodeIds, allNodesMap]);

  const activeFocusSet = useMemo(() => {
    const set = new Set();
    if (!highlightDeps) return set;
    if (hoveredNodeId) {
      set.add(hoveredNodeId);
    } else if (selectedNodes.length > 0) {
      selectedNodes.forEach((id) => set.add(id));
    }
    return set;
  }, [hoveredNodeId, selectedNodes, highlightDeps]);

  const relatedNodeIds = useMemo(() => {
    if (activeFocusSet.size === 0) return new Set();
    const related = new Set(activeFocusSet);

    effectiveEdges.forEach((e) => {
      if (!e.is_hierarchy) {
        if (activeFocusSet.has(e.source)) related.add(e.target);
        if (activeFocusSet.has(e.target)) related.add(e.source);
      }
    });

    Array.from(related).forEach((id) => {
      let curr = allNodesMap[id];
      while (curr) {
        const pId = curr.parent_id || curr.parent;
        if (pId && allNodesMap[pId]) {
          related.add(pId);
          curr = allNodesMap[pId];
        } else {
          break;
        }
      }
    });

    return related;
  }, [activeFocusSet, effectiveEdges, allNodesMap]);

  const { nodes: positionedNodes, edges: formattedEdges } = useMemo(() => {
    return computeHierarchicalLayout(nodes, effectiveEdges, {
      rootStartX: 64,
      rootStartY: 64,
      rootGapX: 88,
      activeNodeIds: activeFocusSet,
      totalChildCountMap,
    });
  }, [nodes, effectiveEdges, activeFocusSet, totalChildCountMap]);

  const handleHoverEnter = useCallback((nodeId) => {
    setHoveredNodeId(nodeId);
  }, []);

  const handleHoverLeave = useCallback(() => {
    setHoveredNodeId(null);
  }, []);

  const flowNodes = useMemo(() => {
    const hasFilter = activeFocusSet.size > 0;

    return positionedNodes.map((node) => {
      const childCount =
        totalChildCountMap[node.id] ??
        (Array.isArray(node.children_ids) ? node.children_ids.length : 0);
      const hasChildren = Boolean(node.hasChildren || childCount > 0);
      const isExpanded = expandedNodeIds.includes(node.id);
      const isCollapsedContainer = Boolean(
        node.isCollapsedContainer || (hasChildren && !isExpanded)
      );
      const isSelected = selectedNodes.includes(node.id);
      const isRelated = relatedNodeIds.has(node.id);
      const isDimmed =
        hasFilter && !isRelated && (!hasChildren || isCollapsedContainer);

      return {
        id: node.id,
        type: "techNode",
        position: node.computedPosition,
        parentId: node.parent_id || undefined,
        extent: node.parent_id ? "parent" : undefined,
        style: {
          width: node.computedWidth,
          height: node.computedHeight,
          zIndex: isSelected
            ? (node.zIndex || 1) + 20
            : node.zIndex || (node.parent_id ? 10 : 1),
        },
        data: {
          node,
          selected: isSelected,
          isExpanded,
          hasChildren,
          isCollapsedContainer,
          childCount,
          depth: node.depth ?? 0,
          staggerIndex: node.staggerIndex ?? 0,
          isDimmed,
          isRelated,
          onSelect: onNodeClick,
          onToggleExpand,
          onHoverEnter: handleHoverEnter,
          onHoverLeave: handleHoverLeave,
        },
      };
    });
  }, [
    positionedNodes,
    totalChildCountMap,
    selectedNodes,
    expandedNodeIds,
    activeFocusSet.size,
    relatedNodeIds,
    onNodeClick,
    onToggleExpand,
    handleHoverEnter,
    handleHoverLeave,
  ]);

  const handleRecenterView = useCallback(() => {
    const duration = prefersReducedMotion() ? 0 : 240;
    fitView({ padding: 0.16, duration, maxZoom: 1 });
  }, [fitView]);

  const smoothZoomToNode = useCallback(
    (targetId) => {
      const duration = prefersReducedMotion() ? 0 : 260;
      const targetNode = positionedNodes.find((n) => n.id === targetId);

      if (targetNode && targetNode.absolutePosition) {
        const padding = 140;
        const bounds = {
          x: targetNode.absolutePosition.x - padding,
          y: targetNode.absolutePosition.y - padding,
          width: (targetNode.computedWidth || 268) + padding * 2,
          height: (targetNode.computedHeight || 86) + padding * 2,
        };
        fitBounds(bounds, { duration, maxZoom: 0.96 });
      } else {
        fitView({ padding: 0.16, duration, maxZoom: 1 });
      }
    },
    [positionedNodes, fitBounds, fitView]
  );

  useEffect(() => {
    if (zoomTargetId) {
      smoothZoomToNode(zoomTargetId);
    }
  }, [zoomTargetId, smoothZoomToNode]);

  if (nodes.length === 0) {
    return (
      <div className="canvas-empty-state" role="status">
        <p className="canvas-empty-title">Sin recursos visibles en el lienzo</p>
        <p className="canvas-empty-copy">
          Ajusta el filtro de búsqueda o despliega los contenedores raíz para explorar la topología.
        </p>
      </div>
    );
  }

  return (
    <div
      className={`canvas-interactive-stage ${isMoving ? "is-panning" : ""}`}
      style={{ width: "100%", height: "100%", position: "relative" }}
    >
      <ReactFlow
        nodes={flowNodes}
        edges={formattedEdges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.16, maxZoom: 1 }}
        minZoom={0.18}
        maxZoom={1.6}
        nodesDraggable={true}
        nodesConnectable={false}
        elementsSelectable={true}
        selectionOnDrag={true}
        selectionMode={SelectionMode.Partial}
        panOnScroll={true}
        onMoveStart={() => setIsMoving(true)}
        onMoveEnd={() => setIsMoving(false)}
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          color="#cbd4e1"
          gap={24}
          size={1.2}
        />
        <Controls showInteractive={false} className="arch-flow-controls" />
        <MiniMap
          pannable
          zoomable
          className="arch-flow-minimap"
          nodeBorderRadius={6}
          nodeColor={(n) => {
            if (selectedNodes.includes(n.id)) return "#1d4ed8";
            if (n.data?.hasChildren) return "#cbd4e1";
            return "#94a3b8";
          }}
          maskColor="rgba(239, 242, 246, 0.78)"
        />
      </ReactFlow>

      {/* Leyenda Semántica y de Procedencia Epistémica */}
      {showLegend && (
        <aside className="cm-canvas-legend" aria-label="Leyenda del grafo de arquitectura">
          <div className="cm-canvas-legend-header">
            <span>Leyenda Semántica y Procedencia CMIR v2.1</span>
            {onCloseLegend && (
              <button
                type="button"
                onClick={onCloseLegend}
                style={{ background: "none", border: "none", cursor: "pointer", fontWeight: 700, fontSize: 14 }}
                aria-label="Cerrar leyenda"
              >
                ×
              </button>
            )}
          </div>
          <div className="cm-legend-row">
            <span className="cm-legend-line" />
            <span>Dependencia <strong>Confirmada / Observada</strong> (Manifiesto / Socket PID)</span>
          </div>
          <div className="cm-legend-row">
            <span className="cm-legend-line dashed" />
            <span>Dependencia <strong>Inferida</strong> (SDK / Heurística — No confirmada)</span>
          </div>
          <div className="cm-legend-row">
            <span className="cm-legend-line hierarchy" />
            <span>Relación <strong>Proyectada / Agrupada</strong> (Contenedor plegado)</span>
          </div>
          <div className="cm-legend-row" style={{ marginTop: 4 }}>
            <span className="cm-legend-swatch" style={{ background: "#ffedd5", border: "1px solid #fb923c" }} />
            <span>Recurso <strong>Compartido Protegido</strong> (Requiere validación)</span>
          </div>
          <div className="cm-legend-row">
            <span className="cm-legend-swatch" style={{ background: "#eff6ff", border: "2px solid #2563eb" }} />
            <span>Carga <strong>Seleccionada</strong> + Resaltado de alcance</span>
          </div>
        </aside>
      )}

      <div className="canvas-hud-bar" aria-label="Resumen de topología en lienzo">
        <span className="hud-stat">
          <strong>{nodes.length}</strong> recursos visibles
        </span>
        <span className="hud-sep" aria-hidden="true">·</span>
        <span className="hud-stat">
          <strong>{formattedEdges.length}</strong> relaciones
        </span>
        <button
          type="button"
          className="hud-recenter-btn"
          onClick={handleRecenterView}
          title="Encuadrar toda la arquitectura visible"
        >
          Encuadrar vista
        </button>
      </div>
    </div>
  );
}

function ArchitectureCanvas(props) {
  return (
    <div className="canvas-wrapper-container" data-ui="architecture-canvas">
      <ReactFlowProvider>
        <InnerCanvas {...props} />
      </ReactFlowProvider>
    </div>
  );
}

export default ArchitectureCanvas;
