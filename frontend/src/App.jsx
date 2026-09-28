import { useEffect, useState, useCallback, useMemo } from "react";
import ArchitectureGraph from "./components/ArchitectureGraph";
import BreadcrumbNav from "./components/BreadcrumbNav";
import DetailPanel from "./components/DetailPanel";
import MigrationPreviewModal from "./components/MigrationPreviewModal";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function App() {
  const [allNodes, setAllNodes] = useState([]);
  const [allEdges, setAllEdges] = useState([]);
  const [architectureMeta, setArchitectureMeta] = useState({ name: "On-Premise Datacenter", provider: "on-premise" });

  const [selectedNodes, setSelectedNodes] = useState([]);
  const [selectedNodeObj, setSelectedNodeObj] = useState(null);
  const [expandedNodeIds, setExpandedNodeIds] = useState(["onprem-dc", "rack-infra"]);
  const [activeLevel, setActiveLevel] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [targetProvider, setTargetProvider] = useState("aws");

  const [dependencies, setDependencies] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState("");
  const [generationResult, setGenerationResult] = useState(null);
  const [showMigrationModal, setShowMigrationModal] = useState(false);

  // Fetch Full Architecture from Backend
  const fetchArchitecture = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/v1/architecture/graph`);
      if (!response.ok) {
        const legacyRes = await fetch(`${API_URL}/graph`);
        const legacyData = await legacyRes.json();
        setAllNodes(legacyData.nodes || []);
        setAllEdges(legacyData.edges || []);
        return;
      }

      const data = await response.json();
      setAllNodes(data.nodes || []);
      setAllEdges(data.edges || []);
      setArchitectureMeta({
        name: data.architecture_name || "On-Premise Enterprise",
        provider: data.provider || "on-premise",
      });

      // Expand root nodes by default
      const rootIds = (data.nodes || [])
        .filter((n) => !n.parent_id || n.level <= 2)
        .map((n) => n.id);
      setExpandedNodeIds((prev) => (prev.length === 0 ? rootIds : prev));
    } catch (err) {
      setMessage("No se pudo conectar con CloudMove Backend API.");
    }
  }, []);

  useEffect(() => {
    fetchArchitecture();
  }, [fetchArchitecture]);

  // Progressive Expansion Logic: Calculate visible nodes based on expanded parent chain
  const visibleNodes = useMemo(() => {
    const isAncestorExpanded = (node) => {
      if (!node.parent_id) return true; // Root nodes are always visible
      if (!expandedNodeIds.includes(node.parent_id)) return false;
      const parentNode = allNodes.find((n) => n.id === node.parent_id);
      return parentNode ? isAncestorExpanded(parentNode) : true;
    };

    let filtered = allNodes.filter(isAncestorExpanded);

    if (activeLevel !== null) {
      filtered = filtered.filter((n) => (n.level ?? 8) === activeLevel);
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
  }, [allNodes, expandedNodeIds, activeLevel, searchQuery]);

  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);

  const visibleEdges = useMemo(() => {
    return allEdges.filter((e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target));
  }, [allEdges, visibleNodeIds]);

  const handleToggleExpand = (nodeId) => {
    setExpandedNodeIds((prev) => {
      if (prev.includes(nodeId)) {
        return prev.filter((id) => id !== nodeId);
      } else {
        return [...prev, nodeId];
      }
    });
  };

  const handleExpandAll = () => {
    setExpandedNodeIds(allNodes.map((n) => n.id));
  };

  const handleCollapseAll = () => {
    const rootIds = allNodes.filter((n) => !n.parent_id || n.level <= 1).map((n) => n.id);
    setExpandedNodeIds(rootIds);
  };

  const toggleResource = (nodeId) => {
    setSelectedNodes((current) =>
      current.includes(nodeId) ? current.filter((id) => id !== nodeId) : [...current, nodeId]
    );

    const targetObj = allNodes.find((n) => n.id === nodeId);
    setSelectedNodeObj(targetObj || null);
  };

  const resolveDependencies = async () => {
    if (selectedNodes.length === 0) {
      setMessage("Selecciona al menos un componente para la migración.");
      return;
    }

    setLoading(true);
    setMessage("");

    try {
      const response = await fetch(`${API_URL}/api/v1/migration/dependencies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resources: selectedNodes }),
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Error resolviendo dependencias.");

      setDependencies(data);
      setShowMigrationModal(true);
      setMessage("Subgrafo migrable y dependencias calculadas.");
    } catch (error) {
      setMessage(error.message || "Error conectando con el backend.");
    } finally {
      setLoading(false);
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
        throw new Error(data.error?.message || data.detail || "No se pudo generar el código IaC.");
      }

      setGenerationResult(data);
      setMessage(`Infraestructura (${targetProvider.toUpperCase()}) generada con éxito.`);
    } catch (error) {
      setMessage(error.message || "Error en la generación IaC.");
    } finally {
      setGenerating(false);
    }
  };

  // Compute breadcrumbs path for currently selected node
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

  return (
    <div className="app-container">
      <header className="header-bar">
        <div className="header-brand">
          <span className="brand-logo">🏢</span>
          <div>
            <h1>CloudMove · On-Premise Migration Platform</h1>
            <p>Descubrimiento On-Premise · Despliegue Jerárquico Progresivo · Generador IaC Multicloud</p>
          </div>
        </div>

        <div className="header-actions">
          <div className="search-box">
            <input
              type="text"
              placeholder="Buscar recurso, VM, DB, VLAN..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          <button
            type="button"
            className="primary-btn-action"
            onClick={resolveDependencies}
            disabled={selectedNodes.length === 0 || loading}
          >
            {loading ? "Calculando..." : `Preparar Migración (${selectedNodes.length})`}
          </button>
        </div>
      </header>

      <div className="main-content">
        <section className="controls-strip">
          <div className="progressive-expansion-controls">
            <span className="expansion-label">Despliegue Progresivo:</span>
            <button type="button" className="action-btn-sm" onClick={handleExpandAll}>
              ▶ Expandir Todo
            </button>
            <button type="button" className="action-btn-sm outline" onClick={handleCollapseAll}>
              ▼ Contraer a Raíz
            </button>
          </div>

          <div className="level-filter-bar">
            <span className="filter-label">Nivel:</span>
            <button
              type="button"
              className={`level-btn ${activeLevel === null ? "active" : ""}`}
              onClick={() => setActiveLevel(null)}
            >
              Todos (L1-L8)
            </button>
            {[1, 2, 3, 4, 5, 6, 7, 8].map((lvl) => (
              <button
                key={lvl}
                type="button"
                className={`level-btn ${activeLevel === lvl ? "active" : ""}`}
                onClick={() => setActiveLevel(lvl)}
              >
                L{lvl}
              </button>
            ))}
          </div>
        </section>

        {breadcrumbs.length > 0 && (
          <div className="breadcrumb-wrapper">
            <BreadcrumbNav
              breadcrumbs={breadcrumbs}
              onNavigate={(nodeId) => {
                const n = allNodes.find((item) => item.id === nodeId);
                setSelectedNodeObj(n || null);
              }}
              onReset={() => setSelectedNodeObj(null)}
            />
          </div>
        )}

        {message && <div className="app-message-banner">{message}</div>}

        <section className="graph-workspace">
          <ArchitectureGraph
            nodes={visibleNodes}
            edges={visibleEdges}
            selectedNodes={selectedNodes}
            expandedNodeIds={expandedNodeIds}
            onNodeClick={toggleResource}
            onToggleExpand={handleToggleExpand}
          />
        </section>

        {selectedNodeObj && (
          <DetailPanel
            node={selectedNodeObj}
            allNodes={allNodes}
            edges={allEdges}
            onClose={() => setSelectedNodeObj(null)}
            onSelectNode={(nodeId) => {
              toggleResource(nodeId);
              if (!expandedNodeIds.includes(nodeId)) {
                handleToggleExpand(nodeId);
              }
            }}
            targetProvider={targetProvider}
          />
        )}
      </div>

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
    </div>
  );
}

export default App;