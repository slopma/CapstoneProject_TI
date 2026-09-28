/**
 * Graph Layout Engine for CloudMove
 * Calculates hierarchical non-overlapping Top->Down positions for nodes & orthogonal edge routing.
 */

export function computeHierarchicalLayout(nodes, edges, options = {}) {
  const rankSpacing = options.rankSpacing || 200;
  const nodeSpacing = options.nodeSpacing || 300;
  const startY = options.startY || 80;
  const canvasWidth = options.canvasWidth || 1400;

  // Group nodes by hierarchy level / rank
  const levelGroups = {};
  nodes.forEach((n) => {
    const lvl = n.level ?? 8;
    if (!levelGroups[lvl]) levelGroups[lvl] = [];
    levelGroups[lvl].push(n);
  });

  const sortedLevels = Object.keys(levelGroups)
    .map(Number)
    .sort((a, b) => a - b);

  // Position nodes by rank symmetrically
  const positionedNodes = [];
  const positionMap = {};

  sortedLevels.forEach((lvl, rowIdx) => {
    const group = levelGroups[lvl];
    const totalRowWidth = (group.length - 1) * nodeSpacing;
    const startX = Math.max(100, (canvasWidth - totalRowWidth) / 2);

    group.forEach((node, colIdx) => {
      let x = startX + colIdx * nodeSpacing;
      let y = startY + rowIdx * rankSpacing;

      // If node has parent, adjust X towards parent's X if single child
      if (node.parent_id && positionMap[node.parent_id]) {
        const parentPos = positionMap[node.parent_id];
        const siblings = group.filter((g) => g.parent_id === node.parent_id);
        if (siblings.length === 1) {
          x = parentPos.x;
        }
      }

      positionMap[node.id] = { x, y };

      positionedNodes.push({
        ...node,
        computedPosition: { x, y },
      });
    });
  });

  // Configure Orthogonal Step Edges without overlapping nodes
  const formattedEdges = edges.map((e) => {
    const isHierarchy = e.is_hierarchy;
    return {
      id: `${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      type: "smoothstep", // Orthogonal routing to prevent diagonal lines cutting across nodes
      label: isHierarchy ? "contains" : e.type || "depends_on",
      animated: !isHierarchy,
      style: {
        stroke: isHierarchy ? "#94a3b8" : "#2563eb",
        strokeWidth: isHierarchy ? 1.8 : 2.5,
        strokeDasharray: isHierarchy ? "6 6" : undefined,
      },
      labelStyle: {
        fill: "#0f172a",
        fontWeight: 700,
        fontSize: 11,
        fontFamily: "'Inter', monospace",
      },
      labelShowBg: true,
      labelBgStyle: {
        fill: "#ffffff",
        stroke: "#cbd5e1",
        strokeWidth: 1.5,
        rx: 4,
        ry: 4,
      },
      labelBgPadding: [6, 4],
    };
  });

  return {
    nodes: positionedNodes,
    edges: formattedEdges,
  };
}
