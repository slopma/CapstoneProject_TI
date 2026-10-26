import React, { useState, useEffect, useCallback, useRef } from "react";
import { getApiBase, buildUrl } from "../../utils/apiClient";
import DiscoveryDiagramCanvas from "./DiscoveryDiagramCanvas";
import CloudMoveDiscovery from "./CloudMoveDiscovery";
import DataCenterCampaignPanel from "./DataCenterCampaignPanel";
import {
  SummarySection,
  HardwareSection,
  SoftwareSection,
  NetworkSection,
  RuntimeSection,
  DatabasesSection,
  AssessmentSection,
  AwsSuggestedDiagramSection,
} from "./DiscoverySections";

const SECTION_NAV = [
  {
    id: "summary",
    label: "A. Summary",
    subtitle: "Resumen ejecutivo y cobertura",
    subsections: [
      { id: "summary-warnings", label: "Calidad y advertencias" },
      { id: "summary-explanations", label: "Análisis explicativo" },
    ],
  },
  {
    id: "diagram",
    label: "Diagrama Principal",
    subtitle: "Mapa interactivo de infraestructura",
    subsections: [],
  },
  {
    id: "aws-archify",
    label: "H. Diagrama AWS y Terraform",
    subtitle: "Archify + HCL desde JSON",
    subsections: [
      { id: "aws-archify-viewer", label: "1. Visor Interactivo Archify" },
      { id: "aws-mapping-table", label: "2. Mapeo Osquery → AWS" },
      { id: "aws-terraform-traceability", label: "3. Trazabilidad JSON → HCL" },
      { id: "aws-terraform-files", label: "4. Código Terraform (.tf)" },
      { id: "aws-archify-explanations", label: "5. Justificación técnica" },
    ],
  },
  {
    id: "datacenter-campaigns",
    label: "I. Campañas Data Center",
    subtitle: "Descubrimiento masivo 1-clic",
    subsections: [
      { id: "dc-sites-collectors", label: "Colectores por sitio y CIDR" },
      { id: "dc-nodes-matrix", label: "Matriz de nodos y 8 controles" },
      { id: "dc-task-queues", label: "Colas de tareas e idempotencia" },
    ],
  },
  {
    id: "hardware",
    label: "B. Hardware",
    subtitle: "CPU, RAM, Discos y Firmware",
    subsections: [
      { id: "hw-cpu", label: "CPU" },
      { id: "hw-memory", label: "Memoria y Swap" },
      { id: "hw-storage", label: "Almacenamiento y Montajes" },
      { id: "hw-firmware", label: "Firmware y Placa Base" },
      { id: "hw-other", label: "Otras características" },
    ],
  },
  {
    id: "software",
    label: "C. Software",
    subtitle: "Paquetes, Servicios y Módulos",
    subsections: [
      { id: "sw-relevant-apps", label: "Aplicaciones relevantes" },
      { id: "sw-services", label: "Servicios del sistema" },
      { id: "sw-packages", label: "Paquetes instalados" },
      { id: "sw-kernel-modules", label: "Módulos del kernel" },
    ],
  },
  {
    id: "network",
    label: "D. Network",
    subtitle: "Interfaces, Rutas, Puertos y Sockets",
    subsections: [
      { id: "net-interfaces", label: "Interfaces y Subredes" },
      { id: "net-listening-ports", label: "Puertos en escucha" },
      { id: "net-remote-endpoints", label: "Endpoints remotos observados" },
      { id: "net-routes", label: "Rutas y Gateways" },
    ],
  },
  {
    id: "runtime",
    label: "E. Runtime / Processes",
    subtitle: "Procesos activos y Uptime",
    subsections: [
      { id: "rt-processes", label: "Procesos y relación con puertos" },
    ],
  },
  {
    id: "databases",
    label: "F. Bases de Datos",
    subtitle: "Indicios vs. Recolectores de catálogo",
    subsections: [
      { id: "db-evidence", label: "Indicios en el host" },
      { id: "db-collectors", label: "Conectores específicos" },
    ],
  },
  {
    id: "assessment",
    label: "G. Assessment Migración",
    subtitle: "Preparación AWS y riesgos",
    subsections: [
      { id: "assess-risks", label: "Riesgos detectados" },
      { id: "assess-deps", label: "Dependencias confirmadas vs. observadas" },
      { id: "assess-next-steps", label: "Próximos pasos" },
    ],
  },
];

