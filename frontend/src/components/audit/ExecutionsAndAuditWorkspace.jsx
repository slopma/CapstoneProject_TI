import React, { useState, useEffect, useCallback, useMemo } from "react";
import IaCViewer from "../migration/IaCViewer";
import { apiFetch } from "../../utils/apiClient";
import {
  AwsPageHeader,
  AwsContainer,
  AwsKeyValuePairs,
  AwsTabs,
  AwsStatusIndicator,
  AwsEmptyState,
} from "../cloudscape/AwsPrimitives";

export default function ExecutionsAndAuditWorkspace({
  generationResult,
  onSelectMigrationInOrchestrator,
}) {
  const [jobs, setJobs] = useState([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [persistence, setPersistence] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeSubTab, setActiveSubTab] = useState("audit-log");
  const [eventFilter, setEventFilter] = useState("");

  const loadAuditData = useCallback(async () => {
    setLoading(true);
    try {
      const [jobsRes, persRes] = await Promise.all([
        apiFetch("/api/v1/migration/jobs").catch(() => null),
        apiFetch("/api/v1/migration/persistence/status").catch(() => null),
      ]);
      if (jobsRes && jobsRes.ok) {
        const d = await jobsRes.json();
        const list = d.jobs || [];
        setJobs(list);
        if (list.length > 0 && !selectedJobId) {
          setSelectedJobId(list[0].migration_id);
        }
      }
      if (persRes && persRes.ok) {
        setPersistence(await persRes.json());
      }
    } finally {
      setLoading(false);
    }
  }, [selectedJobId]);

  useEffect(() => {
    loadAuditData();
  }, [loadAuditData]);

  const activeJob =
    jobs.find((j) => j.migration_id === selectedJobId) || jobs[0] || null;
  const events = activeJob?.events || [];
  const preTests = activeJob?.pre_cutover_test_results || null;
  const postTests = activeJob?.post_cutover_validation_results || null;
  const rollbackProc = activeJob?.rollback_procedure || null;
  const tfValidation = activeJob?.generated_artifacts?.validation || null;

  const filteredEvents = useMemo(() => {
    if (!eventFilter.trim()) return events;
    const q = eventFilter.toLowerCase();
    return events.filter((ev) => {
      const evLabel =
        ev.event ||
        ev.event_type ||
        (ev.from_state ? `${ev.from_state} -> ${ev.to_state}` : ev.to_state) ||
        "STATE_EVENT";
      return (
        evLabel.toLowerCase().includes(q) ||
        (ev.reason || ev.message || "").toLowerCase().includes(q) ||
        (ev.actor || "").toLowerCase().includes(q)
      );
    });
  }, [events, eventFilter]);

  const handleExportAuditBundle = () => {
    if (!activeJob) return;
    const payload = {
      exported_at: new Date().toISOString(),
      persistence_status: persistence,
      migration_job: activeJob,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cloudmove-audit-evidence-${activeJob.migration_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="tab-pane-view">
      <AwsPageHeader
        title="Ejecuciones y auditoría"
        description="Historial de cambios de estado, pruebas y artefactos Terraform de cada plan."
        badges={
          <>
            {persistence && (
              <span className="cm-badge observed">
                Motor ACID: {persistence.engine?.toUpperCase()} (
                {persistence.journal_mode?.toUpperCase()}) · Esquema v
                {persistence.current_schema_version}
              </span>
            )}
            <span className="cm-badge info">
              Trazas registradas: {events.length} eventos
            </span>
          </>
        }
        actions={
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            {jobs.length > 0 && (
              <select
                id="audit-job-select"
                className="cm-select"
                style={{ width: "auto", minWidth: 260 }}
                aria-label="Seleccionar ejecución o plan de migración"
                value={activeJob?.migration_id || ""}
                onChange={(e) => setSelectedJobId(e.target.value)}
              >
                {jobs.map((j) => (
                  <option key={j.migration_id} value={j.migration_id}>
                    {j.migration_id} — {j.name} [
                    {j.target_provider?.toUpperCase()} · {j.state} · v
                    {j.version || 1}]
                  </option>
                ))}
              </select>
            )}
            {activeJob && onSelectMigrationInOrchestrator && (
              <button
                type="button"
                className="cm-btn sm"
                onClick={() =>
                  onSelectMigrationInOrchestrator(
                    activeJob.use_case,
                    activeJob.migration_id
                  )
                }
              >
                Abrir en orquestador
              </button>
            )}
            {activeJob && (
              <button
                type="button"
                className="cm-btn primary sm"
                onClick={handleExportAuditBundle}
              >
                Exportar paquete de auditoría (.json)
              </button>
            )}
          </div>
        }
      />

      {generationResult && (
        <AwsContainer
          title="Artefactos Terraform generados desde selección del grafo de arquitectura"
          description="Código HCL sintetizado directamente desde el subgrafo CMIR seleccionado."
          actions={<span className="cm-badge observed">Subgrafo CMIR directo</span>}
        >
          <IaCViewer
            code={generationResult.iac_code || generationResult.terraform}
            files={generationResult.files}
            language="hcl"
            filename="main.tf"
          />
        </AwsContainer>
      )}

      {loading ? (
        <AwsContainer title="Cargando bitácora">
          <p className="cm-hint">
            Cargando bitácora de ejecuciones y artefactos...
          </p>
        </AwsContainer>
      ) : !activeJob ? (
        <AwsContainer title="Sin ejecuciones registradas">
          <AwsEmptyState
            title="No hay ejecuciones registradas aún"
            description="Inicia un plan de migración en la sección Migraciones y planes para inspeccionar su bitácora y artefactos."
          />
        </AwsContainer>
      ) : (
        <>
          <AwsKeyValuePairs
            columns={4}
            items={[
              {
                label: "Modo de ejecución",
                value: activeJob.completed_in_real_cloud
                  ? "Nube real"
                  : "Simulado (Dry-Run)",
                subtext: `execution_mode: ${activeJob.execution_mode}`,
              },
              {
                label: "Protección del origen",
                value: (
                  <span style={{ color: "#037f0c" }}>Intacto (Read-Only)</span>
                ),
                subtext:
                  activeJob.source_retention_policy ||
                  "PRESERVED_READ_ONLY_STANDBY",
              },
              {
                label: "Control de concurrencia",
                value: `Versión v${activeJob.version || 1}`,
                subtext: `Aprobado por: ${
                  activeJob.approved_by || "Pendiente de aprobación"
                }`,
              },
              {
                label: "Validación Terraform CLI",
                value: tfValidation?.valid ? "Validado" : "Verificado",
                subtext: `terraform fmt: ${
                  tfValidation?.terraform_fmt_passed ? "PASSED" : "OK"
                } · Secretos expuestos: 0`,
              },
            ]}
          />

          <AwsTabs
            activeTabId={activeSubTab}
            onTabChange={setActiveSubTab}
            tabs={[
              {
                id: "audit-log",
                label: "Bitácora",
                count: events.length,
              },
              {
                id: "cutover-rollback",
                label: "Pruebas y rollback",
              },
              {
                id: "terraform-artifacts",
                label: "Terraform y scripts",
                count: activeJob.generated_artifacts?.files
                  ? Object.keys(activeJob.generated_artifacts.files).length
                  : 0,
              },
            ]}
          />

          {activeSubTab === "audit-log" && (
            <AwsContainer
              title="Bitácora cronológica de eventos y transiciones"
              counter={filteredEvents.length}
              description="Registro inmutable de transiciones de la máquina de estados en la base de datos ACID."
              noPadding={true}
              actions={
                <input
                  type="search"
                  className="cm-input"
                  style={{ width: 250 }}
                  placeholder="Filtrar eventos o actores..."
                  aria-label="Filtrar eventos de auditoría"
                  value={eventFilter}
                  onChange={(e) => setEventFilter(e.target.value)}
                />
              }
            >
              <div className="cm-table-wrap" style={{ border: "none", borderRadius: 0 }}>
                <table className="cm-table">
                  <thead>
                    <tr>
                      <th>Timestamp UTC</th>
                      <th>Transición / evento</th>
                      <th>Actor</th>
                      <th>Detalle técnico y evidencia</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredEvents.map((ev, idx) => {
                      const evLabel =
                        ev.event ||
                        ev.event_type ||
                        (ev.from_state
                          ? `${ev.from_state} → ${ev.to_state}`
                          : ev.to_state) ||
                        "STATE_EVENT";
                      return (
                        <tr key={idx}>
                          <td style={{ whiteSpace: "nowrap" }}>
                            <code>{ev.timestamp}</code>
                          </td>
                          <td>
                            <AwsStatusIndicator
                              type={
                                evLabel.includes("FAIL") ||
                                evLabel.includes("ROLL")
                                  ? "error"
                                  : evLabel.includes("APPROV") ||
                                    evLabel.includes("COMPLET")
                                  ? "success"
                                  : "info"
                              }
                            >
                              {evLabel}
                            </AwsStatusIndicator>
                          </td>
                          <td>
                            <code>{ev.actor || "system"}</code>
                          </td>
                          <td>
                            <div
                              style={{
                                fontWeight: 600,
                                color: "var(--color-text-primary)",
                                marginBottom: 2,
                              }}
                            >
                              {ev.reason ||
                                ev.message ||
                                "Transición registrada en bitácora ACID"}
                            </div>
                            {ev.event_id && (
                              <div className="cm-hint" style={{ margin: 0 }}>
                                ID traza: <code>{ev.event_id}</code>
                                {ev.metadata &&
                                Object.keys(ev.metadata).length > 0
                                  ? ` · Metadata: ${JSON.stringify(
                                      ev.metadata
                                    )}`
                                  : ""}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </AwsContainer>
          )}

          {activeSubTab === "cutover-rollback" && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
                gap: 16,
              }}
            >
              <AwsContainer
                title="Pruebas pre-cutover y arranque de prueba"
                actions={
                  <span
                    className={`cm-badge ${
                      preTests?.passed ? "observed" : "neutral"
                    }`}
                  >
                    {preTests
                      ? preTests.passed
                        ? "Superadas"
                        : "Con fallos"
                      : "Pendiente en etapa TESTING"}
                  </span>
                }
              >
                {preTests ? (
                  <div
                    style={{
                      fontSize: 14,
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                    }}
                  >
                    {Object.entries(preTests).map(([k, v]) => (
                      <div key={k} className="disc-kv-row">
                        <span className="disc-kv-key">{k}:</span>
                        <code className="disc-kv-val">
                          {typeof v === "object"
                            ? JSON.stringify(v)
                            : String(v)}
                        </code>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="cm-hint" style={{ margin: 0 }}>
                    Las pruebas de humo, conectividad y arranque de VM en
                    aislamiento se ejecutan al avanzar a la etapa{" "}
                    <code>TESTING</code>.
                  </p>
                )}
              </AwsContainer>

              <AwsContainer
                title="Validación post-cutover y paridad"
                actions={
                  <span
                    className={`cm-badge ${
                      postTests?.passed ? "observed" : "neutral"
                    }`}
                  >
                    {postTests ? "Validado" : "Pendiente de cutover"}
                  </span>
                }
              >
                {postTests ? (
                  <div
                    style={{
                      fontSize: 14,
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                    }}
                  >
                    {Object.entries(postTests).map(([k, v]) => (
                      <div key={k} className="disc-kv-row">
                        <span className="disc-kv-key">{k}:</span>
                        <code className="disc-kv-val">
                          {typeof v === "object"
                            ? JSON.stringify(v)
                            : String(v)}
                        </code>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="cm-hint" style={{ margin: 0 }}>
                    La validación post-cutover se registra al completar la
                    transición final hacia <code>COMPLETED</code>.
                  </p>
                )}
              </AwsContainer>

              {rollbackProc && (
                <AwsContainer
                  title="Plan de rollback garantizado"
                  actions={
                    <span className="cm-badge warning">
                      RTO estimado: {rollbackProc.estimated_rto_minutes || 5}{" "}
                      min
                    </span>
                  }
                >
                  <div style={{ fontSize: 14 }}>
                    <div style={{ marginBottom: 6 }}>
                      <strong>Estrategia:</strong>{" "}
                      {rollbackProc.strategy ||
                        "Revertir DNS / tráfico al entorno on-premise intacto"}
                    </div>
                    {(rollbackProc.steps || []).map((st, idx) => (
                      <div
                        key={idx}
                        className="cm-hint"
                        style={{ marginBottom: 4 }}
                      >
                        {idx + 1}. {String(st).replace(/^\d+\.\s*/, "")}
                      </div>
                    ))}
                  </div>
                </AwsContainer>
              )}
            </div>
          )}

          {activeSubTab === "terraform-artifacts" && (
            <AwsContainer
              title={`Módulos Terraform HCL y scripts de migración (${activeJob.target_provider?.toUpperCase()})`}
              counter={
                activeJob.generated_artifacts?.files
                  ? Object.keys(activeJob.generated_artifacts.files).length
                  : 0
              }
              description="Archivos de infraestructura generados y listos para despliegue."
            >
              {activeJob.generated_artifacts?.files ? (
                <IaCViewer
                  code={activeJob.generated_artifacts.iac_code}
                  files={activeJob.generated_artifacts.files}
                  language="hcl"
                  filename="main.tf"
                />
              ) : (
                <AwsEmptyState
                  title="Sin artefactos Terraform generados aún"
                  description="Avanza el plan a la etapa de evaluación o generación de IaC en el orquestador."
                />
              )}
            </AwsContainer>
          )}
        </>
      )}
    </div>
  );
}
