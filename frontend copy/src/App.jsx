import { useEffect, useState } from "react";
import ArchitectureGraph from "./components/ArchitectureGraph";
import "./App.css";

const API_URL = "http://localhost:8001";

const resourceMeta = {
  compute: {
    title: "Servidor de aplicación",
    description: "Procesa la lógica de negocio, APIs y servicios transaccionales.",
    accent: "#2563eb",
  },
  database: {
    title: "Base de datos",
    description: "Almacena información persistente y relaciones de negocio.",
    accent: "#7c3aed",
  },
  cache: {
    title: "Caché",
    description: "Reduce latencia y mejora rendimiento para datos frecuentes.",
    accent: "#0f766e",
  },
};

function ResourceDiagram({ node, selected, onSelect }) {
  const meta = resourceMeta[node.type] || {
    title: "Servicio",
    description: "Componente que participa en el flujo de la arquitectura.",
    accent: "#475569",
  };

  const renderGlyph = () => {
    if (node.type === "database") {
      return (
        <svg viewBox="0 0 120 90" aria-hidden="true">
          <ellipse cx="60" cy="20" rx="36" ry="12" fill="none" stroke={meta.accent} strokeWidth="3" />
          <path d="M24 20v48c0 8 16 14 36 14s36-6 36-14V20" fill="none" stroke={meta.accent} strokeWidth="3" />
          <path d="M24 35c0 8 16 14 36 14s36-6 36-14" fill="none" stroke={meta.accent} strokeWidth="3" />
        </svg>
      );
    }

    if (node.type === "cache") {
      return (
        <svg viewBox="0 0 120 90" aria-hidden="true">
          <rect x="22" y="25" width="76" height="14" rx="6" fill={meta.accent} opacity="0.18" />
          <rect x="22" y="42" width="76" height="14" rx="6" fill={meta.accent} opacity="0.38" />
          <rect x="22" y="59" width="76" height="14" rx="6" fill={meta.accent} opacity="0.7" />
          <path d="M18 18h84" stroke={meta.accent} strokeWidth="3" strokeLinecap="round" />
        </svg>
      );
    }

    return (
      <svg viewBox="0 0 120 90" aria-hidden="true">
        <rect x="24" y="20" width="72" height="46" rx="10" fill="none" stroke={meta.accent} strokeWidth="3" />
        <path d="M38 20v-8h44v8" fill="none" stroke={meta.accent} strokeWidth="3" />
        <rect x="42" y="36" width="36" height="8" rx="4" fill={meta.accent} opacity="0.18" />
        <rect x="42" y="48" width="28" height="8" rx="4" fill={meta.accent} opacity="0.18" />
      </svg>
    );
  };

  return (
    <button
      type="button"
      className={`diagram-card ${selected ? "selected" : ""}`}
      onClick={() => onSelect(node.id)}
    >
      <span className="diagram-header">
        <span className="diagram-badge" style={{ background: meta.accent }} />
        <span>{node.type}</span>
      </span>
      <div className="diagram-visual">{renderGlyph()}</div>
      <strong>{node.name}</strong>
      <p>{meta.description}</p>
    </button>
  );
}

