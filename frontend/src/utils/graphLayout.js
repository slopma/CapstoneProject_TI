/**
 * Architectural Topology & Nested Hierarchical Layout Engine
 * Designed following Archify structural principles:
 * - Bottom-up container sizing with 3-band semantic stratification (Ingress/Network → Compute/Services → Persistence/Data)
 * - Upstream-to-downstream sub-container stacking to prevent overly wide horizontal strips and minimize edge crossings
 * - Barycenter horizontal ordering within tiers so callers align directly above their downstream dependencies
 * - Cross-hierarchy edge projection when containers are collapsed so dependency topology never disappears
 * - Tonal depth assignment (depth 0..N) for visual containment hierarchy
 * - Vector-based 4-way handle routing (top, bottom, left, right)
 */

export const EDGE_LABELS = {
  depends_on: "Depende de",
  routes_to: "Enruta hacia",
  authenticates: "Autentica con",
  persists_to: "Persiste en",
  replicates: "Replica en",
  connects_to: "Conecta con",
  member_of: "Asociado a",
};

export const RESOURCE_TYPE_LABELS = {
  datacenter: "Centro de datos",
  provider: "Proveedor cloud",
  region: "Región cloud",
  network: "Red virtual",
  vpc: "Red VPC",
  vnet: "Red VNet",
  subnet: "Subred",
  security_boundary: "Perímetro de seguridad",
  security_group: "Grupo de seguridad",
  cluster: "Clúster de cómputo",
  kubernetes_cluster: "Clúster Kubernetes",
  namespace: "Espacio de nombres",
  kubernetes_namespace: "Namespace K8s",
  application: "Sistema de aplicación",
  service: "Servicio de dominio",
  compute: "Instancia de cómputo",
  workload: "Carga de trabajo",
  database: "Base de datos",
  cache: "Caché en memoria",
  storage: "Almacenamiento",
  queue: "Cola de mensajes",
};

