import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

const LEVEL_COLORS = {
  0: "#0f172a", // Dark Slate
  1: "#0f172a", // Datacenter / Provider (Dark)
  2: "#1e293b", // Rack / Physical
  3: "#1d4ed8", // Network / VLAN (Deep Blue)
  4: "#6d28d9", // Cluster / ESXi (Deep Purple)
  5: "#0f766e", // Namespace / Pool (Teal)
  6: "#b45309", // Application (Amber/Orange)
  7: "#2563eb", // Service / VM Workload (Blue)
  8: "#334155", // Atomic Resource (Slate)
};

const TYPE_ICONS = {
  datacenter: "🏢",
  network: "🌐",
  subnet: "🔀",
  security_boundary: "🛡️",
  cluster: "💻",
  namespace: "🏷️",
  application: "🚀",
  service: "⚙️",
  compute: "🖥️",
  workload: "📦",
  database: "🗄️",
  cache: "⚡",
  storage: "💾",
  queue: "📬",
};

function HierarchicalNode({ data }) {
  const { node, selected, isExpanded, hasChildren, childCount, onSelect, onToggleExpand } = data;
  const levelColor = LEVEL_COLORS[node.level ?? 8] || "#334155";
  const icon = TYPE_ICONS[node.type] || "🧱";

  return (
    <div
      className={`custom-hierarchical-node ${selected ? "selected" : ""}`}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(node.id);
      }}
      style={{
        borderRadius: 14,
        border: selected ? `2.5px solid ${levelColor}` : "1.5px solid #94a3b8",
        background: selected ? "#eff6ff" : "#ffffff",
        boxShadow: selected ? "0 10px 25px rgba(37, 99, 235, 0.22)" : "0 4px 14px rgba(15, 23, 42, 0.08)",
        padding: "14px 16px",
        minWidth: 230,
        color: "#0f172a",
        cursor: "pointer",
        position: "relative",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: levelColor, width: 9, height: 9 }} />

      {/* Header Badges */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: 10, fontWeight: 800, background: levelColor, color: "#ffffff", padding: "3px 8px", borderRadius: 4, letterSpacing: "0.04em" }}>
          L{node.level ?? 8} · {node.type?.toUpperCase()}
        </span>
        {node.is_shared && (
          <span style={{ fontSize: 9, fontWeight: 900, background: "#dc2626", color: "#ffffff", padding: "3px 7px", borderRadius: 4 }}>
            COMPARTIDO
          </span>
        )}
      </div>

      {/* Node Main Title */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 22 }}>{icon}</span>
        <strong style={{ fontSize: 14, color: "#0f172a", fontWeight: 800, lineHeight: 1.3, wordBreak: "break-word" }}>
          {node.name}
        </strong>
      </div>

      {/* Progressive Expansion Control Button */}
      {hasChildren && (
        <div style={{ marginTop: 10, paddingTop: 8, borderTop: "1px solid #e2e8f0", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <small style={{ fontSize: 11, fontWeight: 700, color: "#475569" }}>
            {childCount} sub-componentes
          </small>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggleExpand(node.id);
            }}
            style={{
              background: isExpanded ? "#fee2e2" : "#dbeafe",
              color: isExpanded ? "#991b1b" : "#1e40af",
              border: isExpanded ? "1px solid #fca5a5" : "1px solid #93c5fd",
              padding: "4px 10px",
              borderRadius: 6,
              fontSize: 11,
              fontWeight: 800,
              cursor: "pointer",
            }}
          >
            {isExpanded ? "▼ Contraer" : "▶ Desplegar"}
          </button>
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ background: levelColor, width: 9, height: 9 }} />
    </div>
  );
}

const nodeTypes = {
  hierarchical: HierarchicalNode,
};

function ArchitectureGraph({
  nodes,
  edges,
  selectedNodes,
  expandedNodeIds,
  onNodeClick,
  onToggleExpand,
}) {
  // Calculate node child counts
  const childCountMap = {};
  nodes.forEach((n) => {
    if (n.parent_id) {
      childCountMap[n.parent_id] = (childCountMap[n.parent_id] || 0) + 1;
    }
  });

  // Level layout calculation
  const levelGroups = {};
  nodes.forEach((n) => {
    const lvl = n.level ?? 8;
    if (!levelGroups[lvl]) levelGroups[lvl] = [];
    levelGroups[lvl].push(n);
  });

  const sortedLevels = Object.keys(levelGroups).map(Number).sort((a, b) => a - b);

  const flowNodes = [];
  sortedLevels.forEach((lvl, rowIdx) => {
    const group = levelGroups[lvl];
    group.forEach((node, colIdx) => {
      const childCount = childCountMap[node.id] || 0;
      flowNodes.push({
        id: node.id,
        type: "hierarchical",
        position: {
          x: 120 + colIdx * 280,
          y: 60 + rowIdx * 170,
        },
        data: {
          node,
          selected: selectedNodes.includes(node.id),
          isExpanded: expandedNodeIds.includes(node.id),
          hasChildren: childCount > 0,
          childCount: childCount,
          onSelect: onNodeClick,
          onToggleExpand: onToggleExpand,
        },
      });
    });
  });

  const flowEdges = edges.map((e) => {
    const isHierarchy = e.is_hierarchy;
    return {
      id: `${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      label: isHierarchy ? "contiene" : e.type || "depende de",
      animated: !isHierarchy,
      style: {
        stroke: isHierarchy ? "#94a3b8" : "#2563eb",
        strokeWidth: isHierarchy ? 1.8 : 2.2,
        strokeDasharray: isHierarchy ? "5 5" : undefined,
      },
      labelStyle: { fill: "#1e293b", fontWeight: 700, fontSize: 11 },
      labelBgStyle: { fill: "#ffffff", stroke: "#cbd5e1" },
    };
  });

  return (
    <div style={{ width: "100%", height: "640px", borderRadius: "16px", overflow: "hidden", border: "1.5px solid #cbd5e1", background: "#f8fafc" }}>
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={true}
        nodesConnectable={false}
        elementsSelectable={true}
      >
        <Background color="#cbd5e1" gap={24} size={1} />
        <Controls />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) => (selectedNodes.includes(n.id) ? "#2563eb" : "#64748b")}
        />
      </ReactFlow>
    </div>
  );
}

export default ArchitectureGraph;