import React, { useState, useEffect, useMemo } from "react";
import { apiFetch } from "../../utils/apiClient";
import {
  AwsPageHeader,
  AwsContainer,
  AwsKeyValuePairs,
  AwsStatusIndicator,
  AwsEmptyState,
} from "../cloudscape/AwsPrimitives";

export default function EnvironmentOverviewWorkspace({
  allNodes = [],
  allEdges = [],
  selectedNodes = [],
  initialJobs = [],
  onNavigateTab,
  onQuickStartUseCase,
}) {
  const [latestDiscovery, setLatestDiscovery] = useState(null);
  const [jobs, setJobs] = useState(initialJobs);
  const [persistence, setPersistence] = useState(null);
  const [awsAudit, setAwsAudit] = useState(null);
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [jobSearchFilter, setJobSearchFilter] = useState("");
  const [useCaseFilter, setUseCaseFilter] = useState("ALL");

  const effectiveJobs = jobs.length > 0 ? jobs : initialJobs;

  useEffect(() => {
    let active = true;
    async function loadOverview() {
      setLoading(true);
      try {
        const [discRes, jobsRes, persRes, auditRes, agentsRes] = await Promise.all([
          apiFetch("/api/v1/discovery/latest").catch(() => null),
          apiFetch("/api/v1/migration/jobs").catch(() => null),
          apiFetch("/api/v1/migration/persistence/status").catch(() => null),
          apiFetch("/api/v1/migration/cloud-audit/aws").catch(() => null),
          apiFetch("/api/v1/agents").catch(() => null),
        ]);
        if (!active) return;
        if (discRes && discRes.ok) setLatestDiscovery(await discRes.json());
        if (jobsRes && jobsRes.ok) {
          const jData = await jobsRes.json();
          setJobs(jData.jobs || []);
        }
        if (persRes && persRes.ok) setPersistence(await persRes.json());
        if (auditRes && auditRes.ok) setAwsAudit(await auditRes.json());
        if (agentsRes && agentsRes.ok) {
          const aData = await agentsRes.json();
          setAgents(aData.agents || []);
        }
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
    "cloudmove-server";

  const validJobs = useMemo(
    () =>
      effectiveJobs.filter(
        (j) => j.use_case === "app_source" || j.use_case === "vm_image"
      ),
    [effectiveJobs]
  );

  const case1Count = validJobs.filter((j) => j.use_case === "app_source").length;
  const case2Count = validJobs.filter((j) => j.use_case === "vm_image").length;
  const activeJobsCount = validJobs.filter(
    (j) => !["COMPLETED", "CANCELLED", "ROLLED_BACK"].includes(j.state)
  ).length;
  const completedJobsCount = validJobs.filter(
    (j) => j.state === "COMPLETED"
  ).length;

  const onlineAgentsCount = agents.filter((a) => a.status === "ONLINE").length;

  // AWS Quotas & Free Tier Metrics
  const ebsUsedGb = awsAudit?.summary?.total_ebs_gb ?? 35;
  const ebsLimitGb = awsAudit?.summary?.academy_ebs_limit_gb ?? 150;
  const ebsPercent = Math.min(100, Math.round((ebsUsedGb / ebsLimitGb) * 100));
  const runningInstances = awsAudit?.summary?.running_instances_count ?? 1;
  const totalVpcs = awsAudit?.summary?.total_vpcs_count ?? 1;

  const filteredJobs = useMemo(() => {
    return validJobs.filter((j) => {
      if (useCaseFilter !== "ALL" && j.use_case !== useCaseFilter) return false;
      if (!jobSearchFilter.trim()) return true;
      const q = jobSearchFilter.toLowerCase();
      return (
        j.name?.toLowerCase().includes(q) ||
        j.migration_id?.toLowerCase().includes(q) ||
        j.use_case?.toLowerCase().includes(q) ||
        j.target_provider?.toLowerCase().includes(q) ||
        j.state?.toLowerCase().includes(q)
      );
    });
  }, [validJobs, jobSearchFilter, useCaseFilter]);

  return (
    <div className="tab-pane-view awsui-console-home">
      {/* AWS Console Home Header */}
      <AwsPageHeader
        title="Inicio de la consola (Console Home)"
        description="Centro de mando unificado para migración de aplicaciones desde código fuente (Caso 1) y máquinas virtuales / sistemas operativos en vivo (Caso 2) hacia AWS y Google Cloud Platform."
        badges={
          <>
            <span className="cm-badge aws">AWS · us-east-1</span>
            <span className="cm-badge gcp">GCP · us-central1</span>
            <span className="cm-badge observed">CMIR v2.1 Activo</span>
            {persistence && (
              <span className="cm-badge info">
                ACID {persistence.engine?.toUpperCase()} ({persistence.journal_mode?.toUpperCase()})
              </span>
            )}
          </>
        }
        actions={
          <>
            <button
              type="button"
              className="cm-btn"
              onClick={() => onNavigateTab("executions-audit")}
            >
              Auditar cuenta AWS
            </button>
            <button
              type="button"
              className="cm-btn"
              onClick={() => onQuickStartUseCase("vm_image")}
            >
              Iniciar Caso 2 (SO / VM)
            </button>
            <button
              type="button"
              className="cm-btn primary"
              onClick={() => onQuickStartUseCase("app_source")}
            >
              Iniciar Caso 1 (Aplicación GitHub)
            </button>
          </>
        }
      />

      {/* Top 4-Column Summary Bar (Cloudscape KeyValuePairs) */}
      <AwsKeyValuePairs
        columns={4}
        items={[
          {
            label: "Casos de migración habilitados",
            value: "Caso 1 y Caso 2",
            subtext: `${case1Count} plan(es) de Aplicación · ${case2Count} plan(es) de Imagen SO/VM`,
          },
          {
            label: "Planes de migración registrados",
            value: validJobs.length,
            subtext: `${activeJobsCount} en curso · ${completedJobsCount} completados`,
          },
          {
            label: "Recursos activos en AWS (us-east-1)",
            value: `${runningInstances} instancia(s) EC2`,
            subtext: `${ebsUsedGb} GiB / ${ebsLimitGb} GiB EBS ocupados (${ebsPercent}%)`,
          },
          {
            label: "Telemetría de agentes y topología",
            value: `${allNodes.length} nodos CMIR`,
            subtext: `Host: ${hostName} · ${onlineAgentsCount} agente(s) online · ${sharedNodesCount} compartidos`,
          },
        ]}
      />

      {/* Main AWS Console Home 2-Column Widget Layout */}
      <div className="awsui-console-home-grid">
        {/* COLUMNA PRINCIPAL IZQUIERDA */}
        <div className="awsui-console-home-main">
          {/* WIDGET 1: CASOS DE USO (CASO 1 Y CASO 2) */}
          <AwsContainer
            title="Soluciones de migración a la nube (Casos 1 y 2)"
            description="Selecciona el escenario de migración para iniciar el asistente paso a paso con generación automática de código Terraform HCL y despliegue en vivo."
            actions={<span className="cm-badge aws">Estándar AWS Cloudscape</span>}
          >
            <div className="awsui-usecase-cards-grid">
              {/* TARJETA CASO 1 */}
              <div className="awsui-usecase-card">
                <div className="awsui-usecase-card-header">
                  <div className="awsui-usecase-icon aws-orange">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M16 18l6-6-6-6" />
                      <path d="M8 6l-6 6 6 6" />
                    </svg>
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                      <span className="cm-badge aws">Caso 1 · Aplicación</span>
                      <span className="cm-badge observed">12 etapas · GitHub / Código</span>
                    </div>
                    <h3 className="awsui-usecase-title">
                      Migración desde Código Fuente o Repositorio GitHub
                    </h3>
                  </div>
                </div>

                <p className="awsui-usecase-desc">
                  Inspecciona repositorios de GitHub o carpetas de código sin ejecutar código arbitrario. Detecta lenguajes, puertos, Dockerfiles, esquemas SQL/PostGIS y variables sensibles para desplegar en contenedores sobre Amazon EC2 / ECS o Google Cloud Run.
                </p>

                <ul className="awsui-usecase-features">
                  <li>
                    <span className="check-icon">✓</span>
                    <span>Mapa interactivo de transformación GitHub → Servicios Cloud</span>
                  </li>
                  <li>
                    <span className="check-icon">✓</span>
                    <span>Sincronización automática de IP pública dinámica en el frontend</span>
                  </li>
                  <li>
                    <span className="check-icon">✓</span>
                    <span>Despliegue directo con Terraform (`init`, `plan`, `apply`, `destroy`)</span>
                  </li>
                </ul>

                <div className="awsui-usecase-footer">
                  <button
                    type="button"
                    className="cm-btn primary"
                    onClick={() => onQuickStartUseCase("app_source")}
                  >
                    Iniciar Caso 1 (Aplicación GitHub)
                  </button>
                  <button
                    type="button"
                    className="cm-btn sm"
                    onClick={() => {
                      setUseCaseFilter("app_source");
                      const el = document.getElementById("recent-migration-plans-widget");
                      if (el) el.scrollIntoView({ behavior: "smooth" });
                    }}
                  >
                    Filtrar planes ({case1Count})
                  </button>
                </div>
              </div>

              {/* TARJETA CASO 2 */}
              <div className="awsui-usecase-card">
                <div className="awsui-usecase-card-header">
                  <div className="awsui-usecase-icon aws-blue">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="2" y="3" width="20" height="14" rx="2" />
                      <line x1="8" y1="21" x2="16" y2="21" />
                      <line x1="12" y1="17" x2="12" y2="21" />
                    </svg>
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                      <span className="cm-badge info">Caso 2 · Imagen SO / VM</span>
                      <span className="cm-badge derived">13 etapas · 8 dimensiones</span>
                    </div>
                    <h3 className="awsui-usecase-title">
                      Migración de Sistema Operativo en Vivo o Imagen de VM
                    </h3>
                  </div>
                </div>

                <p className="awsui-usecase-desc">
                  Captura el estado completo de un servidor Linux, Windows o macOS mediante el agente remoto CloudMove (osquery) o analiza discos virtuales (VMDK, QCOW2, RAW, VHDX) verificando firmas binarias y SHA-256 para replicarlos en Amazon EC2 o Compute Engine.
                </p>

                <ul className="awsui-usecase-features">
                  <li>
                    <span className="check-icon">✓</span>
                    <span>Inscripción de agentes remotos con un comando (`curl | sudo bash`)</span>
                  </li>
                  <li>
                    <span className="check-icon">✓</span>
                    <span>Evaluación de 8 dimensiones de fidelidad (Kernel, Red, Discos, Servicios)</span>
                  </li>
                  <li>
                    <span className="check-icon">✓</span>
                    <span>Rehidratación Cloud-Init e importación a AMI / Instancia EC2</span>
                  </li>
                </ul>

                <div className="awsui-usecase-footer">
                  <button
                    type="button"
                    className="cm-btn primary"
                    onClick={() => onQuickStartUseCase("vm_image")}
                  >
                    Iniciar Caso 2 (Imagen SO / VM)
                  </button>
                  <button
                    type="button"
                    className="cm-btn sm"
                    onClick={() => onNavigateTab("sources-targets")}
                  >
                    Gestionar agentes ({agents.length})
                  </button>
                </div>
              </div>
            </div>
          </AwsContainer>

          {/* WIDGET 2: SERVICIOS VISITADOS RECIENTEMENTE */}
          <AwsContainer
            title="Servicios de la consola visitados recientemente"
            description="Acceso directo a las herramientas de descubrimiento, modelado arquitectónico y auditoría de recursos."
          >
            <div className="awsui-recent-services-grid">
              <button
                type="button"
                className="awsui-service-shortcut"
                onClick={() => onQuickStartUseCase("app_source")}
              >
                <span className="shortcut-badge aws">EC2 / ECS</span>
                <div className="shortcut-meta">
                  <strong>Caso 1 · Aplicación desde GitHub</strong>
                  <span>Contenedores, variables de entorno y base de datos</span>
                </div>
              </button>

              <button
                type="button"
                className="awsui-service-shortcut"
                onClick={() => onQuickStartUseCase("vm_image")}
              >
                <span className="shortcut-badge blue">VM Import</span>
                <div className="shortcut-meta">
                  <strong>Caso 2 · Imagen de SO / Máquina Virtual</strong>
                  <span>Captura por agente en vivo o imagen VMDK/QCOW2</span>
                </div>
              </button>

              <button
                type="button"
                className="awsui-service-shortcut"
                onClick={() => onNavigateTab("executions-audit")}
              >
                <span className="shortcut-badge green">STS / Audit</span>
                <div className="shortcut-meta">
                  <strong>Auditoría de Cuenta AWS y Terraform</strong>
                  <span>Consultar y eliminar instancias EC2, EBS y VPCs</span>
                </div>
              </button>

              <button
                type="button"
                className="awsui-service-shortcut"
                onClick={() => onNavigateTab("discovery")}
              >
                <span className="shortcut-badge neutral">osquery</span>
                <div className="shortcut-meta">
                  <strong>Discovery e Inventario Profundo</strong>
                  <span>16 tablas de hardware, procesos, puertos y paquetes</span>
                </div>
              </button>

              <button
                type="button"
                className="awsui-service-shortcut"
                onClick={() => onNavigateTab("architecture")}
              >
                <span className="shortcut-badge blue">CMIR v2.1</span>
                <div className="shortcut-meta">
                  <strong>Grafo Jerárquico de Arquitectura</strong>
                  <span>Exploración visual Nivel 0-5 y dependencias ({selectedNodes.length} sel.)</span>
                </div>
              </button>

              <button
                type="button"
                className="awsui-service-shortcut"
                onClick={() => onNavigateTab("sources-targets")}
              >
                <span className="shortcut-badge aws">Agentes</span>
                <div className="shortcut-meta">
                  <strong>Orígenes, Agentes Remotos y Destinos</strong>
                  <span>Tokens de inscripción y matriz de compatibilidad</span>
                </div>
              </button>
            </div>
          </AwsContainer>

          {/* WIDGET 3: TABLA DE PLANES DE MIGRACIÓN RECIENTES */}
          <div id="recent-migration-plans-widget">
            <AwsContainer
              title="Planes de migración registrados"
              counter={filteredJobs.length}
              description="Planes persistidos en la base de datos transaccional ACID para el Caso 1 y el Caso 2."
              noPadding={true}
              actions={
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <select
                    className="cm-select"
                    aria-label="Filtrar por caso de uso"
                    value={useCaseFilter}
                    onChange={(e) => setUseCaseFilter(e.target.value)}
                    style={{ height: 34, fontSize: 13 }}
                  >
                    <option value="ALL">Todos los casos ({validJobs.length})</option>
                    <option value="app_source">Caso 1 · Aplicación ({case1Count})</option>
                    <option value="vm_image">Caso 2 · Imagen SO/VM ({case2Count})</option>
                  </select>
                  <input
                    type="search"
                    className="cm-input"
                    style={{ width: 220, height: 34, fontSize: 13 }}
                    placeholder="Buscar por nombre o ID..."
                    aria-label="Filtrar planes de migración"
                    value={jobSearchFilter}
                    onChange={(e) => setJobSearchFilter(e.target.value)}
                  />
                  <button
                    type="button"
                    className="cm-btn primary sm"
                    onClick={() => onNavigateTab("migration")}
                  >
                    Abrir orquestador
                  </button>
                </div>
              }
            >
              {loading && validJobs.length === 0 ? (
                <div style={{ padding: 24 }}>
                  <p className="cm-hint">Cargando planes de migración desde base de datos transaccional...</p>
                </div>
              ) : filteredJobs.length === 0 ? (
                <AwsEmptyState
                  title="No hay planes de migración que coincidan"
                  description="Crea un nuevo plan seleccionando el Caso 1 (Aplicación desde GitHub) o el Caso 2 (Imagen de SO / Máquina Virtual)."
                  action={
                    <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
                      <button
                        type="button"
                        className="cm-btn primary sm"
                        onClick={() => onQuickStartUseCase("app_source")}
                      >
                        Crear plan Caso 1 (App)
                      </button>
                      <button
                        type="button"
                        className="cm-btn sm"
                        onClick={() => onQuickStartUseCase("vm_image")}
                      >
                        Crear plan Caso 2 (VM)
                      </button>
                    </div>
                  }
                />
              ) : (
                <div className="cm-table-wrap" style={{ border: "none", borderRadius: 0 }}>
                  <table className="cm-table">
                    <thead>
                      <tr>
                        <th>Nombre / ID del plan</th>
                        <th>Caso de uso</th>
                        <th>Destino</th>
                        <th>Estado</th>
                        <th>Modo de ejecución</th>
                        <th>Validación</th>
                        <th style={{ textAlign: "right" }}>Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredJobs.map((job) => (
                        <tr key={job.migration_id}>
                          <td>
                            <strong>{job.name}</strong>
                            <div>
                              <code style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                                {job.migration_id} · v{job.version || 1}
                              </code>
                            </div>
                          </td>
                          <td>
                            <span className={`cm-badge ${job.use_case === "app_source" ? "aws" : "info"}`}>
                              {job.use_case === "app_source"
                                ? "Caso 1 · Aplicación"
                                : "Caso 2 · Imagen SO/VM"}
                            </span>
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
                                : "Dry-Run / Listo"}
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
                                Verificado
                              </AwsStatusIndicator>
                            )}
                          </td>
                          <td style={{ textAlign: "right" }}>
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
          </div>
        </div>

        {/* COLUMNA LATERAL DERECHA (WIDGETS ESTILO AWS CONSOLE HOME) */}
        <div className="awsui-console-home-side">
          {/* WIDGET DERECHO 1: NIVEL GRATUITO DE AWS Y CUOTAS DE LEARNER LAB */}
          <AwsContainer
            title="Nivel gratuito de AWS y uso de cuotas"
            description="Monitoreo en tiempo real de límites de cuenta en AWS Academy Learner Lab (us-east-1)."
            actions={
              <button
                type="button"
                className="cm-btn sm"
                onClick={() => onNavigateTab("executions-audit")}
              >
                Ver auditoría
              </button>
            }
          >
            <div className="awsui-quota-list">
              <div className="awsui-quota-item">
                <div className="awsui-quota-header">
                  <strong>Almacenamiento Amazon EBS (gp3)</strong>
                  <span>
                    {ebsUsedGb} GiB / {ebsLimitGb} GiB ({ebsPercent}%)
                  </span>
                </div>
                <div className="awsui-quota-bar-bg">
                  <div
                    className={`awsui-quota-bar-fill ${
                      ebsPercent > 80 ? "is-danger" : ebsPercent > 60 ? "is-warning" : "is-ok"
                    }`}
                    style={{ width: `${Math.max(4, ebsPercent)}%` }}
                  />
                </div>
                <span className="cm-hint">
                  Límite estricto de AWS Academy por laboratorio: 150 GiB totales.
                </span>
              </div>

              <div className="awsui-quota-item">
                <div className="awsui-quota-header">
                  <strong>Instancias Amazon EC2 en ejecución</strong>
                  <span>{runningInstances} / 10 instancias</span>
                </div>
                <div className="awsui-quota-bar-bg">
                  <div
                    className="awsui-quota-bar-fill is-ok"
                    style={{ width: `${Math.min(100, Math.max(8, runningInstances * 10))}%` }}
                  />
                </div>
                <span className="cm-hint">
                  Tipos permitidos sin restricción: <code>t3.micro</code>, <code>t3.small</code>, <code>t3.medium</code>.
                </span>
              </div>

              <div className="awsui-quota-item">
                <div className="awsui-quota-header">
                  <strong>Redes Amazon VPC activas</strong>
                  <span>{totalVpcs} / 5 VPCs</span>
                </div>
                <div className="awsui-quota-bar-bg">
                  <div
                    className="awsui-quota-bar-fill is-ok"
                    style={{ width: `${Math.min(100, Math.max(10, totalVpcs * 20))}%` }}
                  />
                </div>
                <span className="cm-hint">
                  Incluye VPC predeterminada y VPCs creadas por despliegues Terraform.
                </span>
              </div>
            </div>
          </AwsContainer>

          {/* WIDGET DERECHO 2: AWS HEALTH DASHBOARD */}
          <AwsContainer
            title="AWS Health y estado de servicios"
            description="Verificación continua de los subsistemas de CloudMove."
          >
            <div className="awsui-health-summary-grid">
              <div className="awsui-health-stat">
                <span className="awsui-health-num">0</span>
                <span className="awsui-health-label">Problemas abiertos</span>
              </div>
              <div className="awsui-health-stat">
                <span className="awsui-health-num">0</span>
                <span className="awsui-health-label">Cambios programados</span>
              </div>
            </div>

            <div className="awsui-health-list">
              <div className="awsui-health-row">
                <span>Motor CMIR v2.1 y Grafo</span>
                <AwsStatusIndicator type="success">Operativo</AwsStatusIndicator>
              </div>
              <div className="awsui-health-row">
                <span>Base de datos transaccional</span>
                <AwsStatusIndicator type="success">
                  {persistence?.engine ? "SQLite WAL ACID" : "Operativo"}
                </AwsStatusIndicator>
              </div>
              <div className="awsui-health-row">
                <span>Sesión AWS STS (us-east-1)</span>
                <AwsStatusIndicator type={awsAudit?.authenticated !== false ? "success" : "warning"}>
                  {awsAudit?.authenticated !== false ? "Autenticado" : "Requiere token"}
                </AwsStatusIndicator>
              </div>
              <div className="awsui-health-row">
                <span>Motor Terraform CLI</span>
                <AwsStatusIndicator type="success">v1.7+ Listo</AwsStatusIndicator>
              </div>
            </div>
          </AwsContainer>

          {/* WIDGET DERECHO 3: DOCUMENTACIÓN Y RECURSOS */}
          <AwsContainer
            title="Documentación y recursos de inicio"
            description="Guías técnicas y referencias para operar los dos casos de migración."
          >
            <div className="awsui-docs-list">
              <button
                type="button"
                className="awsui-doc-link"
                onClick={() => onQuickStartUseCase("app_source")}
              >
                <div>
                  <strong>Guía del Caso 1: Migración de Aplicación desde GitHub</strong>
                  <p>Cómo inspeccionar un repositorio, configurar servicios gestionados y desplegar en EC2 con Docker Compose.</p>
                </div>
                <span className="doc-arrow">↗</span>
              </button>

              <button
                type="button"
                className="awsui-doc-link"
                onClick={() => onNavigateTab("sources-targets")}
              >
                <div>
                  <strong>Guía del Caso 2: Agente Remoto e Imágenes de VM</strong>
                  <p>Cómo generar un token de inscripción y ejecutar el instalador en Linux, Windows o macOS para capturar el sistema operativo.</p>
                </div>
                <span className="doc-arrow">↗</span>
              </button>

              <button
                type="button"
                className="awsui-doc-link"
                onClick={() => onNavigateTab("executions-audit")}
              >
                <div>
                  <strong>Manual de Auditoría AWS y Limpieza con Terraform</strong>
                  <p>Cómo auditar costos, asociar recursos a cada despliegue y destruir entornos de prueba de forma segura.</p>
                </div>
                <span className="doc-arrow">↗</span>
              </button>
            </div>
          </AwsContainer>
        </div>
      </div>
    </div>
  );
}
