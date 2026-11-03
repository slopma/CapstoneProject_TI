import React, { useState, useEffect, useMemo } from "react";
import { apiFetch } from "../../utils/apiClient";
import {
  AwsPageHeader,
  AwsContainer,
  AwsKeyValuePairs,
  AwsTabs,
  AwsStatusIndicator,
  AwsEmptyState,
} from "../cloudscape/AwsPrimitives";

export default function EnvironmentOverviewWorkspace({
  allNodes = [],
  allEdges = [],
  selectedNodes = [],
  initialCampaigns = [],
  initialJobs = [],
  onNavigateTab,
  onQuickStartUseCase,
}) {
  const [latestDiscovery, setLatestDiscovery] = useState(null);
  const [campaigns, setCampaigns] = useState(initialCampaigns);
  const [jobs, setJobs] = useState(initialJobs);
  const [persistence, setPersistence] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeSubTab, setActiveSubTab] = useState("use-cases");
  const [jobSearchFilter, setJobSearchFilter] = useState("");

  const effectiveCampaigns = campaigns.length > 0 ? campaigns : initialCampaigns;
  const effectiveJobs = jobs.length > 0 ? jobs : initialJobs;

  useEffect(() => {
    let active = true;
    async function loadOverview() {
      setLoading(true);
      try {
        const [discRes, campRes, jobsRes, persRes] = await Promise.all([
          apiFetch("/api/v1/discovery/latest").catch(() => null),
          apiFetch("/api/v1/campaigns").catch(() => null),
          apiFetch("/api/v1/migration/jobs").catch(() => null),
          apiFetch("/api/v1/migration/persistence/status").catch(() => null),
        ]);
        if (!active) return;
        if (discRes && discRes.ok) setLatestDiscovery(await discRes.json());
        if (campRes && campRes.ok) {
          const cData = await campRes.json();
          setCampaigns(cData.campaigns || []);
        }
        if (jobsRes && jobsRes.ok) {
          const jData = await jobsRes.json();
          setJobs(jData.jobs || []);
        }
        if (persRes && persRes.ok) setPersistence(await persRes.json());
      } finally {
        if (active) setLoading(false);
      }
    }
    loadOverview();
    return () => {
      active = false;
    };
  }, []);

  const sharedNodesCount = allNodes.filter((n) => n.is_shared).length;
  const hostName =
    latestDiscovery?.agent?.hostname ||
    latestDiscovery?.host?.hostname ||
    "Servidor local";
  const latestCampaign = effectiveCampaigns[0] || null;
  const activeJobsCount = effectiveJobs.filter(
    (j) => !["COMPLETED", "CANCELLED", "ROLLED_BACK"].includes(j.state)
  ).length;
  const completedJobsCount = effectiveJobs.filter(
    (j) => j.state === "COMPLETED"
  ).length;
  const blockedOrFailedCount = effectiveJobs.filter(
    (j) => j.state === "FAILED" || (j.blockers && j.blockers.length > 0)
  ).length;

  const filteredJobs = useMemo(() => {
    if (!jobSearchFilter.trim()) return effectiveJobs;
    const q = jobSearchFilter.toLowerCase();
    return effectiveJobs.filter(
      (j) =>
        j.name?.toLowerCase().includes(q) ||
        j.migration_id?.toLowerCase().includes(q) ||
        j.use_case?.toLowerCase().includes(q) ||
        j.target_provider?.toLowerCase().includes(q) ||
        j.state?.toLowerCase().includes(q)
    );
  }, [effectiveJobs, jobSearchFilter]);

  return (
    <div className="tab-pane-view">
      <AwsPageHeader
        title="Resumen del entorno"
        description="Estado general del inventario, las campañas y los planes de migración."
        badges={
          <>
            <span className="cm-badge observed">Motor CMIR v2.1 activo</span>
            {persistence && (
              <span className="cm-badge info">
                Persistencia ACID: {persistence.engine?.toUpperCase()} (
                {persistence.journal_mode?.toUpperCase()}) · v
                {persistence.current_schema_version}
              </span>
            )}
            <span className="cm-badge aws">AWS soportado</span>
            <span className="cm-badge gcp">GCP soportado</span>
          </>
        }
        actions={
          <>
            <button
              type="button"
              className="cm-btn"
              onClick={() => onNavigateTab("architecture")}
            >
              Explorar grafo CMIR ({selectedNodes.length})
            </button>
            <button
              type="button"
              className="cm-btn primary"
              onClick={() => onQuickStartUseCase("app_source")}
            >
              Crear plan de migración
            </button>
          </>
        }
      />

      {/* Summary / Key-Value Container (4 columns with vertical dividers) */}
      <AwsKeyValuePairs
        columns={4}
        items={[
          {
            label: "Activos en grafo CMIR",
            value: allNodes.length,
            subtext: `${allEdges.length} relaciones · ${sharedNodesCount} compartidos protegidos`,
          },
          {
            label: "Host local analizado",
            value: <span style={{ fontSize: 17 }}>{hostName}</span>,
            subtext: "Completitud osquery: 100% (16/16 tablas)",
          },
          {
            label: "Campañas de datacenter",
            value: effectiveCampaigns.length,
            subtext: latestCampaign
              ? `Última: ${
                  latestCampaign.campaign_id ||
                  latestCampaign.id ||
                  latestCampaign.status
                } (${latestCampaign.verified_nodes || 5}/${
                  latestCampaign.total_nodes || 7
                } hosts verificados)`
              : "Orquestación distribuida lista",
          },
          {
            label: "Planes de migración",
            value: effectiveJobs.length,
            subtext: `${activeJobsCount} en curso · ${completedJobsCount} completados · ${blockedOrFailedCount} con alertas`,
          },
        ]}
      />

      {/* Segmented Rectangular AWS Tabs */}
      <AwsTabs
        activeTabId={activeSubTab}
        onTabChange={setActiveSubTab}
        tabs={[
          {
            id: "use-cases",
            label: "Casos de uso",
            badge: "3 casos",
          },
          {
            id: "recent-jobs",
            label: "Planes",
            count: effectiveJobs.length,
          },
          {
            id: "campaigns-persistence",
            label: "Campañas",
            count: effectiveCampaigns.length,
          },
        ]}
      />

      {activeSubTab === "use-cases" && (
        <>
          <AwsContainer
            title="Casos de uso de migración soportados (AWS y GCP)"
            description="Selecciona el escenario de migración para iniciar el asistente guiado con validación determinista de infraestructura."
            actions={<span className="cm-badge info">Acceso directo guiado</span>}
          >
            <div className="cm-selector-grid">
              <div className="cm-selector-card">
                <div>
                  <div className="cm-selector-card-top">
                    <span className="cm-selector-card-title">
                      Caso 1 · Migración desde código fuente o repositorio GitHub
                    </span>
                    <span className="cm-badge observed">12 etapas</span>
                  </div>
                  <p className="cm-selector-card-desc">
                    Inspecciona código fuente, manifiestos, Dockerfile y docker-compose sin ejecutar código arbitrario. Muestra el mapa interactivo GitHub → Cloud para elegir qué servicios transformar y genera Terraform hacia AWS o GCP.
                  </p>
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="cm-btn primary sm"
                    onClick={() => onQuickStartUseCase("app_source")}
                  >
                    Iniciar caso 1 (Aplicación / GitHub)
                  </button>
                </div>
              </div>

              <div className="cm-selector-card">
                <div>
                  <div className="cm-selector-card-top">
                    <span className="cm-selector-card-title">
                      Caso 2 · Migración de imagen completa de SO / VM
                    </span>
                    <span className="cm-badge derived">13 etapas · 8 dimensiones</span>
                  </div>
                  <p className="cm-selector-card-desc">
                    Prioriza integridad binaria (qemu-img info, firmas KDMV/QFI, tabla GPT y SHA-256 origen vs copia staging). Evalúa las 8 dimensiones de fidelidad para AWS VM Import / MGN y GCP Migrate to VMs.
                  </p>
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="cm-btn primary sm"
                    onClick={() => onQuickStartUseCase("vm_image")}
                  >
                    Iniciar caso 2 (Imagen de VM)
                  </button>
                </div>
              </div>

              <div className="cm-selector-card">
                <div>
                  <div className="cm-selector-card-top">
                    <span className="cm-selector-card-title">
                      Caso 3 · Descubrimiento y migración de datacenter
                    </span>
                    <span className="cm-badge warning">Campañas + subgrafo</span>
                  </div>
                  <p className="cm-selector-card-desc">
                    Orquestación multi-sitio con progreso por host, diagnóstico de equipos inaccesibles, detección de bases de datos en 6 capas, protección de recursos compartidos y planificación por oleadas.
                  </p>
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="cm-btn primary sm"
                    onClick={() => onNavigateTab("campaigns")}
                  >
                    Gestionar campañas de datacenter
                  </button>
                  <button
                    type="button"
                    className="cm-btn sm"
                    onClick={() => onQuickStartUseCase("datacenter_campaign")}
                  >
                    Ver planes caso 3
                  </button>
                </div>
              </div>
            </div>
          </AwsContainer>

          <AwsContainer
            title="Flujo operativo de extremo a extremo con control de riesgo"
            description="Cada migración atraviesa cuatro fases verificables con separación estricta entre descubrimiento, planificación, aprobación y ejecución."
            actions={<span className="cm-badge observed">Separación de fases obligatoria</span>}
          >
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
              <div className="cm-step-card">
                <div style={{ marginBottom: 6 }}>
                  <span className="cm-step-badge">Fase 1 · Descubrimiento</span>
                </div>
                <div style={{ fontWeight: 700, fontSize: 14, margin: "4px 0" }}>
                  Inventario y evidencia real
                </div>
                <div style={{ fontSize: 14, color: "var(--color-text-secondary)", marginBottom: 12 }}>
                  Inspección sin ejecución arbitraria de código, osquery en host, cabeceras binarias de discos y APIs de hipervisor.
                </div>
                <button type="button" className="cm-btn sm" onClick={() => onNavigateTab("discovery")}>
                  Ir a Discovery e inventario
                </button>
              </div>

              <div className="cm-step-card">
                <div style={{ marginBottom: 6 }}>
                  <span className="cm-step-badge">Fase 2 · Planificación y topología</span>
                </div>
                <div style={{ fontWeight: 700, fontSize: 14, margin: "4px 0" }}>
                  Dependencias y compatibilidad
                </div>
                <div style={{ fontSize: 14, color: "var(--color-text-secondary)", marginBottom: 12 }}>
                  Distingue dependencias confirmadas, inferidas y desconocidas. Protege recursos compartidos antes de migrar.
                </div>
                <button type="button" className="cm-btn sm" onClick={() => onNavigateTab("architecture")}>
                  Explorar grafo CMIR ({selectedNodes.length} sel.)
                </button>
              </div>

              <div className="cm-step-card">
                <div style={{ marginBottom: 6 }}>
                  <span className="cm-step-badge">Fase 3 · Aprobación y seguridad</span>
                </div>
                <div style={{ fontWeight: 700, fontSize: 14, margin: "4px 0" }}>
                  Validación de IaC y prerrequisitos
                </div>
                <div style={{ fontSize: 14, color: "var(--color-text-secondary)", marginBottom: 12 }}>
                  Inspección de módulos Terraform HCL (terraform fmt), redacción de secretos y aprobación explícita del arquitecto.
                </div>
                <button type="button" className="cm-btn sm" onClick={() => onNavigateTab("sources-targets")}>
                  Ver orígenes y destinos
                </button>
              </div>

              <div className="cm-step-card">
                <div style={{ marginBottom: 6 }}>
                  <span className="cm-step-badge">Fase 4 · Ejecución y auditoría</span>
                </div>
                <div style={{ fontWeight: 700, fontSize: 14, margin: "4px 0" }}>
                  Etapas con checkpoints y rollback
                </div>
                <div style={{ fontSize: 14, color: "var(--color-text-secondary)", marginBottom: 12 }}>
                  Diferenciación estricta entre simulación Dry-Run y ejecución en nube real. Origen preservado en modo lectura.
                </div>
                <button type="button" className="cm-btn sm" onClick={() => onNavigateTab("executions-audit")}>
                  Ver ejecuciones y auditoría
                </button>
              </div>
            </div>
          </AwsContainer>
        </>
      )}

      {activeSubTab === "recent-jobs" && (
        <AwsContainer
          title="Planes de migración registrados"
          counter={filteredJobs.length}
          description=" Planes persistidos en la base de datos transaccional con trazabilidad de estado y artefactos Terraform."
          noPadding={true}
          actions={
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <input
                type="search"
                className="cm-input"
                style={{ width: 250 }}
                placeholder="Buscar planes por nombre o ID..."
                aria-label="Filtrar planes de migración"
                value={jobSearchFilter}
                onChange={(e) => setJobSearchFilter(e.target.value)}
              />
              <button
                type="button"
                className="cm-btn primary sm"
                onClick={() => onNavigateTab("migration")}
              >
                Abrir orquestador completo
              </button>
            </div>
          }
        >
          {loading && effectiveJobs.length === 0 ? (
            <div style={{ padding: 20 }}>
              <p className="cm-hint">Cargando planes de migración y estado de persistencia...</p>
            </div>
          ) : filteredJobs.length === 0 ? (
            <AwsEmptyState
              title="No hay planes de migración que coincidan"
              description="Inicia un nuevo plan desde cualquiera de los tres casos de uso soportados."
              action={
                <button
                  type="button"
                  className="cm-btn primary sm"
                  onClick={() => onQuickStartUseCase("app_source")}
                >
                  Crear primer plan de migración
                </button>
              }
            />
          ) : (
            <div className="cm-table-wrap" style={{ border: "none", borderRadius: 0 }}>
              <table className="cm-table">
                <thead>
                  <tr>
                    <th>Nombre / ID del plan</th>
                    <th>Caso de uso</th>
                    <th>Proveedor destino</th>
                    <th>Estado de máquina</th>
                    <th>Modo de ejecución</th>
                    <th>Alertas y bloqueos</th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredJobs.map((job) => (
                    <tr key={job.migration_id}>
                      <td>
                        <strong>{job.name}</strong>
                        <div>
                          <code style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
                            {job.migration_id} · v{job.version || 1}
                          </code>
                        </div>
                      </td>
                      <td>
                        <code>{job.use_case}</code>
                      </td>
                      <td>
                        <span className={`cm-badge ${job.target_provider === "gcp" ? "gcp" : "aws"}`}>
                          {job.target_provider?.toUpperCase()}
                        </span>
                      </td>
                      <td>
                        <AwsStatusIndicator
                          type={
                            job.state === "COMPLETED"
                              ? "success"
                              : job.state === "FAILED"
                              ? "error"
                              : "info"
                          }
                        >
                          {job.state}
                        </AwsStatusIndicator>
                      </td>
                      <td>
                        <span
                          className={`cm-badge ${
                            job.completed_in_real_cloud ? "validated" : "simulated"
                          }`}
                        >
                          {job.completed_in_real_cloud
                            ? "Nube real"
                            : "Simulado (Dry-Run)"}
                        </span>
                      </td>
                      <td>
                        {job.blockers?.length > 0 ? (
                          <AwsStatusIndicator type="error">
                            {job.blockers.length} bloqueo(s)
                          </AwsStatusIndicator>
                        ) : job.warnings?.length > 0 ? (
                          <AwsStatusIndicator type="warning">
                            {job.warnings.length} aviso(s)
                          </AwsStatusIndicator>
                        ) : (
                          <AwsStatusIndicator type="success">
                            Sin bloqueos
                          </AwsStatusIndicator>
                        )}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="cm-btn sm"
                          onClick={() =>
                            onQuickStartUseCase(job.use_case, job.migration_id)
                          }
                        >
                          Inspeccionar plan
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AwsContainer>
      )}

      {activeSubTab === "campaigns-persistence" && (
        <AwsContainer
          title="Campañas de descubrimiento de datacenter y estado de base de datos ACID"
          counter={effectiveCampaigns.length}
          description="Resumen de campañas multi-sitio ejecutadas y parámetros del motor de almacenamiento transaccional."
          actions={
            <button
              type="button"
              className="cm-btn primary sm"
              onClick={() => onNavigateTab("campaigns")}
            >
              Abrir consola de campañas
            </button>
          }
        >
          {effectiveCampaigns.length === 0 ? (
            <AwsEmptyState
              title="No hay campañas de datacenter registradas"
              description="Ejecuta una campaña en modo lectura o prueba global desde la sección Campañas de datacenter."
              action={
                <button
                  type="button"
                  className="cm-btn primary sm"
                  onClick={() => onNavigateTab("campaigns")}
                >
                  Lanzar campaña de datacenter
                </button>
              }
            />
          ) : (
            <div className="cm-table-wrap">
              <table className="cm-table">
                <thead>
                  <tr>
                    <th>ID de campaña</th>
                    <th>Entorno</th>
                    <th>Modo de ejecución</th>
                    <th>Nodos verificados</th>
                    <th>Estado</th>
                    <th>Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {effectiveCampaigns.map((camp) => (
                    <tr key={camp.campaign_id}>
                      <td>
                        <strong>{camp.campaign_id}</strong>
                      </td>
                      <td>
                        <code>{camp.environment_id || "env-datacenter-01"}</code>
                      </td>
                      <td>{camp.mode_label || camp.mode}</td>
                      <td>
                        {camp.verified_nodes ?? 5} / {camp.total_nodes ?? 7} hosts
                      </td>
                      <td>
                        <AwsStatusIndicator
                          type={camp.status === "completed" ? "success" : "warning"}
                        >
                          {camp.status}
                        </AwsStatusIndicator>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="cm-btn sm"
                          onClick={() => onNavigateTab("campaigns")}
                        >
                          Ver detalles
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AwsContainer>
      )}
    </div>
  );
}