export const FALLBACK_ENTERPRISE_ARCHITECTURE = {
  architecture_name: "On-Premise Enterprise Datacenter",
  provider: "on-premise",
  nodes: [
    {
      id: "onprem-dc",
      name: "Datacenter On-Premise Principal",
      type: "datacenter",
      level: 1,
      provider: "on-premise",
      location: "Sede Central · DC-A",
      environment: "production",
      children_ids: ["rack-infra"],
    },
    {
      id: "rack-infra",
      name: "Rack A1 · Infraestructura Física",
      type: "datacenter",
      level: 2,
      parent_id: "onprem-dc",
      provider: "on-premise",
      location: "Sala de Servidores 1",
      children_ids: ["vlan-prod", "nfs-storage"],
    },
    {
      id: "vlan-prod",
      name: "Red VLAN Producción (192.168.10.0/24)",
      type: "network",
      level: 3,
      parent_id: "rack-infra",
      provider: "on-premise",
      cidr: "192.168.10.0/24",
      children_ids: ["subnet-internal", "firewall-dmz", "vmware-cluster"],
    },
    {
      id: "subnet-internal",
      name: "Subred Interna Servidores",
      type: "subnet",
      level: 3,
      parent_id: "vlan-prod",
      provider: "on-premise",
      cidr: "192.168.10.100/28",
      children_ids: [],
    },
    {
      id: "firewall-dmz",
      name: "Firewall Perimetral & DMZ",
      type: "security_boundary",
      level: 3,
      parent_id: "vlan-prod",
      provider: "on-premise",
      platform: "pfSense HA",
      children_ids: [],
    },
    {
      id: "vmware-cluster",
      name: "Clúster Virtualización VMware ESXi",
      type: "cluster",
      level: 4,
      parent_id: "vlan-prod",
      provider: "on-premise",
      engine: "vSphere 8.0",
      children_ids: ["ns-core-apps", "ns-data-services"],
    },
    {
      id: "ns-core-apps",
      name: "Pool de Recursos · Core Applications",
      type: "namespace",
      level: 5,
      parent_id: "vmware-cluster",
      provider: "on-premise",
      children_ids: ["erp-system"],
    },
    {
      id: "ns-data-services",
      name: "Pool de Recursos · Data Services",
      type: "namespace",
      level: 5,
      parent_id: "vmware-cluster",
      provider: "on-premise",
      children_ids: ["postgres-db", "redis-cache", "rabbitmq-broker"],
    },
    {
      id: "erp-system",
      name: "Sistema ERP & Servicios Centrales",
      type: "application",
      level: 6,
      parent_id: "ns-core-apps",
      provider: "on-premise",
      children_ids: ["auth-jwt-srv", "backend-api-vm", "batch-worker-vm"],
    },
    {
      id: "auth-jwt-srv",
      name: "Servicio Autenticación JWT",
      type: "service",
      level: 7,
      parent_id: "erp-system",
      provider: "on-premise",
      platform: "Node.js · Express",
      children_ids: [],
    },
    {
      id: "backend-api-vm",
      name: "VM Servidor Backend API",
      type: "compute",
      level: 7,
      parent_id: "erp-system",
      provider: "on-premise",
      platform: "Ubuntu 22.04 LTS",
      children_ids: [],
    },
    {
      id: "batch-worker-vm",
      name: "VM Procesamiento Batch",
      type: "workload",
      level: 7,
      parent_id: "erp-system",
      provider: "on-premise",
      platform: "Python Worker",
      children_ids: [],
    },
    {
      id: "redis-cache",
      name: "Servidor Caché Redis On-Prem",
      type: "cache",
      level: 8,
      parent_id: "ns-data-services",
      provider: "on-premise",
      engine: "redis-7",
      is_shared: false,
      children_ids: [],
    },
    {
      id: "postgres-db",
      name: "Servidor Base de Datos PostgreSQL",
      type: "database",
      level: 8,
      parent_id: "ns-data-services",
      provider: "on-premise",
      engine: "postgresql-15",
      is_shared: true,
      security: {
        private_only: true,
        encryption_at_rest: true,
      },
      children_ids: [],
    },
    {
      id: "rabbitmq-broker",
      name: "Message Broker RabbitMQ",
      type: "queue",
      level: 8,
      parent_id: "ns-data-services",
      provider: "on-premise",
      engine: "rabbitmq-3.12",
      children_ids: [],
    },
    {
      id: "nfs-storage",
      name: "Almacenamiento SAN/NFS Compartido",
      type: "storage",
      level: 8,
      parent_id: "rack-infra",
      provider: "on-premise",
      engine: "NetApp NFSv4",
      is_shared: true,
      children_ids: [],
    },
  ],
  edges: [
    { source: "backend-api-vm", target: "auth-jwt-srv", type: "depends_on" },
    { source: "backend-api-vm", target: "postgres-db", type: "depends_on" },
    { source: "backend-api-vm", target: "redis-cache", type: "depends_on" },
    { source: "auth-jwt-srv", target: "postgres-db", type: "depends_on" },
    { source: "auth-jwt-srv", target: "redis-cache", type: "depends_on" },
    { source: "batch-worker-vm", target: "rabbitmq-broker", type: "depends_on" },
    { source: "batch-worker-vm", target: "postgres-db", type: "depends_on" },
    { source: "backend-api-vm", target: "nfs-storage", type: "depends_on" },
    { source: "backend-api-vm", target: "firewall-dmz", type: "member_of" },
  ],
};

export function formatEdgeLabel(rawType, aggregatedCount = 1) {
  const normalized = String(rawType || "depends_on").toLowerCase().trim();
  const base =
    EDGE_LABELS[normalized] ||
    normalized.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  return aggregatedCount > 1 ? `${base} · ${aggregatedCount}` : base;
}

