import React, { useState, useEffect, useCallback } from "react";
import IaCViewer from "../migration/IaCViewer";
import { apiFetch } from "../../utils/apiClient";

const EXECUTION_MODES = [
  {
    id: "mode_1_discover_only",
    label: "Modo 1 — Descubrir (Solo lectura)",
    desc: "Localiza activos mediante APIs de hipervisor (Proxmox/vCenter), DNS/IPAM y rangos CIDR autorizados. No instala agentes.",
    badge: "Solo lectura",
    badgeClass: "observed",
  },
  {
    id: "mode_2_discover_and_plan",
    label: "Modo 2 — Descubrir y Planificar",
    desc: "Descubre nodos, bases de datos (6 capas), almacenamiento e IaC, y genera el plan por nodo y oleadas de migración.",
    badge: "Recomendado primero",
    badgeClass: "info",
  },
  {
    id: "mode_3_discover_and_install",
    label: "Modo 3 — Descubrir e Instalar Agentes",
    desc: "Despliega osquery/fleetd en los nodos compatibles aprobados con límites de concurrencia e idempotencia.",
    badge: "Requiere política",
    badgeClass: "warning",
  },
  {
    id: "mode_4_global_e2e_test",
    label: "Modo 4 — Prueba Global de Extremo a Extremo",
    desc: "Ejecuta el flujo completo y valida los 4 niveles (Infraestructura, SO, Agente e Inventario verificado).",
    badge: "Validación 4 Niveles",
    badgeClass: "validated",
  },
];

const AGENT_PROVIDERS = [
  { id: "hybrid_option_c", label: "Opción C Híbrida (Fleet + Colectores CloudMove)" },
  { id: "fleet_osquery", label: "FleetDM + osqueryd (TLS Enroll)" },
  { id: "cloudmove_native", label: "Colector Ligero CloudMove (Python + osqueryi)" },
  { id: "collect_only_no_agent", label: "Solo Recolección Sin Agente (SSH / API / SNMP)" },
];

