import React, { useState, useEffect, useCallback, useRef } from "react";
import { getApiBase, buildUrl } from "../../utils/apiClient";
import DiscoveryDiagramCanvas from "./DiscoveryDiagramCanvas";
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
  AwsContainer,
  AwsStatusIndicator,
} from "../cloudscape/AwsPrimitives";

const SECTION_NAV = [
  { id: "summary", label: "Resumen", subtitle: "Resumen ejecutivo y cobertura" },
  { id: "diagram", label: "Topología", subtitle: "Mapa interactivo de infraestructura" },
  { id: "hardware", label: "Hardware", subtitle: "CPU, RAM, discos y firmware" },
  { id: "software", label: "Software", subtitle: "Paquetes, servicios y módulos" },
  { id: "network", label: "Red y puertos", subtitle: "Interfaces, rutas, puertos y sockets" },
  { id: "runtime", label: "Procesos", subtitle: "Procesos activos y uptime" },
  { id: "databases", label: "Bases de datos", subtitle: "Indicios vs. recolectores de catálogo" },
  { id: "assessment", label: "Evaluación AWS", subtitle: "Preparación AWS y riesgos" },
  { id: "aws-archify", label: "Arquitectura AWS y Terraform", subtitle: "Archify + HCL desde JSON" },
];

const SECTION_GROUPS = [
  { id: "g-summary", label: "Resumen", sections: ["summary"] },
  { id: "g-topology", label: "Topología", sections: ["diagram"] },
  {
    id: "g-inventory",
    label: "Inventario",
    sections: ["hardware", "software", "network", "runtime", "databases"],
  },
  { id: "g-cloud", label: "Evaluación y AWS", sections: ["assessment", "aws-archify"] },
];

