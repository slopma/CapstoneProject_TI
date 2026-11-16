import React from "react";
import RepositoryTreeViewer from "./RepositoryTreeViewer";
import GithubToCloudTransformationSelector from "./GithubToCloudTransformationSelector";

export function Case1SourceInspectionPanel({
  currentJob,
  srcEnv,
  envVars,
  appDependencies,
  appAssumptions,
  jobDecisions,
  onSelectDecision,
  onApplyToExistingJob,
  updatingDecisions,
  onAttachGithub,
}) {
  return (
    <>
      <div className="cm-card">
        <div className="cm-card-title">
          <span>
            Evidencia de aplicación detectada ({srcEnv.app_name || "Aplicación"})
          </span>
          <span className="cm-badge observed">
            Análisis estático seguro
          </span>
        </div>

        {srcEnv.git_metadata && (
          <div className="cm-alert info" style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <strong>Trazabilidad Git Verificada (Repositorio GitHub Público / PAT):</strong>
              <span className="cm-badge observed">Commit Fijado e Inmutable</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8, fontSize: 13.5 }}>
              <div>Repositorio: <a href={srcEnv.git_metadata.repository_url} target="_blank" rel="noreferrer"><code>{srcEnv.git_metadata.owner}/{srcEnv.git_metadata.repo}</code></a></div>
              <div>Commit SHA: <code>{srcEnv.git_metadata.commit_sha}</code></div>
              <div>Rama / Ref: <code>{srcEnv.git_metadata.ref}</code></div>
              <div>Autor: <strong>{srcEnv.git_metadata.author_name}</strong> ({srcEnv.git_metadata.author_date?.slice(0, 10)})</div>
            </div>
            <div style={{ marginTop: 6, fontSize: 13.5 }}>
              Mensaje: <em>&quot;{srcEnv.git_metadata.commit_message}&quot;</em> · Sandbox efímero: <span style={{ color: "#15803d", fontWeight: 600 }}>Aislado y purgado de archivos temporales</span>
            </div>
          </div>
        )}

        {!srcEnv.git_metadata && (
          <div style={{ marginBottom: 14, padding: "10px 14px", backgroundColor: "#f8fafc", borderRadius: 6, border: "1px dashed #94a3b8", fontSize: 13.5, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <span><strong>¿Deseas probar este caso con un repositorio GitHub real?</strong> Ingresa un enlace público en la sección superior y genera el plan.</span>
            <button
              type="button"
              className="cm-btn sm primary"
              onClick={onAttachGithub}
            >
              Adjuntar Repositorio GitHub
            </button>
          </div>
        )}
        <div className="cm-kpi-grid" style={{ marginBottom: 12 }}>
          <div className="cm-kpi-card">
            <span className="cm-kpi-label">Lenguaje y Framework</span>
            <span className="cm-kpi-value" style={{ fontSize: 16 }}>
              {srcEnv.language || "Python"} · {srcEnv.framework || "FastAPI"}
            </span>
            <span className="cm-kpi-meta">Runtime: <code>{srcEnv.runtime}</code></span>
          </div>
          <div className="cm-kpi-card">
            <span className="cm-kpi-label">Puertos y Healthcheck</span>
            <span className="cm-kpi-value" style={{ fontSize: 16 }}>
              {(srcEnv.exposed_ports || []).join(", ")}
            </span>
            <span className="cm-kpi-meta">Health: <code>{(srcEnv.health_endpoints || []).join(", ")}</code></span>
          </div>
          <div className="cm-kpi-card">
            <span className="cm-kpi-label">Secretos Redactados</span>
            <span className="cm-kpi-value" style={{ fontSize: 16, color: "#15803d" }}>
              {srcEnv.secrets_redacted_count ?? envVars.filter((v) => v.is_secret).length} protegidos
            </span>
            <span className="cm-kpi-meta">0 secretos en texto plano en IaC</span>
          </div>
          <div className="cm-kpi-card">
            <span className="cm-kpi-label">Archivos Inspeccionados</span>
            <span className="cm-kpi-value" style={{ fontSize: 16 }}>
              {srcEnv.tree_summary?.total_files ?? (srcEnv.files_inspected || []).length} archivos
            </span>
            <span className="cm-kpi-meta">{srcEnv.tree_summary?.total_directories ?? 0} carpetas indexadas</span>
          </div>
        </div>

        {srcEnv.repository_tree && (
          <RepositoryTreeViewer
            treeData={{
              hierarchical_tree: srcEnv.repository_tree,
              summary: srcEnv.tree_summary,
              key_manifests: srcEnv.key_manifests,
            }}
            title={`Explorador de Archivos y Carpetas del Código Migrado (${srcEnv.app_name || "aplicación"})`}
            defaultOpen={false}
          />
        )}

        {/* Tabla de Dependencias Clasificadas: Confirmadas vs Inferidas vs Desconocidas */}
        {appDependencies.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>
              Dependencias de Aplicación Clasificadas por Nivel de Certeza Epistémica ({appDependencies.length})
            </h4>
            <div className="cm-table-wrap">
              <table className="cm-table">
                <thead>
                  <tr>
                    <th>Servicio / Dependencia</th>
                    <th>Tipo / Motor</th>
                    <th>Puerto</th>
                    <th>Clasificación Epistémica</th>
                    <th>Migración de Datos</th>
                    <th>Evidencia Técnica</th>
                  </tr>
                </thead>
                <tbody>
                  {appDependencies.map((dep) => {
                    const cls = dep.classification || dep.epistemic_state || "confirmed";
                    const badgeClass =
                      cls === "confirmed" || cls === "observed"
                        ? "observed"
                        : cls === "inferred"
                        ? "inferred"
                        : "unknown";
                    return (
                      <tr key={dep.id}>
                        <td>
                          <strong>{dep.name}</strong>
                          <div className="cm-hint"><code>{dep.relationship_type}</code></div>
                        </td>
                        <td>
                          <code>{dep.type}</code> ({dep.engine})
                        </td>
                        <td>
                          <code>{dep.port || "N/A"}</code>
                        </td>
                        <td>
                          <span className={`cm-badge ${badgeClass}`}>
                            {cls === "confirmed"
                              ? "CONFIRMADA"
                              : cls === "inferred"
                              ? "INFERIDA"
                              : "DESCONOCIDA"}{" "}
                            ({Math.round((dep.confidence ?? 0.8) * 100)}%)
                          </span>
                        </td>
                        <td>
                          {dep.requires_data_migration ? (
                            <span className="cm-badge warning">Requiere pg_dump/sync</span>
                          ) : (
                            <span className="cm-badge neutral">Sin estado persistente</span>
                          )}
                        </td>
                        <td style={{ fontSize: 13.5 }}>
                          {dep.evidence?.[0]?.detail || dep.evidence?.[0]?.source || "Manifiesto de aplicación"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Supuestos explícitos */}
        {appAssumptions.length > 0 && (
          <div className="cm-card-subtle" style={{ marginTop: 12 }}>
            <strong style={{ fontSize: 13.5 }}>Supuestos y Condiciones Operativas Declaradas:</strong>
            {appAssumptions.map((asmp, idx) => (
              <div key={idx} className="cm-hint" style={{ marginTop: 4 }}>
                • {asmp}
              </div>
            ))}
          </div>
        )}

        {/* Mapa Interactivo de Transformación GitHub -> Nube y Selector de Opciones (Post-Detección / En Plan) */}
        {srcEnv.transformation_catalog && (
          <GithubToCloudTransformationSelector
            catalog={srcEnv.transformation_catalog}
            decisions={jobDecisions}
            onSelectDecision={onSelectDecision}
            targetProvider={currentJob.target_provider}
            onApplyToExistingJob={onApplyToExistingJob}
            applyingChanges={updatingDecisions}
            isJobView={true}
          />
        )}
      </div>

      {/* Backups de Base de Datos (.dump / .sql) y Semillas JSON Detectadas */}
      {srcEnv.database_backups?.has_backups && (
        <div className="cm-card" style={{ border: "2px solid #16a34a", backgroundColor: "#f0fdf4" }}>
          <div className="cm-card-title">
            <span style={{ color: "#14532d", fontWeight: 700 }}>
              Backups de Base de Datos y Semillas Detectados para Recreación Automática en {currentJob.target_provider?.toUpperCase()}
            </span>
            <span className="cm-badge observed">
              {srcEnv.database_backups.primary_backup_file} · {srcEnv.database_backups.total_public_tables} Tablas Públicas · {srcEnv.database_backups.total_rows_all_schemas} Filas Totales
            </span>
          </div>
          {(srcEnv.database_backups.backups || []).map((bkp) => (
            <div key={bkp.path} className="cm-card-subtle" style={{ backgroundColor: "#ffffff", marginBottom: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                <div>
                  <strong style={{ fontSize: 14, color: "#14532d" }}>
                    <code>{bkp.path}</code>
                  </strong>{" "}
                  <span className="cm-badge info">{bkp.format}</span>{" "}
                  <span className="cm-badge observed">{bkp.engine} (v{bkp.dumped_from_version})</span>
                </div>
                <span style={{ fontSize: 13, color: "#475569" }}>
                  Tamaño: <strong>{(bkp.size_bytes / 1024).toFixed(1)} KB</strong> · Dominio public: <strong>{bkp.public_rows_count} filas</strong> · Total (incl. auth/storage): <strong>{bkp.total_rows_count} filas</strong>
                </span>
              </div>
              <div style={{ fontSize: 13, color: "#334155", marginBottom: 8 }}>
                <div><strong>Esquemas incluidos:</strong> <code>{(bkp.schemas || []).join(", ")}</code></div>
                <div><strong>Extensiones requeridas:</strong> <code>{(bkp.extensions || []).join(", ")}</code></div>
                {bkp.public_functions?.length > 0 && (
                  <div>
                    <strong>Funciones RPC / SQL Espaciales ({bkp.public_functions.length}):</strong>{" "}
                    <code>{bkp.public_functions.map((f) => f.signature).join(" · ")}</code>
                  </div>
                )}
              </div>
              {bkp.non_empty_tables?.length > 0 && (
                <div className="cm-table-wrap">
                  <table className="cm-table">
                    <thead>
                      <tr>
                        <th>Tabla en Backup</th>
                        <th>Filas a Restaurar en {currentJob.target_provider?.toUpperCase()}</th>
                        <th>Columnas Detectadas</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bkp.non_empty_tables.map((t) => (
                        <tr key={t.table}>
                          <td><strong><code>{t.table}</code></strong></td>
                          <td><span className="cm-badge observed">{t.rows} filas</span></td>
                          <td><code>{(t.columns || []).join(", ")}</code></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
          {srcEnv.database_backups.seed_files?.length > 0 && (
            <div className="cm-card-subtle" style={{ backgroundColor: "#ffffff" }}>
              <strong style={{ fontSize: 13.5, display: "block", marginBottom: 4 }}>
                Archivos Semilla JSON Adicionales en el Repositorio ({srcEnv.database_backups.seed_files.length}):
              </strong>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {srcEnv.database_backups.seed_files.map((sf) => (
                  <span key={sf.path} className="cm-badge neutral" style={{ fontSize: 12.5 }}>
                    <code>{sf.path}</code> ({sf.format}: {sf.record_count} registros)
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Variables de Entorno con Redacción de Secretos */}
      {envVars.length > 0 && (
        <div className="cm-card">
          <div className="cm-card-title">
            <span>Variables de Entorno Detectadas ({envVars.length}) — Secretos Redactados Automáticamente</span>
            <span className="cm-badge observed">Protección Secret-Zero</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: 8 }}>
            {envVars.map((ev) => (
              <div key={ev.name} className="cm-card-subtle" style={{ padding: "8px 12px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                  <strong style={{ fontSize: 13.5 }}>{ev.name}</strong>
                  <span className={`cm-badge ${ev.is_secret ? "danger" : "observed"}`} style={{ fontSize: 12.5, padding: "1px 5px" }}>
                    {ev.is_secret ? "SECRETO REDACTADO" : "CONFIG"}
                  </span>
                </div>
                <code style={{ fontSize: 13.5, color: ev.is_secret ? "#b91c1c" : "#1e40af", wordBreak: "break-all" }}>
                  {ev.redacted_value}
                </code>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

export function Case1CompatibilityInspectionPanel({ currentJob, diffReport }) {
  if (!diffReport || diffReport.comparisons) return null;
  return (
    <div className="cm-card">
      <div className="cm-card-title">
        <span>Verificación de Paridad de Ejecución de la Aplicación ({currentJob.target_provider?.toUpperCase()})</span>
        <span className="cm-badge observed">
          Paridad esperada: {diffReport.behavioral_parity_expected ? "SÍ" : "PARCIAL"}
        </span>
      </div>
      <div className="cm-table-wrap">
        <table className="cm-table">
          <thead>
            <tr>
              <th>Atributo de Aplicación</th>
              <th>Valor Preservado / Configurado en Destino</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Runtime / Imagen Base</strong></td>
              <td><code>{diffReport.runtime_preserved}</code></td>
            </tr>
            <tr>
              <td><strong>Comando de Arranque (Entrypoint)</strong></td>
              <td><code>{diffReport.entrypoint_preserved}</code></td>
            </tr>
            <tr>
              <td><strong>Puertos Expuestos en Security Group / Firewall</strong></td>
              <td><code>{(diffReport.ports_preserved || []).join(", ")}</code></td>
            </tr>
            <tr>
              <td><strong>Endpoint de Salud (Healthcheck)</strong></td>
              <td><code>{diffReport.health_endpoint}</code></td>
            </tr>
            <tr>
              <td><strong>Migración de Datos de Base de Datos</strong></td>
              <td>{diffReport.database_data_migration_included ? "Incluida (script migrate_database_data.sh generado)" : "No requerida"}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