export default function DiscoveryWorkspace({ apiUrl, onSyncToArchitecture }) {
  const [activeSection, setActiveSection] = useState("summary");
  const [sessionData, setSessionData] = useState(null);
  const [sessionsList, setSessionsList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [errorBanner, setErrorBanner] = useState("");
  const [statusBanner, setStatusBanner] = useState("");
  const [resolvedApiBase, setResolvedApiBase] = useState(apiUrl || getApiBase() || "");
  const fileInputRef = useRef(null);

  const fetchWithFallback = useCallback(
    async (path, options = {}) => {
      const candidates = Array.from(
        new Set([
          apiUrl,
          resolvedApiBase,
          getApiBase(),
          "",
        ].filter((c) => c !== undefined && c !== null))
      );

      let lastError = null;
      let lastResponse = null;

      for (const base of candidates) {
        try {
          const targetUrl = buildUrl(base, path);
          const res = await fetch(targetUrl, options);
          // Vite proxy returns 502/504 or 500 empty when target is ECONNREFUSED
          if (res.status === 502 || res.status === 504) {
            lastResponse = res;
            continue;
          }
          const contentType = res.headers.get("content-type") || "";
          if (res.status === 500 && !contentType.includes("application/json")) {
            lastResponse = res;
            continue;
          }
          setResolvedApiBase(base);
          return res;
        } catch (err) {
          lastError = err;
        }
      }

      if (lastResponse) return lastResponse;
      throw lastError || new Error("Backend unreachable");
    },
    [apiUrl, resolvedApiBase]
  );

  const fetchSessionsList = useCallback(async () => {
    try {
      const res = await fetchWithFallback(`/api/v1/discovery/sessions`);
      if (res.ok) {
        const json = await res.json();
        setSessionsList(json.sessions || []);
      }
    } catch {
      // Ignore list error when offline
    }
  }, [fetchWithFallback]);

  const loadLatestSession = useCallback(async () => {
    setLoading(true);
    setErrorBanner("");
    try {
      const res = await fetchWithFallback(`/api/v1/discovery/latest`);
      if (res.ok) {
        const json = await res.json();
        setSessionData(json);
        await fetchSessionsList();
      } else {
        const err = await res.json().catch(() => ({}));
        setErrorBanner(err.detail?.message || err.detail || "No hay inventario cargado. Importe un archivo JSON.");
      }
    } catch {
      setErrorBanner(
        "No se pudo conectar con el backend de CloudMove. Verifique que FastAPI esté activo en el puerto 8000 u 8001."
      );
    } finally {
      setLoading(false);
    }
  }, [fetchWithFallback, fetchSessionsList]);

  useEffect(() => {
    loadLatestSession();
  }, [loadLatestSession]);

  const handleImportLocalPreset = async () => {
    setImporting(true);
    setErrorBanner("");
    setStatusBanner("");
    try {
      const res = await fetchWithFallback(`/api/v1/discovery/import-local`, {
        method: "POST",
      });
      const json = await res.json();
      if (!res.ok) {
        throw new Error(json.detail?.message || json.detail || "Error al importar inventario local.");
      }
      setSessionData(json);
      await fetchSessionsList();
      setStatusBanner(
        `Inventario osquery '${json.filename}' (${json.hostname}) analizado y normalizado correctamente.`
      );
    } catch (err) {
      setErrorBanner(err.message || "Fallo al cargar inventario local.");
    } finally {
      setImporting(false);
    }
  };

  const [scanningDevice, setScanningDevice] = useState(false);
  const [showCollectorModal, setShowCollectorModal] = useState(false);

  const handleCollectLiveDevice = async () => {
    setScanningDevice(true);
    setImporting(true);
    setErrorBanner("");
    setStatusBanner("Ejecutando cloudmove_osquery_export.py (osqueryi) en este dispositivo...");
    try {
      const res = await fetchWithFallback(`/api/v1/discovery/collect-device`, {
        method: "POST",
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg =
          json.detail?.message ||
          (typeof json.detail === "string"
            ? json.detail
            : "No se pudo ejecutar osqueryi en el dispositivo local.");
        throw new Error(msg);
      }
      setSessionData(json);
      await fetchSessionsList();
      setStatusBanner(
        `Escaneo en vivo completado en '${json.hostname}' (${json.summary?.os?.name || "Linux"}) · Sesión activa: ${json.session_id}.`
      );
    } catch (err) {
      setStatusBanner("");
      setErrorBanner(err.message || "Error al ejecutar el recolector osquery en el dispositivo.");
    } finally {
      setScanningDevice(false);
      setImporting(false);
    }
  };

  const handleDownloadCollectorScript = () => {
    const url = buildUrl(resolvedApiBase, "/api/v1/discovery/collector-script");
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const handleFileUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setImporting(true);
    setErrorBanner("");
    setStatusBanner("");

    try {
      const textContent = await file.text();
      const res = await fetchWithFallback(`/api/v1/discovery/import`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Filename": file.name,
        },
        body: textContent,
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg =
          json.detail?.message ||
          (typeof json.detail === "string" ? json.detail : "El archivo JSON no superó la validación de esquema.");
        throw new Error(msg);
      }
      setSessionData(json);
      await fetchSessionsList();
      setStatusBanner(
        `Archivo '${file.name}' importado con éxito (Activo: ${json.hostname} · Sesión: ${json.session_id}).`
      );
    } catch (err) {
      setErrorBanner(err.message || "Error al importar el archivo JSON.");
    } finally {
      setImporting(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleSelectSession = async (sessionId) => {
    if (!sessionId || sessionId === sessionData?.session_id) return;
    setLoading(true);
    setErrorBanner("");
    try {
      const res = await fetchWithFallback(`/api/v1/discovery/sessions/${sessionId}`);
      if (res.ok) {
        const json = await res.json();
        setSessionData(json);
        setStatusBanner(`Consultando análisis previo: ${json.hostname} (${json.session_id}).`);
      }
    } catch {
      setErrorBanner("No se pudo recuperar la sesión seleccionada.");
    } finally {
      setLoading(false);
    }
  };

  const handleExport = (fmt) => {
    if (!sessionData?.session_id) return;
    const url = buildUrl(resolvedApiBase, `/api/v1/discovery/sessions/${sessionData.session_id}/export?format=${fmt}`);
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const handleNavigateFromDiagram = useCallback((sectionId, subsectionId) => {
    setActiveSection(sectionId);
    if (subsectionId) {
      setTimeout(() => {
        const el = document.getElementById(subsectionId) || document.getElementById(`hw-${subsectionId}`) || document.getElementById(`sw-${subsectionId}`) || document.getElementById(`net-${subsectionId}`);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      }, 80);
    }
  }, []);

  return (
    <div className="disc-workspace-shell" data-ui="discovery-workspace">
      {/* Top Import & Session Bar */}
      <header className="disc-top-action-bar">
        <div className="disc-top-left">
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,application/json"
            style={{ display: "none" }}
            onChange={handleFileUpload}
          />
          <button
            type="button"
            className="tech-btn primary"
            onClick={() => setShowCollectorModal((v) => !v)}
            title="Detectar sistema operativo del PC, preparar/instalar osquery automáticamente, probar el binario y escanear el equipo"
          >
            {showCollectorModal ? "Ocultar Descubrimiento de Equipo" : "Descubrir Equipo (Instalar osquery + Escanear)"}
          </button>

          <button
            type="button"
            className="toolbar-btn"
            onClick={() => setActiveSection("datacenter-campaigns")}
            title="Abrir tablero de Descubrimiento Completo del Data Center (Campañas masivas en 4 modos)"
          >
            Campaña Data Center (Masivo)
          </button>

          <button
            type="button"
            className="toolbar-btn"
            disabled={importing}
            onClick={handleCollectLiveDevice}
            title="Ejecutar escaneo rápido de este dispositivo"
          >
            {scanningDevice ? "Escaneando..." : "Escaneo Rápido"}
          </button>

          <button
            type="button"
            className="toolbar-btn"
            disabled={importing}
            onClick={() => fileInputRef.current?.click()}
          >
            {importing && !scanningDevice ? "Procesando JSON..." : "Importar JSON osquery"}
          </button>

          <button
            type="button"
            className="toolbar-btn"
            disabled={importing}
            onClick={handleImportLocalPreset}
            title="Cargar y analizar docs/cloudmove-osquery-inventory.json"
          >
            Recargar inventario local (Kali Linux)
          </button>

          {sessionsList.length > 0 && (
            <div className="disc-session-picker">
              <label htmlFor="disc-session-select" className="toolbar-label">
                Análisis importados:
              </label>
              <select
                id="disc-session-select"
                className="disc-select"
                value={sessionData?.session_id || ""}
                onChange={(e) => handleSelectSession(e.target.value)}
              >
                {sessionsList.map((s) => (
                  <option key={s.session_id} value={s.session_id}>
                    {s.hostname} — {s.filename} ({s.session_id})
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {sessionData && (
          <div className="disc-top-right">
            <button
              type="button"
              className="toolbar-btn"
              onClick={() => handleExport("json")}
              title="Descargar inventario normalizado JSON (re-importable)"
            >
              Exportar JSON Normalizado
            </button>
            <button
              type="button"
              className="toolbar-btn"
              onClick={() => handleExport("md")}
              title="Descargar informe técnico en Markdown"
            >
              Exportar Informe (.md)
            </button>
            <button
              type="button"
              className="toolbar-btn"
              onClick={() => handleExport("cmir")}
              title="Descargar representación CMIR v2.0"
            >
              Exportar CMIR
            </button>
            <button
              type="button"
              className="toolbar-btn"
              onClick={() => handleExport("tf")}
              title="Descargar código Terraform AWS generado desde el JSON"
            >
              Exportar Terraform (.tf)
            </button>
            {onSyncToArchitecture && sessionData.graph && (
              <button
                type="button"
                className="toolbar-btn"
                onClick={() => onSyncToArchitecture(sessionData)}
                title="Cargar este grafo descubierto en la vista general de Arquitectura"
              >
                Ver en Lienzo Arquitectura
              </button>
            )}
          </div>
        )}
      </header>

      {showCollectorModal && (
        <CloudMoveDiscovery
          apiBaseUrl={resolvedApiBase}
          onInventoryDiscovered={async (sessionPayload) => {
            setSessionData(sessionPayload);
            await fetchSessionsList();
            setStatusBanner(
              `Equipo '${sessionPayload.hostname}' descubierto y analizado automáticamente (Sesión: ${sessionPayload.session_id}).`
            );
          }}
          onClose={() => setShowCollectorModal(false)}
        />
      )}

      {errorBanner && (
        <div className="disc-banner is-error" role="alert">
          <strong>Error de validación / importación:</strong> {errorBanner}
          <button type="button" onClick={() => setErrorBanner("")}>&times;</button>
        </div>
      )}

      {statusBanner && (
        <div className="disc-banner is-success" role="status">
          <span>{statusBanner}</span>
          <button type="button" onClick={() => setStatusBanner("")}>&times;</button>
        </div>
      )}

      {loading ? (
        <div className="disc-loading-state">
          <p>Analizando y normalizando inventario de infraestructura...</p>
        </div>
      ) : !sessionData ? (
        <div className="disc-empty-state">
          <h3>Sin inventario de discovery activo</h3>
          <p>
            Escanee este dispositivo en vivo con <code>osqueryi</code>, seleccione un archivo JSON generado por{" "}
            <code>cloudmove_osquery_export.py</code> o cargue el inventario local del proyecto.
          </p>
          <div className="disc-empty-actions">
            <button
              type="button"
              className="tech-btn primary"
              disabled={importing}
              onClick={handleCollectLiveDevice}
            >
              {scanningDevice ? "Escaneando dispositivo..." : "Escanear Este Dispositivo (osquery en vivo)"}
            </button>
            <button
              type="button"
              className="toolbar-btn"
              onClick={() => fileInputRef.current?.click()}
            >
              Seleccionar archivo JSON
            </button>
            <button
              type="button"
              className="toolbar-btn"
              onClick={handleImportLocalPreset}
            >
              Analizar docs/cloudmove-osquery-inventory.json
            </button>
          </div>
        </div>
      ) : (
        <div className="disc-body-split">
          {/* Left Section & Subsection Navigation Tree */}
          <aside className="disc-left-rail" aria-label="Secciones del análisis de discovery">
            <div className="disc-asset-mini-header">
              <span className="disc-asset-tag">ACTIVO DESCUBIERTO</span>
              <strong className="disc-asset-hostname">{sessionData.hostname}</strong>
              <span className="disc-asset-os">
                {sessionData.summary?.os?.name} {sessionData.summary?.os?.version}
              </span>
            </div>

            <nav className="disc-rail-nav">
              {SECTION_NAV.map((sec) => {
                const isActive = activeSection === sec.id;
                return (
                  <div key={sec.id} className="disc-rail-group">
                    <button
                      type="button"
                      className={`disc-rail-btn ${isActive ? "is-active" : ""}`}
                      onClick={() => setActiveSection(sec.id)}
                    >
                      <span className="disc-rail-label">{sec.label}</span>
                      <small className="disc-rail-sub">{sec.subtitle}</small>
                    </button>

                    {isActive && sec.subsections.length > 0 && (
                      <ul className="disc-rail-sublist">
                        {sec.subsections.map((sub) => (
                          <li key={sub.id}>
                            <button
                              type="button"
                              className="disc-rail-subbtn"
                              onClick={() => {
                                const el = document.getElementById(sub.id);
                                if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
                              }}
                            >
                              {sub.label}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
            </nav>
          </aside>

          {/* Main Section Content or Full Interactive Diagram */}
          <div className={`disc-main-pane ${activeSection === "diagram" ? "is-diagram-mode" : ""}`}>
            {activeSection === "diagram" && (
              <DiscoveryDiagramCanvas
                graphData={sessionData.graph}
                onNavigateToSection={handleNavigateFromDiagram}
              />
            )}
            {activeSection === "aws-archify" && (
              <AwsSuggestedDiagramSection data={sessionData} apiUrl={resolvedApiBase} />
            )}
            {activeSection === "datacenter-campaigns" && (
              <DataCenterCampaignPanel apiBaseUrl={resolvedApiBase} />
            )}
            {activeSection === "summary" && (
              <SummarySection
                data={sessionData}
                onNavigateSection={setActiveSection}
              />
            )}
            {activeSection === "hardware" && (
              <HardwareSection hardware={sessionData.sections?.hardware} />
            )}
            {activeSection === "software" && (
              <SoftwareSection
                software={sessionData.sections?.software}
                sessionId={sessionData.session_id}
                apiUrl={resolvedApiBase}
              />
            )}
            {activeSection === "network" && (
              <NetworkSection network={sessionData.sections?.network} />
            )}
            {activeSection === "runtime" && (
              <RuntimeSection runtime={sessionData.sections?.runtime} />
            )}
            {activeSection === "databases" && (
              <DatabasesSection databases={sessionData.sections?.databases} />
            )}
            {activeSection === "assessment" && (
              <AssessmentSection assessment={sessionData.sections?.assessment} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
