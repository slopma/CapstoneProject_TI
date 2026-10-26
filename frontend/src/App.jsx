import React, { useState, useEffect, useCallback, useMemo } from "react";
import AppShell from "./components/layout/AppShell";
import CanvasToolbar from "./components/architecture/CanvasToolbar";
import Breadcrumbs from "./components/layout/Breadcrumbs";
import ArchitectureCanvas from "./components/architecture/ArchitectureCanvas";
import ResourceInspector from "./components/inspector/ResourceInspector";
import MigrationPreviewModal from "./components/migration/MigrationPreviewModal";
import DiscoveryWorkspace from "./components/discovery/DiscoveryWorkspace";
import DataCenterCampaignPanel from "./components/discovery/DataCenterCampaignPanel";
import MigrationOrchestratorWorkspace from "./components/migration/MigrationOrchestratorWorkspace";
import EnvironmentOverviewWorkspace from "./components/overview/EnvironmentOverviewWorkspace";
import SourcesAndTargetsWorkspace from "./components/sources/SourcesAndTargetsWorkspace";
import ExecutionsAndAuditWorkspace from "./components/audit/ExecutionsAndAuditWorkspace";
import { getDomainByType } from "./components/architecture/TechnicalIcons";
import { apiFetch, getApiBase } from "./utils/apiClient";

const OFFLINE_ENTERPRISE_NODES = [
  { id: "dc-root", name: "Datacenter On-Premise Principal", type: "datacenter", category: "container", level: 0, parent: null },
  { id: "rack-a1", name: "Rack A1 - Infraestructura Física", type: "rack", category: "container", level: 1, parent: "dc-root" },
  { id: "vlan-prod", name: "Red VLAN Producción (192.168.10.0/24)", type: "vlan", category: "container", level: 2, parent: "rack-a1" },
  { id: "esxi-cluster", name: "Cluster Virtualización VMware ESXi", type: "cluster", category: "container", level: 3, parent: "vlan-prod" },
  { id: "ns-core", name: "Pool de Recursos: Core Applications", type: "namespace", category: "container", level: 4, parent: "esxi-cluster" },
  { id: "ns-data", name: "Pool de Recursos: Data & Messaging", type: "namespace", category: "container", level: 4, parent: "esxi-cluster" },
  { id: "app-erp", name: "Sistema ERP & Servicios Centrales", type: "application", category: "container", level: 4, parent: "ns-core" },
  { id: "fw-perimetral", name: "Firewall Perimetral & DMZ", type: "firewall", category: "resource", level: 5, parent: "vlan-prod", location: "us-east-1" },
  { id: "lb-haproxy", name: "Balanceador HAProxy / Ingress", type: "load_balancer", category: "resource", level: 5, parent: "ns-core", location: "us-east-1" },
  { id: "srv-web-01", name: "Frontend Web Portal (Nginx)", type: "service", category: "resource", level: 5, parent: "app-erp", location: "us-east-1" },
  { id: "srv-erp-backend", name: "API Core ERP (Java Spring)", type: "service", category: "resource", level: 5, parent: "app-erp", location: "us-east-1" },
  { id: "srv-auth-jwt", name: "Servicio Identidad & SSO (Keycloak)", type: "service", category: "resource", level: 5, parent: "ns-core", is_shared: true, location: "us-east-1" },
  { id: "vm-worker-batch", name: "Nodo Procesamiento Batch", type: "vm", category: "resource", level: 5, parent: "ns-core", location: "us-east-1" },
  { id: "db-postgres-primary", name: "PostgreSQL Cluster Principal", type: "database", category: "resource", level: 5, parent: "ns-data", is_shared: true, location: "us-east-1" },
  { id: "cache-redis", name: "Redis Cache & Session Store", type: "cache", category: "resource", level: 5, parent: "ns-data", is_shared: true, location: "us-east-1" },
  { id: "mq-rabbitmq", name: "Broker Mensajería RabbitMQ", type: "queue", category: "resource", level: 5, parent: "ns-data", location: "us-east-1" },
  { id: "san-netapp", name: "Storage SAN NetApp Volúmenes", type: "storage", category: "resource", level: 5, parent: "ns-data", is_shared: true, location: "us-east-1" },
];

