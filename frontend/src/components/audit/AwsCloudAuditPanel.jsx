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
  const [showCredsForm, setShowCredsForm] = useState(true);

  const [auditData, setAuditData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [actionLoadingId, setActionLoadingId] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);
  const [confirmDeleteKey, setConfirmDeleteKey] = useState(null);
  const [activeSubSection, setActiveSubSection] = useState("projects"); // "projects" | "instances" | "workspaces" | "storage_network"

  // Auto-parse AWS Academy CLI credentials block if pasted
  const handleParseRawBlock = (text) => {
    setRawPasteBlock(text);
    const akMatch = text.match(/aws_access_key_id\s*=\s*([^\s\r\n"']+)/i);
    const skMatch = text.match(/aws_secret_access_key\s*=\s*([^\s\r\n"']+)/i);
    const stMatch = text.match(/aws_session_token\s*=\s*([^\s\r\n"']+)/i);
    const regMatch = text.match(/aws_region\s*=\s*([^\s\r\n"']+)/i);
    if (akMatch) setAwsAccessKeyId(akMatch[1].trim());
    if (skMatch) setAwsSecretAccessKey(skMatch[1].trim());
    if (stMatch) setAwsSessionToken(stMatch[1].trim());
    if (regMatch) setAwsRegion(regMatch[1].trim());
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
        if (typeof onAuditCompleted === "function") {
          onAuditCompleted(data);
        }
      } catch (err) {
        setAuditData({
          authenticated: false,
          error: `Error de red al consultar auditoría AWS: ${err.message}`,
          projects_deployed: [],
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
          text: (data.details || [`Acción ejecutada sobre ${resourceId}.`]).join(
            " · "
          ),
        });
        setConfirmDeleteKey(null);
        await runAudit(creds);
      } else {
        setActionMessage({
          type: "error",
          text: data.error || `No se pudo procesar ${resourceId}.`,
        });
      }
    } catch (err) {
      setActionMessage({
        type: "error",
        text: `Error al ejecutar acción en AWS: ${err.message}`,
      });
    } finally {
      setActionLoadingId(null);
    }
  };

  const summary = auditData?.summary || {};
  const projectsDeployed = auditData?.projects_deployed || [];
  const instances = auditData?.instances || [];
  const workspaces = auditData?.workspaces || [];
  const volumes = auditData?.volumes || [];
  const vpcs = auditData?.vpcs || [];
  const securityGroups = auditData?.security_groups || [];
  const ipSyncEvents = auditData?.ip_sync_events || [];

  const renderProjectBadge = (pinfo) => {
    if (!pinfo) return <span style={{ color: "#94a3b8" }}>Sin asignar</span>;
    const isCp = pinfo.is_control_plane;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <div style={{ fontWeight: 700, color: isCp ? "#1e40af" : "#0f172a", fontSize: 12 }}>
          {isCp ? "🛡️ " : "🚀 "}
          {pinfo.project_name}
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <span
            style={{
              backgroundColor: isCp ? "#dbeafe" : "#e0f2fe",
              color: isCp ? "#1e40af" : "#0369a1",
              padding: "1px 6px",
              borderRadius: 4,
              fontSize: 10.5,
              fontWeight: 700,
            }}
          >
            {pinfo.use_case_label}
          </span>
          {pinfo.migration_id && (
            <code style={{ fontSize: 11, color: "#475569" }}>
              ID: {pinfo.migration_id}
            </code>
          )}
        </div>
        {pinfo.source_detail && (
          <div style={{ fontSize: 11, color: "#64748b", wordBreak: "break-all" }}>
            Origen: {pinfo.source_detail}
          </div>
        )}
      </div>
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Cabecera Principal de la Sesión de Auditoría Terraform & AWS */}
      <div
        style={{
          backgroundColor: "#ffffff",
          border: "1px solid #cbd5e1",
          borderRadius: 8,
          padding: 16,
          display: "flex",
          flexDirection: "column",
          gap: 14,
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
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 20 }}>🛡️</span>
              <h3 style={{ margin: 0, fontSize: 16.5, color: "#0f172a" }}>
                Sesión de Auditoría Terraform y Recursos en Cuenta AWS
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
                  ● Cuenta AWS: {auditData.account_id} ({auditData.region})
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
              Ingresa tus credenciales de AWS (Access Key, Secret Key y Session Token),
              consulta todos los elementos activos en tu cuenta, identifica a qué
              proyecto o despliegue de CloudMove pertenecen y elimínalos de forma segura.
            </p>
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              className="cm-btn sm secondary"
              onClick={() => setShowCredsForm((v) => !v)}
            >
              {showCredsForm
                ? "Ocultar Panel de Credenciales AWS"
                : "🔑 Ingresar / Cambiar Credenciales AWS"}
            </button>
            <button
              type="button"
              className="cm-btn sm primary"
              onClick={() => runAudit()}
              disabled={loading}
            >
              {loading
                ? "Consultando cuenta AWS..."
                : "↻ Consultar Elementos en Cuenta AWS"}
            </button>
          </div>
        </div>

        {/* Panel de Credenciales AWS (Visible por defecto) */}
        {showCredsForm && (
          <div
            style={{
              backgroundColor: "#f8fafc",
              border: "1px solid #94a3b8",
              borderRadius: 8,
              padding: 14,
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
                🔑 Credenciales de Cuenta AWS / AWS Academy Learner Lab
              </div>
              {auditData?.caller_arn && (
                <code style={{ fontSize: 11, color: "#15803d", backgroundColor: "#dcfce7", padding: "2px 8px", borderRadius: 4 }}>
                  Identidad STS activa: {auditData.caller_arn}
                </code>
              )}
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
                gap: 12,
              }}
            >
              <div>
                <label
                  style={{
                    display: "block",
                    fontSize: 11.5,
                    fontWeight: 600,
                    color: "#334155",
                    marginBottom: 4,
                  }}
                >
                  Pegado rápido de bloque AWS Academy (AWS Details → Show):
                </label>
                <textarea
                  rows={5}
                  className="cm-input"
                  style={{ fontFamily: "monospace", fontSize: 11.5, width: "100%" }}
                  placeholder={
                    "[default]\naws_access_key_id=ASIA...\naws_secret_access_key=...\naws_session_token=..."
                  }
                  value={rawPasteBlock}
                  onChange={(e) => handleParseRawBlock(e.target.value)}
                />
                <div style={{ fontSize: 11, color: "#64748b", marginTop: 3 }}>
                  Al pegar el bloque completo aquí, se extraen automáticamente el Access Key, Secret Key y Session Token.
                </div>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 8 }}>
                  <div>
                    <label style={{ fontSize: 11.5, fontWeight: 600, display: "block", marginBottom: 2 }}>
                      AWS Access Key ID:
                    </label>
                    <input
                      type="text"
                      className="cm-input"
                      style={{ fontFamily: "monospace", fontSize: 12, width: "100%" }}
                      value={awsAccessKeyId}
                      onChange={(e) => setAwsAccessKeyId(e.target.value)}
                      placeholder="ASIA... / AKIA..."
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: 11.5, fontWeight: 600, display: "block", marginBottom: 2 }}>
                      Región AWS:
                    </label>
                    <input
                      type="text"
                      className="cm-input"
                      style={{ fontFamily: "monospace", fontSize: 12, width: "100%" }}
                      value={awsRegion}
                      onChange={(e) => setAwsRegion(e.target.value)}
                      placeholder="us-east-1"
                    />
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: 11.5, fontWeight: 600, display: "block", marginBottom: 2 }}>
                    AWS Secret Access Key:
                  </label>
                  <input
                    type="password"
                    className="cm-input"
                    style={{ fontFamily: "monospace", fontSize: 12, width: "100%" }}
                    value={awsSecretAccessKey}
                    onChange={(e) => setAwsSecretAccessKey(e.target.value)}
                    placeholder="••••••••••••••••••••••••••••••••"
                  />
                </div>

                <div>
                  <label style={{ fontSize: 11.5, fontWeight: 600, display: "block", marginBottom: 2 }}>
                    AWS Session Token (Requerido para AWS Academy):
                  </label>
                  <input
                    type="password"
                    className="cm-input"
                    style={{ fontFamily: "monospace", fontSize: 12, width: "100%" }}
                    value={awsSessionToken}
                    onChange={(e) => setAwsSessionToken(e.target.value)}
                    placeholder="IQoJb3JpZ2luX2Vj..."
                  />
                </div>
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
              <button
                type="button"
                className="cm-btn sm primary"
                onClick={() => runAudit()}
                disabled={loading}
              >
                {loading
                  ? "Autenticando y Escaneando AWS..."
                  : "🔍 Autenticar con AWS y Consultar Recursos en Ejecución"}
              </button>
            </div>
          </div>
        )}

        {/* Error de autenticación si ocurre */}
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
                <code>{ev.instance_id}</code>) actualizó su IP de{" "}
                <del>{ev.old_ip}</del> a <strong>{ev.new_ip}</strong>.{" "}
              </span>
            ))}
          </div>
        )}

        {/* Mensaje de confirmación de acción */}
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
                {actionMessage.type === "success" ? "✅ Acción completada:" : "⚠️ Error:"}
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
                PROYECTOS / DESPLIEGUES EN AWS
              </div>
              <div style={{ fontSize: 20, fontWeight: 800, color: "#0f172a", marginTop: 2 }}>
                {projectsDeployed.length}{" "}
                <span style={{ fontSize: 12, fontWeight: 500, color: "#64748b" }}>
                  identificados
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
                INSTANCIAS EC2 EN EJECUCIÓN
              </div>
              <div style={{ fontSize: 20, fontWeight: 800, color: "#0f172a", marginTop: 2 }}>
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
              <div style={{ fontSize: 20, fontWeight: 800, color: "#0f172a", marginTop: 2 }}>
                {summary.total_ebs_gb || 0} GiB{" "}
                <span style={{ fontSize: 12, fontWeight: 500, color: "#64748b" }}>
                  ({summary.total_volumes_count || 0} discos)
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
                REDES VPC Y WORKSPACES
              </div>
              <div style={{ fontSize: 20, fontWeight: 800, color: "#0f172a", marginTop: 2 }}>
                {summary.total_vpcs_count || 0} VPCs{" "}
                <span style={{ fontSize: 12, fontWeight: 500, color: "#64748b" }}>
                  · {summary.active_workspaces_count || 0} tfstate
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Pestañas de visualización */}
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
              activeSubSection === "projects" ? "primary" : "secondary"
            }`}
            onClick={() => setActiveSubSection("projects")}
          >
            🗂️ Por Proyecto / Despliegue ({projectsDeployed.length})
          </button>
          <button
            type="button"
            className={`cm-btn sm ${
              activeSubSection === "instances" ? "primary" : "secondary"
            }`}
            onClick={() => setActiveSubSection("instances")}
          >
            🖥️ Instancias EC2 ({instances.length})
          </button>
          <button
            type="button"
            className={`cm-btn sm ${
              activeSubSection === "storage_network" ? "primary" : "secondary"
            }`}
            onClick={() => setActiveSubSection("storage_network")}
          >
            💾 Discos EBS ({volumes.length}), VPCs ({vpcs.length}) y Security Groups ({securityGroups.length})
          </button>
          <button
            type="button"
            className={`cm-btn sm ${
              activeSubSection === "workspaces" ? "primary" : "secondary"
            }`}
            onClick={() => setActiveSubSection("workspaces")}
          >
            📦 Estados Locales Terraform ({workspaces.length})
          </button>
        </div>

        {/* VISTA 1: AGRUPADA POR PROYECTO / DESPLIEGUE TERRAFORM */}
        {activeSubSection === "projects" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {projectsDeployed.length === 0 ? (
              <div style={{ padding: 20, textAlign: "center", color: "#64748b", fontSize: 13 }}>
                {loading
                  ? "Analizando proyectos y recursos en AWS..."
                  : "No se encontraron recursos activos en la cuenta AWS."}
              </div>
            ) : (
              projectsDeployed.map((proj) => {
                const isCp = proj.is_control_plane;
                const projDelKey = `proj:${proj.project_id}`;
                const primaryVpc = (proj.vpcs || [])[0];
                const primaryInst = (proj.instances || [])[0];

                // Determine best deletion target for the whole project
                const handleDeleteWholeProject = () => {
                  if (proj.migration_id && proj.migration_id !== "deploy/aws" && workspaces.some((w) => w.migration_id === proj.migration_id && w.resource_count > 0)) {
                    handleDeleteResource("terraform_workspace", proj.migration_id, true);
                  } else if (primaryVpc && !primaryVpc.is_default) {
                    handleDeleteResource("vpc", primaryVpc.vpc_id, true);
                  } else if (primaryInst) {
                    handleDeleteResource("ec2_instance", primaryInst.instance_id, true);
                  }
                };

                return (
                  <div
                    key={proj.project_id}
                    style={{
                      backgroundColor: isCp ? "#f8fafc" : "#ffffff",
                      border: `1.5px solid ${isCp ? "#93c5fd" : "#cbd5e1"}`,
                      borderRadius: 8,
                      padding: 14,
                      display: "flex",
                      flexDirection: "column",
                      gap: 10,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "flex-start",
                        flexWrap: "wrap",
                        gap: 10,
                        borderBottom: "1px solid #e2e8f0",
                        paddingBottom: 10,
                      }}
                    >
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <span style={{ fontSize: 16 }}>{isCp ? "🛡️" : "🚀"}</span>
                          <strong style={{ fontSize: 14.5, color: "#0f172a" }}>
                            {proj.project_name}
                          </strong>
                          <span
                            style={{
                              backgroundColor: isCp ? "#dbeafe" : "#dcfce7",
                              color: isCp ? "#1e40af" : "#166534",
                              padding: "2px 8px",
                              borderRadius: 999,
                              fontSize: 11,
                              fontWeight: 700,
                            }}
                          >
                            {proj.use_case_label}
                          </span>
                          {proj.migration_id && (
                            <span
                              style={{
                                backgroundColor: "#f1f5f9",
                                color: "#334155",
                                padding: "2px 8px",
                                borderRadius: 4,
                                fontSize: 11,
                                fontFamily: "monospace",
                                fontWeight: 600,
                              }}
                            >
                              Despliegue: {proj.migration_id}
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
                          <strong>Origen del despliegue:</strong> <code>{proj.source_detail}</code> ·{" "}
                          <strong>Almacenamiento EBS del proyecto:</strong> {proj.total_ebs_gb} GiB ·{" "}
                          <strong>Total elementos AWS:</strong> {proj.total_resources_count}
                        </div>
                      </div>

                      <div>
                        {isCp ? (
                          <span
                            style={{
                              fontSize: 11.5,
                              color: "#1e40af",
                              backgroundColor: "#eff6ff",
                              border: "1px solid #bfdbfe",
                              padding: "4px 10px",
                              borderRadius: 6,
                              fontWeight: 600,
                            }}
                          >
                            🔒 Infraestructura Principal Protegida
                          </span>
                        ) : confirmDeleteKey === projDelKey ? (
                          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                            <button
                              type="button"
                              className="cm-btn sm"
                              style={{
                                backgroundColor: "#dc2626",
                                color: "#fff",
                                border: "none",
                                fontSize: 11.5,
                              }}
                              disabled={Boolean(actionLoadingId)}
                              onClick={handleDeleteWholeProject}
                            >
                              {actionLoadingId
                                ? "Eliminando proyecto de AWS..."
                                : "Confirmar Eliminar Todo el Despliegue"}
                            </button>
                            <button
                              type="button"
                              className="cm-btn sm secondary"
                              style={{ fontSize: 11.5 }}
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
                              fontWeight: 700,
                            }}
                            onClick={() => setConfirmDeleteKey(projDelKey)}
                          >
                            🗑️ Eliminar Todo este Despliegue de AWS
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Elementos de este proyecto */}
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
                        gap: 10,
                      }}
                    >
                      {/* Instancias del proyecto */}
                      <div
                        style={{
                          backgroundColor: "#f8fafc",
                          border: "1px solid #e2e8f0",
                          borderRadius: 6,
                          padding: 10,
                        }}
                      >
                        <div style={{ fontSize: 11.5, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>
                          🖥️ Instancias EC2 ({(proj.instances || []).length})
                        </div>
                        {(proj.instances || []).length === 0 ? (
                          <div style={{ fontSize: 11.5, color: "#94a3b8" }}>
                            Sin instancias EC2 activas en este despliegue.
                          </div>
                        ) : (
                          (proj.instances || []).map((inst) => (
                            <div
                              key={inst.instance_id}
                              style={{
                                display: "flex",
                                flexDirection: "column",
                                gap: 4,
                                paddingBottom: 6,
                                marginBottom: 6,
                                borderBottom: "1px dashed #cbd5e1",
                              }}
                            >
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                <strong style={{ fontSize: 12 }}>
                                  {inst.name} (<code>{inst.instance_id}</code>)
                                </strong>
                                <span
                                  style={{
                                    fontSize: 10.5,
                                    fontWeight: 700,
                                    padding: "1px 6px",
                                    borderRadius: 999,
                                    backgroundColor: inst.state === "running" ? "#dcfce7" : "#fef9c3",
                                    color: inst.state === "running" ? "#166534" : "#854d0e",
                                  }}
                                >
                                  {inst.state.toUpperCase()} · {inst.instance_type}
                                </span>
                              </div>
                              {inst.public_ip && (
                                <div style={{ fontSize: 11.5 }}>
                                  IP Pública: <strong style={{ fontFamily: "monospace" }}>{inst.public_ip}</strong>
                                  {!inst.is_control_plane && inst.state === "running" && (
                                    <span style={{ marginLeft: 8 }}>
                                      <a
                                        href={`http://${inst.public_ip}:3000`}
                                        target="_blank"
                                        rel="noreferrer"
                                        style={{ color: "#0284c7", fontWeight: 700, marginRight: 8 }}
                                      >
                                        {inst.frontend_online ? "🟢" : "⏳"} :3000 ↗
                                      </a>
                                      <a
                                        href={`http://${inst.public_ip}:8000/docs`}
                                        target="_blank"
                                        rel="noreferrer"
                                        style={{ color: "#0284c7", fontWeight: 700 }}
                                      >
                                        {inst.backend_online ? "🟢" : "⏳"} :8000/docs ↗
                                      </a>
                                    </span>
                                  )}
                                </div>
                              )}
                              {!inst.is_control_plane && (
                                <div style={{ display: "flex", gap: 6, marginTop: 2 }}>
                                  {inst.state === "stopped" && (
                                    <button
                                      type="button"
                                      className="cm-btn sm secondary"
                                      style={{ fontSize: 10.5, padding: "2px 6px", color: "#15803d" }}
                                      onClick={() => handleDeleteResource("start_instance", inst.instance_id, false)}
                                    >
                                      ▶️ Iniciar
                                    </button>
                                  )}
                                  {inst.state === "running" && (
                                    <button
                                      type="button"
                                      className="cm-btn sm secondary"
                                      style={{ fontSize: 10.5, padding: "2px 6px", color: "#b45309" }}
                                      onClick={() => handleDeleteResource("stop_instance", inst.instance_id, false)}
                                    >
                                      ⏹️ Detener
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    className="cm-btn sm secondary"
                                    style={{ fontSize: 10.5, padding: "2px 6px", color: "#dc2626" }}
                                    onClick={() => handleDeleteResource("ec2_instance", inst.instance_id, true)}
                                  >
                                    🗑️ Terminar
                                  </button>
                                </div>
                              )}
                            </div>
                          ))
                        )}
                      </div>

                      {/* Volúmenes EBS del proyecto */}
                      <div
                        style={{
                          backgroundColor: "#f8fafc",
                          border: "1px solid #e2e8f0",
                          borderRadius: 6,
                          padding: 10,
                        }}
                      >
                        <div style={{ fontSize: 11.5, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>
                          💾 Volúmenes EBS ({(proj.volumes || []).length} · {proj.total_ebs_gb} GiB)
                        </div>
                        {(proj.volumes || []).map((v) => (
                          <div key={v.volume_id} style={{ fontSize: 11.5, marginBottom: 4 }}>
                            <code>{v.volume_id}</code> — <strong>{v.size_gb} GiB</strong> ({v.volume_type}) ·{" "}
                            <span style={{ color: "#475569" }}>{v.device || v.state}</span>
                          </div>
                        ))}
                      </div>

                      {/* Redes VPC, Subredes y Security Groups del proyecto */}
                      <div
                        style={{
                          backgroundColor: "#f8fafc",
                          border: "1px solid #e2e8f0",
                          borderRadius: 6,
                          padding: 10,
                        }}
                      >
                        <div style={{ fontSize: 11.5, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>
                          🌐 Red VPC, Subredes y Security Groups
                        </div>
                        {(proj.vpcs || []).map((vp) => (
                          <div key={vp.vpc_id} style={{ fontSize: 11.5, marginBottom: 4 }}>
                            VPC: <strong>{vp.name}</strong> (<code>{vp.vpc_id}</code> · {vp.cidr_block})
                            <div style={{ color: "#475569", fontSize: 11 }}>
                              Subredes: {(vp.subnets || []).length} · IGW: {(vp.internet_gateways || []).join(", ") || "N/A"}
                            </div>
                          </div>
                        ))}
                        {(proj.security_groups || []).map((sg) => (
                          <div key={sg.group_id} style={{ fontSize: 11, color: "#334155" }}>
                            SG: <strong>{sg.group_name}</strong> (<code>{sg.group_id}</code>) · Puertos:{" "}
                            <code>{(sg.ingress_ports || []).join(", ") || "Ninguno"}</code>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {/* VISTA 2: TABLA DETALLADA DE INSTANCIAS EC2 CON SU PROYECTO / DESPLIEGUE */}
        {activeSubSection === "instances" && (
          <div style={{ overflowX: "auto" }}>
            <table className="cm-table" style={{ width: "100%", fontSize: 12.5 }}>
              <thead>
                <tr>
                  <th>Instancia EC2</th>
                  <th>Proyecto / Despliegue al que Pertenece</th>
                  <th>Estado y Tipo</th>
                  <th>IP Pública Actual y Accesos</th>
                  <th style={{ textAlign: "right" }}>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {instances.map((inst) => {
                  const delKey = `ec2_instance:${inst.instance_id}`;
                  const isDeleting = actionLoadingId === delKey;
                  const isTerminated =
                    inst.state === "terminated" || inst.state === "shutting-down";

                  return (
                    <tr key={inst.instance_id}>
                      <td>
                        <div style={{ fontWeight: 700, color: "#0f172a" }}>
                          {inst.name}
                        </div>
                        <code style={{ fontSize: 11.5, color: "#475569" }}>
                          {inst.instance_id}
                        </code>
                        <div style={{ fontSize: 11, color: "#64748b" }}>
                          VPC: <code>{inst.vpc_id}</code>
                        </div>
                      </td>
                      <td>{renderProjectBadge(inst.project_info)}</td>
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
                        <div style={{ fontSize: 11.5, color: "#475569", marginTop: 4 }}>
                          {inst.instance_type} · {inst.availability_zone}
                        </div>
                      </td>
                      <td>
                        {inst.public_ip ? (
                          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                            <div>
                              <strong style={{ fontFamily: "monospace", fontSize: 13 }}>
                                {inst.public_ip}
                              </strong>
                              <span style={{ fontSize: 11, color: "#64748b", marginLeft: 6 }}>
                                (Priv: {inst.private_ip})
                              </span>
                            </div>
                            {!inst.is_control_plane && inst.state === "running" && (
                              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                <a
                                  href={`http://${inst.public_ip}:3000`}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{ fontSize: 11.5, fontWeight: 700, color: "#0284c7", fontFamily: "monospace" }}
                                >
                                  {inst.frontend_online ? "🟢" : "⏳"} :3000 (Frontend) ↗
                                </a>
                                <a
                                  href={`http://${inst.public_ip}:8000/docs`}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{ fontSize: 11.5, fontWeight: 700, color: "#0284c7", fontFamily: "monospace" }}
                                >
                                  {inst.backend_online ? "🟢" : "⏳"} :8000/docs (API) ↗
                                </a>
                              </div>
                            )}
                          </div>
                        ) : (
                          <span style={{ color: "#94a3b8" }}>Sin IP pública</span>
                        )}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {inst.is_control_plane ? (
                          <span style={{ fontSize: 11, color: "#64748b", fontStyle: "italic" }}>
                            Protegido (Host actual)
                          </span>
                        ) : isTerminated ? (
                          <span style={{ fontSize: 11, color: "#94a3b8" }}>Terminada</span>
                        ) : confirmDeleteKey === delKey ? (
                          <div style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                            <button
                              type="button"
                              className="cm-btn sm"
                              style={{ backgroundColor: "#dc2626", color: "#fff", border: "none", fontSize: 11 }}
                              disabled={isDeleting}
                              onClick={() => handleDeleteResource("ec2_instance", inst.instance_id, true)}
                            >
                              {isDeleting ? "Eliminando..." : "Confirmar Terminar + VPC"}
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
                          <div style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                            {inst.state === "stopped" && (
                              <button
                                type="button"
                                className="cm-btn sm secondary"
                                style={{ color: "#15803d", borderColor: "#86efac", fontSize: 11.5 }}
                                onClick={() => handleDeleteResource("start_instance", inst.instance_id, false)}
                              >
                                ▶️ Iniciar
                              </button>
                            )}
                            {inst.state === "running" && (
                              <button
                                type="button"
                                className="cm-btn sm secondary"
                                style={{ color: "#b45309", borderColor: "#fcd34d", fontSize: 11.5 }}
                                onClick={() => handleDeleteResource("stop_instance", inst.instance_id, false)}
                              >
                                ⏹️ Detener
                              </button>
                            )}
                            <button
                              type="button"
                              className="cm-btn sm secondary"
                              style={{ color: "#dc2626", borderColor: "#fca5a5", fontSize: 11.5 }}
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
          </div>
        )}

        {/* VISTA 3: VOLÚMENES EBS, REDES VPC Y SECURITY GROUPS CON PROYECTO ASOCIADO */}
        {activeSubSection === "storage_network" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div>
              <h4 style={{ margin: "0 0 8px 0", fontSize: 13.5, color: "#0f172a" }}>
                💾 Volúmenes EBS en la Cuenta AWS ({volumes.length})
              </h4>
              <table className="cm-table" style={{ width: "100%", fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>Volume ID</th>
                    <th>Proyecto / Despliegue Asociado</th>
                    <th>Tamaño y Tipo</th>
                    <th>Instancia Adjunta</th>
                    <th style={{ textAlign: "right" }}>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {volumes.map((v) => (
                    <tr key={v.volume_id}>
                      <td>
                        <code>{v.volume_id}</code>
                        <div style={{ fontSize: 11, color: "#64748b" }}>{v.state.toUpperCase()}</div>
                      </td>
                      <td>{renderProjectBadge(v.project_info)}</td>
                      <td>
                        <strong>{v.size_gb} GiB</strong> ({v.volume_type})
                      </td>
                      <td>
                        {v.attached_instance_id ? (
                          <span>
                            {v.attached_instance_name} (<code>{v.attached_instance_id}</code>)
                          </span>
                        ) : (
                          <span style={{ color: "#d97706", fontWeight: 600 }}>
                            Disponible / Sin adjuntar (available)
                          </span>
                        )}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {v.is_control_plane ? (
                          <span style={{ fontSize: 11, color: "#64748b" }}>Protegido</span>
                        ) : v.state === "available" ? (
                          <button
                            type="button"
                            className="cm-btn sm secondary"
                            style={{ color: "#dc2626", borderColor: "#fca5a5", fontSize: 11 }}
                            onClick={() => handleDeleteResource("ebs_volume", v.volume_id)}
                          >
                            🗑️ Eliminar Volumen
                          </button>
                        ) : (
                          <span style={{ fontSize: 11, color: "#64748b" }}>
                            Se elimina al terminar la instancia ({v.attached_instance_id})
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div>
              <h4 style={{ margin: "0 0 8px 0", fontSize: 13.5, color: "#0f172a" }}>
                🌐 Redes VPC, Subredes e Internet Gateways ({vpcs.length})
              </h4>
              <table className="cm-table" style={{ width: "100%", fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>VPC ID / Nombre</th>
                    <th>Proyecto / Despliegue Asociado</th>
                    <th>CIDR / Subredes / IGW</th>
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
                          <strong>{vp.name}</strong>
                          <div>
                            <code>{vp.vpc_id}</code>
                          </div>
                        </td>
                        <td>{renderProjectBadge(vp.project_info)}</td>
                        <td>
                          <div>
                            CIDR: <code>{vp.cidr_block}</code>
                          </div>
                          <div style={{ fontSize: 11, color: "#475569" }}>
                            {(vp.subnets || []).length} subred(es) · IGW:{" "}
                            {(vp.internet_gateways || []).join(", ") || "Ninguno"}
                          </div>
                        </td>
                        <td>{vp.active_instance_count} instancia(s)</td>
                        <td style={{ textAlign: "right" }}>
                          {vp.is_control_plane || vp.is_default ? (
                            <span style={{ fontSize: 11, color: "#64748b" }}>
                              Protegida (VPC Principal)
                            </span>
                          ) : confirmDeleteKey === delKey ? (
                            <div style={{ display: "inline-flex", gap: 4 }}>
                              <button
                                type="button"
                                className="cm-btn sm"
                                style={{ backgroundColor: "#dc2626", color: "#fff", border: "none", fontSize: 11 }}
                                disabled={isDeleting}
                                onClick={() => handleDeleteResource("vpc", vp.vpc_id)}
                              >
                                {isDeleting ? "Eliminando VPC..." : "Confirmar Eliminar VPC"}
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
                              style={{ color: "#dc2626", borderColor: "#fca5a5", fontSize: 11 }}
                              onClick={() => setConfirmDeleteKey(delKey)}
                            >
                              🗑️ Eliminar VPC y Subredes
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

        {/* VISTA 4: WORKSPACES LOCALES DE TERRAFORM */}
        {activeSubSection === "workspaces" && (
          <div style={{ overflowX: "auto" }}>
            <table className="cm-table" style={{ width: "100%", fontSize: 12.5 }}>
              <thead>
                <tr>
                  <th>Workspace / Migration ID</th>
                  <th>Proyecto / Caso de Uso</th>
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
                        <strong style={{ fontFamily: "monospace", color: "#0f172a" }}>
                          {ws.migration_id}
                        </strong>
                        <div style={{ fontSize: 11, color: "#64748b" }}>
                          {ws.workspace_dir}
                        </div>
                      </td>
                      <td>{renderProjectBadge(ws.project_info)}</td>
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
                          <span style={{ color: "#94a3b8" }}>Sin instancia activa</span>
                        )}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {ws.resource_count === 0 ? (
                          <span style={{ fontSize: 11, color: "#94a3b8" }}>
                            Limpio (0 recursos)
                          </span>
                        ) : confirmDeleteKey === delKey ? (
                          <div style={{ display: "inline-flex", gap: 4 }}>
                            <button
                              type="button"
                              className="cm-btn sm"
                              style={{ backgroundColor: "#dc2626", color: "#fff", border: "none", fontSize: 11 }}
                              disabled={isDeleting}
                              onClick={() => handleDeleteResource("terraform_workspace", ws.migration_id, true)}
                            >
                              {isDeleting ? "Destruyendo..." : "Confirmar Destruir Todo"}
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
                            style={{ color: "#dc2626", borderColor: "#fca5a5", fontSize: 11.5 }}
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
          </div>
        )}
      </div>
    </div>
  );
}