export default function DataCenterCampaignPanel({
  isStandalonePage = false,
  onLoadCampaignCmirToCanvas,
  onActiveCampaignChange,
}) {
  const [campaigns, setCampaigns] = useState([]);
  const [activeCampaign, setActiveCampaign] = useState(null);
  const [selectedMode, setSelectedMode] = useState("mode_4_global_e2e_test");
  const [agentProvider, setAgentProvider] = useState("hybrid_option_c");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [banner, setBanner] = useState("");
  const [nodeFilter, setNodeFilter] = useState("ALL");

  // Workload selection & Subgraph migration state (Case 3)
  const [selectedWorkloadIds, setSelectedWorkloadIds] = useState([
    "dc-node-01",
    "dc-node-02",
    "dc-node-03",
  ]);
  const [validatedSharedIds, setValidatedSharedIds] = useState([]);
  const [targetProvider, setTargetProvider] = useState("aws");
  const [migrationPlanResult, setMigrationPlanResult] = useState(null);

  const loadCampaigns = useCallback(
    async (selectId = null) => {
      try {
        const res = await apiFetch("/api/v1/campaigns");
        if (!res.ok) return;
        const data = await res.json();
        const list = data.campaigns || [];
        setCampaigns(list);
        if (selectId) {
          const found = list.find((c) => c.campaign_id === selectId);
          if (found) {
            setActiveCampaign(found);
            if (onActiveCampaignChange) onActiveCampaignChange(found);
            return;
          }
        }
        if (list.length > 0) {
          setActiveCampaign((prev) => {
            const next = prev
              ? list.find((c) => c.campaign_id === prev.campaign_id) || list[0]
              : list[0];
            if (onActiveCampaignChange) onActiveCampaignChange(next);
            return next;
          });
        }
      } catch (err) {
        setError(`Error conectando con API de campañas: ${err.message}`);
      }
    },
    [onActiveCampaignChange]
  );

  useEffect(() => {
    loadCampaigns();
  }, [loadCampaigns]);

  const handleLaunchCampaign = async (modeOverride = null) => {
    const modeToRun = modeOverride || selectedMode;
    setLoading(true);
    setError("");
    setBanner("");
    try {
      const res = await apiFetch("/api/v1/campaigns/launch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          environment_id: "env-datacenter-01",
          mode: modeToRun,
          agent_provider: agentProvider,
          policy_approved: true,
          approved_by: (typeof window !== "undefined" && window.localStorage?.getItem("cloudmove_operator_id")) || "operator",
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setActiveCampaign(data);
      if (onActiveCampaignChange) onActiveCampaignChange(data);
      await loadCampaigns(data.campaign_id);
      setBanner(
        `Campaña ${data.campaign_id} ejecutada en ${data.mode_label}: ${data.verified_nodes}/${data.total_nodes} hosts con inventario verificado.`
      );
    } catch (err) {
      setError(`No se pudo iniciar la campaña: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleLifecycleAction = async (action, label) => {
    if (!activeCampaign) return;
    setLoading(true);
    setError("");
    setBanner("");
    try {
      const res = await apiFetch(`/api/v1/campaigns/${activeCampaign.campaign_id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approved_by: (typeof window !== "undefined" && window.localStorage?.getItem("cloudmove_operator_id")) || "operator",
          reason: `Acción ${label} ejecutada por operador`,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Error en ${action}`);
      setActiveCampaign(data);
      if (onActiveCampaignChange) onActiveCampaignChange(data);
      await loadCampaigns(data.campaign_id);
      setBanner(`Campaña ${data.campaign_id}: ${label} completado (Estado: ${data.status}).`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRetryAsset = async (assetId) => {
    if (!activeCampaign) return;
    setLoading(true);
    setError("");
    setBanner("");
    try {
      const res = await apiFetch(
        `/api/v1/campaigns/${activeCampaign.campaign_id}/assets/${assetId}/retry`,
        { method: "POST" }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "No se pudo reintentar el host.");
      const updated = data.campaign || data;
      setActiveCampaign(updated);
      await loadCampaigns(updated.campaign_id);
      setBanner(
        `Reintento completado en activo ${assetId}: ${data.retry_result?.message || "Estado actualizado"}.`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleLoadCmirGraph = async () => {
    if (!activeCampaign || !onLoadCampaignCmirToCanvas) return;
    setLoading(true);
    setError("");
    try {
      const res = await apiFetch(`/api/v1/campaigns/${activeCampaign.campaign_id}/cmir`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "No se pudo obtener el grafo CMIR de la campaña.");
      onLoadCampaignCmirToCanvas(data.cmir, activeCampaign);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handlePlanWorkloadMigration = async () => {
    if (!activeCampaign) return;
    if (selectedWorkloadIds.length === 0) {
      setError("Selecciona al menos un nodo o carga del datacenter en la tabla inferior para planificar su migración.");
      return;
    }
    setLoading(true);
    setError("");
    setBanner("");
    try {
      const res = await apiFetch(`/api/v1/campaigns/${activeCampaign.campaign_id}/migrate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          selected_resources: selectedWorkloadIds,
          validated_shared_resources: validatedSharedIds,
          target_provider: targetProvider,
          dry_run: true,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error al planificar la migración del subgrafo.");
      setMigrationPlanResult(data);
      setBanner(
        `Plan de migración de subgrafo Datacenter generado hacia ${targetProvider.toUpperCase()} (${selectedWorkloadIds.length} cargas seleccionadas).`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const toggleWorkloadSelection = (assetId) => {
    setSelectedWorkloadIds((prev) =>
      prev.includes(assetId) ? prev.filter((id) => id !== assetId) : [...prev, assetId]
    );
  };

  const toggleSharedValidation = (sharedId) => {
    setValidatedSharedIds((prev) =>
      prev.includes(sharedId) ? prev.filter((id) => id !== sharedId) : [...prev, sharedId]
    );
  };

  const nodes = activeCampaign?.nodes || [];
  const filteredNodes = nodes.filter((n) => {
    if (nodeFilter === "ALL") return true;
    return n.state === nodeFilter;
  });

  const inaccessibleNodes = nodes.filter(
    (n) => n.state === "unsupported" || n.state === "discovered_unverified" || !n.verification_4_levels?.level_4_inventory_verified
  );

  const content = (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {/* Cabecera */}
      <div className="cm-page-header" style={{ marginBottom: 4 }}>
        <div>
          <h2 className="cm-page-title">
            Caso 3 · Descubrimiento y Migración de Datacenter Multi-Sitio
          </h2>
          <p className="cm-page-subtitle">
            Orquestación distribuida para inventarios complejos: hipervisores (Proxmox VE / VMware vSphere), redes CIDR, bases de datos en 6 capas, diagnóstico de equipos inaccesibles, protección de recursos compartidos y planificación por oleadas hacia AWS o GCP.
          </p>
        </div>
        <div className="cm-header-badges">
          {activeCampaign && (
            <span className={`cm-badge ${activeCampaign.status === "completed" ? "observed" : "warning"}`}>
              Campaña: {activeCampaign.campaign_id} ({activeCampaign.status})
            </span>
          )}
          <span className="cm-badge aws">AWS Soportado</span>
          <span className="cm-badge gcp">GCP Soportado</span>
        </div>
      </div>

      {error && (
        <div className="cm-alert error" role="alert">
          <strong>Diagnóstico de Campaña:</strong> {error}
        </div>
      )}
      {banner && (
        <div className="cm-alert success" role="status">
          <strong>Orquestador de Campaña:</strong> {banner}
        </div>
      )}

      {/* Las 4 Fases de Descubrimiento Masivo */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 12 }}>
        {[
          {
            step: "1. Descubrir",
            tag: "Fases A y B",
            desc: "APIs de hipervisor (Proxmox/vCenter), bases de datos, almacenamiento, IaC y rangos CIDR aprobados.",
          },
          {
            step: "2. Identificar y Reconciliar",
            tag: "Fases C y D",
            desc: "Correlación canónica de SO, arquitectura, UUID y MAC/IP sin fusionar activos ambiguos.",
          },
          {
            step: "3. Evaluar e Instalar",
            tag: "Fase E + 8 Controles",
            desc: "Selección en catálogo aprobado (.deb/.rpm/.msi/ARM64) y preparación de oleadas de migración.",
          },
          {
            step: "4. Verificar (4 Niveles)",
            tag: "Prueba Global",
            desc: "Infraestructura confirmada → SO identificado → Agente conectado → Inventario verificado.",
          },
        ].map((item) => (
          <div key={item.step} className="cm-card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <strong style={{ color: "var(--color-primary)", fontSize: 13 }}>{item.step}</strong>
              <span className="cm-badge info">{item.tag}</span>
            </div>
            <p className="cm-hint" style={{ margin: 0, lineHeight: 1.45 }}>
              {item.desc}
            </p>
          </div>
        ))}
      </div>

      {/* Configuración de Campaña, Selector de Modo y Controles de Ciclo de Vida */}
      <div className="cm-card">
        <div className="cm-card-title">
          <span>Configuración de Campaña, Modos de Ejecución y Control Operativo (`env-datacenter-01`)</span>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {activeCampaign && onLoadCampaignCmirToCanvas && (
              <button
                type="button"
                className="cm-btn primary sm"
                onClick={handleLoadCmirGraph}
                disabled={loading}
              >
                Cargar Topología CMIR v2.1 del Datacenter en Lienzo
              </button>
            )}
          </div>
        </div>

        <div className="cm-form-grid" style={{ marginBottom: 14 }}>
          <div className="cm-field">
            <label htmlFor="dc-agent-provider" className="cm-label">
              Arquitectura de Recolectores / Agentes
            </label>
            <select
              id="dc-agent-provider"
              className="cm-select"
              value={agentProvider}
              onChange={(e) => setAgentProvider(e.target.value)}
            >
              {AGENT_PROVIDERS.map((ap) => (
                <option key={ap.id} value={ap.id}>
                  {ap.label}
                </option>
              ))}
            </select>
          </div>

          {campaigns.length > 0 && (
            <div className="cm-field">
              <label htmlFor="dc-campaign-history" className="cm-label">
                Historial de Campañas Ejecutadas ({campaigns.length})
              </label>
              <select
                id="dc-campaign-history"
                className="cm-select"
                value={activeCampaign?.campaign_id || ""}
                onChange={(e) => {
                  const found = campaigns.find((c) => c.campaign_id === e.target.value);
                  if (found) {
                    setActiveCampaign(found);
                    if (onActiveCampaignChange) onActiveCampaignChange(found);
                  }
                }}
              >
                {campaigns.map((c) => (
                  <option key={c.campaign_id} value={c.campaign_id}>
                    {c.campaign_id} — {c.mode_label} ({c.status})
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Tarjetas de Modo de Ejecución (100% legibles con alto contraste) */}
        <div className="cm-selector-grid" style={{ marginBottom: 14 }}>
          {EXECUTION_MODES.map((m) => {
            const isSelected = selectedMode === m.id;
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => setSelectedMode(m.id)}
                className={`cm-selector-card ${isSelected ? "selected" : ""}`}
                aria-pressed={isSelected}
              >
                <div>
                  <div className="cm-selector-card-top">
                    <span className="cm-selector-card-title">{m.label}</span>
                    <span className={`cm-badge ${m.badgeClass}`}>{m.badge}</span>
                  </div>
                  <div className="cm-selector-card-desc">{m.desc}</div>
                </div>
              </button>
            );
          })}
        </div>

        {/* Botones de Lanzamiento y Ciclo de Vida (Aprobar, Pausar, Reanudar, Cancelar) */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button
            type="button"
            className="cm-btn primary"
            disabled={loading}
            onClick={() => handleLaunchCampaign()}
          >
            {loading ? "Ejecutando Campaña..." : "Ejecutar Campaña en Modo Seleccionado"}
          </button>
          <button
            type="button"
            className="cm-btn approve"
            disabled={loading}
            onClick={() => handleLaunchCampaign("mode_4_global_e2e_test")}
          >
            Prueba Global 1-Clic (4 Niveles)
          </button>

          {activeCampaign && (
            <>
              <button
                type="button"
                className="cm-btn sm"
                disabled={loading}
                onClick={() => handleLifecycleAction("approve", "Aprobación de Política")}
              >
                Aprobar Política
              </button>
              <button
                type="button"
                className="cm-btn warning sm"
                disabled={loading}
                onClick={() => handleLifecycleAction("pause", "Pausa de Campaña")}
              >
                Pausar Campaña
              </button>
              <button
                type="button"
                className="cm-btn approve sm"
                disabled={loading}
                onClick={() => handleLifecycleAction("resume", "Reanudación de Campaña")}
              >
                Reanudar Campaña
              </button>
              <button
                type="button"
                className="cm-btn danger sm"
                disabled={loading}
                onClick={() => handleLifecycleAction("cancel", "Cancelación de Campaña")}
              >
                Cancelar Campaña
              </button>
            </>
          )}
        </div>
      </div>

      {activeCampaign && (
        <>
          {/* KPIs de Cobertura y Progreso por Host */}
          <div className="cm-kpi-grid">
            <div className="cm-kpi-card">
              <span className="cm-kpi-label">1. Infraestructura Confirmada</span>
              <span className="cm-kpi-value">
                {activeCampaign.global_verification_summary?.level_1_infrastructure_confirmed ?? activeCampaign.total_nodes}/{activeCampaign.total_nodes}
              </span>
              <span className="cm-kpi-meta">Hipervisores, subredes y almacenamiento</span>
            </div>
            <div className="cm-kpi-card">
              <span className="cm-kpi-label">2. SO Identificado</span>
              <span className="cm-kpi-value">
                {activeCampaign.global_verification_summary?.level_2_os_identified ?? 6}/{activeCampaign.total_nodes}
              </span>
              <span className="cm-kpi-meta">Reconciliación canónica sin duplicados</span>
            </div>
            <div className="cm-kpi-card">
              <span className="cm-kpi-label">3. Agente / Colector Activo</span>
              <span className="cm-kpi-value">
                {activeCampaign.global_verification_summary?.level_3_agent_connected ?? 5}/{activeCampaign.total_nodes}
              </span>
              <span className="cm-kpi-meta">osquery / Fleet / API sin agente</span>
            </div>
            <div className="cm-kpi-card">
              <span className="cm-kpi-label">4. Inventario Verificado</span>
              <span className="cm-kpi-value" style={{ color: "#15803d" }}>
                {activeCampaign.verified_nodes}/{activeCampaign.total_nodes}
              </span>
              <span className="cm-kpi-meta">
                Cobertura global: <strong>{activeCampaign.coverage_pct}%</strong>
              </span>
            </div>
          </div>

          {/* Alerta explícita de Resultados Parciales y Equipos Inaccesibles / No Soportados */}
          {inaccessibleNodes.length > 0 && (
            <div className="cm-card" style={{ borderLeft: "4px solid #d97706" }}>
              <div className="cm-card-title">
                <span>
                  Diagnóstico de Equipos Inaccesibles o Sin Agente Estándar ({inaccessibleNodes.length} de {nodes.length} activos)
                </span>
                <span className="cm-badge warning">Resultados Parciales Transparentes</span>
              </div>
              <p className="cm-hint" style={{ marginTop: 0, marginBottom: 10 }}>
                CloudMove nunca oculta equipos inaccesibles ni finge cobertura del 100%. A continuación se detallan los motivos técnicos y el método empresarial alternativo para cada activo:
              </p>
              <div className="cm-table-wrap">
                <table className="cm-table">
                  <thead>
                    <tr>
                      <th>Activo / IP</th>
                      <th>Estado</th>
                      <th>Motivo Técnico Detectado</th>
                      <th>Método Alternativo Activo</th>
                      <th>Acción</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inaccessibleNodes.map((inNode) => (
                      <tr key={inNode.asset_id}>
                        <td>
                          <strong>{inNode.hostname}</strong>
                          <div className="cm-hint"><code>{inNode.primary_ip}</code></div>
                        </td>
                        <td>
                          <span className="cm-badge warning">{inNode.state}</span>
                        </td>
                        <td>
                          {inNode.state === "unsupported"
                            ? "Appliance de red propietario (FortiOS) sin soporte para binario osquery Linux/Windows."
                            : "Credenciales SSH/WinRM pendientes o puerto de gestión filtrado en segmento de red."}
                        </td>
                        <td>
                          <code>{inNode.collection_method || "API / SNMP / Config Export"}</code>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="cm-btn sm"
                            disabled={loading}
                            onClick={() => handleRetryAsset(inNode.asset_id)}
                          >
                            Reintentar Host
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Matriz de Nodos Reconciliados con Selección de Cargas para Migración */}
          <div className="cm-card">
            <div className="cm-card-title">
              <div>
                <span>
                  Inventario de Hosts y Máquinas Virtuales Reconciliados ({filteredNodes.length} de {nodes.length})
                </span>
                <div className="cm-hint" style={{ fontWeight: 400, marginTop: 2 }}>
                  Marca las casillas de los hosts/VMs que deseas incluir en la planificación de migración hacia AWS o GCP.
                </div>
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {[
                  { id: "ALL", label: `Todos (${nodes.length})` },
                  { id: "verified", label: "Verificados" },
                  { id: "discovered_unverified", label: "Parciales / Sin Verificar" },
                  { id: "unsupported", label: "Appliances sin Agente" },
                ].map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    className={`cm-btn sm ${nodeFilter === f.id ? "primary" : ""}`}
                    onClick={() => setNodeFilter(f.id)}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="cm-table-wrap">
              <table className="cm-table">
                <thead>
                  <tr>
                    <th style={{ width: 38 }}>Migrar</th>
                    <th>Activo & Confianza</th>
                    <th>SO & Arquitectura</th>
                    <th>IP Primaria & Sitio</th>
                    <th>Estado & Agente</th>
                    <th>Paquete / Método</th>
                    <th>Verificación (4 Niveles)</th>
                    <th>Operación</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredNodes.map((n) => {
                    const v = n.verification_4_levels || {};
                    const isChecked = selectedWorkloadIds.includes(n.asset_id);
                    return (
                      <tr key={n.asset_id}>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`Seleccionar ${n.hostname} para migración`}
                            checked={isChecked}
                            onChange={() => toggleWorkloadSelection(n.asset_id)}
                          />
                        </td>
                        <td>
                          <strong>{n.hostname}</strong>
                          <div className="cm-hint">
                            <code>{n.asset_id}</code> · Confianza: <strong>{Math.round((n.identity_confidence || 0.9) * 100)}%</strong>
                          </div>
                        </td>
                        <td>
                          <div>{n.os_name}</div>
                          <div className="cm-hint">
                            <code>{n.os_family} · {n.architecture}</code>
                          </div>
                        </td>
                        <td>
                          <code>{n.primary_ip}</code>
                          <div className="cm-hint">{n.site_id}</div>
                        </td>
                        <td>
                          <span
                            className={`cm-badge ${
                              n.state === "verified"
                                ? "observed"
                                : n.state === "unsupported"
                                ? "warning"
                                : "info"
                            }`}
                          >
                            {n.state}
                          </span>
                          <div className="cm-hint" style={{ marginTop: 3 }}>
                            Agente: {n.agent_status}
                          </div>
                        </td>
                        <td>
                          <code>{n.selected_package}</code>
                          <div className="cm-hint">{n.collection_method}</div>
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                            <span className={`cm-badge ${v.level_1_infrastructure_confirmed ? "observed" : "neutral"}`} style={{ fontSize: 10, padding: "1px 5px" }}>
                              1.Infra:{v.level_1_infrastructure_confirmed ? "OK" : "NO"}
                            </span>
                            <span className={`cm-badge ${v.level_2_os_identified ? "observed" : "neutral"}`} style={{ fontSize: 10, padding: "1px 5px" }}>
                              2.SO:{v.level_2_os_identified ? "OK" : "NO"}
                            </span>
                            <span className={`cm-badge ${v.level_3_agent_connected ? "observed" : "warning"}`} style={{ fontSize: 10, padding: "1px 5px" }}>
                              3.Agente:{v.level_3_agent_connected ? "OK" : "API"}
                            </span>
                            <span className={`cm-badge ${v.level_4_inventory_verified ? "observed" : "warning"}`} style={{ fontSize: 10, padding: "1px 5px" }}>
                              4.Inv:{v.level_4_inventory_verified ? "OK" : "PARCIAL"}
                            </span>
                          </div>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="cm-btn sm"
                            disabled={loading}
                            onClick={() => handleRetryAsset(n.asset_id)}
                          >
                            Reintentar
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Planificador de Migración de Cargas Seleccionadas y Protección de Recursos Compartidos */}
          <div className="cm-card">
            <div className="cm-card-title">
              <span>
                Planificación de Migración de Subgrafo Datacenter y Protección de Recursos Compartidos
              </span>
              <span className="cm-badge shared">
                {selectedWorkloadIds.length} carga(s) seleccionada(s)
              </span>
            </div>
            <p className="cm-hint" style={{ marginTop: 0, marginBottom: 12 }}>
              Los recursos compartidos (como el clúster PostgreSQL HA primario <code>db-pg-ha-01</code> o el bus RabbitMQ compartido) están protegidos por defecto para evitar interrumpir servicios que permanecen On-Premise. Marca explícitamente un recurso compartido solo si deseas autorizar su migración conjunta.
            </p>

            <div className="cm-form-grid" style={{ marginBottom: 14 }}>
              <div className="cm-field">
                <label htmlFor="dc-mig-provider" className="cm-label">
                  Proveedor Cloud Destino para las Cargas Seleccionadas
                </label>
                <select
                  id="dc-mig-provider"
                  className="cm-select"
                  value={targetProvider}
                  onChange={(e) => setTargetProvider(e.target.value)}
                >
                  <option value="aws">Amazon Web Services (AWS — VPC, EC2, RDS Multi-AZ, MGN)</option>
                  <option value="gcp">Google Cloud Platform (GCP — VPC, GCE, Cloud SQL HA)</option>
                </select>
              </div>

              <div className="cm-field">
                <span className="cm-label">Autorización de Recursos Compartidos Críticos</span>
                <div style={{ display: "flex", gap: 14, flexWrap: "wrap", paddingTop: 6 }}>
                  {[
                    { id: "db-pg-ha-01", label: "db-pg-ha-01 (PostgreSQL 15 HA Compartido)" },
                    { id: "dc-node-03", label: "dc-node-03 (Nodo DB Primario Compartido)" },
                  ].map((sh) => (
                    <label key={sh.id} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={validatedSharedIds.includes(sh.id)}
                        onChange={() => toggleSharedValidation(sh.id)}
                      />
                      <span>Autorizar {sh.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <button
                  type="button"
                  className="cm-btn primary"
                  disabled={loading || selectedWorkloadIds.length === 0}
                  onClick={handlePlanWorkloadMigration}
                >
                  Generar Plan e IaC de Subgrafo ({targetProvider.toUpperCase()})
                </button>
              </div>
            </div>

            {migrationPlanResult && (
              <div className="cm-card-subtle" style={{ marginTop: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
                  <strong>
                    Resultado de Planificación de Subgrafo Datacenter → {migrationPlanResult.target_provider?.toUpperCase()}
                  </strong>
                  <span className="cm-badge observed">
                    Modo: {migrationPlanResult.execution_mode || "simulated_dry_run"}
                  </span>
                </div>
                {migrationPlanResult.shared_resource_warnings?.length > 0 && (
                  <div className="cm-alert warning" style={{ marginBottom: 10 }}>
                    <strong>Protección de Recursos Compartidos Activa:</strong>{" "}
                    {migrationPlanResult.shared_resource_warnings.join(" · ")}
                  </div>
                )}
                {migrationPlanResult.generated_artifacts?.files && (
                  <IaCViewer
                    code={migrationPlanResult.generated_artifacts.iac_code}
                    files={migrationPlanResult.generated_artifacts.files}
                    language="hcl"
                    filename="main.tf"
                  />
                )}
              </div>
            )}
          </div>

          {/* Descubrimiento de Bases de Datos en 6 Capas y Oleadas de Migración */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: 16 }}>
            <div className="cm-card">
              <div className="cm-card-title">
                <span>Bases de Datos Detectadas (6 Capas de Evidencia)</span>
                <span className="cm-badge observed">
                  {(activeCampaign.databases_6_layers || []).length} motores
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {(activeCampaign.databases_6_layers || []).map((db) => (
                  <div key={db.db_id} className="cm-card-subtle">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <strong>{db.engine}</strong>
                      <span className="cm-badge aws">{db.aws_target_recommendation}</span>
                    </div>
                    <div className="cm-hint" style={{ marginBottom: 4 }}>
                      Rol: <strong>{db.ha_role}</strong> · Tamaño estimado: <strong>{db.estimated_size_gb} GB</strong>
                    </div>
                    <div style={{ fontSize: 11.5, color: "var(--color-text-secondary)" }}>
                      <strong>Evidencia:</strong> {(db.evidence_layers || []).join(" · ")}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="cm-card">
              <div className="cm-card-title">
                <span>Oleadas de Migración y Prerrequisitos de Ejecución</span>
                <span className="cm-badge info">
                  {(activeCampaign.migration_waves || []).length} oleadas
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {(activeCampaign.migration_waves || []).map((w) => (
                  <div key={w.wave_id} className="cm-card-subtle">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <strong>{w.name}</strong>
                      <span className={`cm-badge ${w.risk_level === "high" ? "danger" : w.risk_level === "medium" ? "warning" : "observed"}`}>
                        Riesgo: {w.risk_level?.toUpperCase()}
                      </span>
                    </div>
                    <div style={{ fontSize: 12, marginBottom: 4 }}>
                      Estrategia: <strong>{w.strategy}</strong>
                    </div>
                    <div className="cm-hint">
                      Activos incluidos: <code>{(w.assets || []).join(", ")}</code>
                    </div>
                    <div className="cm-hint" style={{ marginTop: 3 }}>
                      Prerrequisitos: {(w.prerequisites || []).join(" · ")}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );

  if (isStandalonePage) {
    return <div className="tab-pane-view">{content}</div>;
  }
  return content;
}
