import React, { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../../utils/apiClient";

export default function AwsCloudAuditPanel({
  initialCredentials = null,
  onAuditCompleted = null,
}) {
  const [awsAccessKeyId, setAwsAccessKeyId] = useState(
    initialCredentials?.aws_access_key_id || ""
  );
  const [awsSecretAccessKey, setAwsSecretAccessKey] = useState(
    initialCredentials?.aws_secret_access_key || ""
  );
  const [awsSessionToken, setAwsSessionToken] = useState(
    initialCredentials?.aws_session_token || ""
  );
  const [awsRegion, setAwsRegion] = useState(
    initialCredentials?.aws_region || "us-east-1"
  );
  const [rawPasteBlock, setRawPasteBlock] = useState("");
  const [showCredsForm, setShowCredsForm] = useState(false);

  const [auditData, setAuditData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [actionLoadingId, setActionLoadingId] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);
  const [confirmDeleteKey, setConfirmDeleteKey] = useState(null);
  const [activeSubSection, setActiveSubSection] = useState("instances"); // "instances" | "workspaces" | "storage_network"

  // Auto-parse AWS Academy CLI credentials block if pasted
  const handleParseRawBlock = (text) => {
    setRawPasteBlock(text);
    const akMatch = text.match(/aws_access_key_id\s*=\s*([^\s\r\n"']+)/i);
    const skMatch = text.match(/aws_secret_access_key\s*=\s*([^\s\r\n"']+)/i);
    const stMatch = text.match(/aws_session_token\s*=\s*([^\s\r\n"']+)/i);
    if (akMatch) setAwsAccessKeyId(akMatch[1].trim());
    if (skMatch) setAwsSecretAccessKey(skMatch[1].trim());
    if (stMatch) setAwsSessionToken(stMatch[1].trim());
  };

  const buildCredsPayload = useCallback(() => {
    if (awsAccessKeyId.trim() && awsSecretAccessKey.trim()) {
      const c = {
        aws_access_key_id: awsAccessKeyId.trim(),
        aws_secret_access_key: awsSecretAccessKey.trim(),
        aws_region: awsRegion.trim() || "us-east-1",
      };
      if (awsSessionToken.trim()) {
        c.aws_session_token = awsSessionToken.trim();
      }
      return c;
    }
    if (
      initialCredentials?.aws_access_key_id &&
      initialCredentials?.aws_secret_access_key
    ) {
      return initialCredentials;
    }
    return null;
  }, [
    awsAccessKeyId,
    awsSecretAccessKey,
    awsSessionToken,
    awsRegion,
    initialCredentials,
  ]);

  const runAudit = useCallback(
    async (explicitCreds = null) => {
      setLoading(true);
      setActionMessage(null);
      try {
        const creds = explicitCreds || buildCredsPayload();
        const res = await apiFetch("/api/v1/migration/cloud-audit/aws", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ credentials: creds }),
        });
        const data = await res.json();
        setAuditData(data);
        if (!data.authenticated) {
          setShowCredsForm(true);
        }
        if (typeof onAuditCompleted === "function") {
          onAuditCompleted(data);
        }
      } catch (err) {
        setAuditData({
          authenticated: false,
          error: `Error de red al consultar auditoría AWS: ${err.message}`,
          instances: [],
          volumes: [],
          vpcs: [],
          workspaces: [],
        });
      } finally {
        setLoading(false);
      }
    },
    [buildCredsPayload, onAuditCompleted]
  );

  useEffect(() => {
    runAudit();
  }, [runAudit]);

  const handleDeleteResource = async (
    resourceType,
    resourceId,
    cleanupVpc = true
  ) => {
    setActionLoadingId(`${resourceType}:${resourceId}`);
    setActionMessage(null);
    try {
      const creds = buildCredsPayload();
      const res = await apiFetch(
        "/api/v1/migration/cloud-audit/aws/delete-resource",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            resource_type: resourceType,
            resource_id: resourceId,
            cleanup_vpc: cleanupVpc,
            credentials: creds,
          }),
        }
      );
      const data = await res.json();
      if (data.success) {
        setActionMessage({
          type: "success",
          text: (data.details || [`Recurso ${resourceId} eliminado.`]).join(
            " · "
          ),
        });
        setConfirmDeleteKey(null);
        await runAudit(creds);
      } else {
        setActionMessage({
          type: "error",
          text: data.error || `No se pudo eliminar ${resourceId}.`,
        });
      }
    } catch (err) {
      setActionMessage({
        type: "error",
        text: `Error al eliminar recurso: ${err.message}`,
      });
    } finally {
      setActionLoadingId(null);
    }
  };

  const summary = auditData?.summary || {};
  const instances = auditData?.instances || [];
  const workspaces = auditData?.workspaces || [];
  const volumes = auditData?.volumes || [];
  const vpcs = auditData?.vpcs || [];
  const ipSyncEvents = auditData?.ip_sync_events || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Cabecera de Auditoría Cloud */}
      <div
        style={{
          backgroundColor: "#ffffff",
          border: "1px solid #cbd5e1",
          borderRadius: 8,
          padding: 16,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 10,
          }}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 18 }}>🛡️</span>
              <h3 style={{ margin: 0, fontSize: 16, color: "#0f172a" }}>
                Auditoría en Vivo de Cuenta AWS y Workspaces Terraform
              </h3>
              {auditData?.authenticated && (
                <span
                  style={{
                    backgroundColor: "#dcfce7",
                    color: "#166534",
                    border: "1px solid #86efac",
                    borderRadius: 999,
                    padding: "2px 10px",
                    fontSize: 11.5,
                    fontWeight: 700,
                  }}
                >
                  ● Conectado a AWS ({auditData.account_id} · {auditData.region})
                </span>
              )}
            </div>
            <p
              style={{
                margin: "4px 0 0 0",
                fontSize: 12.5,
                color: "#475569",
              }}
            >
              Consulta en tiempo real todas las instancias EC2, volúmenes EBS,
              redes VPC y estados de Terraform que corren en tu cuenta AWS,
              sincroniza IPs dinámicas y elimina recursos huérfanos con un clic.
            </p>
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              className="cm-btn sm secondary"
              onClick={() => setShowCredsForm((v) => !v)}
            >
              {showCredsForm
                ? "Ocultar Credenciales AWS"
                : "🔑 Actualizar Credenciales AWS Academy"}
            </button>
            <button
              type="button"
              className="cm-btn sm primary"
              onClick={() => runAudit()}
              disabled={loading}
            >
              {loading
                ? "Auditando cuenta AWS..."
                : "↻ Escanear Recursos en AWS Ahora"}
            </button>
          </div>
        </div>

        {/* Formulario desplegable de credenciales AWS Academy */}
        {showCredsForm && (
          <div
            style={{
              backgroundColor: "#f8fafc",
              border: "1px solid #cbd5e1",
              borderRadius: 6,
              padding: 12,
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            <div style={{ fontSize: 12.5, fontWeight: 700, color: "#0f172a" }}>
              Credenciales de AWS Academy Learner Lab (AWS Details)
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                gap: 10,
              }}
            >
              <div>
                <label
                  style={{
                    display: "block",
                    fontSize: 11.5,
                    fontWeight: 600,
                    marginBottom: 4,
                  }}
                >
                  Pega aquí el bloque completo de AWS CLI (Auto-rellena):
                </label>
                <textarea
                  rows={4}
                  className="cm-input"
                  style={{ fontFamily: "monospace", fontSize: 11.5 }}
                  placeholder={
                    "aws_access_key_id=ASIA...\naws_secret_access_key=...\naws_session_token=..."
                  }
                  value={rawPasteBlock}
                  onChange={(e) => handleParseRawBlock(e.target.value)}
                />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div>
                  <label style={{ fontSize: 11, fontWeight: 600 }}>
                    AWS Access Key ID:
                  </label>
                  <input
                    type="text"
                    className="cm-input"
                    style={{ fontFamily: "monospace", fontSize: 12 }}
                    value={awsAccessKeyId}
                    onChange={(e) => setAwsAccessKeyId(e.target.value)}
                    placeholder="ASIA..."
                  />
                </div>
                <div>
                  <label style={{ fontSize: 11, fontWeight: 600 }}>
                    AWS Secret Access Key:
                  </label>
                  <input
                    type="password"
                    className="cm-input"
                    style={{ fontFamily: "monospace", fontSize: 12 }}
                    value={awsSecretAccessKey}
                    onChange={(e) => setAwsSecretAccessKey(e.target.value)}
                    placeholder="••••••••••••"
                  />
                </div>
                <div>
                  <label style={{ fontSize: 11, fontWeight: 600 }}>
                    AWS Session Token:
                  </label>
                  <input
                    type="password"
                    className="cm-input"
                    style={{ fontFamily: "monospace", fontSize: 12 }}
                    value={awsSessionToken}
                    onChange={(e) => setAwsSessionToken(e.target.value)}
                    placeholder="IQoJb3JpZ2luX2Vj..."
                  />
                </div>
              </div>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button
                type="button"
                className="cm-btn sm primary"
                onClick={() => runAudit()}
                disabled={loading}
              >
                Guardar y Auditar Cuenta AWS
              </button>
            </div>
          </div>
        )}

        {/* Mensaje de error de autenticación si ocurre */}
        {auditData && !auditData.authenticated && (
          <div
            style={{
              backgroundColor: "#fef2f2",
              border: "1px solid #fecaca",
              borderRadius: 6,
              padding: "10px 12px",
              color: "#991b1b",
              fontSize: 12.5,
            }}
          >
            <strong>⚠️ No se pudo conectar a AWS EC2:</strong> {auditData.error}
          </div>
        )}

        {/* Aviso si se sincronizaron IPs dinámicas automáticamente */}
        {ipSyncEvents.length > 0 && (
          <div
            style={{
              backgroundColor: "#eff6ff",
              border: "1px solid #93c5fd",
              borderRadius: 6,
              padding: "10px 12px",
              color: "#1e40af",
              fontSize: 12.5,
            }}
          >
            <strong>🔄 IP Pública Dinámica Sincronizada Automáticamente:</strong>{" "}
            {ipSyncEvents.map((ev, i) => (
              <span key={i}>
                El despliegue <code>{ev.migration_id}</code> (instancia{" "}
                <code>{ev.instance_id}</code>) cambió su IP de{" "}
                <del>{ev.old_ip}</del> a <strong>{ev.new_ip}</strong> tras el
                reinicio de AWS. El estado de Terraform ha sido actualizado.{" "}
              </span>
            ))}
          </div>
        )}

        {/* Mensaje de confirmación de acción (eliminación, etc.) */}
        {actionMessage && (
          <div
            style={{
              backgroundColor:
                actionMessage.type === "success" ? "#f0fdf4" : "#fef2f2",
              border: `1px solid ${
                actionMessage.type === "success" ? "#86efac" : "#fecaca"
              }`,
              borderRadius: 6,
              padding: "10px 12px",
              color: actionMessage.type === "success" ? "#166534" : "#991b1b",
              fontSize: 12.5,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>
              <strong>
                {actionMessage.type === "success" ? "✅ Éxito:" : "⚠️ Error:"}
              </strong>{" "}
              {actionMessage.text}
            </span>
            <button
              type="button"
              className="cm-btn sm secondary"
              onClick={() => setActionMessage(null)}
              style={{ padding: "2px 6px", fontSize: 11 }}
            >
              Cerrar
            </button>
          </div>
        )}

        {/* Tarjetas KPI de Resumen */}
        {auditData?.authenticated && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              gap: 10,
            }}
          >
            <div
              style={{
                backgroundColor: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 6,
                padding: "10px 12px",
              }}
            >
              <div style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>
                INSTANCIAS EC2 EN EJECUCIÓN
              </div>
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 800,
                  color: "#0f172a",
                  marginTop: 2,
                }}
              >
                {summary.running_instances_count || 0}{" "}
                <span style={{ fontSize: 12, fontWeight: 500, color: "#64748b" }}>
                  / {summary.total_instances_count || 0} totales
                </span>
              </div>
            </div>

            <div
              style={{
                backgroundColor: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 6,
                padding: "10px 12px",
              }}
            >
              <div style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>
                ALMACENAMIENTO EBS ACTIVO
              </div>
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 800,
                  color: "#0f172a",
                  marginTop: 2,
                }}
              >
                {summary.total_ebs_gb || 0} GiB{" "}
                <span style={{ fontSize: 12, fontWeight: 500, color: "#64748b" }}>
                  ({summary.total_volumes_count || 0} volúmenes)
                </span>
              </div>
            </div>

            <div
              style={{
                backgroundColor: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 6,
                padding: "10px 12px",
              }}
            >
              <div style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>
                REDES VPC EN LA CUENTA
              </div>
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 800,
                  color: "#0f172a",
                  marginTop: 2,
                }}
              >
                {summary.total_vpcs_count || 0}{" "}
                <span style={{ fontSize: 12, fontWeight: 500, color: "#64748b" }}>
                  ({summary.custom_vpcs_count || 0} creadas por Terraform)
                </span>
              </div>
            </div>

            <div
              style={{
                backgroundColor: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 6,
                padding: "10px 12px",
              }}
            >
              <div style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>
                WORKSPACES TERRAFORM
              </div>
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 800,
                  color: "#0f172a",
                  marginTop: 2,
                }}
              >
                {summary.active_workspaces_count || 0}{" "}
                <span style={{ fontSize: 12, fontWeight: 500, color: "#64748b" }}>
                  con estado activo
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Sub-pestañas de la auditoría */}
        <div
          style={{
            display: "flex",
            gap: 6,
            borderBottom: "1px solid #e2e8f0",
            paddingBottom: 8,
            flexWrap: "wrap",
          }}
        >
          <button
            type="button"
            className={`cm-btn sm ${
              activeSubSection === "instances" ? "primary" : "secondary"
            }`}
            onClick={() => setActiveSubSection("instances")}
          >
            🖥️ Instancias EC2 en AWS ({instances.length})
          </button>
          <button
            type="button"
            className={`cm-btn sm ${
              activeSubSection === "workspaces" ? "primary" : "secondary"
            }`}
            onClick={() => setActiveSubSection("workspaces")}
          >
            📦 Workspaces de Terraform ({workspaces.length})
          </button>
          <button
            type="button"
            className={`cm-btn sm ${
              activeSubSection === "storage_network" ? "primary" : "secondary"
            }`}
            onClick={() => setActiveSubSection("storage_network")}
          >
            💾 Volúmenes EBS ({volumes.length}) y Redes VPC ({vpcs.length})
          </button>
        </div>

        {/* SECCIÓN 1: INSTANCIAS EC2 EN EJECUCIÓN */}
        {activeSubSection === "instances" && (
          <div style={{ overflowX: "auto" }}>
            {instances.length === 0 ? (
              <div
                style={{
                  padding: 20,
                  textAlign: "center",
                  color: "#64748b",
                  fontSize: 13,
                }}
              >
                {loading
                  ? "Consultando instancias EC2 en AWS..."
                  : "No se encontraron instancias EC2 en esta cuenta/región."}
              </div>
            ) : (
              <table className="cm-table" style={{ width: "100%", fontSize: 12.5 }}>
                <thead>
                  <tr>
                    <th>Instancia / Nombre</th>
                    <th>Estado y Tipo</th>
                    <th>IP Pública Actual y Accesos Directos</th>
                    <th>VPC / Workspace</th>
                    <th style={{ textAlign: "right" }}>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {instances.map((inst) => {
                    const delKey = `ec2_instance:${inst.instance_id}`;
                    const isDeleting = actionLoadingId === delKey;
                    const isTerminated =
                      inst.state === "terminated" ||
                      inst.state === "shutting-down";

                    return (
                      <tr key={inst.instance_id}>
                        <td>
                          <div style={{ fontWeight: 700, color: "#0f172a" }}>
                            {inst.name}
                          </div>
                          <code style={{ fontSize: 11.5, color: "#475569" }}>
                            {inst.instance_id}
                          </code>
                          {inst.is_control_plane && (
                            <div style={{ marginTop: 3 }}>
                              <span
                                style={{
                                  backgroundColor: "#dbeafe",
                                  color: "#1e40af",
                                  padding: "1px 6px",
                                  borderRadius: 4,
                                  fontSize: 10.5,
                                  fontWeight: 700,
                                }}
                              >
                                🛡️ Servidor Principal CloudMove
                              </span>
                            </div>
                          )}
                        </td>
                        <td>
                          <span
                            style={{
                              display: "inline-block",
                              padding: "2px 8px",
                              borderRadius: 999,
                              fontSize: 11,
                              fontWeight: 700,
                              backgroundColor:
                                inst.state === "running"
                                  ? "#dcfce7"
                                  : isTerminated
                                  ? "#f1f5f9"
                                  : "#fef9c3",
                              color:
                                inst.state === "running"
                                  ? "#166534"
                                  : isTerminated
                                  ? "#64748b"
                                  : "#854d0e",
                            }}
                          >
                            {inst.state.toUpperCase()}
                          </span>
                          <div
                            style={{
                              fontSize: 11.5,
                              color: "#475569",
                              marginTop: 4,
                            }}
                          >
                            {inst.instance_type} · {inst.availability_zone}
                          </div>
                        </td>
                        <td>
                          {inst.public_ip ? (
                            <div
                              style={{
                                display: "flex",
                                flexDirection: "column",
                                gap: 3,
                              }}
                            >
                              <div>
                                <strong
                                  style={{
                                    fontFamily: "monospace",
                                    fontSize: 13,
                                    color: "#0f172a",
                                  }}
                                >
                                  {inst.public_ip}
                                </strong>
                                <span
                                  style={{
                                    fontSize: 11,
                                    color: "#64748b",
                                    marginLeft: 6,
                                  }}
                                >
                                  (Priv: {inst.private_ip})
                                </span>
                              </div>
                              {!inst.is_control_plane &&
                                inst.state === "running" && (
                                  <div
                                    style={{
                                      display: "flex",
                                      gap: 8,
                                      flexWrap: "wrap",
                                      marginTop: 2,
                                    }}
                                  >
                                    <a
                                      href={`http://${inst.public_ip}:3000`}
                                      target="_blank"
                                      rel="noreferrer"
                                      style={{
                                        fontSize: 11.5,
                                        fontWeight: 700,
                                        color: "#0284c7",
                                        fontFamily: "monospace",
                                      }}
                                    >
                                      {inst.frontend_online ? "🟢" : "⏳"} :3000
                                      (Frontend) ↗
                                    </a>
                                    <a
                                      href={`http://${inst.public_ip}:8000/docs`}
                                      target="_blank"
                                      rel="noreferrer"
                                      style={{
                                        fontSize: 11.5,
                                        fontWeight: 700,
                                        color: "#0284c7",
                                        fontFamily: "monospace",
                                      }}
                                    >
                                      {inst.backend_online ? "🟢" : "⏳"} :8000/docs
                                      (API) ↗
                                    </a>
                                    <a
                                      href={`http://${inst.public_ip}:8000/health`}
                                      target="_blank"
                                      rel="noreferrer"
                                      style={{
                                        fontSize: 11.5,
                                        color: "#0369a1",
                                        fontFamily: "monospace",
                                      }}
                                    >
                                      /health ↗
                                    </a>
                                  </div>
                                )}
                            </div>
                          ) : (
                            <span style={{ color: "#94a3b8" }}>Sin IP pública</span>
                          )}
                        </td>
                        <td>
                          <div style={{ fontSize: 11.5 }}>
                            VPC: <code>{inst.vpc_id || "N/A"}</code>
                          </div>
                          {inst.migration_id && (
                            <div style={{ fontSize: 11.5, marginTop: 2 }}>
                              Job: <code>{inst.migration_id}</code>
                            </div>
                          )}
                        </td>
                        <td style={{ textAlign: "right" }}>
                          {inst.is_control_plane ? (
                            <span
                              style={{
                                fontSize: 11,
                                color: "#64748b",
                                fontStyle: "italic",
                              }}
                            >
                              Protegido (Host actual)
                            </span>
                          ) : isTerminated ? (
                            <span style={{ fontSize: 11, color: "#94a3b8" }}>
                              Terminada
                            </span>
                          ) : confirmDeleteKey === delKey ? (
                            <div
                              style={{
                                display: "inline-flex",
                                gap: 4,
                                alignItems: "center",
                              }}
                            >
                              <button
                                type="button"
                                className="cm-btn sm"
                                style={{
                                  backgroundColor: "#dc2626",
                                  color: "#fff",
                                  border: "none",
                                  fontSize: 11,
                                }}
                                disabled={isDeleting}
                                onClick={() =>
                                  handleDeleteResource(
                                    "ec2_instance",
                                    inst.instance_id,
                                    true
                                  )
                                }
                              >
                                {isDeleting
                                  ? "Eliminando..."
                                  : "Confirmar Terminar + VPC"}
                              </button>
                              <button
                                type="button"
                                className="cm-btn sm secondary"
                                style={{ fontSize: 11 }}
                                onClick={() => setConfirmDeleteKey(null)}
                              >
                                Cancelar
                              </button>
                            </div>
                          ) : (
                            <div
                              style={{
                                display: "inline-flex",
                                gap: 6,
                                alignItems: "center",
                              }}
                            >
                              {inst.state === "stopped" && (
                                <button
                                  type="button"
                                  className="cm-btn sm secondary"
                                  style={{
                                    color: "#15803d",
                                    borderColor: "#86efac",
                                    fontSize: 11.5,
                                  }}
                                  disabled={
                                    actionLoadingId ===
                                    `start_instance:${inst.instance_id}`
                                  }
                                  onClick={() =>
                                    handleDeleteResource(
                                      "start_instance",
                                      inst.instance_id,
                                      false
                                    )
                                  }
                                >
                                  ▶️ Iniciar
                                </button>
                              )}
                              <button
                                type="button"
                                className="cm-btn sm secondary"
                                style={{
                                  color: "#dc2626",
                                  borderColor: "#fca5a5",
                                  fontSize: 11.5,
                                }}
                                onClick={() => setConfirmDeleteKey(delKey)}
                              >
                                🗑️ Terminar Instancia
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* SECCIÓN 2: WORKSPACES LOCALES DE TERRAFORM */}
        {activeSubSection === "workspaces" && (
          <div style={{ overflowX: "auto" }}>
            {workspaces.length === 0 ? (
              <div
                style={{
                  padding: 20,
                  textAlign: "center",
                  color: "#64748b",
                  fontSize: 13,
                }}
              >
                No hay workspaces de Terraform generados en el servidor.
              </div>
            ) : (
              <table className="cm-table" style={{ width: "100%", fontSize: 12.5 }}>
                <thead>
                  <tr>
                    <th>Workspace / Migration ID</th>
                    <th>Estado Terraform</th>
                    <th>Recursos en tfstate</th>
                    <th>Instancia Primaria / IP Actual</th>
                    <th style={{ textAlign: "right" }}>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {workspaces.map((ws) => {
                    const delKey = `terraform_workspace:${ws.migration_id}`;
                    const isDeleting = actionLoadingId === delKey;
                    return (
                      <tr key={ws.migration_id}>
                        <td>
                          <strong
                            style={{ fontFamily: "monospace", color: "#0f172a" }}
                          >
                            {ws.migration_id}
                          </strong>
                          <div style={{ fontSize: 11, color: "#64748b" }}>
                            {ws.workspace_dir}
                          </div>
                        </td>
                        <td>
                          <span
                            style={{
                              padding: "2px 8px",
                              borderRadius: 999,
                              fontSize: 11,
                              fontWeight: 700,
                              backgroundColor:
                                ws.resource_count > 0 ? "#dcfce7" : "#f1f5f9",
                              color:
                                ws.resource_count > 0 ? "#166534" : "#475569",
                            }}
                          >
                            {ws.resource_count > 0
                              ? "ACTIVO EN NUBE"
                              : ws.status}
                          </span>
                        </td>
                        <td>
                          <strong>{ws.resource_count}</strong> recurso(s)
                        </td>
                        <td>
                          {ws.primary_instance_id ? (
                            <div>
                              <code>{ws.primary_instance_id}</code>
                              {ws.primary_public_ip && (
                                <span
                                  style={{
                                    marginLeft: 6,
                                    fontWeight: 700,
                                    color: "#0284c7",
                                    fontFamily: "monospace",
                                  }}
                                >
                                  ({ws.primary_public_ip})
                                </span>
                              )}
                            </div>
                          ) : (
                            <span style={{ color: "#94a3b8" }}>
                              Sin instancia activa
                            </span>
                          )}
                        </td>
                        <td style={{ textAlign: "right" }}>
                          {ws.resource_count === 0 ? (
                            <span style={{ fontSize: 11, color: "#94a3b8" }}>
                              Limpio (0 recursos)
                            </span>
                          ) : confirmDeleteKey === delKey ? (
                            <div
                              style={{
                                display: "inline-flex",
                                gap: 4,
                                alignItems: "center",
                              }}
                            >
                              <button
                                type="button"
                                className="cm-btn sm"
                                style={{
                                  backgroundColor: "#dc2626",
                                  color: "#fff",
                                  border: "none",
                                  fontSize: 11,
                                }}
                                disabled={isDeleting}
                                onClick={() =>
                                  handleDeleteResource(
                                    "terraform_workspace",
                                    ws.migration_id,
                                    true
                                  )
                                }
                              >
                                {isDeleting
                                  ? "Destruyendo..."
                                  : "Confirmar Destruir Todo"}
                              </button>
                              <button
                                type="button"
                                className="cm-btn sm secondary"
                                style={{ fontSize: 11 }}
                                onClick={() => setConfirmDeleteKey(null)}
                              >
                                Cancelar
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              className="cm-btn sm secondary"
                              style={{
                                color: "#dc2626",
                                borderColor: "#fca5a5",
                                fontSize: 11.5,
                              }}
                              onClick={() => setConfirmDeleteKey(delKey)}
                            >
                              🗑️ Destruir Workspace y Recursos AWS
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* SECCIÓN 3: VOLÚMENES EBS Y REDES VPC */}
        {activeSubSection === "storage_network" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div>
              <h4 style={{ margin: "0 0 8px 0", fontSize: 13.5, color: "#0f172a" }}>
                Volúmenes EBS en la Cuenta ({volumes.length})
              </h4>
              <table className="cm-table" style={{ width: "100%", fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>Volume ID</th>
                    <th>Tamaño y Tipo</th>
                    <th>Estado</th>
                    <th>Instancia Asociada</th>
                    <th style={{ textAlign: "right" }}>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {volumes.map((v) => {
                    const delKey = `ebs_volume:${v.volume_id}`;
                    const isDeleting = actionLoadingId === delKey;
                    return (
                      <tr key={v.volume_id}>
                        <td>
                          <code>{v.volume_id}</code>
                        </td>
                        <td>
                          <strong>{v.size_gb} GiB</strong> ({v.volume_type})
                        </td>
                        <td>{v.state.toUpperCase()}</td>
                        <td>
                          {v.attached_instance_id ? (
                            <span>
                              {v.attached_instance_name} (
                              <code>{v.attached_instance_id}</code>)
                            </span>
                          ) : (
                            <span style={{ color: "#d97706", fontWeight: 600 }}>
                              Huérfano / Disponible (available)
                            </span>
                          )}
                        </td>
                        <td style={{ textAlign: "right" }}>
                          {v.is_control_plane ? (
                            <span style={{ fontSize: 11, color: "#64748b" }}>
                              Protegido
                            </span>
                          ) : v.state === "available" ? (
                            <button
                              type="button"
                              className="cm-btn sm secondary"
                              style={{
                                color: "#dc2626",
                                borderColor: "#fca5a5",
                                fontSize: 11,
                              }}
                              disabled={isDeleting}
                              onClick={() =>
                                handleDeleteResource("ebs_volume", v.volume_id)
                              }
                            >
                              {isDeleting ? "Eliminando..." : "🗑️ Eliminar Volumen"}
                            </button>
                          ) : (
                            <span style={{ fontSize: 11, color: "#64748b" }}>
                              Se elimina al terminar la instancia
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div>
              <h4 style={{ margin: "0 0 8px 0", fontSize: 13.5, color: "#0f172a" }}>
                Redes VPC en la Cuenta ({vpcs.length})
              </h4>
              <table className="cm-table" style={{ width: "100%", fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>VPC ID / Nombre</th>
                    <th>Bloque CIDR</th>
                    <th>Instancias Activas</th>
                    <th style={{ textAlign: "right" }}>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {vpcs.map((vp) => {
                    const delKey = `vpc:${vp.vpc_id}`;
                    const isDeleting = actionLoadingId === delKey;
                    return (
                      <tr key={vp.vpc_id}>
                        <td>
                          <strong>{vp.name}</strong> (<code>{vp.vpc_id}</code>)
                          {vp.is_default && (
                            <span
                              style={{
                                marginLeft: 6,
                                fontSize: 10.5,
                                backgroundColor: "#e2e8f0",
                                padding: "1px 6px",
                                borderRadius: 4,
                              }}
                            >
                              Default VPC
                            </span>
                          )}
                        </td>
                        <td>
                          <code>{vp.cidr_block}</code>
                        </td>
                        <td>{vp.active_instance_count} instancia(s)</td>
                        <td style={{ textAlign: "right" }}>
                          {vp.is_control_plane || vp.is_default ? (
                            <span style={{ fontSize: 11, color: "#64748b" }}>
                              Protegida (VPC Principal)
                            </span>
                          ) : confirmDeleteKey === delKey ? (
                            <div
                              style={{
                                display: "inline-flex",
                                gap: 4,
                                alignItems: "center",
                              }}
                            >
                              <button
                                type="button"
                                className="cm-btn sm"
                                style={{
                                  backgroundColor: "#dc2626",
                                  color: "#fff",
                                  border: "none",
                                  fontSize: 11,
                                }}
                                disabled={isDeleting}
                                onClick={() =>
                                  handleDeleteResource("vpc", vp.vpc_id)
                                }
                              >
                                {isDeleting
                                  ? "Eliminando VPC..."
                                  : "Confirmar Eliminar VPC"}
                              </button>
                              <button
                                type="button"
                                className="cm-btn sm secondary"
                                style={{ fontSize: 11 }}
                                onClick={() => setConfirmDeleteKey(null)}
                              >
                                Cancelar
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              className="cm-btn sm secondary"
                              style={{
                                color: "#dc2626",
                                borderColor: "#fca5a5",
                                fontSize: 11,
                              }}
                              onClick={() => setConfirmDeleteKey(delKey)}
                            >
                              🗑️ Eliminar VPC y Dependencias
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