const OFFLINE_ENTERPRISE_EDGES = [
  { source: "dc-root", target: "rack-a1", type: "contains", is_hierarchy: true },
  { source: "rack-a1", target: "vlan-prod", type: "contains", is_hierarchy: true },
  { source: "vlan-prod", target: "esxi-cluster", type: "contains", is_hierarchy: true },
  { source: "vlan-prod", target: "fw-perimetral", type: "contains", is_hierarchy: true },
  { source: "esxi-cluster", target: "ns-core", type: "contains", is_hierarchy: true },
  { source: "esxi-cluster", target: "ns-data", type: "contains", is_hierarchy: true },
  { source: "ns-core", target: "app-erp", type: "contains", is_hierarchy: true },
  { source: "ns-core", target: "lb-haproxy", type: "contains", is_hierarchy: true },
  { source: "ns-core", target: "srv-auth-jwt", type: "contains", is_hierarchy: true },
  { source: "ns-core", target: "vm-worker-batch", type: "contains", is_hierarchy: true },
  { source: "app-erp", target: "srv-web-01", type: "contains", is_hierarchy: true },
  { source: "app-erp", target: "srv-erp-backend", type: "contains", is_hierarchy: true },
  { source: "ns-data", target: "db-postgres-primary", type: "contains", is_hierarchy: true },
  { source: "ns-data", target: "cache-redis", type: "contains", is_hierarchy: true },
  { source: "ns-data", target: "mq-rabbitmq", type: "contains", is_hierarchy: true },
  { source: "ns-data", target: "san-netapp", type: "contains", is_hierarchy: true },
  { source: "fw-perimetral", target: "lb-haproxy", type: "routes_to", is_hierarchy: false },
  { source: "lb-haproxy", target: "srv-web-01", type: "exposes", is_hierarchy: false },
  { source: "srv-web-01", target: "srv-erp-backend", type: "depends_on", is_hierarchy: false },
  { source: "srv-erp-backend", target: "srv-auth-jwt", type: "authenticates_via", is_hierarchy: false },
  { source: "srv-erp-backend", target: "db-postgres-primary", type: "connects_to", is_hierarchy: false },
  { source: "srv-erp-backend", target: "cache-redis", type: "reads_writes", is_hierarchy: false },
  { source: "srv-erp-backend", target: "mq-rabbitmq", type: "publishes_to", is_hierarchy: false },
  { source: "vm-worker-batch", target: "mq-rabbitmq", type: "consumes_from", is_hierarchy: false },
  { source: "vm-worker-batch", target: "db-postgres-primary", type: "connects_to", is_hierarchy: false },
  { source: "vm-worker-batch", target: "san-netapp", type: "mounts", is_hierarchy: false },
  { source: "db-postgres-primary", target: "san-netapp", type: "backed_by", is_hierarchy: false },
];

const VALID_TABS = new Set([
  "overview",
  "discovery",
  "campaigns",
  "architecture",
  "migration",
  "sources-targets",
  "executions-audit",
]);

function getInitialTabFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get("tab");
    if (tab && VALID_TABS.has(tab)) return tab;
  } catch {
    // Ignore URL parse error
  }
  return "architecture";
}

