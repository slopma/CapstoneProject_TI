import React from "react";
import UserFileSelectionPanel, {
  saveSelectedUserPathsToSession,
} from "./UserFileSelectionPanel";
import {
  ContextualTechnicalModal,
  HelpTooltipButton,
} from "./PlannedCloudStructureGraphModal";
import GithubToCloudTransformationSelector from "./GithubToCloudTransformationSelector";
import TargetArchitectureView from "./TargetArchitectureView";
import VmOsToCloudTransformationMap from "./VmOsToCloudTransformationMap";
import { copyTextToClipboard } from "../../utils/credentialVault";

export function WizardCase2SourceForm({
  showCase2HelpModal,
  setShowCase2HelpModal,
  uc2SourceMode,
  setUc2SourceMode,
  setUc2PreInspection,
  agentTokenData,
  enrolledAgents,
  generatingAgentToken,
  handleGenerateAgentToken,
  copiedAgentCmd,
  setCopiedAgentCmd,
  hostDevicesData,
  setHostDevicesData,
  selectedStorageDevice,
  setSelectedStorageDevice,
  queryingDevices,
  handleQueryLiveDevices,
  selectedUserPaths,
  setSelectedUserPaths,
  uc2Decisions,
  setUc2Decisions,
  setUc2StageMeta,
  setStatusBanner,
  uc2OutputFormat,
  setUc2OutputFormat,
  imagePath,
  setImagePath,
  imageFormatOverride,
  setImageFormatOverride,
  consistencyStrategy,
  setConsistencyStrategy,
}) {
  return (
    <div
      className="cm-card"
      style={{
        backgroundColor: "#fafafa",
        border: "1px solid #d5dbdb",
        borderRadius: 6,
        padding: "14px 16px",
        marginTop: 14,
        marginBottom: 14,
      }}
    >
      <ContextualTechnicalModal
        isOpen={showCase2HelpModal}
        onClose={() => setShowCase2HelpModal(false)}
        title="Caso 2 · Migración de Sistema Operativo / Imagen VM hacia AWS"
        badge="AWS Nitro & VM Import"
        whyTransformed="CloudMove ejecuta el agente en modo solo lectura o valida la imagen binaria (qemu-img info + SHA-256), adaptando el disco hacia Amazon EBS gp3 respetando el límite por volumen de AWS Academy (100 GiB) y preservando exclusivamente los archivos seleccionados por el usuario."
        customSections={[
          {
            heading: "Consistencia de Snapshot vs RAM Volátil",
            body: "Los hipervisores en la nube requieren discos consistentes (vía sync / quiesce o replicación de bloques AWS MGN). La memoria RAM volátil en ejecución y sockets TCP activos no se transfieren directamente; los servicios systemd se reinician de manera limpia en Amazon EC2 mediante Cloud-Init.",
          },
        ]}
      />

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span className="cm-badge aws">CASO 2 · VM / SO</span>
          <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#000716" }}>
            Origen del Sistema Operativo hacia Amazon EC2
          </h4>
          <HelpTooltipButton
            label="¿Cómo funciona?"
            onClick={() => setShowCase2HelpModal(true)}
          />
        </div>

        {/* Selector de Modalidad */}
        <div style={{ display: "flex", gap: 4, backgroundColor: "#e2e8f0", padding: 3, borderRadius: 6, flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={() => {
              setUc2SourceMode("live_capture");
              setUc2PreInspection(null);
            }}
            style={{
              border: "none",
              backgroundColor: uc2SourceMode === "live_capture" ? "#ffffff" : "transparent",
              color: uc2SourceMode === "live_capture" ? "#0972d3" : "#414d5c",
              fontWeight: uc2SourceMode === "live_capture" ? 700 : 500,
              padding: "6px 12px",
              borderRadius: 4,
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            Agente en Vivo
          </button>
          <button
            type="button"
            onClick={() => {
              setUc2SourceMode("file_path");
              setUc2PreInspection(null);
            }}
            style={{
              border: "none",
              backgroundColor: uc2SourceMode === "file_path" ? "#ffffff" : "transparent",
              color: uc2SourceMode === "file_path" ? "#0972d3" : "#414d5c",
              fontWeight: uc2SourceMode === "file_path" ? 700 : 500,
              padding: "6px 12px",
              borderRadius: 4,
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            Imagen de Disco (.vmdk / .qcow2)
          </button>
        </div>
      </div>

      {uc2SourceMode === "live_capture" ? (
        <div style={{ marginBottom: 14 }}>
          {/* PASO 1 OBLIGATORIO: Generar Token de Inscripción del Agente Remoto */}
          <div
            style={{
              padding: "14px 16px",
              backgroundColor: "#ffffff",
              border: agentTokenData?.token || enrolledAgents.length > 0 ? "1.5px solid #0972D3" : "2px solid #f59e0b",
              borderRadius: 6,
              marginBottom: 12,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span className="cm-badge" style={{ backgroundColor: "#0972D3", color: "#ffffff", fontWeight: 700, fontSize: 12 }}>
                    PASO 1 DE 3 · OBLIGATORIO
                  </span>
                  <strong style={{ fontSize: 14, color: "#000716" }}>
                    Generar Token de Inscripción del Agente Remoto
                  </strong>
                  {agentTokenData?.token ? (
                    <span className="cm-badge observed">
                      Token Activo en Sesión ({agentTokenData.fingerprint || "sha256"})
                    </span>
                  ) : enrolledAgents.length > 0 ? (
                    <span className="cm-badge observed">
                      {enrolledAgents.length} Agente(s) Remoto(s) Conectado(s)
                    </span>
                  ) : (
                    <span className="cm-badge warning">
                      Pendiente — Genera el token primero
                    </span>
                  )}
                </div>
                <p style={{ margin: "4px 0 0 0", fontSize: 13, color: "#414d5c" }}>
                  El flujo del Caso 2 es estrictamente secuencial: genera primero el token de inscripción (<code>cmat_...</code>) para vincular el servidor o máquina virtual remota antes de ejecutar la captura y migración.
                </p>
              </div>

              <button
                type="button"
                className="cm-btn primary sm"
                onClick={handleGenerateAgentToken}
                disabled={generatingAgentToken}
              >
                {generatingAgentToken
                  ? "Generando Token..."
                  : agentTokenData?.token
                  ? "Regenerar Token del Agente"
                  : "Paso 1: Generar Token del Agente Remoto"}
              </button>
            </div>

            {agentTokenData && (agentTokenData.token || agentTokenData.enrollment_token) && (
              <div
                style={{
                  marginTop: 10,
                  padding: "10px 12px",
                  backgroundColor: "#f8fafc",
                  border: "1px solid #cbd5e1",
                  borderRadius: 4,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 6 }}>
                  <span style={{ fontSize: 12.5, fontWeight: 700, color: "#0f172a" }}>
                    Token generado: <code>{agentTokenData.token || agentTokenData.enrollment_token}</code>
                  </span>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="cm-btn sm secondary"
                      onClick={async () => {
                        const rawTok = agentTokenData.token || agentTokenData.enrollment_token;
                        await copyTextToClipboard(rawTok);
                        setCopiedAgentCmd("token_only");
                        setTimeout(() => setCopiedAgentCmd(""), 2500);
                      }}
                    >
                      {copiedAgentCmd === "token_only" ? "Token Copiado" : "Copiar Solo Token"}
                    </button>
                    <button
                      type="button"
                      className="cm-btn sm secondary"
                      onClick={async () => {
                        const rawTok = agentTokenData.token || agentTokenData.enrollment_token;
                        const installCmd =
                          agentTokenData.install_command_linux ||
                          `curl -sSL ${window.location.origin}/api/v1/agents/install.sh | sudo bash -s -- --token ${rawTok} --server ${window.location.origin}`;
                        await copyTextToClipboard(installCmd);
                        setCopiedAgentCmd("install");
                        setTimeout(() => setCopiedAgentCmd(""), 2500);
                      }}
                    >
                      {copiedAgentCmd === "install" ? "Comando Copiado" : "Copiar Comando de Instalación Linux/macOS"}
                    </button>
                  </div>
                </div>
                <pre
                  style={{
                    margin: 0,
                    padding: "8px 10px",
                    backgroundColor: "#0f172a",
                    color: "#e2e8f0",
                    borderRadius: 4,
                    fontSize: 12,
                    overflowX: "auto",
                  }}
                >
                  {agentTokenData.install_command_linux ||
                    `curl -sSL ${typeof window !== "undefined" ? window.location.origin : ""}/api/v1/agents/install.sh | sudo bash -s -- --token ${agentTokenData.token || agentTokenData.enrollment_token} --server ${typeof window !== "undefined" ? window.location.origin : ""}`}
                </pre>
              </div>
            )}
          </div>

          {/* PASO 2: Panel de Consulta en Vivo de Dispositivos del Agente Remoto */}
          <div
            style={{
              padding: "14px 16px",
              backgroundColor: "#ffffff",
              border: "1px solid #86efac",
              borderRadius: 8,
              marginBottom: 14,
              opacity: agentTokenData?.token || enrolledAgents.length > 0 ? 1 : 0.55,
              pointerEvents: agentTokenData?.token || enrolledAgents.length > 0 ? "auto" : "none",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 10 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="cm-badge" style={{ backgroundColor: "#14532d", color: "#ffffff", fontSize: 12.5, fontWeight: 700 }}>PASO 2 DE 3 · TELEMETRÍA REMOTA</span>
                  <span style={{ fontWeight: 700, fontSize: 13.5, color: "#14532d" }}>
                    Dispositivos y Particiones del Equipo Origen Remoto
                  </span>
                  {hostDevicesData?.queried_at && (
                    <span className="cm-badge observed" style={{ fontSize: 12.5 }}>
                      Consulta Ejecutada: {new Date(hostDevicesData.queried_at).toLocaleTimeString()}
                    </span>
                  )}
                </div>
                <p style={{ margin: "3px 0 0 0", fontSize: 13.5, color: "#475569" }}>
                  Una vez ejecutado el agente en el servidor origen, consulta su topología de discos y particiones remotas (el servidor donde se ejecuta CloudMove permanece oculto por seguridad).
                </p>
              </div>

              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button
                  type="button"
                  className="cm-btn secondary sm"
                  onClick={() => handleQueryLiveDevices(true)}
                  disabled={queryingDevices || !(agentTokenData?.token || enrolledAgents.length > 0)}
                  style={{ whiteSpace: "nowrap" }}
                >
                  {queryingDevices
                    ? "Consultando Agente Remoto..."
                    : hostDevicesData
                    ? "Re-consultar Agente Remoto"
                    : "Paso 2: Consultar Dispositivos del Agente Remoto"}
                </button>
                {hostDevicesData && (
                  <button
                    type="button"
                    className="cm-btn sm"
                    onClick={() => {
                      setHostDevicesData(null);
                      setSelectedStorageDevice("");
                    }}
                    style={{ fontSize: 13, padding: "4px 8px" }}
                    title="Limpiar datos detectados del agente"
                  >
                    Limpiar Consulta
                  </button>
                )}
              </div>
            </div>

            {hostDevicesData?.host && hostDevicesData.host.hostname && !["cloudmove-server", "localhost", "127.0.0.1"].includes(String(hostDevicesData.host.hostname).toLowerCase()) && !/^[0-9a-f]{12}$/i.test(String(hostDevicesData.host.hostname)) && (
              <div
                style={{
                  backgroundColor: "#f8fafc",
                  border: "1px solid #e2e8f0",
                  borderRadius: 6,
                  padding: "8px 12px",
                  marginBottom: 10,
                  fontSize: 13.5,
                  color: "#334155",
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 16,
                }}
              >
                <div>Agente Remoto: <strong><code>{hostDevicesData.host.hostname}</code></strong></div>
                <div>Distribución: <strong>{hostDevicesData.host.distro}</strong> ({hostDevicesData.host.version})</div>
                <div>Kernel: <strong><code>{hostDevicesData.host.kernel}</code></strong></div>
                <div>Arranque: <strong>{hostDevicesData.host.boot_mode} ({hostDevicesData.host.partition_scheme})</strong></div>
                <div>Memoria RAM: <strong>{hostDevicesData.host.ram_total_gib} GiB</strong></div>
              </div>
            )}

            {/* Lista Limpia de Dispositivos de Bloque Reales (Con particiones colapsables) */}
            {hostDevicesData?.devices?.length > 0 ? (
              <div className="cm-choice-cards-grid" style={{ marginBottom: 10 }}>
                {hostDevicesData.devices.map((dev) => {
                  const isPrimary = dev.is_boot_device || dev.path === selectedStorageDevice;
                  const isChecked = selectedStorageDevice === dev.path || (!selectedStorageDevice && isPrimary);
                  return (
                    <div
                      key={dev.name}
                      className={`cm-choice-card ${isChecked ? "is-selected" : ""}`}
                      onClick={() => setSelectedStorageDevice(dev.path)}
                    >
                      <div>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 6 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <input
                              type="radio"
                              id={`dev-${dev.name}`}
                              name="selected_device"
                              checked={isChecked}
                              onChange={() => setSelectedStorageDevice(dev.path)}
                              style={{ cursor: "pointer" }}
                            />
                            <label htmlFor={`dev-${dev.name}`} style={{ cursor: "pointer", fontWeight: 700, fontSize: 13.5, color: "#000716" }}>
                              <code>{dev.path}</code>
                            </label>
                          </div>
                          <span className="cm-badge observed" style={{ fontSize: 11.5 }}>
                            {dev.size_gib} GiB
                          </span>
                        </div>
                        <div className="cm-hint" style={{ marginLeft: 20 }}>
                          {dev.model} {dev.is_boot_device ? "· Disco Principal" : ""}
                        </div>
                      </div>

                      {dev.partitions?.length > 0 && (
                        <details
                          style={{ marginLeft: 20, marginTop: 4 }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <summary style={{ fontSize: 12, fontWeight: 700, color: "#0972d3", cursor: "pointer" }}>
                            Ver {dev.partitions.length} partición(es) y UUIDs
                          </summary>
                          <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
                            {dev.partitions.map((p) => (
                              <div
                                key={p.name}
                                style={{
                                  fontSize: 12,
                                  color: "#414d5c",
                                  backgroundColor: "#f8fafc",
                                  padding: "4px 8px",
                                  borderRadius: 4,
                                  border: "1px solid #eaeded",
                                  display: "flex",
                                  justifyContent: "space-between",
                                  gap: 6,
                                  flexWrap: "wrap",
                                }}
                              >
                                <span>
                                  <code>{p.path}</code> {p.mount_point ? `(${p.mount_point})` : ""} · {p.filesystem}
                                </span>
                                <strong>{p.size_gib} GiB</strong>
                              </div>
                            ))}
                          </div>
                        </details>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ fontSize: 14, color: "#64748b", padding: "16px 12px", textAlign: "center", backgroundColor: "#f8fafc", borderRadius: 6, border: "1px dashed #cbd5e1" }}>
                {queryingDevices
                  ? "Ejecutando consulta de hardware y carpetas en tiempo real desde el agente..."
                  : "Haz clic en 'Paso 2: Consultar Dispositivos del Agente Remoto' arriba para cargar los discos, carpetas y archivos de tu equipo."}
              </div>
            )}

            {/* Selector Interactivo de Carpetas y Archivos del Usuario con Control de Cuota AWS */}
            <UserFileSelectionPanel
              filesystemTree={hostDevicesData?.filesystem_tree || []}
              selectedPaths={selectedUserPaths}
              onChangeSelectedPaths={(paths) => {
                setSelectedUserPaths(paths);
                saveSelectedUserPathsToSession(paths);
              }}
              maxAwsStorageGib={
                uc2Decisions.ebs_storage_sizing === "aws_academy_max_100gb"
                  ? 100.0
                  : uc2Decisions.ebs_storage_sizing === "full_physical_capacity"
                  ? 150.0
                  : 30.0
              }
              baseOsOverheadGib={2.5}
              awsAcademyAccountLimitGib={150.0}
              onUpgradeStorageProfile={(newSizing) =>
                setUc2Decisions((prev) => ({
                  ...prev,
                  ebs_storage_sizing: newSizing,
                }))
              }
              onRefreshAgentInventory={() => handleQueryLiveDevices(true)}
              refreshing={queryingDevices}
              hostname={
                hostDevicesData?.host?.hostname ||
                enrolledAgents[0]?.hostname ||
                "dispositivo-local"
              }
              agentId={
                hostDevicesData?.agent_id ||
                enrolledAgents[0]?.agent_id ||
                null
              }
              onStageReady={setUc2StageMeta}
              onCopy={(txt, msg) => {
                navigator.clipboard?.writeText(txt);
                setStatusBanner(msg || "Copiado al portapapeles");
              }}
            />
          </div>

          {/* Formato de Salida */}
          <div className="cm-field">
            <label htmlFor="uc2-output-format-select" className="cm-label" style={{ fontWeight: 600, color: "#1e293b" }}>
              Formato de Imagen de Disco de Salida para la Nube
            </label>
            <select
              id="uc2-output-format-select"
              className="cm-select"
              value={uc2OutputFormat}
              onChange={(e) => setUc2OutputFormat(e.target.value)}
              style={{ backgroundColor: "#ffffff" }}
            >
              <option value="QCOW2">QCOW2 (Recomendado para KVM y Staging Optimizado en AWS)</option>
              <option value="RAW">RAW (Recomendado para AWS VM Import / EBS)</option>
              <option value="VMDK">VMDK (Compatible VMware)</option>
            </select>
            <span className="cm-hint">
              Crea la imagen con <code>qemu-img</code> y empaqueta la configuración <code>/etc</code> (fstab, red, host) en <code>os_config_bundle.tar.gz</code>.
            </span>
          </div>
        </div>
      ) : (
        <div className="cm-form-grid" style={{ marginBottom: 12 }}>
          <div className="cm-field">
            <label htmlFor="uc2-image-path" className="cm-label" style={{ fontWeight: 600, color: "#1e293b" }}>
              Ruta del Archivo de Imagen de Disco / SO *
            </label>
            <input
              id="uc2-image-path"
              type="text"
              className="cm-input"
              placeholder="Ej. /var/lib/libvirt/images/servidor.qcow2 o ./disk.vmdk"
              value={imagePath}
              onChange={(e) => {
                setImagePath(e.target.value);
                setUc2PreInspection(null);
                const ext = e.target.value.split(".").pop()?.toUpperCase();
                if (["VMDK", "QCOW2", "RAW", "VHDX", "OVA"].includes(ext)) {
                  setImageFormatOverride(ext);
                }
              }}
              style={{ backgroundColor: "#ffffff" }}
            />
            <span className="cm-hint">Soporta formatos VMDK (VMware), QCOW2 (KVM/Proxmox), VHDX (Hyper-V) y RAW.</span>
          </div>

          <div className="cm-field">
            <label htmlFor="uc2-format-select" className="cm-label" style={{ fontWeight: 600, color: "#1e293b" }}>
              Formato de Imagen Declarado
            </label>
            <select
              id="uc2-format-select"
              className="cm-select"
              value={imageFormatOverride}
              onChange={(e) => setImageFormatOverride(e.target.value)}
              style={{ backgroundColor: "#ffffff" }}
            >
              <option value="VMDK">VMDK (VMware Sparse / StreamOptimized)</option>
              <option value="QCOW2">QCOW2 (KVM / Proxmox — Conversión automática)</option>
              <option value="VHDX">VHDX (Microsoft Hyper-V)</option>
              <option value="RAW">RAW Disk Image</option>
              <option value="OVA">OVA Appliance</option>
            </select>
            <span className="cm-hint">La cabecera binaria real se validará contra este formato.</span>
          </div>
        </div>
      )}

      {/* Estrategia de Consistencia de Datos y Transferencia en Tarjetas Comparativas */}
      <div
        style={{
          marginTop: 12,
          padding: "12px 14px",
          backgroundColor: "#ffffff",
          borderRadius: 6,
          border: "1px solid #d5dbdb",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
          <strong style={{ fontSize: 13.5, color: "#000716" }}>
            Estrategia de Consistencia en Snapshot / Transferencia AWS
          </strong>
          <HelpTooltipButton
            label="Comparativa técnica"
            onClick={() => setShowCase2HelpModal(true)}
          />
        </div>
        <div className="cm-choice-cards-grid">
          {[
            {
              id: "quiesced_snapshot",
              title: "Snapshot Quiesced",
              badge: "Recomendado",
              badgeClass: "observed",
              desc: "Vaciado sync() de discos y reinicio limpio en EC2.",
            },
            {
              id: "continuous_replication",
              title: "Replicación AWS MGN",
              badge: "Mínimo downtime",
              badgeClass: "info",
              desc: "Sincronización continua de bloques en segundo plano.",
            },
            {
              id: "demo_live_ram",
              title: "Exigir RAM Volátil",
              badge: "Simular bloqueo",
              badgeClass: "danger",
              desc: "Audita incompatibilidad física de RAM entre hipervisores.",
            },
          ].map((strat) => {
            const active = consistencyStrategy === strat.id;
            return (
              <label
                key={strat.id}
                className={`cm-choice-card ${active ? "is-selected" : ""}`}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6, marginBottom: 4 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <input
                        type="radio"
                        name="consistency_strategy"
                        value={strat.id}
                        checked={active}
                        onChange={() => setConsistencyStrategy(strat.id)}
                        style={{ cursor: "pointer" }}
                      />
                      <strong style={{ fontSize: 13.5, color: active ? "#0972d3" : "#000716" }}>
                        {strat.title}
                      </strong>
                    </div>
                    <span className={`cm-badge ${strat.badgeClass}`} style={{ fontSize: 11 }}>
                      {strat.badge}
                    </span>
                  </div>
                  <div className="cm-hint" style={{ marginLeft: 20 }}>
                    {strat.desc}
                  </div>
                </div>
              </label>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function WizardCase2PreInspectionPreview({
  uc2PreInspection,
  hostDevicesData,
  uc2Decisions,
  setUc2Decisions,
  newProvider,
  consistencyStrategy,
}) {
  if (!(uc2PreInspection?.transformation_catalog || hostDevicesData?.transformation_catalog)) {
    return null;
  }

  return (
    <div className="cm-step-card" style={{ marginTop: 14 }}>
      {uc2PreInspection?.manifest && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <strong style={{ fontSize: 14.5, color: "#000716" }}>
                {uc2PreInspection.manifest.is_live_capture
                  ? `Captura SO en Vivo: ${uc2PreInspection.manifest.name}`
                  : `Pre-Inspección Binaria: ${uc2PreInspection.manifest.name}`} ({uc2PreInspection.manifest.format})
              </strong>
              <span className={`cm-badge ${uc2PreInspection.manifest.is_authentic_binary_image ? "observed" : "warning"}`}>
                {uc2PreInspection.manifest.binary_inspection?.authenticity_classification || "Binario Verificado"}
              </span>
            </div>
            <span className="cm-badge observed">
              Snapshot: {uc2PreInspection.manifest.snapshot_consistency?.consistency_type || "quiesced"}
            </span>
          </div>

          <div className="cm-kpi-grid">
            <div className="cm-kpi-card">
              <span className="cm-kpi-label">Sistema Operativo y Arranque</span>
              <span className="cm-kpi-value" style={{ fontSize: 14.5 }}>
                {uc2PreInspection.manifest.os?.distro} {uc2PreInspection.manifest.os?.version}
              </span>
              <span className="cm-kpi-meta">
                {uc2PreInspection.manifest.boot_mode} ({uc2PreInspection.manifest.partition_scheme}) · {uc2PreInspection.manifest.os?.architecture}
              </span>
            </div>
            <div className="cm-kpi-card">
              <span className="cm-kpi-label">Volumen EBS en AWS</span>
              <span className="cm-kpi-value" style={{ fontSize: 14.5 }}>
                {uc2Decisions.ebs_storage_sizing === "aws_academy_max_100gb"
                  ? "100 GiB gp3"
                  : uc2Decisions.ebs_storage_sizing === "full_physical_capacity"
                  ? `${uc2PreInspection.manifest.total_provisioned_gib} GiB gp3`
                  : "30 GiB gp3 (Free Tier)"}
              </span>
              <span className="cm-kpi-meta">
                Origen: {uc2PreInspection.manifest.total_used_gib} GiB en uso / {uc2PreInspection.manifest.total_provisioned_gib} GiB prov.
              </span>
            </div>
            <div className="cm-kpi-card">
              <span className="cm-kpi-label">Telemetría del Equipo</span>
              <span className="cm-kpi-value" style={{ fontSize: 14.5 }}>
                {uc2PreInspection.manifest.installed_packages_summary?.total_count || 0} paq · {(uc2PreInspection.manifest.running_processes || []).length} proc
              </span>
              <span className="cm-kpi-meta">
                Usuarios: {(uc2PreInspection.manifest.local_users || ["root"]).slice(0, 3).join(", ")}
              </span>
            </div>
            <div className="cm-kpi-card">
              <span className="cm-kpi-label">Integridad SHA-256</span>
              <span className="cm-kpi-value" style={{ fontSize: 13.5, fontFamily: "monospace" }}>
                {String(uc2PreInspection.manifest.sha256 || "").slice(0, 16)}...
              </span>
              <span className="cm-kpi-meta">
                Snapshot listo para AWS EC2
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Selector Interactivo de Opciones de Tamaño EBS, Cómputo, Instancia y Puertos (Caso 2) */}
      <GithubToCloudTransformationSelector
        catalog={
          uc2PreInspection?.transformation_catalog ||
          uc2PreInspection?.manifest?.transformation_catalog ||
          hostDevicesData?.transformation_catalog
        }
        decisions={uc2Decisions}
        onSelectDecision={(itemId, optId) =>
          setUc2Decisions((prev) => ({ ...prev, [itemId]: optId }))
        }
        targetProvider={newProvider}
        isJobView={false}
      />

      {/* Gráfica Interactiva en Vivo de Cómo Quedará la Arquitectura en la Nube según las Opciones Escogidas (Caso 2) */}
      <div style={{ marginTop: 14 }}>
        <TargetArchitectureView
          job={{
            use_case: "vm_image",
            target_provider: newProvider,
            name:
              uc2PreInspection?.manifest?.name ||
              (hostDevicesData?.host?.hostname
                ? `${hostDevicesData.host.hostname}-live-os`
                : "live-os"),
            source_environment: uc2PreInspection?.manifest || {
              name: hostDevicesData?.host?.hostname
                ? `${hostDevicesData.host.hostname}-live-os`
                : "live-os",
              boot_mode: hostDevicesData?.host?.boot_mode || "UEFI",
              partition_scheme: hostDevicesData?.host?.partition_scheme || "GPT",
              total_provisioned_gib: hostDevicesData?.primary_boot_device?.size_gib || 476,
              total_used_gib: hostDevicesData?.root_mount_info?.used_gib || 15,
              os: {
                distro: hostDevicesData?.host?.distro || "Linux",
                version: hostDevicesData?.host?.version || "",
                kernel: hostDevicesData?.host?.kernel || "",
              },
              disks: [
                {
                  device: hostDevicesData?.primary_boot_device?.path || "/dev/nvme0n1",
                  size_gib: hostDevicesData?.primary_boot_device?.size_gib || 476,
                },
              ],
              listening_ports: [80, 443, 3000, 5173, 8000],
            },
            source_config: { user_decisions: uc2Decisions },
          }}
        />
      </div>

      {uc2PreInspection?.manifest && (
        <VmOsToCloudTransformationMap
          manifest={uc2PreInspection.manifest}
          targetProvider={newProvider}
          consistencyStrategy={consistencyStrategy}
        />
      )}
    </div>
  );
}
