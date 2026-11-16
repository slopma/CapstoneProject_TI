import React from "react";
import GithubToCloudTransformationSelector from "./GithubToCloudTransformationSelector";
import TargetArchitectureView from "./TargetArchitectureView";
import VmOsToCloudTransformationMap from "./VmOsToCloudTransformationMap";
import { FIDELITY_STATUS_META } from "./orchestratorConstants";

export function Case2SourceInspectionPanel({
  currentJob,
  srcEnv,
  binaryInspection,
  stagingVerification,
  disks,
  jobDecisions,
  onSelectDecision,
  onApplyToExistingJob,
  updatingDecisions,
}) {
  return (
    <div className="cm-card">
      <div className="cm-card-title">
        <span>Caso 2 · Integridad de Imagen, Cabecera Binaria (`qemu-img info`) y Checksum SHA-256</span>
        <span className={`cm-badge ${binaryInspection.is_authentic_binary_image ? "observed" : "warning"}`}>
          {binaryInspection.authenticity_classification}
        </span>
      </div>

      <div className="cm-kpi-grid" style={{ marginBottom: 12 }}>
        <div className="cm-kpi-card">
          <span className="cm-kpi-label">Firma Mágica Binaria</span>
          <span className="cm-kpi-value" style={{ fontSize: 16 }}>
            <code>{binaryInspection.magic_signature || "N/A"}</code>
          </span>
          <span className="cm-kpi-meta">
            Formato detectado: <strong>{binaryInspection.detected_format || srcEnv.format}</strong>
          </span>
        </div>
        <div className="cm-kpi-card">
          <span className="cm-kpi-label">Esquema de Partición y Boot</span>
          <span className="cm-kpi-value" style={{ fontSize: 16 }}>
            {srcEnv.partition_scheme || "GPT"} · {srcEnv.boot_mode || "UEFI"}
          </span>
          <span className="cm-kpi-meta">
            Etiquetas GPT: <code>{(binaryInspection.discovered_gpt_partition_labels || []).join(", ") || "EFI / ROOT"}</code>
          </span>
        </div>
        <div className="cm-kpi-card">
          <span className="cm-kpi-label">Consistencia del Snapshot</span>
          <span className="cm-kpi-value" style={{ fontSize: 16 }}>
            {srcEnv.snapshot_consistency?.consistency_type || "application_consistent"}
          </span>
          <span className="cm-kpi-meta">
            Agentes: {(srcEnv.snapshot_consistency?.quiesced_agents || ["fsfreeze", "qemu-guest-agent"]).join(", ")}
          </span>
        </div>
        <div className="cm-kpi-card">
          <span className="cm-kpi-label">Estrategia Oficial</span>
          <span className="cm-kpi-value" style={{ fontSize: 15 }}>
            {currentJob.compatibility_assessment?.migration_strategy?.selected_strategy_id ||
              currentJob.compatibility_assessment?.target_import_mechanism}
          </span>
          <span className="cm-kpi-meta">
            Capacidad: {srcEnv.total_used_gib || 40} GiB usados / {srcEnv.total_provisioned_gib || 150} GiB prov.
          </span>
        </div>
      </div>

      {/* Verificación de Copia de Staging y SHA-256 */}
      {stagingVerification && (
        <div className="cm-card-subtle" style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 6 }}>
            <strong style={{ fontSize: 14 }}>
              Trazabilidad Criptográfica SHA-256 (Imagen de Origen vs Copia de Staging)
            </strong>
            <span className={`cm-badge ${stagingVerification.source_and_staging_checksum_match ? "observed" : "danger"}`}>
              Checksum Match: {stagingVerification.source_and_staging_checksum_match ? "VERIFICADO (100% Idéntico)" : "MISMATCH"}
            </span>
          </div>
          <div style={{ fontSize: 13.5, display: "flex", flexDirection: "column", gap: 3 }}>
            <div>
              <strong>SHA-256 Origen (Intacto):</strong> <code>{stagingVerification.source_sha256}</code>
            </div>
            <div>
              <strong>SHA-256 Staging:</strong> <code>{stagingVerification.staging_copy_sha256}</code>
            </div>
            {stagingVerification.converted_artifact && (
              <div>
                <strong>Conversión de Formato (`qemu-img convert`):</strong>{" "}
                <code>{stagingVerification.converted_artifact.conversion_command || "RAW/VMDK listo para importación"}</code>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tabla de Discos y Particiones Detectados */}
      {disks.length > 0 && (
        <div>
          <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>
            Discos Físicos/Virtuales y Tabla de Particiones Detectados ({disks.length} discos)
          </h4>
          <div className="cm-table-wrap">
            <table className="cm-table">
              <thead>
                <tr>
                  <th>Dispositivo / Rol</th>
                  <th>Formato / Tamaño</th>
                  <th>Tabla / Etiquetas GPT</th>
                  <th>Particiones y Puntos de Montaje (fstab)</th>
                  <th>SHA-256 de Disco</th>
                </tr>
              </thead>
              <tbody>
                {disks.map((d) => (
                  <tr key={d.disk_id || d.device}>
                    <td>
                      <strong><code>{d.device}</code></strong>{" "}
                      <span className={`cm-badge ${d.is_boot ? "info" : "neutral"}`}>
                        {d.is_boot ? "BOOT DISK" : "DATA VOLUME"}
                      </span>
                    </td>
                    <td>
                      <code>{d.format}</code> · <strong>{d.size_gib} GiB</strong> ({d.used_gib} GiB en uso)
                    </td>
                    <td>
                      <code>{d.partition_table || "GPT"}</code>
                      {d.gpt_partition_labels?.length > 0 && (
                        <div className="cm-hint">{d.gpt_partition_labels.join(", ")}</div>
                      )}
                    </td>
                    <td>
                      {(d.partitions || []).map((p, pIdx) => (
                        <div key={p.device || p.name || pIdx} style={{ fontSize: 13.5 }}>
                          <code>{p.device || p.name || `part-${pIdx + 1}`}</code> → <strong>{p.mount_point || "[SWAP]"}</strong> ({p.filesystem}, {p.size_gib ? `${p.size_gib} GiB` : `${p.size_mib || 0} MiB`}, <code>{p.fstab_ref || (p.uuid ? `UUID=${p.uuid}` : "UUID")}</code>)
                        </div>
                      ))}
                    </td>
                    <td>
                      <code style={{ fontSize: 13 }}>{d.sha256?.slice(0, 20)}...</code>
                      <div>
                        <span className={`cm-badge ${d.binary_verified ? "observed" : "warning"}`} style={{ fontSize: 12.5 }}>
                          {d.binary_verified ? "Binario Verificado" : "Stub Simulado"}
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Selector Interactivo de Decisiones AWS Academy + Mapa de Transformación SO / VM -> Nube */}
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

      <div style={{ marginTop: 14 }}>
        <TargetArchitectureView
          job={{
            ...currentJob,
            source_config: {
              ...(currentJob.source_config || {}),
              user_decisions: jobDecisions,
            },
          }}
        />
      </div>

      <VmOsToCloudTransformationMap
        manifest={srcEnv}
        targetProvider={currentJob.target_provider}
      />

      {/* Procesos en Ejecución Capturados (ps) y Directorios del SO (Filesystem) */}
      <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>
        <details className="cm-accordion-shell">
          <summary className="cm-accordion-trigger">
            <span>
              Procesos en ejecución en el SO ({(srcEnv.running_processes || []).length})
            </span>
            <span className="cm-badge observed" style={{ fontSize: 11.5 }}>ps aux</span>
          </summary>
          <div className="cm-accordion-body" style={{ padding: 0 }}>
            <div style={{ maxHeight: 240, overflowY: "auto" }}>
              <table className="cm-table" style={{ margin: 0, fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>PID</th>
                    <th>Usuario</th>
                    <th>Proceso</th>
                    <th>CPU%</th>
                    <th>MEM%</th>
                  </tr>
                </thead>
                <tbody>
                  {(srcEnv.running_processes || []).slice(0, 25).map((proc, idx) => (
                    <tr key={`${proc.pid}-${idx}`}>
                      <td><code>{proc.pid}</code></td>
                      <td><code>{proc.user}</code></td>
                      <td><strong>{proc.name}</strong></td>
                      <td>{proc.cpu_percent}%</td>
                      <td>{proc.mem_percent}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </details>

        <details className="cm-accordion-shell">
          <summary className="cm-accordion-trigger">
            <span>
              Directorios del SO capturados ({(srcEnv.filesystem_inventory || srcEnv.filesystem_summary || []).length})
            </span>
            <span className="cm-badge info" style={{ fontSize: 11.5 }}>Filesystem</span>
          </summary>
          <div className="cm-accordion-body" style={{ padding: 0 }}>
            <div style={{ maxHeight: 240, overflowY: "auto" }}>
              <table className="cm-table" style={{ margin: 0, fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>Directorio</th>
                    <th>Archivos</th>
                    <th>Muestra Capturada</th>
                  </tr>
                </thead>
                <tbody>
                  {(srcEnv.filesystem_inventory || srcEnv.filesystem_summary || []).map((dir) => (
                    <tr key={dir.path}>
                      <td><strong><code>{dir.path}</code></strong></td>
                      <td>{dir.files_count ?? 0}</td>
                      <td><code>{(dir.sample_entries || []).slice(0, 5).join(", ")}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </details>
      </div>
    </div>
  );
}

export function Case2CompatibilityInspectionPanel({
  currentJob,
  fidelityDims,
  fidelityFilter,
  setFidelityFilter,
  diffReport,
}) {
  return (
    <>
      {/* Caso 2: Las 8 Dimensiones de Fidelidad (Preservado vs Modificado vs No Transferible vs Reconfiguración) */}
      {fidelityDims && (
        <div className="cm-card">
          <div className="cm-card-title">
            <span>
              Caso 2 · Evaluación de Fidelidad y Limitaciones Físicas ({Object.keys(fidelityDims).length} Dimensiones)
            </span>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {[
                { id: "ALL", label: "Todas (8)" },
                { id: "preserved", label: "Preservados" },
                { id: "modified_or_adapted", label: "Modificados / Adaptados" },
                { id: "not_preserved", label: "No Transferibles (RAM Volátil)" },
                { id: "requires_manual_reconfiguration", label: "Requieren Reconfiguración" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  className={`cm-btn sm ${fidelityFilter === tab.id ? "primary" : ""}`}
                  onClick={() => setFidelityFilter(tab.id)}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
            {Object.values(fidelityDims)
              .filter((dim) => fidelityFilter === "ALL" || dim.status === fidelityFilter)
              .map((dim) => {
                const meta = FIDELITY_STATUS_META[dim.status] || {
                  label: dim.status,
                  badgeClass: "info",
                };
                return (
                  <div key={dim.dimension} className="cm-card-subtle">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                      <strong style={{ fontSize: 13.5, color: "#16191f" }}>{dim.dimension}</strong>
                      <span className={`cm-badge ${meta.badgeClass}`} style={{ fontSize: 11.5 }}>
                        {meta.label}
                      </span>
                    </div>
                    {dim.detail && (
                      <details style={{ marginTop: 6 }}>
                        <summary style={{ cursor: "pointer", fontSize: 12, color: "#0972d3", fontWeight: 600 }}>
                          Ver detalle técnico
                        </summary>
                        <div style={{ marginTop: 4, fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.45 }}>
                          {dim.detail}
                        </div>
                      </details>
                    )}
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* Caso 2: Tabla de Diferencias de Configuración Previstas (diffReport.comparisons) */}
      {Array.isArray(diffReport?.comparisons) && (
        <div className="cm-card">
          <div className="cm-card-title">
            <span>
              Caso 2 · Diferencias de Configuración Previstas: Origen vs Instancia {currentJob.target_provider?.toUpperCase()}
            </span>
            <span className="cm-badge observed">
              Paridad Persistente en Disco: {diffReport.parity_score_percent}%
            </span>
          </div>
          <div className="cm-table-wrap">
            <table className="cm-table">
              <thead>
                <tr>
                  <th>Categoría del Sistema</th>
                  <th>Estado en Imagen de Origen</th>
                  <th>Estado Previsto en Instancia {currentJob.target_provider?.toUpperCase()}</th>
                  <th>Clasificación de Fidelidad</th>
                </tr>
              </thead>
              <tbody>
                {diffReport.comparisons.map((row) => {
                  const isPreserved = row.status?.includes("PRESERVED") && !row.status?.includes("NOT");
                  const isNotPreserved = row.status?.includes("NOT_PRESERVED") || row.status?.includes("VOLATILE");
                  return (
                    <tr key={row.category}>
                      <td>
                        <strong>{row.category}</strong>
                      </td>
                      <td>{row.source_value}</td>
                      <td>{row.target_expected_value}</td>
                      <td>
                        <span
                          className={`cm-badge ${
                            isNotPreserved ? "danger" : isPreserved ? "observed" : "derived"
                          }`}
                        >
                          {row.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
