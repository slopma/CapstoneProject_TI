import React, { useMemo, useCallback, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useReactFlow,
  ReactFlowProvider,
  SelectionMode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import ArchitectureNode from "./ArchitectureNode";
import { computeHierarchicalLayout } from "../../utils/graphLayout";

const nodeTypes = {
  techNode: ArchitectureNode,
};

function InnerCanvas({
  nodes,
  edges,
  selectedNodes,
  expandedNodeIds,
  onNodeClick,
  onToggleExpand,
  zoomTargetId,
}) {
  const { fitView, fitBounds } = useReactFlow();

  // Child count map
  const childCountMap = useMemo(() => {
    const map = {};
    nodes.forEach((n) => {
      if (n.parent_id) {
        map[n.parent_id] = (map[n.parent_id] || 0) + 1;
      }
    });
    return map;
  }, [nodes]);

  // Compute non-overlapping Top->Down Dagre Layout
  const { nodes: positionedNodes, edges: formattedEdges } = useMemo(() => {
    return computeHierarchicalLayout(nodes, edges, {
      rankSpacing: 200,
      nodeSpacing: 300,
      startY: 80,
      canvasWidth: 1400,
    });
  }, [nodes, edges]);

  const flowNodes = useMemo(() => {
    return positionedNodes.map((node) => {
      const childCount = childCountMap[node.id] || 0;
      return {
        id: node.id,
        type: "techNode",
        position: node.computedPosition,
        data: {
          node,
          selected: selectedNodes.includes(node.id),
          isExpanded: expandedNodeIds.includes(node.id),
          hasChildren: childCount > 0,
          childCount: childCount,
          onSelect: onNodeClick,
          onToggleExpand: onToggleExpand,
        },
      };
    });
  }, [positionedNodes, childCountMap, selectedNodes, expandedNodeIds, onNodeClick, onToggleExpand]);

  const smoothZoomToNode = useCallback(
    (targetId) => {
      const targetNode = flowNodes.find((n) => n.id === targetId);
      if (targetNode) {
        const padding = 140;
        const bounds = {
          x: targetNode.position.x - padding,
          y: targetNode.position.y - padding,
          width: 300 + padding * 2,
          height: 180 + padding * 2,
        };
        fitBounds(bounds, { duration: 600 });
      } else {
        fitView({ padding: 0.2, duration: 600 });
      }
    },
    [flowNodes, fitBounds, fitView]
  );

  useEffect(() => {
    if (zoomTargetId) {
      smoothZoomToNode(zoomTargetId);
    }
  }, [zoomTargetId, smoothZoomToNode]);

  return (
    <ReactFlow
      nodes={flowNodes}
      edges={formattedEdges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.25 }}
      nodesDraggable={true}
      nodesConnectable={false}
      elementsSelectable={true}
      selectionOnDrag={true}
      selectionMode={SelectionMode.Partial}
      panOnScroll={false}
    >
      <Background color="#cbd5e1" gap={24} size={1} />
      <Controls />
      <MiniMap
        pannable
        zoomable
        nodeColor={(n) => (selectedNodes.includes(n.id) ? "#2563eb" : "#94a3b8")}
        maskColor="rgba(248, 250, 252, 0.7)"
      />
    </ReactFlow>
  );
}

function ArchitectureCanvas(props) {
  return (
    <div className="canvas-wrapper-container">
      <ReactFlowProvider>
        <InnerCanvas {...props} />
      </ReactFlowProvider>
    </div>
  );
}

export default ArchitectureCanvas;
