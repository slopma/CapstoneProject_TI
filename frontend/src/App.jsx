import { useEffect, useState, useCallback, useMemo } from "react";
import AppShell from "./components/layout/AppShell";
import Breadcrumbs from "./components/layout/Breadcrumbs";
import ArchitectureCanvas from "./components/architecture/ArchitectureCanvas";
import CanvasToolbar from "./components/architecture/CanvasToolbar";
import ResourceInspector from "./components/inspector/ResourceInspector";
import MigrationPreviewModal from "./components/migration/MigrationPreviewModal";
import IaCViewer from "./components/migration/IaCViewer";
import DiscoveryWorkspace from "./components/discovery/DiscoveryWorkspace";
import { FALLBACK_ENTERPRISE_ARCHITECTURE } from "./utils/graphLayout";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function App() {
  const [activeTab, setActiveTab] = useState("architecture");

  const [allNodes, setAllNodes] = useState(FALLBACK_ENTERPRISE_ARCHITECTURE.nodes);
  const [allEdges, setAllEdges] = useState(FALLBACK_ENTERPRISE_ARCHITECTURE.edges);
  const [architectureMeta, setArchitectureMeta] = useState({
    name: FALLBACK_ENTERPRISE_ARCHITECTURE.architecture_name,
    provider: FALLBACK_ENTERPRISE_ARCHITECTURE.provider,
  });

  const [selectedNodes, setSelectedNodes] = useState([]);
  const [selectedNodeObj, setSelectedNodeObj] = useState(null);
  const [expandedNodeIds, setExpandedNodeIds] = useState(() =>
    FALLBACK_ENTERPRISE_ARCHITECTURE.nodes.map((n) => n.id)
  );
  const [activeLevel, setActiveLevel] = useState(null);
  const [focusNodeId, setFocusNodeId] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [targetProvider, setTargetProvider] = useState("aws");

  const [dependencies, setDependencies] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState("");
  const [generationResult, setGenerationResult] = useState(null);
  const [showMigrationModal, setShowMigrationModal] = useState(false);

  // Synchronize architecture graph with Backend API when available
  useEffect(() => {
    let isCancelled = false;

    async function loadArchitectureFromApi() {
      try {
        const response = await fetch(`${API_URL}/api/v1/architecture/graph`);
        if (!response.ok) {
          const legacyRes = await fetch(`${API_URL}/graph`);
          if (!legacyRes.ok) return;
          const legacyData = await legacyRes.json();
          if (!isCancelled && Array.isArray(legacyData.nodes) && legacyData.nodes.length > 0) {
            setAllNodes(legacyData.nodes);
            setAllEdges(legacyData.edges || []);
            setExpandedNodeIds(legacyData.nodes.map((n) => n.id));
          }
          return;
        }

        const data = await response.json();
        if (!isCancelled && Array.isArray(data.nodes) && data.nodes.length > 0) {
          setAllNodes(data.nodes);
          setAllEdges(data.edges || []);
          setArchitectureMeta({
            name: data.architecture_name || "On-Premise Enterprise",
            provider: data.provider || "on-premise",
          });
          setExpandedNodeIds(data.nodes.map((n) => n.id));
        }
      } catch {
        // Offline resilience: fallback topology is already initialized
      }
    }

    loadArchitectureFromApi();
    return () => {
      isCancelled = true;
    };
  }, []);

  // Progressive Expansion & Filter Logic
  const visibleNodes = useMemo(() => {
    const isAncestorExpanded = (node) => {
      if (!node.parent_id) return true;
      if (!expandedNodeIds.includes(node.parent_id)) return false;
      const parentNode = allNodes.find((n) => n.id === node.parent_id);
      return parentNode ? isAncestorExpanded(parentNode) : true;
    };

    let filtered = allNodes.filter(isAncestorExpanded);

    if (activeLevel !== null) {
      filtered = filtered.filter((n) => (n.level ?? 8) === activeLevel);
    }

    if (focusNodeId) {
      const focusRelated = new Set([focusNodeId]);
      allNodes.forEach((n) => {
        if (n.parent_id === focusNodeId || n.id === focusNodeId) focusRelated.add(n.id);
      });
      allEdges.forEach((e) => {
        if (e.source === focusNodeId) focusRelated.add(e.target);
        if (e.target === focusNodeId) focusRelated.add(e.source);
      });
      filtered = filtered.filter((n) => focusRelated.has(n.id));
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      filtered = allNodes.filter(
        (n) =>
          n.name.toLowerCase().includes(q) ||
          n.id.toLowerCase().includes(q) ||
          n.type.toLowerCase().includes(q)
      );
    }

    return filtered;
  }, [allNodes, allEdges, expandedNodeIds, activeLevel, focusNodeId, searchQuery]);

  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);

  const visibleEdges = useMemo(() => {
    return allEdges.filter((e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target));
  }, [allEdges, visibleNodeIds]);

  const handleToggleExpand = useCallback((nodeId) => {
    setExpandedNodeIds((prev) =>
      prev.includes(nodeId) ? prev.filter((id) => id !== nodeId) : [...prev, nodeId]
    );
  }, []);

  const handleExpandAll = useCallback(() => {
    setExpandedNodeIds(allNodes.map((n) => n.id));
  }, [allNodes]);

  const handleCollapseAll = useCallback(() => {
    const rootIds = allNodes.filter((n) => !n.parent_id || n.level <= 2).map((n) => n.id);
    setExpandedNodeIds(rootIds);
  }, [allNodes]);

  const toggleResourceSelection = useCallback(
    (nodeId) => {
      setSelectedNodes((current) =>
        current.includes(nodeId) ? current.filter((id) => id !== nodeId) : [...current, nodeId]
      );
      const targetObj = allNodes.find((n) => n.id === nodeId);
      setSelectedNodeObj(targetObj || null);
    },
    [allNodes]
  );

  const resolveDependencies = async () => {
    if (selectedNodes.length === 0) return;

    setMessage("");

    try {
      const response = await fetch(`${API_URL}/api/v1/migration/dependencies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resources: selectedNodes }),
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Error resolving dependencies.");

      setDependencies(data);
      setShowMigrationModal(true);
    } catch {
      // Offline dependency resolution fallback using local graph edges
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

  const generateIaC = async () => {
    if (selectedNodes.length === 0) return;

    setGenerating(true);
    setGenerationResult(null);

    try {
      const response = await fetch(`${API_URL}/api/v1/migration/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resources: selectedNodes,
          target_provider: targetProvider,
        }),
      });

      const data = await response.json();
      if (!response.ok || data.error) {
        throw new Error(data.error?.message || data.detail || "IaC generation failed.");
      }

      setGenerationResult(data);
      setMessage(`Infrastructure code (${targetProvider.toUpperCase()}) generated successfully.`);
    } catch (error) {
      setMessage(error.message || "Generation error.");
    } finally {
      setGenerating(false);
    }
  };

  // Compute Breadcrumb Trail for selected node
  const breadcrumbs = useMemo(() => {
    if (!selectedNodeObj) return [];
    const crumbs = [];
    let curr = selectedNodeObj;
    const visited = new Set();
    while (curr && !visited.has(curr.id)) {
      visited.add(curr.id);
      crumbs.unshift({ id: curr.id, name: curr.name, level: curr.level ?? 0 });
      curr = allNodes.find((n) => n.id === curr.parent_id);
    }
    return crumbs;
  }, [selectedNodeObj, allNodes]);

  const handleBack = () => {
    if (selectedNodeObj && selectedNodeObj.parent_id) {
      const parentObj = allNodes.find((n) => n.id === selectedNodeObj.parent_id);
      setSelectedNodeObj(parentObj || null);
    } else {
      setSelectedNodeObj(null);
    }
  };

  return (
    <AppShell
      activeTab={activeTab}
      onSelectTab={setActiveTab}
      architectureName={architectureMeta.name}
      environment={
        architectureMeta.provider === "on-premise"
          ? "On-Premise Enterprise"
          : "Multi-Cloud Scope"
      }
      searchQuery={searchQuery}
      onSearchChange={setSearchQuery}
      selectedCount={selectedNodes.length}
      onPrepareMigration={resolveDependencies}
    >
      {activeTab === "discovery" ? (
        <DiscoveryWorkspace
          apiUrl={API_URL}
          onSyncToArchitecture={(session) => {
            if (session?.graph?.nodes?.length > 0) {
              setAllNodes(session.graph.nodes);
              setAllEdges(session.graph.edges || []);
              setArchitectureMeta({
                name: session.graph.architecture_name || `Discovery · ${session.hostname}`,
                provider: session.graph.provider || "on-premise",
              });
              setExpandedNodeIds(session.graph.nodes.map((n) => n.id));
              setActiveTab("architecture");
              setMessage(`Grafo de discovery (${session.hostname}) cargado en el lienzo de Arquitectura.`);
            }
          }}
        />
      ) : activeTab === "architecture" ? (
        <>
          <CanvasToolbar
            activeLevel={activeLevel}
            onSelectLevel={setActiveLevel}
            onExpandAll={handleExpandAll}
            onCollapseAll={handleCollapseAll}
            focusNodeId={focusNodeId}
            onClearFocus={() => setFocusNodeId(null)}
            selectedCount={selectedNodes.length}
          />

          {breadcrumbs.length > 0 && (
            <Breadcrumbs
              breadcrumbs={breadcrumbs}
              onNavigate={(nodeId) => {
                const item = allNodes.find((n) => n.id === nodeId);
                if (item) setSelectedNodeObj(item);
              }}
              onReset={() => setSelectedNodeObj(null)}
              onBack={handleBack}
            />
          )}

          {message && <div className="app-message-banner">{message}</div>}

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
      ) : activeTab === "dependencies" ? (
        <div className="tab-pane-view">
          <h3>Dependency Resolution Engine</h3>
          <p className="sub-text">
            Select components on the Architecture canvas to analyze direct, transitive and shared dependencies.
          </p>
          {selectedNodes.length === 0 ? (
            <p className="empty-text">No resources currently selected for dependency resolution.</p>
          ) : (
            <button type="button" className="tech-btn primary" onClick={resolveDependencies}>
              Calculate Migration Scope & Dependencies ({selectedNodes.length} selected)
            </button>
          )}
        </div>
      ) : activeTab === "iac" ? (
        <div className="tab-pane-view">
          <h3>Generated Infrastructure as Code (IaC)</h3>
          {generationResult ? (
            <IaCViewer
              code={generationResult.iac_code || generationResult.terraform}
              language={targetProvider === "kubernetes" ? "yaml" : "hcl"}
              filename={targetProvider === "kubernetes" ? "manifests.yaml" : "main.tf"}
            />
          ) : (
            <p className="empty-text">
              No IaC generated yet. Select resources and run &apos;Prepare Migration&apos;.
            </p>
          )}
        </div>
      ) : (
        <div className="tab-pane-view">
          <h3>{activeTab.toUpperCase()} Module</h3>
          <p className="sub-text">
            Module &apos;{activeTab}&apos; active. Connected to CMIR Domain Engine v2.0.
          </p>
        </div>
      )}

      {showMigrationModal && (
        <MigrationPreviewModal
          selectedNodes={selectedNodes}
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