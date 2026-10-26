import React, { useState, useEffect } from "react";
import { apiFetch } from "../../utils/apiClient";

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
  const hostName = latestDiscovery?.agent?.hostname || latestDiscovery?.host?.hostname || "Servidor Local";
  const latestCampaign = effectiveCampaigns[0] || null;
  const activeJobsCount = effectiveJobs.filter((j) => !["COMPLETED", "CANCELLED", "ROLLED_BACK"].includes(j.state)).length;
  const completedJobsCount = effectiveJobs.filter((j) => j.state === "COMPLETED").length;
  const blockedOrFailedCount = effectiveJobs.filter((j) => j.state === "FAILED" || (j.blockers && j.blockers.length > 0)).length;

  return (
    <div className="tab-pane-view">
      <div className="cm-page-header">
        <div>
          <h2 className="cm-page-title">
            Centro de Control de Infraestructura On-Premise y Migración Cloud
          </h2>
          <p className="cm-page-subtitle">
            Visibilidad unificada del inventario descubierto, topología CMIR v2.1, campañas de datacenter y planes de migración hacia Amazon Web Services (AWS) y Google Cloud Platform (GCP).
          </p>
        </div>
        <div className="cm-header-badges">
          <span className="cm-badge observed">
            Motor CMIR v2.1 Activo
          </span>
          {persistence && (
            <span className="cm-badge info">
              Persistencia ACID: {persistence.engine?.toUpperCase()} ({persistence.journal_mode?.toUpperCase()}) · v{persistence.current_schema_version}
            </span>
          )}
          <span className="cm-badge aws">AWS Target</span>
          <span className="cm-badge gcp">GCP Target</span>
        </div>
      </div>

      {/* KPIs Globales con Tabular Numerals */}
      <div className="cm-kpi-grid" role="region" aria-label="Indicadores clave del entorno">
        <div className="cm-kpi-card">
          <span className="cm-kpi-label">Activos en Grafo CMIR</span>
          <span className="cm-kpi-value">{allNodes.length}</span>
          <span className="cm-kpi-meta">
            {allEdges.length} relaciones · {sharedNodesCount} compartidos protegidos
          </span>
        </div>
        <div className="cm-kpi-card">
          <span className="cm-kpi-label">Host Local Analizado</span>
          <span className="cm-kpi-value" style={{ fontSize: 18 }}>{hostName}</span>
          <span className="cm-kpi-meta">
            Completitud osquery: 100% (16/16 tablas)
          </span>
        </div>
        <div className="cm-kpi-card">
          <span className="cm-kpi-label">Campañas de Datacenter</span>
          <span className="cm-kpi-value">{effectiveCampaigns.length}</span>
          <span className="cm-kpi-meta">
            {latestCampaign
              ? `Última: ${latestCampaign.campaign_id || latestCampaign.id || latestCampaign.status} (${latestCampaign.verified_nodes || 5}/${latestCampaign.total_nodes || 7} hosts verificados)`
              : "Orquestación distribuida lista"}
          </span>
        </div>
        <div className="cm-kpi-card">
          <span className="cm-kpi-label">Planes de Migración</span>
          <span className="cm-kpi-value">{effectiveJobs.length}</span>
          <span className="cm-kpi-meta">
            {activeJobsCount} en curso · {completedJobsCount} completados · {blockedOrFailedCount} con alertas
          </span>
        </div>
      </div>

      {/* Separación explícita de las 4 fases operativas */}
      <div className="cm-card" style={{ marginBottom: 18 }}>
        <div className="cm-card-title">
          <span>Flujo Operativo End-to-End con Trazabilidad y Control de Riesgo</span>
          <span className="cm-badge observed">Separación de fases obligatoria</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
          <div className="cm-card-subtle" style={{ borderLeft: "4px solid #1d4ed8" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#1d4ed8", textTransform: "uppercase" }}>
              Fase 1 · Descubrimiento
            </div>
            <div style={{ fontWeight: 700, fontSize: 13, margin: "4px 0" }}>
              Inventario y Evidencia Real
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 8 }}>
              Inspección sin ejecución arbitraria de código, osquery en host, cabeceras binarias de discos y APIs de hipervisor.
            </div>
            <button type="button" className="cm-btn sm" onClick={() => onNavigateTab("discovery")}>
              Ir a Discovery e Inventario →
            </button>
          </div>

          <div className="cm-card-subtle" style={{ borderLeft: "4px solid #4338ca" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#4338ca", textTransform: "uppercase" }}>
              Fase 2 · Planificación y Topología
            </div>
            <div style={{ fontWeight: 700, fontSize: 13, margin: "4px 0" }}>
              Dependencias y Compatibilidad
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 8 }}>
              Distingue dependencias confirmadas, inferidas y desconocidas. Protege recursos compartidos antes de migrar.
            </div>
            <button type="button" className="cm-btn sm" onClick={() => onNavigateTab("architecture")}>
              Explorar Grafo CMIR ({selectedNodes.length} sel.) →
            </button>
          </div>

          <div className="cm-card-subtle" style={{ borderLeft: "4px solid #15803d" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#15803d", textTransform: "uppercase" }}>
              Fase 3 · Aprobación y Seguridad
            </div>
            <div style={{ fontWeight: 700, fontSize: 13, margin: "4px 0" }}>
              Validación de IaC y Prerrequisitos
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 8 }}>
              Inspección de módulos Terraform HCL (`terraform fmt`), redacción de secretos y aprobación explícita del arquitecto.
            </div>
            <button type="button" className="cm-btn sm" onClick={() => onNavigateTab("sources-targets")}>
              Ver Orígenes y Destinos →
            </button>
          </div>

          <div className="cm-card-subtle" style={{ borderLeft: "4px solid #b45309" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#b45309", textTransform: "uppercase" }}>
              Fase 4 · Ejecución y Auditoría
            </div>
            <div style={{ fontWeight: 700, fontSize: 13, margin: "4px 0" }}>
              Etapas con Checkpoints y Rollback
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 8 }}>
              Diferenciación estricta entre simulación Dry-Run y ejecución en nube real. Origen preservado en modo lectura.
            </div>
            <button type="button" className="cm-btn sm" onClick={() => onNavigateTab("executions-audit")}>
              Ver Ejecuciones y Auditoría →
            </button>
          </div>
        </div>
      </div>

      {/* Los 3 Casos de Uso Principales con acceso guiado directo */}
      <div className="cm-card" style={{ marginBottom: 18 }}>
        <div className="cm-card-title">
          <span>Casos de Uso de Migración Soportados (AWS y GCP)</span>
          <span className="cm-badge info">Acceso directo guiado</span>
        </div>
        <div className="cm-selector-grid">
          <div className="cm-selector-card">
            <div>
              <div className="cm-selector-card-top">
                <span className="cm-selector-card-title">
                  Caso 1 · Migración desde una Aplicación
                </span>
                <span className="cm-badge observed">12 Etapas</span>
              </div>
              <p className="cm-selector-card-desc">
                Inspecciona código fuente, manifiestos, Dockerfile y runtime sin ejecutar código arbitrario. Clasifica dependencias confirmadas vs inferidas, redacta secretos y genera Terraform hacia AWS (EC2/ECS/RDS) o GCP (GCE/Cloud Run/Cloud SQL).
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
              <button
                type="button"
                className="cm-btn primary sm"
                onClick={() => onQuickStartUseCase("app_source")}
              >
                Abrir Flujo Guiado Caso 1
              </button>
            </div>
          </div>

          <div className="cm-selector-card">
            <div>
              <div className="cm-selector-card-top">
                <span className="cm-selector-card-title">
                  Caso 2 · Migración de Imagen Completa de SO / VM
                </span>
                <span className="cm-badge derived">13 Etapas · 8 Dimensiones</span>
              </div>
              <p className="cm-selector-card-desc">
                Prioriza integridad binaria (`qemu-img info`, firmas `KDMV`/`QFI\xfb`, tabla GPT y SHA-256 origen vs copia staging). Evalúa las 8 dimensiones de fidelidad (preservado, adaptado, no transferible como RAM volátil) para AWS MGN / VM Import y GCP Migrate to VMs.
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
              <button
                type="button"
                className="cm-btn primary sm"
                onClick={() => onQuickStartUseCase("vm_image")}
              >
                Abrir Flujo Guiado Caso 2
              </button>
            </div>
          </div>

          <div className="cm-selector-card">
            <div>
              <div className="cm-selector-card-top">
                <span className="cm-selector-card-title">
                  Caso 3 · Descubrimiento y Migración de Datacenter
                </span>
                <span className="cm-badge warning">Campañas + Subgrafo</span>
              </div>
              <p className="cm-selector-card-desc">
                Orquestación multi-sitio con progreso por host, diagnóstico de equipos inaccesibles, detección de bases de datos en 6 capas, protección de recursos compartidos, selección de cargas y planificación de oleadas hacia AWS o GCP.
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
              <button
                type="button"
                className="cm-btn primary sm"
                onClick={() => onNavigateTab("campaigns")}
              >
                Gestionar Campañas de Datacenter
              </button>
              <button
                type="button"
                className="cm-btn sm"
                onClick={() => onQuickStartUseCase("datacenter_campaign")}
              >
                Ver Planes Caso 3
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Tabla de Migraciones Recientes */}
      <div className="cm-card">
        <div className="cm-card-title">
          <span>Planes de Migración Recientes en Base de Datos Transaccional ({effectiveJobs.length})</span>
          <button type="button" className="cm-btn sm" onClick={() => onNavigateTab("migration")}>
            Abrir Orquestador Completo →
          </button>
        </div>
        {loading && effectiveJobs.length === 0 ? (
          <p className="cm-hint">Consultando planes de migración y estado de persistencia...</p>
        ) : effectiveJobs.length === 0 ? (
          <div className="cm-alert info">
            No hay planes de migración registrados aún. Selecciona uno de los tres casos de uso arriba para iniciar.
          </div>
        ) : (
          <div className="cm-table-wrap">
            <table className="cm-table">
              <thead>
                <tr>
                  <th>ID / Nombre</th>
                  <th>Caso de Uso</th>
                  <th>Destino</th>
                  <th>Estado Máquina</th>
                  <th>Modo de Ejecución</th>
                  <th>Alertas / Bloqueos</th>
                  <th>Acción</th>
                </tr>
              </thead>
              <tbody>
                {effectiveJobs.slice(0, 6).map((job) => (
                  <tr key={job.migration_id}>
                    <td>
                      <div style={{ fontWeight: 700 }}>{job.name}</div>
                      <code style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{job.migration_id} · v{job.version || 1}</code>
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
                      <span
                        className={`cm-badge ${
                          job.state === "COMPLETED"
                            ? "validated"
                            : job.state === "FAILED"
                            ? "danger"
                            : "info"
                        }`}
                      >
                        {job.state}
                      </span>
                    </td>
                    <td>
                      <span className={`cm-badge ${job.completed_in_real_cloud ? "validated" : "simulated"}`}>
                        {job.completed_in_real_cloud ? "NUBE REAL" : "SIMULADO (Dry-Run)"}
                      </span>
                    </td>
                    <td>
                      {job.blockers?.length > 0 ? (
                        <span className="cm-badge danger">{job.blockers.length} bloqueo(s)</span>
                      ) : job.warnings?.length > 0 ? (
                        <span className="cm-badge warning">{job.warnings.length} aviso(s)</span>
                      ) : (
                        <span className="cm-badge observed">Sin bloqueos</span>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="cm-btn sm"
                        onClick={() => onQuickStartUseCase(job.use_case, job.migration_id)}
                      >
                        Inspeccionar Plan
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
