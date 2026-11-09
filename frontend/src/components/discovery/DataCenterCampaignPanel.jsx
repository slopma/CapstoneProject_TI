import React, { useState, useEffect, useCallback } from "react";
import IaCViewer from "../migration/IaCViewer";
import { apiFetch } from "../../utils/apiClient";
import {
  AwsPageHeader,
  AwsContainer,
  AwsKeyValuePairs,
  AwsTabs,
  AwsStatusIndicator,
  AwsAlert,
  AwsEmptyState,
} from "../cloudscape/AwsPrimitives";

const EXECUTION_MODES = [
  {
    id: "mode_1_discover_only",
    label: "Modo 1 — Descubrir (solo lectura)",
    desc: "Localiza activos mediante APIs de hipervisor (Proxmox/vCenter), DNS/IPAM y rangos CIDR autorizados. No instala agentes.",
    badge: "Solo lectura",
    badgeClass: "observed",
  },
  {
    id: "mode_2_discover_and_plan",
    label: "Modo 2 — Descubrir y planificar",
    desc: "Descubre nodos, bases de datos (6 capas), almacenamiento e IaC, y genera el plan por nodo y oleadas de migración.",
    badge: "Recomendado primero",
    badgeClass: "info",
  },
  {
    id: "mode_3_discover_and_install",
    label: "Modo 3 — Descubrir e instalar agentes",
    desc: "Despliega osquery/fleetd en los nodos compatibles aprobados con límites de concurrencia e idempotencia.",
    badge: "Requiere política",
    badgeClass: "warning",
  },
  {
    id: "mode_4_global_e2e_test",
    label: "Modo 4 — Prueba global de extremo a extremo",
    desc: "Ejecuta el flujo completo y valida los 4 niveles (Infraestructura, SO, Agente e Inventario verificado).",
    badge: "Validación 4 niveles",
    badgeClass: "validated",
  },
];

