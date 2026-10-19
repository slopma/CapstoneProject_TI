import React, { useMemo, useState, useCallback } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import ArchitectureNode from "./architecture/ArchitectureNode";
import { computeStratifiedLayout } from "../utils/graphLayout";

const nodeTypes = {
  hierarchical: ArchitectureNode,
};

function ArchitectureGraph({
  nodes = [],
  edges = [],
  selectedNodes = [],
  expandedNodeIds = [],
  onNodeClick,
  onToggleExpand,
}) {
  const [hoveredNodeId, setHoveredNodeId] = useState(null);
  const [isMoving, setIsMoving] = useState(false);

  const childCountMap = useMemo(() => {
    const map = {};
    nodes.forEach((n) => {
      if (Array.isArray(n.children_ids) && n.children_ids.length > 0) {
        map[n.id] = n.children_ids.length;
      }
      if (n.parent_id) {
        map[n.parent_id] = (map[n.parent_id] || 0) + 1;
      }
    });
    return map;
  }, [nodes]);

  const activeFocusSet = useMemo(() => {
    const set = new Set();
    if (hoveredNodeId) {
      set.add(hoveredNodeId);
    } else if (selectedNodes.length > 0) {
      selectedNodes.forEach((id) => set.add(id));
    }
    return set;
  }, [hoveredNodeId, selectedNodes]);

  const relatedNodeIds = useMemo(() => {
    if (activeFocusSet.size === 0) return new Set();
    const related = new Set(activeFocusSet);

    edges.forEach((e) => {
      if (activeFocusSet.has(e.source)) related.add(e.target);
      if (activeFocusSet.has(e.target)) related.add(e.source);
    });

    return related;
  }, [activeFocusSet, edges]);

  const handleHoverEnter = useCallback((nodeId) => {
    setHoveredNodeId(nodeId);
  }, []);

  const handleHoverLeave = useCallback(() => {
    setHoveredNodeId(null);
  }, []);

  const { nodes: positionedNodes, edges: flowEdges } = useMemo(() => {
    return computeStratifiedLayout(nodes, edges, {
      activeNodeIds: activeFocusSet,
    });
  }, [nodes, edges, activeFocusSet]);

  const flowNodes = useMemo(() => {
    const hasFilter = activeFocusSet.size > 0;

    return positionedNodes.map((node) => {
      const childCount = childCountMap[node.id] || 0;
      const isSelected = selectedNodes.includes(node.id);
      const isRelated = relatedNodeIds.has(node.id);
      const isDimmed = hasFilter && !isRelated;

      return {
        id: node.id,
        type: "hierarchical",
        position: node.computedPosition,
        style: {
          width: node.computedWidth,
          height: node.computedHeight,
        },
        data: {
          node,
          selected: isSelected,
          isExpanded: expandedNodeIds.includes(node.id),
          hasChildren: false,
          isCollapsedContainer: false,
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
    childCountMap,
    selectedNodes,
    expandedNodeIds,
    activeFocusSet.size,
    relatedNodeIds,
    onNodeClick,
    onToggleExpand,
    handleHoverEnter,
    handleHoverLeave,
  ]);

  return (
    <div
      className="canvas-wrapper-container arch-standalone-graph"
      data-ui="architecture-graph"
    >
      <div
        className={`canvas-interactive-stage ${isMoving ? "is-panning" : ""}`}
        style={{ width: "100%", height: "100%" }}
      >
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.18, maxZoom: 1 }}
          nodesDraggable={true}
          nodesConnectable={false}
          elementsSelectable={true}
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
            nodeColor={(n) =>
              selectedNodes.includes(n.id) ? "#1d4ed8" : "#94a3b8"
            }
            maskColor="rgba(239, 242, 246, 0.78)"
          />
        </ReactFlow>
      </div>
    </div>
  );
}

export default ArchitectureGraph;