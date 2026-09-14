import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";

const resourceMeta = {
  compute: {
    title: "Servidor de aplicación",
    description:
      "Procesa la lógica de negocio, APIs y servicios de la aplicación.",
    accent: "#2563eb",
  },

  database: {
    title: "Base de datos",
    description:
      "Almacena la información persistente de la aplicación.",
    accent: "#7c3aed",
  },

  cache: {
    title: "Caché",
    description:
      "Mantiene datos de acceso frecuente para reducir la latencia.",
    accent: "#0f766e",
  },
};


function ResourceGlyph({ type, accent }) {
  const commonStyle = {
    display: "block",
    width: type === "database" ? 100 : type === "cache" ? 92 : 86,
    height: type === "database" ? 70 : type === "cache" ? 66 : 62,
  };

  if (type === "database") {
    return (
      <svg viewBox="0 0 120 90" aria-hidden="true" style={commonStyle}>
        <ellipse
          cx="60"
          cy="20"
          rx="36"
          ry="12"
          fill="none"
          stroke={accent}
          strokeWidth="3"
        />

        <path
          d="M24 20v48c0 8 16 14 36 14s36-6 36-14V20"
          fill="none"
          stroke={accent}
          strokeWidth="3"
        />

        <path
          d="M24 35c0 8 16 14 36 14s36-6 36-14"
          fill="none"
          stroke={accent}
          strokeWidth="3"
        />
      </svg>
    );
  }

  if (type === "cache") {
    return (
      <svg viewBox="0 0 120 90" aria-hidden="true" style={commonStyle}>
        <rect
          x="22"
          y="25"
          width="76"
          height="14"
          rx="6"
          fill={accent}
          opacity="0.18"
        />

        <rect
          x="22"
          y="42"
          width="76"
          height="14"
          rx="6"
          fill={accent}
          opacity="0.38"
        />

        <rect
          x="22"
          y="59"
          width="76"
          height="14"
          rx="6"
          fill={accent}
          opacity="0.7"
        />

        <path
          d="M18 18h84"
          stroke={accent}
          strokeWidth="3"
          strokeLinecap="round"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 120 90" aria-hidden="true" style={commonStyle}>
      <rect
        x="24"
        y="20"
        width="72"
        height="46"
        rx="10"
        fill="none"
        stroke={accent}
        strokeWidth="3"
      />

      <path
        d="M38 20v-8h44v8"
        fill="none"
        stroke={accent}
        strokeWidth="3"
      />

      <rect
        x="42"
        y="36"
        width="36"
        height="8"
        rx="4"
        fill={accent}
        opacity="0.18"
      />

      <rect
        x="42"
        y="48"
        width="28"
        height="8"
        rx="4"
        fill={accent}
        opacity="0.18"
      />
    </svg>
  );
}


function getNodeDimensions(node) {
  const textLength = `${node.name} ${node.type}`.length;
  const width = Math.min(260, Math.max(210, 120 + textLength * 4.5));
  const descriptionLines = Math.max(1, Math.ceil((metaDescription(node) || "").length / 32));
  const height = Math.min(240, Math.max(180, 150 + descriptionLines * 16));

  if (node.type === "database") {
    return { width: Math.max(width, 220), height: 210 };
  }

  if (node.type === "cache") {
    return { width: Math.max(width, 220), height: 195 };
  }

  return { width: Math.max(width, 230), height: 220 };
}

function metaDescription(node) {
  const meta = resourceMeta[node.type] || {
    description: "Componente que participa en la arquitectura.",
  };

  return meta.description;
}

function ResourceNode({ data }) {
  const { node, selected, onSelect } = data;
  const meta = resourceMeta[node.type] || {
    title: "Servicio",
    description: "Componente que participa en la arquitectura.",
    accent: "#475569",
  };
  const dimensions = getNodeDimensions(node);

  return (
    <>
      <Handle
        type="target"
        position={Position.Top}
        style={{
          background: meta.accent,
          width: 8,
          height: 8,
          border: "none",
        }}
      />

      <button
        type="button"
        onClick={() => onSelect(node.id)}
        style={{
          width: "100%",
          height: "100%",
          minHeight: dimensions.height,
          minWidth: dimensions.width,
          borderRadius: 18,
          border: selected
            ? `2px solid ${meta.accent}`
            : "1px solid #dfe7f3",
          background: selected ? "#f5f9ff" : "#ffffff",
          boxShadow: selected
            ? "0 14px 30px rgba(37, 99, 235, 0.16)"
            : "0 8px 24px rgba(15, 23, 42, 0.07)",
          padding: "14px",
          cursor: "pointer",
          textAlign: "left",
          color: "#0f172a",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 4,
            color: "#475569",
            fontSize: 11,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: meta.accent,
              display: "inline-block",
            }}
          />

          {node.type}
        </div>

        <div
          style={{
            height: node.type === "database" ? 88 : node.type === "cache" ? 80 : 82,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            margin: "8px 0 12px",
            borderRadius: 12,
            background:
              node.type === "database"
                ? "rgba(124, 58, 237, 0.04)"
                : node.type === "cache"
                  ? "rgba(15, 118, 110, 0.04)"
                  : "rgba(37, 99, 235, 0.04)",
          }}
        >
          <ResourceGlyph
            type={node.type}
            accent={meta.accent}
          />
        </div>

        <strong
          style={{
            display: "block",
            fontSize: 14,
            marginBottom: 4,
          }}
        >
          {node.name}
        </strong>

        <span
          style={{
            display: "block",
            fontSize: 11,
            color: "#64748b",
            lineHeight: 1.4,
            whiteSpace: "normal",
            wordBreak: "break-word",
          }}
        >
          {meta.description}
        </span>
      </button>

      <Handle
        type="source"
        position={Position.Bottom}
        style={{
          background: meta.accent,
          width: 8,
          height: 8,
          border: "none",
        }}
      />
    </>
  );
}


const nodeTypes = {
  resource: ResourceNode,
};


function ArchitectureGraph({
  nodes,
  edges,
  selectedNodes,
  onNodeClick,
}) {
  const positions = [
    { x: 350, y: 30 },
    { x: 80, y: 300 },
    { x: 620, y: 300 },
  ];

  const flowNodes = nodes.map((node, index) => {
    const dimensions = getNodeDimensions(node);

    return {
      id: node.id,

      type: "resource",

      position:
        positions[index] || {
          x: 100 + index * 240,
          y: 400,
        },

      style: {
        width: dimensions.width,
        height: dimensions.height,
      },

      data: {
        node,
        selected: selectedNodes.includes(node.id),
        onSelect: onNodeClick,
      },

      draggable: false,
    };
  });

  const flowEdges = edges.map((edge) => ({
    id: `${edge.source}-${edge.target}`,

    source: edge.source,

    target: edge.target,

    label: "depende de",

    animated: true,

    style: {
      stroke: "#94a3b8",
      strokeWidth: 2,
    },

    labelStyle: {
      fill: "#475569",
      fontWeight: 600,
      fontSize: 11,
    },

    labelBgStyle: {
      fill: "#ffffff",
    },
  }));

  return (
    <div
      style={{
        width: "100%",
        height: "560px",
        borderRadius: "18px",
        overflow: "hidden",
        border: "1px solid #e2e8f0",
        background: "#f8fafc",
      }}
    >
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{
          padding: 0.2,
        }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
      >
        <Background
          color="#dfe7f3"
          gap={18}
          size={1}
        />

        <Controls />

        <MiniMap
          pannable
          zoomable
          nodeColor={(node) => {
            return selectedNodes.includes(node.id)
              ? "#2563eb"
              : "#cbd5e1";
          }}
        />
      </ReactFlow>
    </div>
  );
}

export default ArchitectureGraph;