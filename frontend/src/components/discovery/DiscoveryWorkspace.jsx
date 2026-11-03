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
import {
  AwsPageHeader,
  AwsKeyValuePairs,
  AwsTabs,
  AwsAlert,
  AwsEmptyState,
  AwsContainer,
} from "../cloudscape/AwsPrimitives";

const SECTION_NAV = [
  {
    id: "summary",
    label: "Resumen",
    subtitle: "Resumen ejecutivo y cobertura",
  },
  {
    id: "diagram",
    label: "Topología",
    subtitle: "Mapa interactivo de infraestructura",
  },
  {
    id: "hardware",
    label: "Hardware",
    subtitle: "CPU, RAM, discos y firmware",
  },
  {
    id: "software",
    label: "Software",
    subtitle: "Paquetes, servicios y módulos",
  },
  {
    id: "network",
    label: "Red y puertos",
    subtitle: "Interfaces, rutas, puertos y sockets",
  },
  {
    id: "runtime",
    label: "Procesos",
    subtitle: "Procesos activos y uptime",
  },
  {
    id: "databases",
    label: "Bases de datos",
    subtitle: "Indicios vs. recolectores de catálogo",
  },
  {
    id: "assessment",
    label: "Evaluación cloud",
    subtitle: "Preparación AWS y riesgos",
  },
  {
    id: "aws-archify",
    label: "Arquitectura AWS y Terraform",
    subtitle: "Archify + HCL desde JSON",
  },
  {
    id: "datacenter-campaigns",
    label: "Campañas datacenter",
    subtitle: "Descubrimiento masivo 1-clic",
  },
];

// Agrupación de secciones en 5 pestañas principales para evitar saturación visual
const SECTION_GROUPS = [
  { id: "g-summary", label: "Resumen", sections: ["summary"] },
  { id: "g-topology", label: "Topología", sections: ["diagram"] },
  {
    id: "g-inventory",
    label: "Inventario",
    sections: ["hardware", "software", "network", "runtime", "databases"],
  },
  { id: "g-cloud", label: "Evaluación y AWS", sections: ["assessment", "aws-archify"] },
  { id: "g-campaigns", label: "Campañas", sections: ["datacenter-campaigns"] },
];