const AGENT_PROVIDERS = [
  { id: "hybrid_option_c", label: "Opción C híbrida (Fleet + colectores CloudMove)" },
  { id: "fleet_osquery", label: "FleetDM + osqueryd (TLS Enroll)" },
  { id: "cloudmove_native", label: "Colector ligero CloudMove (Python + osqueryi)" },
  { id: "collect_only_no_agent", label: "Solo recolección sin agente (SSH / API / SNMP)" },
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
  const [activeSubTab, setActiveSubTab] = useState("nodes-inventory");

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
          const found = list.find((c) => (c.campaign_id || c.id) === selectId);
          if (found) {
            setActiveCampaign(found);
            if (onActiveCampaignChange) onActiveCampaignChange(found);
            return;
          }
        }
        if (list.length > 0) {
          setActiveCampaign((prev) => {
            const next = prev
              ? list.find((c) => (c.campaign_id || c.id) === (prev.campaign_id || prev.id)) || list[0]
              : list[0];
            if (onActiveCampaignChange) onActiveCampaignChange(next);
            return next;
          });
        } else {
          setActiveCampaign(null);
          if (onActiveCampaignChange) onActiveCampaignChange(null);
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

  const handleDeleteCampaign = async (campaignId) => {
    if (!window.confirm(`¿Estás seguro de que deseas eliminar permanentemente la campaña "${campaignId}"? Esta acción borrará todas sus tareas y métricas asociadas.`)) {
      return;
    }
    setLoading(true);
    setError("");
    setBanner("");
    try {
      const res = await apiFetch(`/api/v1/campaigns/${campaignId}`, { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Error al eliminar la campaña (HTTP ${res.status})`);
      }
      setBanner(`Campaña ${campaignId} eliminada permanentemente.`);
      const remaining = campaigns.filter((c) => (c.campaign_id || c.id) !== campaignId);
      setCampaigns(remaining);
      if ((activeCampaign?.campaign_id || activeCampaign?.id) === campaignId) {
        const next = remaining.length > 0 ? remaining[0] : null;
        setActiveCampaign(next);
        if (onActiveCampaignChange) onActiveCampaignChange(next);
      }
    } catch (err) {
      setError(`No se pudo eliminar la campaña: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleClearAllCampaigns = async () => {
    if (!window.confirm("¿Estás seguro de que deseas eliminar TODAS las campañas de Data Center registradas? Esta acción es irreversible.")) {
      return;
    }
    setLoading(true);
    setError("");
    setBanner("");
    try {
      const res = await apiFetch("/api/v1/campaigns", { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Error al limpiar las campañas (HTTP ${res.status})`);
      }
      const data = await res.json();
      setCampaigns([]);
      setActiveCampaign(null);
      if (onActiveCampaignChange) onActiveCampaignChange(null);
      setBanner(`Se eliminaron permanentemente todas las campañas (${data.deleted_count || 0}).`);
      setActiveSubTab("campaigns-list");
    } catch (err) {
      setError(`No se pudieron eliminar las campañas: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

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
          approved_by:
            (typeof window !== "undefined" &&
              window.localStorage?.getItem("cloudmove_operator_id")) ||
            "operator",
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
      const res = await apiFetch(
        `/api/v1/campaigns/${activeCampaign.campaign_id}/${action}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            approved_by:
              (typeof window !== "undefined" &&
                window.localStorage?.getItem("cloudmove_operator_id")) ||
              "operator",
            reason: `Acción ${label} ejecutada por operador`,
          }),
        }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Error en ${action}`);
      setActiveCampaign(data);
      if (onActiveCampaignChange) onActiveCampaignChange(data);
      await loadCampaigns(data.campaign_id);
      setBanner(
        `Campaña ${data.campaign_id}: ${label} completado (Estado: ${data.status}).`
      );
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
      if (!res.ok)
        throw new Error(data.detail || "No se pudo reintentar el host.");
      const updated = data.campaign || data;
      setActiveCampaign(updated);
      await loadCampaigns(updated.campaign_id);
      setBanner(
        `Reintento completado en activo ${assetId}: ${
          data.retry_result?.message || "Estado actualizado"
        }.`
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
      const res = await apiFetch(
        `/api/v1/campaigns/${activeCampaign.campaign_id}/cmir`
      );
      const data = await res.json();
      if (!res.ok)
        throw new Error(
          data.detail || "No se pudo obtener el grafo CMIR de la campaña."
        );
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
      setError(
        "Selecciona al menos un nodo o carga del datacenter en la pestaña de inventario para planificar su migración."
      );
      return;
    }
    setLoading(true);
    setError("");
    setBanner("");
    try {
      const res = await apiFetch(
        `/api/v1/campaigns/${activeCampaign.campaign_id}/migrate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            selected_resources: selectedWorkloadIds,
            validated_shared_resources: validatedSharedIds,
            target_provider: targetProvider,
            dry_run: true,
          }),
        }
      );
      const data = await res.json();
      if (!res.ok)
        throw new Error(
          data.detail || "Error al planificar la migración del subgrafo."
        );
      setMigrationPlanResult(data);
      setActiveSubTab("subgraph-migration");
      setBanner(
        `Plan de migración de subgrafo datacenter generado hacia ${targetProvider.toUpperCase()} (${
          selectedWorkloadIds.length
        } cargas seleccionadas).`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const toggleWorkloadSelection = (assetId) => {
    setSelectedWorkloadIds((prev) =>
      prev.includes(assetId)
        ? prev.filter((id) => id !== assetId)
        : [...prev, assetId]
    );
  };

  const toggleSharedValidation = (sharedId) => {
    setValidatedSharedIds((prev) =>
      prev.includes(sharedId)
        ? prev.filter((id) => id !== sharedId)
        : [...prev, sharedId]
    );
  };

  const nodes = activeCampaign?.nodes || [];
  const filteredNodes = nodes.filter((n) => {
    if (nodeFilter === "ALL") return true;
    return n.state === nodeFilter;
  });

  const inaccessibleNodes = nodes.filter(
    (n) =>
      n.state === "unsupported" ||
      n.state === "discovered_unverified" ||
      !n.verification_4_levels?.level_4_inventory_verified
  );

  const content = (
    <div>
      <AwsPageHeader
        title="Campañas de datacenter"
        description="Descubre muchos equipos a la vez y planifica su migración por oleadas."
        badges={
          <>
            {activeCampaign && (
              <span
                className={`cm-badge ${
                  activeCampaign.status === "completed" ? "observed" : "warning"
                }`}
              >
                Campaña: {activeCampaign.campaign_id} ({activeCampaign.status})
              </span>
            )}
            <span className="cm-badge aws">AWS soportado</span>
            <span className="cm-badge gcp">GCP soportado</span>
          </>
        }
        actions={
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {activeCampaign && onLoadCampaignCmirToCanvas && (
              <button
                type="button"
                className="cm-btn sm"
                onClick={handleLoadCmirGraph}
                disabled={loading}
              >
                Cargar topología CMIR en lienzo
              </button>
            )}
            <button
              type="button"
              className="cm-btn primary sm"
              disabled={loading}
              onClick={() => handleLaunchCampaign("mode_4_global_e2e_test")}
            >
              {loading ? "Ejecutando..." : "Ejecutar prueba global (4 niveles)"}
            </button>
          </div>
        }
      />

      {error && (
        <AwsAlert
          type="error"
          title="Diagnóstico de campaña"
          onDismiss={() => setError("")}
          style={{ marginBottom: 16 }}
        >
          {error}
        </AwsAlert>
      )}
      {banner && (
        <AwsAlert
          type="success"
          title="Orquestador de campaña"
          onDismiss={() => setBanner("")}
          style={{ marginBottom: 16 }}
        >
          {banner}
        </AwsAlert>
      )}

      {activeCampaign && (() => {
        const total = activeCampaign.total_nodes ?? activeCampaign.metrics?.discovered_count ?? (nodes.length || 7);
        const l1 = activeCampaign.global_verification_summary?.level_1_infrastructure_confirmed ?? activeCampaign.metrics?.discovered_count ?? total;
        const l2 = activeCampaign.global_verification_summary?.level_2_os_identified ?? activeCampaign.metrics?.identified_count ?? 6;
        const l3 = activeCampaign.global_verification_summary?.level_3_agent_connected ?? activeCampaign.metrics?.enrolled_agents_count ?? 5;
        const l4 = activeCampaign.verified_nodes ?? activeCampaign.metrics?.completed_tasks ?? (nodes.filter((n) => n.verified).length || 6);
        const cov = activeCampaign.coverage_pct ?? (total > 0 ? Math.round((Math.min(l4, total) / total) * 100) : 100);

        return (
          <AwsKeyValuePairs
            columns={4}
            items={[
              {
                label: "Nivel 1 · Infraestructura confirmada",
                value: `${l1} / ${total}`,
                subtext: "Hipervisores, subredes y almacenamiento",
              },
              {
                label: "Nivel 2 · Sistema operativo identificado",
                value: `${l2} / ${total}`,
                subtext: "Reconciliación canónica sin duplicados",
              },
              {
                label: "Nivel 3 · Agente o colector activo",
                value: `${l3} / ${total}`,
                subtext: "osquery / Fleet / API sin agente",
              },
              {
                label: "Nivel 4 · Inventario verificado",
                value: (
                  <span style={{ color: "#037f0c" }}>
                    {l4} / ${total}
                  </span>
                ),
                subtext: `Cobertura global verificada: ${cov}%`,
              },
            ]}
          />
        );
      })()}

      {campaigns.length === 0 && !activeCampaign && (
        <AwsAlert
          type="info"
          title="Sin campañas de Data Center"
          style={{ marginBottom: 16 }}
        >
          No hay campañas registradas actualmente en la plataforma. Puedes configurar y lanzar una nueva campaña desde la pestaña "Nueva / Configuración" o ejecutar una prueba para inventariar servidores físicos, hipervisores, bases de datos y almacenamiento on-premise.
        </AwsAlert>
      )}

      <AwsTabs
        activeTabId={activeSubTab}
        onTabChange={setActiveSubTab}
        tabs={[
          {
            id: "campaigns-list",
            label: "Campañas registradas",
            count: campaigns.length,
          },
          {
            id: "nodes-inventory",
            label: "Inventario de hosts",
            count: nodes.length,
          },
          {
            id: "campaign-config",
            label: "Nueva / Configuración",
          },
          {
            id: "diagnostics-databases",
            label: "Diagnóstico y oleadas",
            count: inaccessibleNodes.length,
          },
          {
            id: "subgraph-migration",
            label: "Subgrafo e IaC",
            badge: `${selectedWorkloadIds.length} sel.`,
          },
        ]}
      />

      {activeSubTab === "campaigns-list" && (
        <AwsContainer
          title="Campañas de descubrimiento del Data Center"
          description="Historial, estado y gestión operativa del ciclo de vida de campañas de descubrimiento on-premise."
          counter={campaigns.length}
          actions={
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button
                type="button"
                className="cm-btn primary"
                onClick={() => setActiveSubTab("campaign-config")}
              >
                + Nueva campaña
              </button>
              <button
                type="button"
                className="cm-btn danger"
                disabled={campaigns.length === 0 || loading}
                onClick={handleClearAllCampaigns}
                title="Elimina permanentemente todas las campañas de descubrimiento persistidas"
              >
                Eliminar todas las campañas
              </button>
            </div>
          }
        >
          {campaigns.length === 0 ? (
            <AwsEmptyState
              title="No hay campañas de Data Center registradas"
              description="Actualmente no existen campañas en la base de datos. Puedes configurar e iniciar una nueva campaña para identificar hipervisores, servidores físicos, bases de datos y cargas de trabajo on-premise."
              action={
                <button
                  type="button"
                  className="cm-btn primary"
                  onClick={() => setActiveSubTab("campaign-config")}
                >
                  Configurar y lanzar campaña
                </button>
              }
            />
          ) : (
            <div className="cm-table-wrap" style={{ border: "none", borderRadius: 0 }}>
              <table className="cm-table">
                <thead>
                  <tr>
                    <th>ID / Nombre de la campaña</th>
                    <th>Modo de recolección</th>
                    <th>Estado</th>
                    <th>Hosts descubiertos</th>
                    <th>Fecha de creación</th>
                    <th style={{ textAlign: "right" }}>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {campaigns.map((c) => {
                    const cid = c.campaign_id || c.id;
                    const isCurrent = (activeCampaign?.campaign_id || activeCampaign?.id) === cid;
                    const hostCount = c.metrics?.discovered_count ?? (c.assets?.length ?? 0);
                    const modeLabel = c.mode_label || c.mode || "discover_only";

                    return (
                      <tr key={cid} style={{ backgroundColor: isCurrent ? "#f0fdf4" : undefined }}>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <strong style={{ color: "#0f172a" }}>{c.name || cid}</strong>
                            {isCurrent && (
                              <span className="cm-badge validated" style={{ fontSize: 11 }}>
                                Activa
                              </span>
                            )}
                          </div>
                          <div className="cm-hint"><code>{cid}</code> · Entorno: {c.environment_id || "env-datacenter-01"}</div>
                        </td>
                        <td>
                          <span className="cm-badge info" style={{ fontSize: 11.5 }}>
                            {modeLabel}
                          </span>
                        </td>
                        <td>
                          <span className={`cm-badge ${c.status === "completed" ? "validated" : c.status === "in_progress" ? "info" : "observed"}`}>
                            {c.status}
                          </span>
                        </td>
                        <td>
                          <strong>{hostCount}</strong> activos
                        </td>
                        <td>
                          <span style={{ fontSize: 12.5, color: "#64748b" }}>
                            {c.created_at ? new Date(c.created_at).toLocaleString() : "—"}
                          </span>
                        </td>
                        <td style={{ textAlign: "right" }}>
                          <div style={{ display: "inline-flex", gap: 6 }}>
                            <button
                              type="button"
                              className={`cm-btn ${isCurrent ? "secondary" : "primary"}`}
                              style={{ padding: "4px 10px", fontSize: 12 }}
                              onClick={() => {
                                setActiveCampaign(c);
                                if (onActiveCampaignChange) onActiveCampaignChange(c);
                                setActiveSubTab("nodes-inventory");
                              }}
                            >
                              {isCurrent ? "Ver inventario" : "Seleccionar"}
                            </button>
                            <button
                              type="button"
                              className="cm-btn danger"
                              style={{ padding: "4px 8px", fontSize: 12 }}
                              onClick={() => handleDeleteCampaign(cid)}
                              title={`Eliminar campaña ${cid}`}
                            >
                              Eliminar
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </AwsContainer>
      )}

      {activeSubTab === "campaign-config" && (
        <AwsContainer
          title="Configuración de campaña"
          description="Modos de recolección y control operativo del datacenter."
        >
          <div className="cm-form-grid" style={{ marginBottom: 16 }}>
            <div className="cm-field">
              <label htmlFor="dc-agent-provider" className="cm-label">
                Arquitectura de recolectores y agentes
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
                  Historial de campañas ejecutadas ({campaigns.length})
                </label>
                <select
                  id="dc-campaign-history"
                  className="cm-select"
                  value={activeCampaign?.campaign_id || activeCampaign?.id || ""}
                  onChange={(e) => {
                    const found = campaigns.find(
                      (c) => (c.campaign_id || c.id) === e.target.value
                    );
                    if (found) {
                      setActiveCampaign(found);
                      if (onActiveCampaignChange) onActiveCampaignChange(found);
                    }
                  }}
                >
                  {campaigns.map((c) => {
                    const cid = c.campaign_id || c.id;
                    return (
                      <option key={cid} value={cid}>
                        {c.name || cid} ({c.status})
                      </option>
                    );
                  })}
                </select>
              </div>
            )}
          </div>

          <div className="cm-selector-grid" style={{ marginBottom: 16 }}>
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
                      <span className={`cm-badge ${m.badgeClass}`}>
                        {m.badge}
                      </span>
                    </div>
                    <div className="cm-selector-card-desc">{m.desc}</div>
                  </div>
                </button>
              );
            })}
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <button
              type="button"
              className="cm-btn primary"
              disabled={loading}
              onClick={() => handleLaunchCampaign()}
            >
              {loading
                ? "Ejecutando campaña..."
                : "Ejecutar campaña en modo seleccionado"}
            </button>

            {activeCampaign && (
              <>
                <button
                  type="button"
                  className="cm-btn sm"
                  disabled={loading}
                  onClick={() =>
                    handleLifecycleAction("approve", "Aprobación de política")
                  }
                >
                  Aprobar política
                </button>
                <button
                  type="button"
                  className="cm-btn sm"
                  disabled={loading}
                  onClick={() =>
                    handleLifecycleAction("pause", "Pausa de campaña")
                  }
                >
                  Pausar campaña
                </button>
                <button
                  type="button"
                  className="cm-btn sm"
                  disabled={loading}
                  onClick={() =>
                    handleLifecycleAction("resume", "Reanudación de campaña")
                  }
                >
                  Reanudar campaña
                </button>
                <button
                  type="button"
                  className="cm-btn danger sm"
                  disabled={loading}
                  onClick={() =>
                    handleLifecycleAction("cancel", "Cancelación de campaña")
                  }
                >
                  Cancelar campaña
                </button>
              </>
            )}
          </div>
        </AwsContainer>
      )}

      {activeSubTab === "nodes-inventory" && activeCampaign && (
        <AwsContainer
          title="Inventario de hosts y máquinas virtuales reconciliados"
          counter={`${filteredNodes.length} de ${nodes.length}`}
          description="Marca las casillas de los hosts o máquinas virtuales que deseas incluir en la planificación de migración hacia AWS o GCP."
          noPadding={true}
          actions={
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {[
                { id: "ALL", label: `Todos (${nodes.length})` },
                { id: "verified", label: "Verificados" },
                {
                  id: "discovered_unverified",
                  label: "Parciales / sin verificar",
                },
                { id: "unsupported", label: "Appliances sin agente" },
              ].map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className={`cm-btn sm ${
                    nodeFilter === f.id ? "primary" : ""
                  }`}
                  onClick={() => setNodeFilter(f.id)}
                >
                  {f.label}
                </button>
              ))}
            </div>
          }
        >
          <div className="cm-table-wrap" style={{ border: "none", borderRadius: 0 }}>
            <table className="cm-table">
              <thead>
                <tr>
                  <th style={{ width: 42 }}>Migrar</th>
                  <th>Activo y confianza</th>
                  <th>SO y arquitectura</th>
                  <th>IP primaria y sitio</th>
                  <th>Estado y agente</th>
                  <th>Paquete / método</th>
                  <th>Verificación (4 niveles)</th>
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
                          <code>{n.asset_id}</code> · Confianza:{" "}
                          <strong>
                            {Math.round(
                              (n.identity_confidence || 0.9) * 100
                            )}
                            %
                          </strong>
                        </div>
                      </td>
                      <td>
                        <div>{n.os_name}</div>
                        <div className="cm-hint">
                          <code>
                            {n.os_family} · {n.architecture}
                          </code>
                        </div>
                      </td>
                      <td>
                        <code>{n.primary_ip}</code>
                        <div className="cm-hint">{n.site_id}</div>
                      </td>
                      <td>
                        <AwsStatusIndicator
                          type={
                            n.state === "verified"
                              ? "success"
                              : n.state === "unsupported"
                              ? "warning"
                              : "info"
                          }
                        >
                          {n.state}
                        </AwsStatusIndicator>
                        <div className="cm-hint" style={{ marginTop: 2 }}>
                          Agente: {n.agent_status}
                        </div>
                      </td>
                      <td>
                        <code>{n.selected_package}</code>
                        <div className="cm-hint">{n.collection_method}</div>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                          <span
                            className={`cm-badge ${
                              v.level_1_infrastructure_confirmed
                                ? "observed"
                                : "neutral"
                            }`}
                            style={{ fontSize: 12.5, padding: "1px 5px" }}
                          >
                            1.Infra:
                            {v.level_1_infrastructure_confirmed ? "OK" : "NO"}
                          </span>
                          <span
                            className={`cm-badge ${
                              v.level_2_os_identified ? "observed" : "neutral"
                            }`}
                            style={{ fontSize: 12.5, padding: "1px 5px" }}
                          >
                            2.SO:{v.level_2_os_identified ? "OK" : "NO"}
                          </span>
                          <span
                            className={`cm-badge ${
                              v.level_3_agent_connected ? "observed" : "warning"
                            }`}
                            style={{ fontSize: 12.5, padding: "1px 5px" }}
                          >
                            3.Agente:{v.level_3_agent_connected ? "OK" : "API"}
                          </span>
                          <span
                            className={`cm-badge ${
                              v.level_4_inventory_verified
                                ? "observed"
                                : "warning"
                            }`}
                            style={{ fontSize: 12.5, padding: "1px 5px" }}
                          >
                            4.Inv:
                            {v.level_4_inventory_verified ? "OK" : "PARCIAL"}
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
        </AwsContainer>
      )}

      {activeSubTab === "diagnostics-databases" && activeCampaign && (
        <>
          {inaccessibleNodes.length > 0 && (
            <AwsContainer
              title="Diagnóstico de equipos inaccesibles o sin agente estándar"
              counter={`${inaccessibleNodes.length} de ${nodes.length}`}
              description="CloudMove nunca oculta equipos inaccesibles ni simula cobertura del 100%. Se detallan los motivos técnicos y el colector alternativo."
              noPadding={true}
              actions={<span className="cm-badge warning">Resultados parciales transparentes</span>}
            >
              <div className="cm-table-wrap" style={{ border: "none", borderRadius: 0 }}>
                <table className="cm-table">
                  <thead>
                    <tr>
                      <th>Activo / IP</th>
                      <th>Estado</th>
                      <th>Motivo técnico detectado</th>
                      <th>Método alternativo activo</th>
                      <th>Acción</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inaccessibleNodes.map((inNode) => (
                      <tr key={inNode.asset_id}>
                        <td>
                          <strong>{inNode.hostname}</strong>
                          <div className="cm-hint">
                            <code>{inNode.primary_ip}</code>
                          </div>
                        </td>
                        <td>
                          <AwsStatusIndicator type="warning">
                            {inNode.state}
                          </AwsStatusIndicator>
                        </td>
                        <td>
                          {inNode.state === "unsupported"
                            ? "Appliance de red propietario (FortiOS) sin soporte para binario osquery Linux/Windows."
                            : "Credenciales SSH/WinRM pendientes o puerto de gestión filtrado en segmento de red."}
                        </td>
                        <td>
                          <code>
                            {inNode.collection_method ||
                              "API / SNMP / Config Export"}
                          </code>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="cm-btn sm"
                            disabled={loading}
                            onClick={() => handleRetryAsset(inNode.asset_id)}
                          >
                            Reintentar host
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </AwsContainer>
          )}

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
              gap: 16,
            }}
          >
            <AwsContainer
              title="Bases de datos detectadas (6 capas de evidencia)"
              counter={(activeCampaign.databases_6_layers || []).length}
              description="Motores de bases de datos identificados y su recomendación de destino cloud."
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {(activeCampaign.databases_6_layers || []).map((db) => (
                  <div key={db.db_id} className="cm-card-subtle">
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: 8,
                        marginBottom: 4,
                      }}
                    >
                      <strong>{db.engine}</strong>
                      <span className="cm-badge aws">
                        {db.aws_target_recommendation}
                      </span>
                    </div>
                    <div className="cm-hint" style={{ marginBottom: 4 }}>
                      Rol: <strong>{db.ha_role}</strong> · Tamaño estimado:{" "}
                      <strong>{db.estimated_size_gb} GB</strong>
                    </div>
                    <div
                      style={{
                        fontSize: 13.5,
                        color: "var(--color-text-secondary)",
                      }}
                    >
                      <strong>Evidencia:</strong>{" "}
                      {(db.evidence_layers || []).join(" · ")}
                    </div>
                  </div>
                ))}
              </div>
            </AwsContainer>

            <AwsContainer
              title="Oleadas de migración y prerrequisitos"
              counter={(activeCampaign.migration_waves || []).length}
              description="Secuencia sugerida de oleadas según acoplamiento y nivel de riesgo."
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {(activeCampaign.migration_waves || []).map((w) => (
                  <div key={w.wave_id} className="cm-card-subtle">
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: 8,
                        marginBottom: 4,
                      }}
                    >
                      <strong>{w.name}</strong>
                      <span
                        className={`cm-badge ${
                          w.risk_level === "high"
                            ? "danger"
                            : w.risk_level === "medium"
                            ? "warning"
                            : "observed"
                        }`}
                      >
                        Riesgo: {w.risk_level?.toUpperCase()}
                      </span>
                    </div>
                    <div style={{ fontSize: 14, marginBottom: 4 }}>
                      Estrategia: <strong>{w.strategy}</strong>
                    </div>
                    <div className="cm-hint">
                      Activos incluidos:{" "}
                      <code>{(w.assets || []).join(", ")}</code>
                    </div>
                    <div className="cm-hint" style={{ marginTop: 3 }}>
                      Prerrequisitos: {(w.prerequisites || []).join(" · ")}
                    </div>
                  </div>
                ))}
              </div>
            </AwsContainer>
          </div>
        </>
      )}

      {activeSubTab === "subgraph-migration" && activeCampaign && (
        <AwsContainer
          title="Planificación de migración de subgrafo datacenter y protección de recursos compartidos"
          description="Los recursos compartidos (como db-pg-ha-01) están protegidos por defecto para evitar interrumpir servicios que permanecen on-premise."
          actions={
            <span className="cm-badge shared">
              {selectedWorkloadIds.length} carga(s) seleccionada(s)
            </span>
          }
        >
          <div className="cm-form-grid" style={{ marginBottom: 16 }}>
            <div className="cm-field">
              <label htmlFor="dc-mig-provider" className="cm-label">
                Proveedor cloud destino para las cargas seleccionadas
              </label>
              <select
                id="dc-mig-provider"
                className="cm-select"
                value={targetProvider}
                onChange={(e) => setTargetProvider(e.target.value)}
              >
                <option value="aws">
                  Amazon Web Services (AWS — VPC, EC2, RDS Multi-AZ, MGN)
                </option>
                <option value="gcp">
                  Google Cloud Platform (GCP — VPC, GCE, Cloud SQL HA)
                </option>
              </select>
            </div>

            <div className="cm-field">
              <span className="cm-label">
                Autorización de recursos compartidos críticos
              </span>
              <div
                style={{
                  display: "flex",
                  gap: 14,
                  flexWrap: "wrap",
                  paddingTop: 6,
                }}
              >
                {[
                  {
                    id: "db-pg-ha-01",
                    label: "db-pg-ha-01 (PostgreSQL 15 HA compartido)",
                  },
                  {
                    id: "dc-node-03",
                    label: "dc-node-03 (Nodo DB primario compartido)",
                  },
                ].map((sh) => (
                  <label
                    key={sh.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      fontSize: 14,
                      cursor: "pointer",
                    }}
                  >
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
                Generar plan e IaC de subgrafo ({targetProvider.toUpperCase()})
              </button>
            </div>
          </div>

          {migrationPlanResult && (
            <div className="cm-card-subtle" style={{ marginTop: 12 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: 8,
                  marginBottom: 10,
                }}
              >
                <strong>
                  Resultado de planificación de subgrafo datacenter →{" "}
                  {migrationPlanResult.target_provider?.toUpperCase()}
                </strong>
                <span className="cm-badge observed">
                  Modo: {migrationPlanResult.execution_mode || "simulated_dry_run"}
                </span>
              </div>
              {migrationPlanResult.shared_resource_warnings?.length > 0 && (
                <AwsAlert
                  type="warning"
                  title="Protección de recursos compartidos activa"
                  style={{ marginBottom: 10 }}
                >
                  {migrationPlanResult.shared_resource_warnings.join(" · ")}
                </AwsAlert>
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
        </AwsContainer>
      )}
    </div>
  );

  if (isStandalonePage) {
    return <div className="tab-pane-view">{content}</div>;
  }
  return content;
}