export function formatResourceType(rawType) {
  if (!rawType) return "Recurso";
  const key = String(rawType).toLowerCase().trim();
  if (RESOURCE_TYPE_LABELS[key]) return RESOURCE_TYPE_LABELS[key];
  const cleaned = key.replace(/[_-]+/g, " ");
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

export function resolveProviderMeta(node) {
  const raw = [node?.provider, node?.platform, node?.engine, node?.type, node?.name]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  if (raw.includes("aws") || raw.includes("eks") || raw.includes("ebs") || raw.includes("alb")) {
    return {
      id: "aws",
      label: "AWS",
      accent: "var(--color-provider-aws)",
      surface: "var(--color-provider-aws-bg)",
    };
  }
  if (raw.includes("azure") || raw.includes("aks") || raw.includes("agic") || raw.includes("entra")) {
    return {
      id: "azure",
      label: "Azure",
      accent: "var(--color-provider-azure)",
      surface: "var(--color-provider-azure-bg)",
    };
  }
  if (raw.includes("k8s") || raw.includes("kubernetes") || raw.includes("namespace") || raw.includes("pod")) {
    return {
      id: "k8s",
      label: "Kubernetes",
      accent: "var(--color-provider-k8s)",
      surface: "var(--color-provider-k8s-bg)",
    };
  }
  return {
    id: "onprem",
    label: "On-Premise",
    accent: "var(--color-provider-onprem)",
    surface: "var(--color-provider-onprem-bg)",
  };
}

export function resolveArchitecturalDomain(node) {
  const t = String(node?.type || "").toLowerCase();
  const name = String(node?.name || "").toLowerCase();
  if (
    t.includes("database") ||
    t.includes("cache") ||
    t.includes("storage") ||
    t.includes("queue") ||
    name.includes("data")
  ) {
    return "data";
  }
  if (
    t.includes("security") ||
    t.includes("firewall") ||
    t.includes("network") ||
    t.includes("subnet") ||
    t.includes("vpc")
  ) {
    return "network";
  }
  if (
    t.includes("compute") ||
    t.includes("service") ||
    t.includes("workload") ||
    t.includes("app")
  ) {
    return "compute";
  }
  return "infrastructure";
}

export function resolveDomainAccent(domain, providerMeta) {
  if (domain === "data") {
    return {
      accent: "var(--color-domain-data)",
      surface: "var(--color-domain-data-bg)",
    };
  }
  if (domain === "network") {
    return {
      accent: "var(--color-domain-network)",
      surface: "var(--color-domain-network-bg)",
    };
  }
  if (domain === "compute") {
    return {
      accent: "var(--color-domain-compute)",
      surface: "var(--color-domain-compute-bg)",
    };
  }
  return {
    accent: providerMeta.accent,
    surface: providerMeta.surface,
  };
}

/**
 * Projects operational edges onto visible ancestor containers when leaf endpoints
 * are hidden inside collapsed containers. Avoids self-loops and deduplicates edges.
 */
export function projectVisibleEdges(allEdges = [], visibleNodeIds = new Set(), allNodesMap = {}) {
  const findVisibleCarrier = (nodeId) => {
    let currId = nodeId;
    const visited = new Set();
    while (currId && !visited.has(currId)) {
      if (visibleNodeIds.has(currId)) return currId;
      visited.add(currId);
      const nodeObj = allNodesMap[currId];
      currId = nodeObj ? nodeObj.parent_id : null;
    }
    return null;
  };

  const bucketMap = new Map();

  allEdges.forEach((edge) => {
    if (edge.is_hierarchy) return;
    const carrierSource = findVisibleCarrier(edge.source);
    const carrierTarget = findVisibleCarrier(edge.target);

    if (!carrierSource || !carrierTarget || carrierSource === carrierTarget) {
      return;
    }

    const isProjected = carrierSource !== edge.source || carrierTarget !== edge.target;
    const edgeType = edge.type || "depends_on";
    const key = `${carrierSource}:::${carrierTarget}:::${edgeType}`;

    if (!bucketMap.has(key)) {
      bucketMap.set(key, {
        source: carrierSource,
        target: carrierTarget,
        type: edgeType,
        is_hierarchy: false,
        is_projected: isProjected,
        aggregatedCount: 1,
      });
    } else {
      const existing = bucketMap.get(key);
      existing.aggregatedCount += 1;
      existing.is_projected = existing.is_projected || isProjected;
    }
  });

  return Array.from(bucketMap.values());
}

/**
 * Selects optimal source and target handle IDs ("top", "bottom", "left", "right")
 * using the geometric vector between absolute node centers.
 */
function resolveDirectionalHandles(sourceNode, targetNode) {
  if (!sourceNode || !targetNode) {
    return { sourceHandle: "bottom", targetHandle: "top" };
  }

  const sPos = sourceNode.absolutePosition || sourceNode.computedPosition || { x: 0, y: 0 };
  const tPos = targetNode.absolutePosition || targetNode.computedPosition || { x: 0, y: 0 };
  const sW = sourceNode.computedWidth || 268;
  const sH = sourceNode.computedHeight || 88;
  const tW = targetNode.computedWidth || 268;
  const tH = targetNode.computedHeight || 88;

  const sCenterX = sPos.x + sW / 2;
  const sCenterY = sPos.y + sH / 2;
  const tCenterX = tPos.x + tW / 2;
  const tCenterY = tPos.y + tH / 2;

  const dx = tCenterX - sCenterX;
  const dy = tCenterY - sCenterY;

  // Prefer top-down / bottom-up routing whenever vertical separation is significant
  if (Math.abs(dy) >= Math.abs(dx) * 0.55) {
    return dy >= 0
      ? { sourceHandle: "bottom", targetHandle: "top" }
      : { sourceHandle: "top", targetHandle: "bottom" };
  }

  return dx >= 0
    ? { sourceHandle: "right", targetHandle: "left" }
    : { sourceHandle: "left", targetHandle: "right" };
}

/**
 * Formats operational and hierarchical edges with semantic contrast and clean routing.
 */
export function buildFormattedEdges(edges, nodeLookup, options = {}) {
  const activeNodeIds = options.activeNodeIds || new Set();
  const hasActiveFilter = activeNodeIds.size > 0;
  const includeHierarchy = Boolean(options.includeHierarchy);

  return edges
    .filter((e) => includeHierarchy || !e.is_hierarchy)
    .map((e) => {
      const isHierarchy = Boolean(e.is_hierarchy);
      const isAssociation = e.type === "member_of";
      const isProjected = Boolean(e.is_projected);
      const isHighlighted =
        hasActiveFilter &&
        (activeNodeIds.has(e.source) || activeNodeIds.has(e.target));
      const isDimmed = hasActiveFilter && !isHighlighted;

      const sourceNode = nodeLookup[e.source];
      const targetNode = nodeLookup[e.target];
      const { sourceHandle, targetHandle } = resolveDirectionalHandles(
        sourceNode,
        targetNode
      );

      const strokeColor = isHighlighted
        ? "var(--color-edge-highlight, #1d4ed8)"
        : isDimmed
          ? "var(--color-edge-dimmed, #cbd5e1)"
          : isHierarchy || isAssociation
            ? "var(--color-edge-hierarchy, #94a3b8)"
            : "var(--color-edge-default, #64748b)";

      return {
        id: `${e.source}-${e.target}-${e.type || "rel"}`,
        source: e.source,
        target: e.target,
        sourceHandle,
        targetHandle,
        type: "smoothstep",
        pathOptions: {
          borderRadius: 12,
          offset: 18,
        },
        label: isHierarchy
          ? "Contiene"
          : formatEdgeLabel(e.type, e.aggregatedCount || 1),
        animated: !isHierarchy && isHighlighted,
        className: [
          "arch-edge",
          isHighlighted ? "is-highlighted" : "",
          isDimmed ? "is-dimmed" : "",
          isAssociation ? "is-association" : "",
          isProjected ? "is-projected" : "",
        ]
          .filter(Boolean)
          .join(" "),
        style: {
          stroke: strokeColor,
          strokeWidth: isHighlighted ? 2.1 : isHierarchy ? 1.2 : 1.5,
          strokeDasharray:
            isHierarchy || isAssociation
              ? "5 4"
              : isProjected
                ? "6 3"
                : undefined,
          opacity: isDimmed ? 0.22 : isHighlighted ? 1 : 0.85,
        },
        markerEnd: isHierarchy
          ? undefined
          : {
              type: "arrowclosed",
              width: 12,
              height: 12,
              color: strokeColor,
            },
        labelStyle: {
          fill: isHighlighted ? "#0f172a" : "#334155",
          fontWeight: isHighlighted ? 600 : 500,
          fontSize: 11,
          fontFamily: "var(--font-family-sans)",
          letterSpacing: "-0.01em",
          fontVariantNumeric: "tabular-nums",
        },
        labelShowBg: !isDimmed,
        labelBgStyle: {
          fill: isHighlighted ? "#eff6ff" : "#ffffff",
          stroke: isHighlighted ? "#93c5fd" : "#e3e8ef",
          strokeWidth: 1,
          rx: 5,
          ry: 5,
          fillOpacity: isDimmed ? 0 : 0.95,
        },
        labelBgPadding: [6, 3],
      };
    });
}

/**
 * Helper to assign an intrinsic horizontal role rank so connected nodes align
 * cleanly from left to right (e.g. Auth / Security / Cache on left, Primary API / DB in center,
 * Batch / Queue / Async on right).
 */
function resolveHorizontalRoleRank(node) {
  const key = `${node.id} ${node.type} ${node.name}`.toLowerCase();
  if (
    key.includes("auth") ||
    key.includes("redis") ||
    key.includes("cache") ||
    key.includes("firewall") ||
    key.includes("security") ||
    key.includes("public")
  ) {
    return 1;
  }
  if (
    key.includes("api") ||
    key.includes("postgres") ||
    key.includes("database") ||
    key.includes("db") ||
    key.includes("core") ||
    key.includes("internal")
  ) {
    return 2;
  }
  if (
    key.includes("batch") ||
    key.includes("worker") ||
    key.includes("queue") ||
    key.includes("rabbit") ||
    key.includes("sqs") ||
    key.includes("storage") ||
    key.includes("nfs")
  ) {
    return 3;
  }
  return 2;
}

/**
 * Computes nested hierarchical layout for React Flow sub-flows.
 * Stratifies children inside containers into semantic architectural tiers
 * (Band 0: Network/Perimeter, Band 1: Compute/Clusters, Band 2: Data/Storage)
 * and stacks upstream vs. downstream sub-containers vertically for optimal aspect ratio.
 */
export function computeHierarchicalLayout(nodes, edges, options = {}) {
  const rootStartX = options.rootStartX ?? 64;
  const rootStartY = options.rootStartY ?? 64;
  const rootGapX = options.rootGapX ?? 88;
  const activeNodeIds = options.activeNodeIds || new Set();
  const totalChildCountMap = options.totalChildCountMap || {};

  if (!nodes || nodes.length === 0) {
    return { nodes: [], edges: [] };
  }

  const LEAF_WIDTH = 268;
  const LEAF_HEIGHT = 86;
  const COLLAPSED_CONTAINER_WIDTH = 296;
  const COLLAPSED_CONTAINER_HEIGHT = 86;
  const HEADER_HEIGHT = 54;
  const PADDING_X = 26;
  const PADDING_BOTTOM = 26;
  const GAP_X = 24;
  const GAP_Y = 24;

  // 1. Build lookup maps for visible nodes
  const nodeMap = {};
  const childrenMap = {};

  nodes.forEach((n) => {
    nodeMap[n.id] = { ...n };
    childrenMap[n.id] = [];
  });

  const rootNodes = [];

  nodes.forEach((n) => {
    if (n.parent_id && nodeMap[n.parent_id]) {
      childrenMap[n.parent_id].push(nodeMap[n.id]);
    } else {
      rootNodes.push(nodeMap[n.id]);
    }
  });

  // Compute effective max/avg descendant level for each container to stratify
  // upstream application containers above downstream data containers
  function computeEffectiveTier(node) {
    const children = childrenMap[node.id] || [];
    const domain = resolveArchitecturalDomain(node);
    if (children.length === 0) {
      const baseLvl = node.level ?? 8;
      return domain === "data" ? Math.max(baseLvl, 8) : baseLvl;
    }
    const childTiers = children.map(computeEffectiveTier);
    const maxChildTier = Math.max(...childTiers);
    node.effectiveTier = domain === "data" ? Math.max(maxChildTier, 8) : maxChildTier;
    return node.effectiveTier;
  }

  rootNodes.forEach(computeEffectiveTier);

  const sortSiblings = (a, b) => {
    const tierA = a.effectiveTier ?? a.level ?? 8;
    const tierB = b.effectiveTier ?? b.level ?? 8;
    if (tierA !== tierB) return tierA - tierB;
    const rankA = resolveHorizontalRoleRank(a);
    const rankB = resolveHorizontalRoleRank(b);
    if (rankA !== rankB) return rankA - rankB;
    return a.name.localeCompare(b.name);
  };

  Object.keys(childrenMap).forEach((pId) => {
    childrenMap[pId].sort(sortSiblings);
  });
  rootNodes.sort(sortSiblings);

  // 2. Bottom-Up recursive measurement and 3-Band Semantic Stratification
  function measureAndLayoutNode(node) {
    const visibleChildren = childrenMap[node.id] || [];
    const declaredChildrenCount =
      totalChildCountMap[node.id] ??
      (Array.isArray(node.children_ids) ? node.children_ids.length : 0);
    const isContainerResource =
      visibleChildren.length > 0 || declaredChildrenCount > 0;

    // Leaf resource OR collapsed container with no currently visible children
    if (visibleChildren.length === 0) {
      node.hasChildren = isContainerResource;
      node.isCollapsedContainer = isContainerResource;
      node.computedWidth = isContainerResource ? COLLAPSED_CONTAINER_WIDTH : LEAF_WIDTH;
      node.computedHeight = isContainerResource
        ? COLLAPSED_CONTAINER_HEIGHT
        : LEAF_HEIGHT;
      return { width: node.computedWidth, height: node.computedHeight };
    }

    node.hasChildren = true;
    node.isCollapsedContainer = false;

    // Measure all visible children first
    visibleChildren.forEach((child) => {
      measureAndLayoutNode(child);
    });

    // Classify children into 3 architectural bands (Archify hierarchy):
    // Band 0: Ingress, Network & Security Perimeter leaves (level <= 3 or network domain leaves)
    // Band 1: Core Compute, Clusters, Namespaces & Services
    // Band 2: Downstream Data, Storage & Queues (level >= 8 or data domain leaves)
    const band0NetworkLeaves = [];
    const band1CoreContainers = [];
    const band1CoreLeaves = [];
    const band2DataLeaves = [];

    visibleChildren.forEach((child) => {
      const isExpandedChildContainer =
        child.hasChildren && !child.isCollapsedContainer;
      const domain = resolveArchitecturalDomain(child);
      const lvl = child.level ?? 8;

      if (isExpandedChildContainer || child.isCollapsedContainer) {
        band1CoreContainers.push(child);
      } else if (lvl >= 8 || domain === "data") {
        band2DataLeaves.push(child);
      } else if (lvl <= 3 || domain === "network") {
        band0NetworkLeaves.push(child);
      } else {
        band1CoreLeaves.push(child);
      }
    });

    const rows = [];
    const chunkIntoRows = (items, maxCols) => {
      for (let i = 0; i < items.length; i += maxCols) {
        rows.push(items.slice(i, i + maxCols));
      }
    };

    if (band0NetworkLeaves.length > 0) {
      chunkIntoRows(band0NetworkLeaves, band0NetworkLeaves.length === 4 ? 2 : 3);
    }

    if (band1CoreLeaves.length > 0) {
      chunkIntoRows(band1CoreLeaves, band1CoreLeaves.length === 4 ? 2 : 3);
    }

    if (band1CoreContainers.length > 0) {
      // Group sub-containers by their effective tier or domain so upstream compute
      // pools stack cleanly above downstream data pools instead of stretching sideways
      const upstreamContainers = band1CoreContainers.filter(
        (c) => resolveArchitecturalDomain(c) !== "data" && (c.effectiveTier ?? 7) <= 7
      );
      const downstreamContainers = band1CoreContainers.filter(
        (c) => resolveArchitecturalDomain(c) === "data" || (c.effectiveTier ?? 7) > 7
      );

      if (upstreamContainers.length > 0 && downstreamContainers.length > 0) {
        chunkIntoRows(upstreamContainers, 2);
        chunkIntoRows(downstreamContainers, 2);
      } else {
        // If any container is already wide (> 640px), stack containers 1 per row
        // so the parent container maintains a balanced, readable aspect ratio
        const hasWideContainer = band1CoreContainers.some(
          (c) => (c.computedWidth || 0) > 640
        );
        chunkIntoRows(band1CoreContainers, hasWideContainer ? 1 : 2);
      }
    }

    if (band2DataLeaves.length > 0) {
      chunkIntoRows(band2DataLeaves, band2DataLeaves.length === 4 ? 2 : 3);
    }

    // Calculate row dimensions and center-align narrower rows within the container
    const rowMetrics = rows.map((rowItems) => {
      const width =
        rowItems.reduce((sum, item) => sum + item.computedWidth, 0) +
        Math.max(0, rowItems.length - 1) * GAP_X;
      const height = rowItems.reduce(
        (maxH, item) => Math.max(maxH, item.computedHeight),
        0
      );
      return { rowItems, width, height };
    });

    const maxInnerWidth = rowMetrics.reduce(
      (maxW, r) => Math.max(maxW, r.width),
      0
    );
    const containerWidth = Math.max(324, maxInnerWidth + PADDING_X * 2);

    let cursorY = HEADER_HEIGHT;
    rowMetrics.forEach(({ rowItems, width: rowWidth, height }) => {
      // Center each row horizontally inside the container for balanced symmetry
      let cursorX = PADDING_X + Math.max(0, Math.round((maxInnerWidth - rowWidth) / 2));
      rowItems.forEach((child) => {
        child.relativePosition = { x: cursorX, y: cursorY };
        cursorX += child.computedWidth + GAP_X;
      });
      cursorY += height + GAP_Y;
    });

    const totalContentHeight =
      rowMetrics.length > 0
        ? cursorY - GAP_Y + PADDING_BOTTOM
        : HEADER_HEIGHT + PADDING_BOTTOM;

    node.computedWidth = containerWidth;
    node.computedHeight = Math.max(120, totalContentHeight);

    return { width: node.computedWidth, height: node.computedHeight };
  }

  // 3. Measure all roots
  let currentRootX = rootStartX;
  rootNodes.forEach((root) => {
    measureAndLayoutNode(root);
    root.absolutePosition = { x: currentRootX, y: rootStartY };
    currentRootX += root.computedWidth + rootGapX;
  });

  // 4. Flatten in Parent-First Top-Down order & compute exact absolute coordinates
  const orderedNodes = [];
  let staggerCounter = 0;

  function traverseTopDown(node, depth = 0, parentAbs = { x: 0, y: 0 }) {
    node.depth = depth;
    node.zIndex = depth + 1;
    node.staggerIndex = staggerCounter++;

    if (node.parent_id && nodeMap[node.parent_id]) {
      node.computedPosition = node.relativePosition;
      node.absolutePosition = {
        x: parentAbs.x + node.relativePosition.x,
        y: parentAbs.y + node.relativePosition.y,
      };
    } else {
      node.computedPosition = node.absolutePosition;
    }

    orderedNodes.push(node);

    const children = childrenMap[node.id] || [];
    children.forEach((c) => traverseTopDown(c, depth + 1, node.absolutePosition));
  }

  rootNodes.forEach((r) => traverseTopDown(r, 0, { x: 0, y: 0 }));

  // 5. Build formatted edges with 4-way vector routing
  const formattedEdges = buildFormattedEdges(edges, nodeMap, {
    activeNodeIds,
    includeHierarchy: false,
  });

  return {
    nodes: orderedNodes,
    edges: formattedEdges,
  };
}

/**
 * Computes a clean stratified tier layout (Level 0..8) for standalone flat graphs.
 */
export function computeStratifiedLayout(nodes, edges, options = {}) {
  const activeNodeIds = options.activeNodeIds || new Set();
  if (!nodes || nodes.length === 0) {
    return { nodes: [], edges: [] };
  }

  const NODE_WIDTH = 268;
  const NODE_HEIGHT = 86;
  const COL_SPAN = 308;
  const ROW_SPAN = 148;

  const levelGroups = {};
  nodes.forEach((n) => {
    const lvl = n.level ?? 8;
    if (!levelGroups[lvl]) levelGroups[lvl] = [];
    levelGroups[lvl].push({ ...n });
  });

  const sortedLevels = Object.keys(levelGroups)
    .map(Number)
    .sort((a, b) => a - b);

  const maxCols = Math.max(
    1,
    ...sortedLevels.map((lvl) => levelGroups[lvl].length)
  );
  const totalCanvasWidth = maxCols * COL_SPAN;

  const nodeMap = {};
  const positionedNodes = [];
  let staggerCounter = 0;

  sortedLevels.forEach((lvl, rowIdx) => {
    const group = levelGroups[lvl].sort(
      (a, b) =>
        resolveHorizontalRoleRank(a) - resolveHorizontalRoleRank(b) ||
        a.name.localeCompare(b.name)
    );
    const rowWidth = group.length * COL_SPAN;
    const startX = Math.max(64, Math.round((totalCanvasWidth - rowWidth) / 2) + 64);

    group.forEach((node, colIdx) => {
      const pos = {
        x: startX + colIdx * COL_SPAN,
        y: 64 + rowIdx * ROW_SPAN,
      };
      node.computedPosition = pos;
      node.absolutePosition = pos;
      node.computedWidth = NODE_WIDTH;
      node.computedHeight = NODE_HEIGHT;
      node.depth = rowIdx;
      node.staggerIndex = staggerCounter++;
      nodeMap[node.id] = node;
      positionedNodes.push(node);
    });
  });

  const formattedEdges = buildFormattedEdges(edges, nodeMap, {
    activeNodeIds,
    includeHierarchy: true,
  });

  return {
    nodes: positionedNodes,
    edges: formattedEdges,
  };
}