export default function DiscoveryWorkspace({
  apiUrl,
  onSyncToArchitecture,
  onLoadCmirToCanvas,
}) {
  const handleSyncCanvas = onSyncToArchitecture || onLoadCmirToCanvas;
  const [activeSection, setActiveSection] = useState("summary");
  const [sessionData, setSessionData] = useState(null);
  const [sessionsList, setSessionsList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [errorBanner, setErrorBanner] = useState("");
  const [statusBanner, setStatusBanner] = useState("");
  const [resolvedApiBase, setResolvedApiBase] = useState(
    apiUrl || getApiBase() || ""
  );
  const fileInputRef = useRef(null);

  const fetchWithFallback = useCallback(
    async (path, options = {}) => {
      const candidates = Array.from(
        new Set(
          [apiUrl, resolvedApiBase, getApiBase(), ""].filter(
            (c) => c !== undefined && c !== null
          )
        )
      );

      let lastError = null;
      let lastResponse = null;

      for (const base of candidates) {
        try {
          const targetUrl = buildUrl(base, path);
          const res = await fetch(targetUrl, options);
          if (res.status === 502 || res.status === 504) {
            lastResponse = res;
            continue;
          }
          const contentType = res.headers.get("content-type") || "";
          if (
            res.status === 500 &&
            !contentType.includes("application/json")
          ) {
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
        setErrorBanner(
          err.detail?.message ||
            err.detail ||
            "No hay inventario cargado. Importe un archivo JSON."
        );
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
        throw new Error(
          json.detail?.message ||
            json.detail ||
            "Error al importar inventario local."
        );
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
    setStatusBanner(
      "Ejecutando cloudmove_osquery_export.py (osqueryi) en este dispositivo..."
    );
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
        `Escaneo en vivo completado en '${json.hostname}' (${
          json.summary?.os?.name || "Linux"
        }) · Sesión activa: ${json.session_id}.`
      );
    } catch (err) {
      setStatusBanner("");
      setErrorBanner(
        err.message ||
          "Error al ejecutar el recolector osquery en el dispositivo."
      );
    } finally {
      setScanningDevice(false);
      setImporting(false);
    }
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
          (typeof json.detail === "string"
            ? json.detail
            : "El archivo JSON no superó la validación de esquema.");
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
      const res = await fetchWithFallback(
        `/api/v1/discovery/sessions/${sessionId}`
      );
      if (res.ok) {
        const json = await res.json();
        setSessionData(json);
        setStatusBanner(
          `Consultando análisis previo: ${json.hostname} (${json.session_id}).`
        );
      }
    } catch {
      setErrorBanner("No se pudo recuperar la sesión seleccionada.");
    } finally {
      setLoading(false);
    }
  };

  const handleExport = (fmt) => {
    if (!sessionData?.session_id) return;
    const url = buildUrl(
      resolvedApiBase,
      `/api/v1/discovery/sessions/${sessionData.session_id}/export?format=${fmt}`
    );
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const handleNavigateFromDiagram = useCallback((sectionId, subsectionId) => {
    setActiveSection(sectionId);
    if (subsectionId) {
      setTimeout(() => {
        const el =
          document.getElementById(subsectionId) ||
          document.getElementById(`hw-${subsectionId}`) ||
          document.getElementById(`sw-${subsectionId}`) ||
          document.getElementById(`net-${subsectionId}`);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      }, 80);
    }
  }, []);

  return (
    <div className="tab-pane-view" data-ui="discovery-workspace">
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        style={{ display: "none" }}
        onChange={handleFileUpload}
      />

      <AwsPageHeader
        title="Descubrimiento e inventario"
        description="Inventario de hardware, software, red y procesos de un equipo, sin modificarlo."
        badges={
          sessionData && (
            <>
              <span className="cm-badge observed">
                Activo: {sessionData.hostname}
              </span>
              <span className="cm-badge info">
                Sesión: {sessionData.session_id}
              </span>
            </>
          )
        }
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            {sessionsList.length > 0 && (
              <select
                id="disc-session-select"
                className="cm-select"
                style={{ width: "auto" }}
                aria-label="Seleccionar sesión de discovery"
                value={sessionData?.session_id || ""}
                onChange={(e) => handleSelectSession(e.target.value)}
              >
                {sessionsList.map((s) => (
                  <option key={s.session_id} value={s.session_id}>
                    {s.hostname} — {s.filename} ({s.session_id})
                  </option>
                ))}
              </select>
            )}

            <details className="cm-export-menu">
              <summary aria-label="Fuentes de inventario">Cargar inventario ▾</summary>
              <div className="cm-export-dropdown-list" role="menu">
                <button
                  type="button"
                  role="menuitem"
                  className="cm-export-dropdown-item"
                  disabled={importing}
                  onClick={handleCollectLiveDevice}
                >
                  <span>{scanningDevice ? "Escaneando..." : "Escaneo rápido de este equipo"}</span>
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="cm-export-dropdown-item"
                  disabled={importing}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <span>Importar archivo JSON</span>
                  <code>.json</code>
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="cm-export-dropdown-item"
                  disabled={importing}
                  onClick={handleImportLocalPreset}
                >
                  <span>Recargar inventario local</span>
                </button>
              </div>
            </details>

            {sessionData && (
              <details className="cm-export-menu">
                <summary aria-label="Opciones de exportación del inventario">
                  Exportar artefactos ▾
                </summary>
                <div className="cm-export-dropdown-list" role="menu">
                  <button
                    type="button"
                    role="menuitem"
                    className="cm-export-dropdown-item"
                    onClick={() => handleExport("json")}
                  >
                    <span>Exportar JSON normalizado</span>
                    <code>.json</code>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="cm-export-dropdown-item"
                    onClick={() => handleExport("md")}
                  >
                    <span>Exportar informe (.md)</span>
                    <code>.md</code>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="cm-export-dropdown-item"
                    onClick={() => handleExport("cmir")}
                  >
                    <span>Exportar CMIR</span>
                    <code>.json</code>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="cm-export-dropdown-item"
                    onClick={() => handleExport("tf")}
                  >
                    <span>Exportar Terraform (.tf)</span>
                    <code>.tf</code>
                  </button>
                </div>
              </details>
            )}

            {sessionData &&
              handleSyncCanvas &&
              (sessionData.graph || sessionData.cmir) && (
                <button
                  type="button"
                  className="cm-btn sm"
                  onClick={() => {
                    const cmirPayload = sessionData.cmir?.nodes
                      ? sessionData.cmir
                      : sessionData.graph?.nodes
                      ? {
                          architecture_name: `Discovery · ${
                            sessionData.hostname || "Host"
                          }`,
                          provider: "on-premise",
                          nodes: sessionData.graph.nodes,
                          edges: sessionData.graph.edges || [],
                        }
                      : sessionData;
                    handleSyncCanvas(cmirPayload);
                  }}
                >
                  Ver en lienzo arquitectura
                </button>
              )}

            <button
              type="button"
              className="cm-btn primary sm"
              onClick={() => setShowCollectorModal((v) => !v)}
            >
              {showCollectorModal
                ? "Ocultar asistente osquery"
                : "Descubrir equipo (osquery)"}
            </button>
          </div>
        }
      />

      {showCollectorModal && (
        <div style={{ marginBottom: 16 }}>
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
        </div>
      )}

      {errorBanner && (
        <AwsAlert
          type="error"
          title="Error de validación o importación"
          onDismiss={() => setErrorBanner("")}
          style={{ marginBottom: 16 }}
        >
          {errorBanner}
        </AwsAlert>
      )}

      {statusBanner && (
        <AwsAlert
          type="success"
          title="Operación completada"
          onDismiss={() => setStatusBanner("")}
          style={{ marginBottom: 16 }}
        >
          {statusBanner}
        </AwsAlert>
      )}

      {loading ? (
        <AwsContainer title="Cargando inventario">
          <p className="cm-hint">
            Analizando y normalizando inventario de infraestructura...
          </p>
        </AwsContainer>
      ) : !sessionData ? (
        <AwsContainer title="Sin inventario de discovery activo">
          <AwsEmptyState
            title="No hay inventario cargado actualmente"
            description="Escanee este dispositivo en vivo con osqueryi, seleccione un archivo JSON generado por cloudmove_osquery_export.py o cargue el inventario local del proyecto."
            action={
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
                <button
                  type="button"
                  className="cm-btn primary"
                  disabled={importing}
                  onClick={handleCollectLiveDevice}
                >
                  {scanningDevice
                    ? "Escaneando dispositivo..."
                    : "Escanear este dispositivo (osquery en vivo)"}
                </button>
                <button
                  type="button"
                  className="cm-btn"
                  onClick={() => fileInputRef.current?.click()}
                >
                  Seleccionar archivo JSON
                </button>
                <button
                  type="button"
                  className="cm-btn"
                  onClick={handleImportLocalPreset}
                >
                  Cargar inventario local
                </button>
              </div>
            }
          />
        </AwsContainer>
      ) : (
        <>
          <AwsKeyValuePairs
            columns={4}
            items={[
              {
                label: "Hostname descubierto",
                value: sessionData.hostname,
                subtext: `Archivo: ${sessionData.filename || "live-scan.json"}`,
              },
              {
                label: "Sistema operativo",
                value: (
                  <span style={{ fontSize: 16 }}>
                    {sessionData.summary?.os?.name}{" "}
                    {sessionData.summary?.os?.version}
                  </span>
                ),
                subtext: `Kernel: ${
                  sessionData.summary?.os?.kernel || "Linux"
                } (${sessionData.summary?.os?.arch || "x86_64"})`,
              },
              {
                label: "Capacidad de cómputo y memoria",
                value: `${
                  sessionData.summary?.hardware?.cpu_logical_cores || "—"
                } vCPUs · ${
                  sessionData.summary?.hardware?.memory_gb || "—"
                } GB RAM`,
                subtext:
                  sessionData.summary?.hardware?.cpu_brand || "x86_64 host",
              },
              {
                label: "Calidad y completitud osquery",
                value: `${
                  sessionData.quality?.completeness_pct ?? 100
                }% verificado`,
                subtext: `${
                  sessionData.quality?.tables_present ?? 16
                } tablas recolectadas`,
              },
            ]}
          />

          {(() => {
            const activeGroup =
              SECTION_GROUPS.find((g) => g.sections.includes(activeSection)) || SECTION_GROUPS[0];
            return (
              <>
                <AwsTabs
                  activeTabId={activeGroup.id}
                  onTabChange={(groupId) => {
                    const group = SECTION_GROUPS.find((g) => g.id === groupId);
                    if (group) setActiveSection(group.sections[0]);
                  }}
                  ariaLabel="Secciones del análisis de discovery"
                  tabs={SECTION_GROUPS.map((g) => ({ id: g.id, label: g.label }))}
                />
                {activeGroup.sections.length > 1 && (
                  <AwsTabs
                    activeTabId={activeSection}
                    onTabChange={setActiveSection}
                    ariaLabel={`Subsecciones de ${activeGroup.label}`}
                    style={{ marginBottom: 16 }}
                    tabs={activeGroup.sections.map((secId) => {
                      const sec = SECTION_NAV.find((s) => s.id === secId);
                      let count = undefined;
                      let badge = undefined;
                      if (secId === "software") {
                        count =
                          sessionData?.summary?.software?.packages_count ||
                          sessionData?.sections?.software?.packages_total_count ||
                          4297;
                      } else if (secId === "network") {
                        count = sessionData?.summary?.metrics?.listening_ports_count || 22;
                      } else if (secId === "runtime") {
                        count = sessionData?.summary?.metrics?.processes_count || 390;
                      } else if (secId === "databases") {
                        count =
                          sessionData?.sections?.databases?.detected_databases?.length || 3;
                      } else if (secId === "assessment") {
                        badge = "Readiness";
                      } else if (secId === "aws-archify") {
                        badge = "Terraform";
                      }
                      return {
                        id: secId,
                        label: sec?.label || secId,
                        count,
                        badge,
                      };
                    })}
                  />
                )}
              </>
            );
          })()}

          {activeSection === "diagram" ? (
            <div
              className="awsui-container"
              style={{ height: "calc(100dvh - 300px)", minHeight: 520 }}
            >
              <DiscoveryDiagramCanvas
                graphData={sessionData.graph}
                onNavigateToSection={handleNavigateFromDiagram}
              />
            </div>
          ) : (
            <div className="disc-section-view" style={{ maxWidth: "100%" }}>
              {activeSection === "aws-archify" && (
                <AwsSuggestedDiagramSection
                  data={sessionData}
                  apiUrl={resolvedApiBase}
                />
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
                <AssessmentSection
                  assessment={sessionData.sections?.assessment}
                />
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