function App() {
  const [activeTab, setActiveTabState] = useState(getInitialTabFromUrl);
  const [allNodes, setAllNodes] = useState([]);
  const [allEdges, setAllEdges] = useState([]);
  const [architectureMeta, setArchitectureMeta] = useState(null);

  // Canvas & Hierarchy Exploration States
  const [expandedNodeIds, setExpandedNodeIds] = useState([]);
  const [activeLayer, setActiveLayer] = useState("ALL");
  const [domainFilter, setDomainFilter] = useState("ALL");
  const [highlightDeps, setHighlightDeps] = useState(true);
  const [showLegend, setShowLegend] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [focusNodeId, setFocusNodeId] = useState(null);

  // Selection & Inspector States
  const [selectedNodes, setSelectedNodes] = useState([]);
  const [selectedNodeObj, setSelectedNodeObj] = useState(null);

  // Migration & IaC Modal States
  const [dependencies, setDependencies] = useState(null);
  const [targetProvider, setTargetProvider] = useState("aws");
  const [generationResult, setGenerationResult] = useState(null);
  const [showMigrationModal, setShowMigrationModal] = useState(false);

  // Persistent Work Context Across Tabs
  const [activeHost, setActiveHost] = useState("");
  const [activeCampaign, setActiveCampaign] = useState(null);
  const [activeMigrationJob, setActiveMigrationJob] = useState(null);
  const [cachedCampaigns, setCachedCampaigns] = useState([]);
  const [cachedJobs, setCachedJobs] = useState([]);
  const [persistenceEngine, setPersistenceEngine] = useState("SQLITE (WAL)");
  const [jobsCount, setJobsCount] = useState(0);
  const [orchestratorUseCase, setOrchestratorUseCase] = useState("app_source");
  const [orchestratorJobId, setOrchestratorJobId] = useState(null);

  // Status States
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState("");

  const setActiveTab = useCallback((nextTab) => {
    setActiveTabState(nextTab);
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", nextTab);
      window.history.replaceState({}, "", url.toString());
    } catch {
      // Ignore history error
    }
  }, []);

  const fetchArchitecture = useCallback(async () => {
    setLoading(true);
    try {
      let response = await apiFetch("/api/v1/architecture/graph");
      if (!response.ok) {
        response = await apiFetch("/graph");
      }
      if (!response.ok) throw new Error("Backend unreachable");
      const data = await response.json();

      const fetchedNodes = data.nodes || [];
      const fetchedEdges = data.edges || [];

      setAllNodes(fetchedNodes);
      setAllEdges(fetchedEdges);
      setArchitectureMeta(data.architecture || { name: "onpremise-datacenter-enterprise", provider: "on-premise" });

      const initialExpanded = fetchedNodes
        .filter((n) => (n.level ?? 0) <= 4)
        .map((n) => n.id);
      setExpandedNodeIds(initialExpanded);
      setMessage("");
    } catch {
      setAllNodes(OFFLINE_ENTERPRISE_NODES);
      setAllEdges(OFFLINE_ENTERPRISE_EDGES);
      setArchitectureMeta({ name: "onpremise-datacenter-enterprise", provider: "on-premise" });
      const initialExpanded = OFFLINE_ENTERPRISE_NODES.filter((n) => (n.level ?? 0) <= 4).map((n) => n.id);
      setExpandedNodeIds(initialExpanded);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchWorkContextSummary = useCallback(async () => {
    try {
      const [discRes, campRes, jobsRes, persRes] = await Promise.all([
        apiFetch("/api/v1/discovery/latest").catch(() => null),
        apiFetch("/api/v1/campaigns").catch(() => null),
        apiFetch("/api/v1/migration/jobs").catch(() => null),
        apiFetch("/api/v1/migration/persistence/status").catch(() => null),
      ]);
      if (discRes && discRes.ok) {
        const d = await discRes.json();
        if (d.hostname || d.agent?.hostname) setActiveHost(d.hostname || d.agent?.hostname);
      }
      if (campRes && campRes.ok) {
        const c = await campRes.json();
        const cList = c.campaigns || [];
        setCachedCampaigns(cList);
        if (cList.length > 0) setActiveCampaign(cList[0]);
      }
      if (jobsRes && jobsRes.ok) {
        const j = await jobsRes.json();
        const list = j.jobs || [];
        setCachedJobs(list);
        setJobsCount(list.length);
        if (list.length > 0) setActiveMigrationJob((prev) => prev || list[0]);
      }
      if (persRes && persRes.ok) {
        const p = await persRes.json();
        setPersistenceEngine(`${(p.engine || "sqlite").toUpperCase()} (${(p.journal_mode || "wal").toUpperCase()})`);
      }
    } catch {
      // Ignore summary load error
    }
  }, []);

  useEffect(() => {
    fetchArchitecture();
    fetchWorkContextSummary();
  }, [fetchArchitecture, fetchWorkContextSummary]);

  const handleToggleExpand = useCallback((nodeId) => {
    setExpandedNodeIds((prev) =>
      prev.includes(nodeId) ? prev.filter((id) => id !== nodeId) : [...prev, nodeId]
    );
  }, []);

  const handleExpandAll = useCallback(() => {
    const allContainerIds = allNodes
      .filter((n) => n.category === "container" || (n.level ?? 5) < 5)
      .map((n) => n.id);
    setExpandedNodeIds(allContainerIds);
  }, [allNodes]);

  const handleCollapseAll = useCallback(() => {
    const rootIds = allNodes.filter((n) => (n.level ?? 0) === 0).map((n) => n.id);
    setExpandedNodeIds(rootIds);
  }, [allNodes]);

  const toggleResourceSelection = useCallback(
    (nodeId) => {
      const nodeObj = allNodes.find((n) => n.id === nodeId) || null;
      setSelectedNodeObj(nodeObj);
      setSelectedNodes((prev) =>
        prev.includes(nodeId) ? prev.filter((id) => id !== nodeId) : [...prev, nodeId]
      );
    },
    [allNodes]
  );

  const resolveDependencies = async () => {
    if (selectedNodes.length === 0) return;
    setMessage("");

    try {
      const response = await apiFetch("/api/v1/migration/dependencies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resources: selectedNodes }),
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Error al calcular dependencias.");

      setDependencies(data);
      setShowMigrationModal(true);
    } catch {
      const directSet = new Set();
      const sharedSet = new Set();
      selectedNodes.forEach((sId) => {
        allEdges.forEach((e) => {
          if (!e.is_hierarchy && e.source === sId && !selectedNodes.includes(e.target)) {
            directSet.add(e.target);
            const targetObj = allNodes.find((n) => n.id === e.target);
            if (targetObj?.is_shared) sharedSet.add(e.target);
          }
        });
      });
      setDependencies({
        required_direct: Array.from(directSet),
        required_transitive: [],
        shared_dependencies: Array.from(sharedSet),
      });
      setShowMigrationModal(true);
    }
  };

  const generateIaC = async (validatedSharedResources = []) => {
    if (selectedNodes.length === 0) return;

    setGenerating(true);
    setGenerationResult(null);

    try {
      const response = await apiFetch("/api/v1/migration/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resources: selectedNodes,
          target_provider: targetProvider,
          validated_shared_resources: Array.isArray(validatedSharedResources)
            ? validatedSharedResources
            : [],
        }),
      });

      const data = await response.json();
      if (!response.ok || data.error) {
        throw new Error(data.error?.message || data.detail || "Fallo al generar Terraform IaC.");
      }

      setGenerationResult(data);
      setMessage(`Módulos Terraform HCL (${targetProvider.toUpperCase()}) generados y validados correctamente.`);
    } catch (error) {
      setMessage(error.message || "Error al generar IaC.");
    } finally {
      setGenerating(false);
    }
  };

  const breadcrumbs = useMemo(() => {
    if (!selectedNodeObj) return [];
    const crumbs = [];
    let curr = selectedNodeObj;
    const visited = new Set();
    while (curr && !visited.has(curr.id)) {
      visited.add(curr.id);
      crumbs.unshift({ id: curr.id, name: curr.name, level: curr.level ?? 0 });
      curr = curr.parent ? allNodes.find((n) => n.id === curr.parent) : null;
    }
    return crumbs;
  }, [selectedNodeObj, allNodes]);

  const { visibleNodes, visibleEdges } = useMemo(() => {
    let filtered = allNodes;

    if (activeLayer !== "ALL") {
      filtered = filtered.filter((n) => {
        const lvl = n.level ?? 5;
        if (activeLayer === "L0_L1") return lvl <= 1;
        if (activeLayer === "L2") return lvl <= 2;
        if (activeLayer === "L3_L4") return lvl <= 4;
        if (activeLayer === "L5") return true;
        return true;
      });
    }

    if (domainFilter !== "ALL") {
      filtered = filtered.filter((n) => {
        const isContainer = n.category === "container" || (n.level ?? 5) < 5;
        if (isContainer) return true; // Keep parent containers so leaf nodes remain anchored
        if (domainFilter === "shared") return Boolean(n.is_shared);
        const dom = getDomainByType(n.type);
        if (domainFilter === "network") return dom === "network" || dom === "security";
        if (domainFilter === "data") return dom === "data" || dom === "storage";
        return dom === domainFilter;
      });
    }

    if (searchQuery.trim() !== "") {
      const q = searchQuery.toLowerCase();
      const matchedIds = new Set(
        filtered
          .filter(
            (n) =>
              n.name?.toLowerCase().includes(q) ||
              n.type?.toLowerCase().includes(q) ||
              n.id?.toLowerCase().includes(q)
          )
          .map((n) => n.id)
      );
      filtered.forEach((n) => {
        if (matchedIds.has(n.id)) {
          let p = n.parent;
          while (p) {
            matchedIds.add(p);
            const parentObj = allNodes.find((x) => x.id === p);
            p = parentObj ? parentObj.parent : null;
          }
        }
      });
      filtered = filtered.filter((n) => matchedIds.has(n.id));
    }

    if (focusNodeId) {
      const subtreeIds = new Set([focusNodeId]);
      let added = true;
      while (added) {
        added = false;
        allNodes.forEach((n) => {
          if (n.parent && subtreeIds.has(n.parent) && !subtreeIds.has(n.id)) {
            subtreeIds.add(n.id);
            added = true;
          }
        });
      }
      filtered = filtered.filter((n) => subtreeIds.has(n.id));
    }

    const nodeIds = new Set(filtered.map((n) => n.id));
    const edges = allEdges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));

    return { visibleNodes: filtered, visibleEdges: edges };
  }, [allNodes, allEdges, activeLayer, domainFilter, searchQuery, focusNodeId]);

  const handleLoadCmirJobToCanvas = useCallback(
    (jobOrPayload) => {
      const cmir = jobOrPayload?.cmir || jobOrPayload;
      if (cmir?.resources?.length > 0) {
        const cmirNodes = cmir.resources;
        const cmirEdges = (cmir.relationships || []).map((r) => ({
          source: r.source,
          target: r.target,
          type: r.type,
          is_hierarchy: ["contains", "parent_of", "hosts"].includes(r.type),
          metadata: r.metadata || {},
        }));
        setAllNodes(cmirNodes);
        setAllEdges(cmirEdges);
        setArchitectureMeta({
          name: cmir.name || jobOrPayload?.name || "Subgrafo CMIR v2.1",
          provider: jobOrPayload?.target_provider || "aws",
        });
        setExpandedNodeIds(cmirNodes.map((n) => n.id));
        if (jobOrPayload?.target_provider) {
          setTargetProvider(jobOrPayload.target_provider);
        }
        setActiveTab("architecture");
        setMessage(
          `Topología CMIR v2.1 '${cmir.name || jobOrPayload?.name}' (${cmirNodes.length} nodos) cargada en el Grafo de Arquitectura.`
        );
      }
    },
    [setActiveTab]
  );

  const handleQuickStartUseCase = useCallback(
    (useCaseId, jobId = null) => {
      setOrchestratorUseCase(useCaseId || "app_source");
      setOrchestratorJobId(jobId);
      setActiveTab("migration");
    },
    [setActiveTab]
  );

  return (
    <AppShell
      activeTab={activeTab}
      setActiveTab={setActiveTab}
      architectureName={architectureMeta?.name}
      searchQuery={searchQuery}
      setSearchQuery={setSearchQuery}
      selectedCount={selectedNodes.length}
      onPrepareMigration={resolveDependencies}
      targetProvider={targetProvider}
      setTargetProvider={setTargetProvider}
      workContext={{
        activeHost,
        activeCampaign,
        activeMigrationJob,
        persistenceEngine,
        jobsCount,
      }}
    >
      {loading ? (
        <div className="loading-state-overlay">
          <div className="spinner-ring" />
          <p>Inicializando motor de topología CMIR v2.1 e inventario de infraestructura...</p>
        </div>
      ) : activeTab === "overview" ? (
        <EnvironmentOverviewWorkspace
          allNodes={allNodes}
          allEdges={allEdges}
          selectedNodes={selectedNodes}
          initialCampaigns={cachedCampaigns}
          initialJobs={cachedJobs}
          onNavigateTab={setActiveTab}
          onQuickStartUseCase={handleQuickStartUseCase}
        />
      ) : activeTab === "discovery" ? (
        <DiscoveryWorkspace
          apiUrl={getApiBase()}
          onLoadCmirToCanvas={() => {
            fetchArchitecture();
            setActiveTab("architecture");
          }}
        />
      ) : activeTab === "campaigns" ? (
        <DataCenterCampaignPanel
          isStandalonePage={true}
          onActiveCampaignChange={setActiveCampaign}
          onLoadCampaignCmirToCanvas={(cmir, camp) => {
            handleLoadCmirJobToCanvas({
              cmir,
              name: `Campaña Datacenter ${camp?.campaign_id || ""}`,
              target_provider: "aws",
            });
          }}
        />
      ) : activeTab === "architecture" ? (
        <>
          <CanvasToolbar
            activeLayer={activeLayer}
            setActiveLayer={setActiveLayer}
            domainFilter={domainFilter}
            setDomainFilter={setDomainFilter}
            highlightDeps={highlightDeps}
            setHighlightDeps={setHighlightDeps}
            showLegend={showLegend}
            setShowLegend={setShowLegend}
            onExpandAll={handleExpandAll}
            onCollapseAll={handleCollapseAll}
            selectedCount={selectedNodes.length}
            onClearSelection={() => {
              setSelectedNodes([]);
              setSelectedNodeObj(null);
            }}
            onAnalyzeDependencies={resolveDependencies}
          />

          {breadcrumbs.length > 0 && (
            <Breadcrumbs
              breadcrumbs={breadcrumbs}
              onNavigate={(nodeId) => {
                const item = allNodes.find((n) => n.id === nodeId);
                if (item) setSelectedNodeObj(item);
              }}
              onReset={() => {
                setSelectedNodeObj(null);
                setFocusNodeId(null);
              }}
              onBack={() => {
                if (breadcrumbs.length > 1) {
                  const parentCrumb = breadcrumbs[breadcrumbs.length - 2];
                  const parentObj = allNodes.find((n) => n.id === parentCrumb.id);
                  setSelectedNodeObj(parentObj || null);
                } else {
                  setSelectedNodeObj(null);
                }
              }}
            />
          )}

          {message && (
            <div className="app-message-banner" role="status">
              <span>{message}</span>
              <button
                type="button"
                className="cm-btn sm"
                style={{ marginLeft: 12 }}
                onClick={() => {
                  fetchArchitecture();
                  setMessage("");
                }}
              >
                Restaurar Topología Completa
              </button>
            </div>
          )}

          <ArchitectureCanvas
            nodes={visibleNodes}
            edges={visibleEdges}
            allNodes={allNodes}
            allEdges={allEdges}
            selectedNodes={selectedNodes}
            expandedNodeIds={expandedNodeIds}
            onNodeClick={toggleResourceSelection}
            onToggleExpand={handleToggleExpand}
            zoomTargetId={selectedNodeObj?.id}
            highlightDeps={highlightDeps}
            showLegend={showLegend}
            onCloseLegend={() => setShowLegend(false)}
          />

          {selectedNodeObj && (
            <ResourceInspector
              node={selectedNodeObj}
              allNodes={allNodes}
              edges={allEdges}
              onClose={() => setSelectedNodeObj(null)}
              onSelectNode={(nodeId) => {
                toggleResourceSelection(nodeId);
                setFocusNodeId(nodeId);
              }}
              targetProvider={targetProvider}
              onToggleExpand={handleToggleExpand}
              isExpanded={expandedNodeIds.includes(selectedNodeObj.id)}
            />
          )}
        </>
      ) : activeTab === "migration" ? (
        <MigrationOrchestratorWorkspace
          initialUseCase={orchestratorUseCase}
          initialJobId={orchestratorJobId}
          onActiveJobChange={setActiveMigrationJob}
          onNavigateTab={setActiveTab}
          onLoadCmirToCanvas={handleLoadCmirJobToCanvas}
        />
      ) : activeTab === "sources-targets" ? (
        <SourcesAndTargetsWorkspace />
      ) : (
        <ExecutionsAndAuditWorkspace
          generationResult={generationResult}
          onSelectMigrationInOrchestrator={handleQuickStartUseCase}
        />
      )}

      {showMigrationModal && (
        <MigrationPreviewModal
          selectedNodes={selectedNodes}
          allNodes={allNodes}
          dependencies={dependencies}
          targetProvider={targetProvider}
          setTargetProvider={setTargetProvider}
          onConfirmGenerate={generateIaC}
          onClose={() => setShowMigrationModal(false)}
          generating={generating}
          generationResult={generationResult}
        />
      )}
    </AppShell>
  );
}

export default App;