function App() {
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [selectedNodes, setSelectedNodes] = useState([]);
  const [dependencies, setDependencies] = useState([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState("");
  const [generationResult, setGenerationResult] = useState(null);

  useEffect(() => {
    fetch(`${API_URL}/graph`)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Graph request failed");
        }

        return response.json();
      })
      .then((data) => setGraph(data))
      .catch(() => setMessage("No se pudo conectar con CloudMove Backend."));
  }, []);

  const toggleResource = (resourceId) => {
    setSelectedNodes((current) =>
      current.includes(resourceId)
        ? current.filter((id) => id !== resourceId)
        : [...current, resourceId]
    );
  };

  const resolveDependencies = async () => {
    if (selectedNodes.length === 0) {
      setMessage("Selecciona al menos un recurso.");
      return;
    }

    setLoading(true);
    setMessage("");
    setGenerationResult(null);

    try {
      const response = await fetch(`${API_URL}/dependencies`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          resources: selectedNodes,
        }),
      });

      const data = await response.json();

      if (!response.ok || data.error) {
        throw new Error(
          data.error?.message || "No se pudieron resolver las dependencias."
        );
      }

      setDependencies(data.dependencies || []);
      setMessage("Dependencias resueltas correctamente.");
    } catch (error) {
      setMessage(error.message || "Error conectando con el backend.");
    } finally {
      setLoading(false);
    }
  };

  const generateTerraform = async () => {
    if (selectedNodes.length === 0) {
      setMessage("Selecciona al menos un recurso.");
      return;
    }

    setGenerating(true);
    setMessage("");
    setGenerationResult(null);

    try {
      const response = await fetch(`${API_URL}/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          resources: selectedNodes,
        }),
      });

      const data = await response.json();

      if (!response.ok || data.error) {
        throw new Error(
          data.error?.message || "No se pudo generar Terraform."
        );
      }

      setGenerationResult(data);
      setDependencies(data.dependencies || []);
      setMessage("Terraform generado correctamente para AWS.");
    } catch (error) {
      setMessage(error.message || "Error generando Terraform.");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>CloudMove</h1>
          <p>Plataforma de abstracción de arquitectura y migración selectiva</p>
        </div>
        <div className="status">
          <span className="status-dot"></span>
          MVP · AWS
        </div>
      </header>

      <main className="container">
        <div className="overview-strip">
          <div className="metric-card">
            <span>Recursos</span>
            <strong>{graph.nodes.length}</strong>
          </div>
          <div className="metric-card">
            <span>Seleccionados</span>
            <strong>{selectedNodes.length}</strong>
          </div>
          <div className="metric-card">
            <span>Destino</span>
            <strong>AWS</strong>
          </div>
        </div>

        <section className="studio-hero card">
          <div className="hero-copy">
            <span className="step-pill">Migración inteligente</span>
            <h2>Mapea tu infraestructura antes de moverla.</h2>
            <p>
              Cada servicio aporta una función distinta: un servidor procesa, una base de
              datos guarda, y una capa de caché acelera la experiencia.
            </p>
          </div>
          <div className="hero-diagram">
            <div className="diagram-flow">
              <div className="flow-node flow-node-primary">
                <span>API</span>
                <small>Compute</small>
              </div>
              <div className="flow-connector" />
              <div className="flow-node flow-node-violet">
                <span>DB</span>
                <small>PostgreSQL</small>
              </div>
              <div className="flow-connector" />
              <div className="flow-node flow-node-teal">
                <span>Cache</span>
                <small>Redis</small>
              </div>
            </div>
          </div>
        </section>

        <section className="card">
          <div className="section-header">
            <span className="step-pill">Paso 1</span>
            <h2>Arquitectura On-Premise</h2>
          </div>
          <p>Selecciona los recursos que deseas migrar.</p>
          <ArchitectureGraph
            nodes={graph.nodes}
            edges={graph.edges}
            selectedNodes={selectedNodes}
            onNodeClick={toggleResource}
          />
        </section>

        <section className="card">
          <div className="section-header">
            <span className="step-pill">Paso 2</span>
            <h2>Componentes del servidor a migrar</h2>
          </div>
          <p>Representación visual de cada bloque funcional con una explicación breve.</p>
          <div className="diagram-grid">
            {graph.nodes.map((node) => (
              <ResourceDiagram
                key={node.id}
                node={node}
                selected={selectedNodes.includes(node.id)}
                onSelect={toggleResource}
              />
            ))}
          </div>

          <div className="selection-summary compact">
            <strong>Recursos seleccionados:</strong>
            {selectedNodes.length === 0 ? " Ninguno" : ` ${selectedNodes.join(", ")}`}
          </div>

          <div className="selection-actions">
            <button
              className="primary-button"
              onClick={resolveDependencies}
              disabled={loading || selectedNodes.length === 0}
            >
              {loading ? "Resolviendo..." : "Resolver dependencias"}
            </button>
          </div>

          {message && <p className="message">{message}</p>}
        </section>

        <section className="card">
          <div className="section-header">
            <span className="step-pill">Paso 3</span>
            <h2>Dependencias resueltas</h2>
          </div>
          {dependencies.length === 0 ? (
            <p>Selecciona recursos y ejecuta la resolución de dependencias.</p>
          ) : (
            <div className="dependency-list">
              {dependencies.map((dependency) => (
                <div key={dependency} className="dependency-item">
                  {dependency}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card">
          <div className="section-header">
            <span className="step-pill">Paso 4</span>
            <h2>Cloud destino</h2>
          </div>

          <div className="cloud-options">
            <div className="cloud selected">
              <strong>AWS</strong>
              <span>Amazon Web Services</span>
            </div>
          </div>

          <p className="cloud-label">
            Cloud seleccionada:
            <strong> AWS</strong>
          </p>

          <button
            className="secondary-button"
            onClick={generateTerraform}
            disabled={generating || selectedNodes.length === 0}
          >
            {generating ? "Generando Terraform..." : "Generar Terraform"}
          </button>

          {generationResult && (
            <div className="generation-result">
              <h3>Generación completada</h3>
              <p>
                <strong>Destino:</strong> AWS
              </p>
              <p>
                <strong>Recursos:</strong>{" "}
                {generationResult.resources_generated.join(", ")}
              </p>
              <p>
                <strong>Archivo:</strong> {generationResult.output}
              </p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;