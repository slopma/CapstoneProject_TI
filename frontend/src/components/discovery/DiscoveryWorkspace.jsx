import React, { useState, useEffect, useCallback, useRef } from "react";
import { getApiBase, buildUrl, apiFetch } from "../../utils/apiClient";
import {
  getSessionAgentToken,
  saveSessionAgentToken,
  copyTextToClipboard,
} from "../../utils/credentialVault";
import UserFileSelectionPanel, {
  loadSavedSelectedUserPaths,
  saveSelectedUserPathsToSession,
} from "../migration/UserFileSelectionPanel";
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
  AwsEmptyState,
} from "../cloudscape/AwsPrimitives";

export default function DiscoveryWorkspace({
  apiUrl,
  onSyncToArchitecture,
  onLoadCmirToCanvas,
  onNavigateTab,
  onQuickStartUseCase,
}) {
  const handleSyncCanvas = onSyncToArchitecture || onLoadCmirToCanvas;

  // Live Agent Automatic Discovery State
  const [liveAgentData, setLiveAgentData] = useState(null);
  const [loadingLiveAgent, setLoadingLiveAgent] = useState(true);
  const [refreshingAgent, setRefreshingAgent] = useState(false);
  const [liveTab, setLiveTab] = useState("files"); // "files" | "ports" | "processes" | "disks" | "osquery-json"
  const [selectedUserPaths, setSelectedUserPaths] = useState(
    () => loadSavedSelectedUserPaths() || []
  );
  const [maxAwsStorageGib, setMaxAwsStorageGib] = useState(30.0);
  const [processFilter, setProcessFilter] = useState("");
  const [portFilter, setPortFilter] = useState("");
  const [agentToken, setAgentToken] = useState(() => getSessionAgentToken());
  const [generatingToken, setGeneratingToken] = useState(false);
  const [copiedCmd, setCopiedCmd] = useState("");

  // Optional Manual Osquery JSON State
  const [activeSection, setActiveSection] = useState("summary");
  const [sessionData, setSessionData] = useState(null);
  const [sessionsList, setSessionsList] = useState([]);
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

  const loadLiveAgentDiscovery = useCallback(
    async (silent = false) => {
      if (!silent) setLoadingLiveAgent(true);
      try {
        const res = await fetchWithFallback(`/api/v1/discovery/agent-live`);
        if (res.ok) {
          const data = await res.json();
          setLiveAgentData(data);
        }
      } catch {
        // Ignore transient network errors
      } finally {
        if (!silent) setLoadingLiveAgent(false);
      }
    },
    [fetchWithFallback]
  );

  const loadManualSessions = useCallback(async () => {
    try {
      const [latestRes, listRes] = await Promise.all([
        fetchWithFallback(`/api/v1/discovery/latest`).catch(() => null),
        fetchWithFallback(`/api/v1/discovery/sessions`).catch(() => null),
      ]);
      if (latestRes && latestRes.ok) {
        setSessionData(await latestRes.json());
      }
      if (listRes && listRes.ok) {
        const j = await listRes.json();
        setSessionsList(j.sessions || []);
      }
    } catch {
      // Ignore
    }
  }, [fetchWithFallback]);

  useEffect(() => {
    loadLiveAgentDiscovery(false);
    loadManualSessions();
    const interval = setInterval(() => {
      loadLiveAgentDiscovery(true);
    }, 8000);
    return () => clearInterval(interval);
  }, [loadLiveAgentDiscovery, loadManualSessions]);

  const handleTriggerAgentScan = async () => {
    const activeId = liveAgentData?.active_agent?.agent_id;
    setRefreshingAgent(true);
    setErrorBanner("");
    try {
      if (activeId) {
        await apiFetch(`/api/v1/agents/${activeId}/dispatch-task`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "collect_inventory", parameters: {} }),
        });
      }
      await loadLiveAgentDiscovery(false);
      setStatusBanner(
        `Solicitud de escaneo en vivo enviada al agente '${
          liveAgentData?.active_agent?.hostname || activeId
        }'. Los archivos, carpetas, puertos y procesos se actualizarán automáticamente.`
      );
    } catch (err) {
      setErrorBanner(err.message || "Error al solicitar escaneo al agente.");
    } finally {
      setRefreshingAgent(false);
    }
  };

  const handleGenerateTokenHere = async () => {
    setGeneratingToken(true);
    setErrorBanner("");
    try {
      const res = await apiFetch("/api/v1/agents/enrollment-tokens", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ttl_seconds: 86400,
          max_uses: 10,
          org_id: "default",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "No se pudo generar el token.");
      const saved = saveSessionAgentToken(data) || data;
      setAgentToken(saved);
      setStatusBanner(
        "Token de agente generado. Ejecuta el comando de instalación en tu dispositivo y esta vista se poblará automáticamente con tus carpetas, archivos, puertos y procesos."
      );
    } catch (err) {
      setErrorBanner(err.message);
    } finally {
      setGeneratingToken(false);
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
        throw new Error(
          json.detail?.message ||
            (typeof json.detail === "string"
              ? json.detail
              : "El archivo seleccionado no cumple con el esquema JSON requerido.")
        );
      }
      setSessionData(json);
      setLiveTab("osquery-json");
      await loadManualSessions();
      setStatusBanner(
        `Archivo '${file.name}' importado correctamente (${json.hostname}).`
      );
    } catch (err) {
      setErrorBanner(err.message);
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const activeAgent = liveAgentData?.active_agent;
  const inv = liveAgentData?.inventory || {};
  const fsTree = inv.filesystem_tree || [];
  const ports = inv.listening_ports || [];
  const interfaces = inv.network_interfaces || [];
  const processes = inv.processes || [];
  const services = inv.services || [];
  const disks = inv.disks || [];
  const databases = inv.databases || [];
  const runtimes = inv.runtimes || [];
  const cpu = inv.cpu || {};
  const memory = inv.memory || {};
  const hm = activeAgent?.health_metrics || {};

  const filteredProcesses = processes.filter((p) => {
    if (!processFilter.trim()) return true;
    const q = processFilter.toLowerCase();
    return (
      String(p.pid).includes(q) ||
      (p.name || "").toLowerCase().includes(q) ||
      (p.user || "").toLowerCase().includes(q) ||
      (p.cmdline || "").toLowerCase().includes(q)
    );
  });

  const filteredPorts = ports.filter((pt) => {
    if (!portFilter.trim()) return true;
    const q = portFilter.toLowerCase();
    return (
      String(pt.port || "").includes(q) ||
      (pt.protocol || "").toLowerCase().includes(q) ||
      (pt.local_address || "").toLowerCase().includes(q) ||
      (pt.process_raw || "").toLowerCase().includes(q)
    );
  });

  const rawTokenStr = agentToken?.token || agentToken?.enrollment_token || "";
  const installCmdLinux =
    agentToken?.install_command_linux ||
    (rawTokenStr
      ? `curl -sSL ${window.location.origin}/api/v1/agents/install.sh | sudo bash -s -- --token ${rawTokenStr} --server ${window.location.origin}`
      : "");

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
        title="Discovery Automático del Dispositivo (Agente CloudMove)"
        description="Inspección automática en tiempo real de las carpetas, archivos del usuario, puertos en escucha, procesos en ejecución, servicios y discos del dispositivo donde se instaló el agente."
        badges={
          <>
            {activeAgent ? (
              <>
                <span className="cm-badge observed">
                  Agente Conectado: {activeAgent.hostname} ({activeAgent.ip_address})
                </span>
                <span className="cm-badge aws">
                  Estado: {activeAgent.status}
                </span>
              </>
            ) : (
              <span className="cm-badge warning">Esperando conexión de agente</span>
            )}
            <span className="cm-badge info">Sincronización automática cada 8s</span>
          </>
        }
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              className="cm-btn sm"
              onClick={handleTriggerAgentScan}
              disabled={refreshingAgent || !activeAgent}
            >
              {refreshingAgent
                ? "Actualizando telemetría..."
                : "Actualizar telemetría del agente ahora"}
            </button>
            <button
              type="button"
              className="cm-btn primary sm"
              disabled={!activeAgent}
              onClick={() => {
                saveSelectedUserPathsToSession(selectedUserPaths);
                if (onQuickStartUseCase) {
                  onQuickStartUseCase("vm_image");
                } else if (onNavigateTab) {
                  onNavigateTab("migration", "vm_image");
                }
              }}
            >
              Migrar este dispositivo y archivos en Caso 2 →
            </button>
          </div>
        }
      />

      {errorBanner && (
        <AwsAlert
          type="error"
          title="Aviso de Discovery"
          onDismiss={() => setErrorBanner("")}
          style={{ marginBottom: 16 }}
        >
          {errorBanner}
        </AwsAlert>
      )}

      {statusBanner && (
        <AwsAlert
          type="success"
          title="Discovery sincronizado"
          onDismiss={() => setStatusBanner("")}
          style={{ marginBottom: 16 }}
        >
          {statusBanner}
        </AwsAlert>
      )}

      {/* Si no hay agente conectado todavía, mostrar generador de comando 1-click */}
      {!loadingLiveAgent && !activeAgent && (
        <AwsContainer
          title="Conecta tu dispositivo instalando el Agente CloudMove"
          description="En cuanto ejecutes el comando de instalación en tu máquina Linux o Windows, esta sección descubrirá y mostrará automáticamente tus carpetas, archivos, puertos abiertos, servicios y procesos corriendo."
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <button
                type="button"
                className="cm-btn primary sm"
                onClick={handleGenerateTokenHere}
                disabled={generatingToken}
              >
                {generatingToken
                  ? "Generando token..."
                  : rawTokenStr
                  ? "Regenerar token de instalación"
                  : "1. Generar comando de instalación del agente"}
              </button>
              {installCmdLinux && (
                <button
                  type="button"
                  className="cm-btn sm"
                  onClick={async () => {
                    await copyTextToClipboard(installCmdLinux);
                    setCopiedCmd("agent_cmd");
                    setTimeout(() => setCopiedCmd(""), 2000);
                  }}
                >
                  {copiedCmd === "agent_cmd" ? "Comando copiado" : "Copiar comando Linux"}
                </button>
              )}
            </div>
            {installCmdLinux && (
              <pre
                style={{
                  margin: 0,
                  padding: "10px 12px",
                  backgroundColor: "#0f172a",
                  color: "#f8fafc",
                  borderRadius: 4,
                  fontSize: 12,
                  overflowX: "auto",
                }}
              >
                {installCmdLinux}
              </pre>
            )}
          </div>
        </AwsContainer>
      )}

      {/* Resumen Ejecutivo del Dispositivo Conectado */}
      {activeAgent && (
        <>
          <AwsKeyValuePairs
            columns={4}
            items={[
              {
                label: "Dispositivo y Agente Activo",
                value: `${inv.hostname || activeAgent.hostname} (${
                  inv.ip_address || activeAgent.ip_address
                })`,
                subtext: `ID: ${activeAgent.agent_id} · Último heartbeat: ${(
                  activeAgent.last_heartbeat_at || ""
                )
                  .replace("T", " ")
                  .slice(0, 19)}`,
              },
              {
                label: "Sistema Operativo y Hardware",
                value: `${cpu.cores_logical || 8} vCPUs · ${Math.round(
                  (memory.total_mb || hm.ram_total_mb || 16000) / 1024
                )} GiB RAM`,
                subtext: `${inv.os_name || activeAgent.os_name} · Uso CPU: ${
                  hm.cpu_percent ?? cpu.usage_percent ?? 0
                }% · Uso RAM: ${hm.ram_percent ?? memory.usage_percent ?? 0}%`,
              },
              {
                label: "Carpetas y Archivos Descubiertos",
                value: `${
                  inv.filesystem_summary?.total_size_gib ?? 0
                } GiB inventariados`,
                subtext: `${fsTree.length} directorio(s) raíz · ${selectedUserPaths.length} ruta(s) seleccionada(s) para migrar`,
              },
              {
                label: "Puertos, Procesos y Servicios",
                value: `${ports.length} puertos · ${processes.length} procesos`,
                subtext: `${services.filter((s) => s.is_running).length} servicios systemd activos · ${
                  databases.length
                } BD(s)`,
              },
            ]}
          />

          <AwsTabs
            activeTabId={liveTab}
            onTabChange={setLiveTab}
            ariaLabel="Secciones del dispositivo descubierto por el agente"
            tabs={[
              {
                id: "files",
                label: "Carpetas y Archivos del Dispositivo",
                count: fsTree.length,
              },
              {
                id: "ports",
                label: "Puertos Activos y Red",
                count: ports.length,
              },
              {
                id: "processes",
                label: "Procesos y Servicios Corriendo",
                count: processes.length + services.length,
              },
              {
                id: "disks",
                label: "Hardware, Discos y Particiones",
                count: disks.length,
              },
              {
                id: "osquery-json",
                label: "Importador JSON Osquery (Opcional)",
              },
            ]}
          />

          {/* PESTAÑA 1: CARPETAS Y ARCHIVOS DEL DISPOSITIVO */}
          {liveTab === "files" && (
            <div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: 10,
                  backgroundColor: "#ffffff",
                  border: "1px solid #d5dbdb",
                  borderRadius: 6,
                  padding: "10px 14px",
                  marginBottom: 12,
                }}
              >
                <div style={{ fontSize: 13.5, color: "#000716" }}>
                  <strong>Perfil de límite de almacenamiento AWS EBS para cálculo de selección:</strong>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {[
                    { gib: 30.0, label: "30 GiB gp3 (Free Tier AWS)" },
                    { gib: 100.0, label: "100 GiB gp3 (Máx. por volumen AWS Academy)" },
                    { gib: 150.0, label: "150 GiB gp3 (Cuota total AWS Academy)" },
                  ].map((opt) => (
                    <button
                      key={opt.gib}
                      type="button"
                      className={`cm-btn sm ${
                        maxAwsStorageGib === opt.gib ? "primary" : "secondary"
                      }`}
                      onClick={() => setMaxAwsStorageGib(opt.gib)}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              <UserFileSelectionPanel
                filesystemTree={fsTree}
                selectedPaths={selectedUserPaths}
                onChangeSelectedPaths={setSelectedUserPaths}
                maxAwsStorageGib={maxAwsStorageGib}
                baseOsOverheadGib={2.5}
                awsAcademyAccountLimitGib={150.0}
                onUpgradeStorageProfile={() => setMaxAwsStorageGib(100.0)}
                onRefreshAgentInventory={handleTriggerAgentScan}
                refreshing={refreshingAgent}
                hostname={inv.hostname || activeAgent.hostname}
                onProceedToMigration={(paths) => {
                  saveSelectedUserPathsToSession(paths);
                  if (onQuickStartUseCase) {
                    onQuickStartUseCase("vm_image");
                  } else if (onNavigateTab) {
                    onNavigateTab("migration", "vm_image");
                  }
                }}
              />
            </div>
          )}

          {/* PESTAÑA 2: PUERTOS ACTIVOS Y RED */}
          {liveTab === "ports" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <AwsContainer
                title="Puertos TCP/UDP en Escucha Detectados en el Dispositivo"
                counter={filteredPorts.length}
                description="Sockets abiertos relevados directamente en el dispositivo mediante ss -tulpn y /proc/net."
                noPadding={true}
                actions={
                  <input
                    type="search"
                    className="cm-input"
                    placeholder="Filtrar por puerto, protocolo o proceso..."
                    value={portFilter}
                    onChange={(e) => setPortFilter(e.target.value)}
                    style={{ width: 260, height: 32, fontSize: 13 }}
                  />
                }
              >
                {filteredPorts.length === 0 ? (
                  <AwsEmptyState
                    title="Sin puertos que coincidan"
                    description="Haz clic en 'Actualizar telemetría del agente ahora' para refrescar los sockets activos."
                  />
                ) : (
                  <div className="cm-table-wrap" style={{ border: "none" }}>
                    <table className="cm-table">
                      <thead>
                        <tr>
                          <th>Puerto</th>
                          <th>Protocolo</th>
                          <th>Estado</th>
                          <th>Dirección Local</th>
                          <th>Proceso Asociado</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredPorts.map((pt, idx) => (
                          <tr key={`${pt.protocol}-${pt.local_address}-${idx}`}>
                            <td>
                              <span className="cm-badge aws">
                                Puerto {pt.port ?? "—"}
                              </span>
                            </td>
                            <td>
                              <code>{(pt.protocol || "tcp").toUpperCase()}</code>
                            </td>
                            <td>
                              <AwsStatusIndicator type="success">
                                {pt.state || "LISTEN"}
                              </AwsStatusIndicator>
                            </td>
                            <td>
                              <code>{pt.local_address}</code>
                            </td>
                            <td>
                              <code>{pt.process_raw || "kernel / systemd"}</code>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </AwsContainer>

              <AwsContainer
                title="Interfaces de Red del Dispositivo"
                counter={interfaces.length}
                noPadding={true}
              >
                <div className="cm-table-wrap" style={{ border: "none" }}>
                  <table className="cm-table">
                    <thead>
                      <tr>
                        <th>Interfaz</th>
                        <th>Dirección MAC</th>
                        <th>Estado</th>
                        <th>Direcciones IP Asignadas</th>
                      </tr>
                    </thead>
                    <tbody>
                      {interfaces.map((iface, idx) => (
                        <tr key={iface.interface || idx}>
                          <td>
                            <strong><code>{iface.interface}</code></strong>
                          </td>
                          <td>
                            <code>{iface.mac_address || "—"}</code>
                          </td>
                          <td>
                            <AwsStatusIndicator
                              type={
                                iface.operstate === "UP" || iface.is_up
                                  ? "success"
                                  : "info"
                              }
                            >
                              {iface.operstate || (iface.is_up ? "UP" : "DOWN")}
                            </AwsStatusIndicator>
                          </td>
                          <td>
                            {(iface.ip_addresses || []).length > 0 ? (
                              iface.ip_addresses.map((ip, i) => (
                                <span
                                  key={i}
                                  className="cm-badge info"
                                  style={{ marginRight: 6 }}
                                >
                                  {ip.local}/{ip.prefixlen}
                                </span>
                              ))
                            ) : (
                              <span className="cm-hint">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </AwsContainer>
            </div>
          )}

          {/* PESTAÑA 3: PROCESOS Y SERVICIOS CORRIENDO */}
          {liveTab === "processes" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <AwsContainer
                title="Procesos en Ejecución en el Dispositivo (Tiempo Real)"
                counter={filteredProcesses.length}
                description="Procesos activos ordenados por consumo de memoria y CPU."
                noPadding={true}
                actions={
                  <input
                    type="search"
                    className="cm-input"
                    placeholder="Buscar proceso por nombre, PID, usuario o comando..."
                    value={processFilter}
                    onChange={(e) => setProcessFilter(e.target.value)}
                    style={{ width: 280, height: 32, fontSize: 13 }}
                  />
                }
              >
                {filteredProcesses.length === 0 ? (
                  <AwsEmptyState
                    title="Sincronizando lista de procesos activos"
                    description="Haz clic en 'Actualizar telemetría del agente ahora' arriba para obtener los procesos en ejecución."
                  />
                ) : (
                  <div
                    className="cm-table-wrap"
                    style={{ border: "none", maxHeight: 420, overflowY: "auto" }}
                  >
                    <table className="cm-table">
                      <thead>
                        <tr>
                          <th>PID</th>
                          <th>Usuario</th>
                          <th>Proceso</th>
                          <th>CPU %</th>
                          <th>RAM %</th>
                          <th>Memoria RSS</th>
                          <th>Línea de Comando</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredProcesses.map((proc) => (
                          <tr key={proc.pid}>
                            <td>
                              <code>{proc.pid}</code>
                            </td>
                            <td>
                              <code>{proc.user}</code>
                            </td>
                            <td>
                              <strong>{proc.name}</strong>
                            </td>
                            <td>{proc.cpu_percent}%</td>
                            <td>{proc.mem_percent}%</td>
                            <td>
                              <code>{proc.rss_mb} MiB</code>
                            </td>
                            <td style={{ maxWidth: 420, wordBreak: "break-all" }}>
                              <code style={{ fontSize: 11.5 }}>{proc.cmdline}</code>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </AwsContainer>

              <AwsContainer
                title="Servicios Systemd, Runtimes y Bases de Datos Detectadas"
                counter={services.length}
                noPadding={true}
              >
                {(runtimes.length > 0 || databases.length > 0) && (
                  <div
                    style={{
                      padding: "12px 16px",
                      borderBottom: "1px solid #eaeded",
                      display: "flex",
                      gap: 10,
                      flexWrap: "wrap",
                    }}
                  >
                    {runtimes.map((rt, i) => (
                      <span key={i} className="cm-badge observed">
                        {rt.runtime}: {rt.version}
                      </span>
                    ))}
                    {databases.map((db, i) => (
                      <span key={i} className="cm-badge aws">
                        BD Detectada: {db.engine?.toUpperCase()} (Puerto {db.default_port})
                      </span>
                    ))}
                  </div>
                )}
                <div
                  className="cm-table-wrap"
                  style={{ border: "none", maxHeight: 360, overflowY: "auto" }}
                >
                  <table className="cm-table">
                    <thead>
                      <tr>
                        <th>Servicio Systemd</th>
                        <th>Estado</th>
                        <th>Subestado</th>
                        <th>Descripción</th>
                      </tr>
                    </thead>
                    <tbody>
                      {services.map((svc, idx) => (
                        <tr key={svc.name || idx}>
                          <td>
                            <strong><code>{svc.name}</code></strong>
                          </td>
                          <td>
                            <AwsStatusIndicator
                              type={svc.is_running ? "success" : "info"}
                            >
                              {svc.active_state}
                            </AwsStatusIndicator>
                          </td>
                          <td>
                            <code>{svc.sub_state}</code>
                          </td>
                          <td>{svc.description}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </AwsContainer>
            </div>
          )}

          {/* PESTAÑA 4: HARDWARE, DISCOS Y PARTICIONES */}
          {liveTab === "disks" && (
            <AwsContainer
              title="Discos Físicos, Particiones y Puntos de Montaje del Dispositivo"
              counter={disks.length}
              description={`Procesador: ${cpu.model || "x86_64"} (${
                cpu.cores_logical || 8
              } núcleos) · Memoria RAM Total: ${Math.round(
                (memory.total_mb || 16384) / 1024
              )} GiB (Disponible: ${Math.round(
                (memory.available_mb || 4096) / 1024
              )} GiB)`}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {disks.map((d, idx) => (
                  <div key={d.name || idx} className="cm-card-subtle">
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        flexWrap: "wrap",
                        gap: 8,
                        marginBottom: 8,
                      }}
                    >
                      <div>
                        <strong style={{ fontSize: 14.5 }}>
                          Disco <code>/dev/{d.name}</code>
                        </strong>{" "}
                        <span className="cm-badge info">
                          {d.size_gb} GiB · {(d.type || "disk").toUpperCase()}
                        </span>
                      </div>
                      {d.mountpoint && (
                        <span className="cm-badge observed">
                          Montado en {d.mountpoint}
                        </span>
                      )}
                    </div>
                    {Array.isArray(d.children) && d.children.length > 0 && (
                      <div className="cm-table-wrap">
                        <table className="cm-table">
                          <thead>
                            <tr>
                              <th>Partición</th>
                              <th>Punto de Montaje</th>
                              <th>Sistema de Archivos</th>
                              <th>UUID</th>
                              <th style={{ textAlign: "right" }}>Tamaño</th>
                            </tr>
                          </thead>
                          <tbody>
                            {d.children.map((ch, cIdx) => (
                              <tr key={ch.name || cIdx}>
                                <td>
                                  <strong><code>/dev/{ch.name}</code></strong>
                                </td>
                                <td>
                                  <code>{ch.mountpoint || "—"}</code>
                                </td>
                                <td>
                                  <code>{ch.fstype || "—"}</code>
                                </td>
                                <td>
                                  <code style={{ fontSize: 11.5 }}>{ch.uuid || "—"}</code>
                                </td>
                                <td style={{ textAlign: "right" }}>
                                  {ch.size
                                    ? `${(Number(ch.size) / 1024 ** 3).toFixed(2)} GiB`
                                    : "—"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </AwsContainer>
          )}
        </>
      )}

      {/* PESTAÑA 5: IMPORTADOR MANUAL OSQUERY JSON (OPCIONAL) */}
      {liveTab === "osquery-json" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <AwsContainer
            title="Importación Manual de Captura Osquery JSON (Opcional)"
            description="Además del descubrimiento automático mediante el agente CloudMove, puedes subir manualmente un archivo JSON exportado por osquery."
            actions={
              <button
                type="button"
                className="cm-btn primary sm"
                disabled={importing}
                onClick={() => fileInputRef.current?.click()}
              >
                {importing ? "Importando..." : "Seleccionar archivo JSON (.json)"}
              </button>
            }
          >
            {sessionsList.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <span className="cm-hint">
                  Sesiones manuales cargadas: {sessionsList.length}
                </span>
              </div>
            )}
          </AwsContainer>

          {sessionData && (
            <div className="disc-section-view" style={{ maxWidth: "100%" }}>
              <SummarySection
                data={sessionData}
                onNavigateSection={setActiveSection}
              />
              {activeSection === "aws-archify" && (
                <AwsSuggestedDiagramSection
                  data={sessionData}
                  apiUrl={resolvedApiBase}
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
        </div>
      )}
    </div>
  );
}