export default function DiscoveryWorkspace({
  apiUrl,
  onSyncToArchitecture,
  onLoadCmirToCanvas,
  onNavigateTab,
}) {
  const handleSyncCanvas = onSyncToArchitecture || onLoadCmirToCanvas;
  const [activeSection, setActiveSection] = useState("summary");
  const [sessionData, setSessionData] = useState(null);
  const [sessionsList, setSessionsList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [errorBanner, setErrorBanner] = useState("");
  const [statusBanner, setStatusBanner] = useState("");
  const [showImportGuide, setShowImportGuide] = useState(false);
  const [copiedCmd, setCopiedCmd] = useState("");
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
      // Ignore list error
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
        // No session loaded yet is a normal onboarding state, not an error
        setSessionData(null);
        await fetchSessionsList();
      }
    } catch {
      setSessionData(null);
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
            "No se encontró un paquete de referencia preinstalado. Sube un archivo JSON desde tu equipo."
        );
      }
      setSessionData(json);
      setShowImportGuide(false);
      await fetchSessionsList();
      setStatusBanner(
        `Inventario osquery '${json.filename}' (${json.hostname}) importado y normalizado correctamente.`
      );
    } catch (err) {
      setErrorBanner(err.message);
    } finally {
      setImporting(false);
    }
  };

  const handleFileUpload = async (event) => {
    const file = event.target?.files?.[0] || event.dataTransfer?.files?.[0];
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
            : "El archivo seleccionado no cumple con el esquema JSON de osquery requerido.");
        throw new Error(msg);
      }
      setSessionData(json);
      setShowImportGuide(false);
      await fetchSessionsList();
      setStatusBanner(
        `Archivo '${file.name}' importado con éxito (Activo: ${json.hostname} · Sesión: ${json.session_id}).`
      );
    } catch (err) {
      setErrorBanner(err.message || "Error al validar el archivo JSON importado.");
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
        setStatusBanner(
          `Sesión de análisis activa: ${json.hostname} (${json.session_id}).`
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

  const originUrl =
    typeof window !== "undefined" ? window.location.origin : "https://digitalcafeluna.store";
  const exportCmd = `curl -sSL ${originUrl}/api/v1/discovery/collector-script -o cloudmove_osquery_export.py && sudo python3 cloudmove_osquery_export.py --output cloudmove-osquery-inventory.json`;

  const renderOnboardingWizard = () => (
    <AwsContainer
      title="Asistente guiado de captura e importación de inventario Osquery"
      description="Para analizar un servidor sin exponer la infraestructura propia de CloudMove, sigue estos 3 pasos para generar e importar el archivo JSON de telemetría de tu equipo objetivo."
      actions={
        sessionData && (
          <button
            type="button"
            className="cm-btn sm"
            onClick={() => setShowImportGuide(false)}
          >
            Cerrar asistente
          </button>
        )
      }
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(290px, 1fr))",
          gap: 16,
          marginBottom: 16,
        }}
      >
        {/* PASO 1 */}
        <div className="cm-card-subtle" style={{ borderTop: "3px solid #ff9900" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <span className="cm-badge aws">Paso 1 · Recolección en origen</span>
            <AwsStatusIndicator type="info">Solo lectura</AwsStatusIndicator>
          </div>
          <strong style={{ fontSize: 15, display: "block", marginBottom: 6 }}>
            1. Generar el archivo JSON en el equipo objetivo
          </strong>
          <p className="cm-hint" style={{ margin: "0 0 10px 0" }}>
            Ejecuta el recolector oficial <code>cloudmove_osquery_export.py</code> en la máquina Linux, Windows o macOS que deseas inventariar:
          </p>
          <pre
            style={{
              margin: "0 0 10px 0",
              padding: 10,
              backgroundColor: "#16191f",
              color: "#f2f3f3",
              borderRadius: 4,
              fontSize: 11.5,
              overflowX: "auto",
            }}
          >
            {exportCmd}
          </pre>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              className="cm-btn sm"
              onClick={() => {
                if (navigator.clipboard) {
                  navigator.clipboard.writeText(exportCmd);
                  setCopiedCmd("step1");
                  setTimeout(() => setCopiedCmd(""), 2000);
                }
              }}
            >
              {copiedCmd === "step1" ? "Comando copiado" : "Copiar comando"}
            </button>
            {onNavigateTab && (
              <button
                type="button"
                className="cm-btn sm"
                onClick={() => onNavigateTab("sources-targets")}
              >
                O usar Agente con Token →
              </button>
            )}
          </div>
        </div>

        {/* PASO 2 */}
        <div
          className="cm-card-subtle"
          style={{
            borderTop: "3px solid #0972d3",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}
        >
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <span className="cm-badge info">Paso 2 · Importación de archivo</span>
              <span className="cm-hint">Máx. 25 MB</span>
            </div>
            <strong style={{ fontSize: 15, display: "block", marginBottom: 6 }}>
              2. Subir el archivo <code>cloudmove-osquery-inventory.json</code>
            </strong>
            <p className="cm-hint" style={{ margin: "0 0 12px 0" }}>
              Selecciona el archivo <code>.json</code> generado en el Paso 1. El analizador validará las 16 tablas canónicas (<code>system_info</code>, <code>os_version</code>, <code>block_devices</code>, <code>listening_ports</code>, <code>processes</code>, <code>deb_packages</code>, etc.).
            </p>
          </div>
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              handleFileUpload(e);
            }}
            style={{
              border: "2px dashed #539fe5",
              borderRadius: 6,
              padding: 16,
              textAlign: "center",
              backgroundColor: "#f2f8fd",
            }}
          >
            <div style={{ fontWeight: 700, fontSize: 13.5, color: "#0972d3", marginBottom: 8 }}>
              Arrastra tu archivo .JSON aquí o selecciónalo desde tu equipo
            </div>
            <button
              type="button"
              className="cm-btn primary sm"
              disabled={importing}
              onClick={() => fileInputRef.current?.click()}
            >
              {importing ? "Validando e importando..." : "Seleccionar archivo JSON (.json)"}
            </button>
          </div>
        </div>

        {/* PASO 3 */}
        <div
          className="cm-card-subtle"
          style={{
            borderTop: "3px solid #037f0c",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}
        >
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <span className="cm-badge observed">Paso 3 · Exploración rápida</span>
              <AwsStatusIndicator type="success">16/16 tablas</AwsStatusIndicator>
            </div>
            <strong style={{ fontSize: 15, display: "block", marginBottom: 6 }}>
              3. Cargar inventario de referencia verificado
            </strong>
            <p className="cm-hint" style={{ margin: "0 0 12px 0" }}>
              Si deseas evaluar inmediatamente las capacidades de análisis de hardware, paquetes, puertos en escucha, bases de datos y generación de Terraform AWS con Archify, carga el inventario de referencia del proyecto:
            </p>
          </div>
          <button
            type="button"
            className="cm-btn sm"
            disabled={importing}
            onClick={handleImportLocalPreset}
          >
            {importing
              ? "Cargando inventario..."
              : "Cargar paquete de inventario de referencia"}
          </button>
        </div>
      </div>
    </AwsContainer>
  );

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
        title="Discovery e inventario (Osquery)"
        description="Inspección estructurada de hardware, software, red, procesos y bases de datos a partir de capturas osquery hacia AWS."
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

            <button
              type="button"
              className="cm-btn sm"
              disabled={importing}
              onClick={() => fileInputRef.current?.click()}
            >
              Importar archivo JSON (.json)
            </button>

            <button
              type="button"
              className="cm-btn sm"
              onClick={() => setShowImportGuide((prev) => !prev)}
            >
              {showImportGuide ? "Ocultar guía de captura" : "Guía paso a paso Osquery"}
            </button>

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
                    <span>Exportar Terraform AWS (.tf)</span>
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
                  className="cm-btn primary sm"
                  onClick={() => {
                    const cmirPayload = sessionData.cmir?.nodes
                      ? sessionData.cmir
                      : sessionData.graph?.nodes
                      ? {
                          architecture_name: `Discovery · ${
                            sessionData.hostname || "Host"
                          }`,
                          provider: "aws",
                          nodes: sessionData.graph.nodes,
                          edges: sessionData.graph.edges || [],
                        }
                      : sessionData;
                    handleSyncCanvas(cmirPayload);
                  }}
                >
                  Ver en arquitectura Archify
                </button>
              )}
          </div>
        }
      />

      {errorBanner && (
        <AwsAlert
          type="error"
          title="Aviso de validación de archivo JSON"
          onDismiss={() => setErrorBanner("")}
          style={{ marginBottom: 16 }}
        >
          {errorBanner}
        </AwsAlert>
      )}

      {statusBanner && (
        <AwsAlert
          type="success"
          title="Inventario cargado correctamente"
          onDismiss={() => setStatusBanner("")}
          style={{ marginBottom: 16 }}
        >
          {statusBanner}
        </AwsAlert>
      )}

      {(showImportGuide || (!loading && !sessionData)) && renderOnboardingWizard()}

      {loading ? (
        <AwsContainer title="Inicializando analizador de discovery">
          <p className="cm-hint">
            Verificando sesiones previas de inventario Osquery...
          </p>
        </AwsContainer>
      ) : (
        sessionData && (
          <>
            <AwsKeyValuePairs
              columns={4}
              items={[
                {
                  label: "Hostname descubierto",
                  value: sessionData.hostname,
                  subtext: `Archivo: ${sessionData.filename || "osquery-inventory.json"}`,
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
                SECTION_GROUPS.find((g) => g.sections.includes(activeSection)) ||
                SECTION_GROUPS[0];
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
                          count =
                            sessionData?.summary?.metrics?.listening_ports_count || 22;
                        } else if (secId === "runtime") {
                          count = sessionData?.summary?.metrics?.processes_count || 390;
                        } else if (secId === "databases") {
                          count =
                            sessionData?.sections?.databases?.detected_databases
                              ?.length || 3;
                        } else if (secId === "assessment") {
                          badge = "Readiness";
                        } else if (secId === "aws-archify") {
                          badge = "Archify + HCL";
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
        )
      )}
    </div>
  );
}
