import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch } from "../../utils/apiClient";
import {
  saveSessionCredentials,
  getSessionCredentials,
  getCredentialsSummary,
  clearSessionCredentials,
  maskSecretValue,
} from "../../utils/credentialVault";
import {
  AwsContainer,
  AwsKeyValuePairs,
  AwsTabs,
  AwsStatusIndicator,
  AwsAlert,
  AwsEmptyState,
} from "../cloudscape/AwsPrimitives";

export default function AwsCloudAuditPanel({
  initialCredentials = null,
  onAuditCompleted = null,
}) {
  const sessionCreds = getSessionCredentials();
  const seedCreds = sessionCreds || initialCredentials || {};

  const [awsAccessKeyId, setAwsAccessKeyId] = useState(
    seedCreds.aws_access_key_id || ""
  );
  const [awsSecretAccessKey, setAwsSecretAccessKey] = useState(
    seedCreds.aws_secret_access_key || ""
  );
  const [awsSessionToken, setAwsSessionToken] = useState(
    seedCreds.aws_session_token || ""
  );
  const [awsRegion, setAwsRegion] = useState(
    seedCreds.aws_region || "us-east-1"
  );
  const [rawPasteBlock, setRawPasteBlock] = useState("");
  const [showCredsForm, setShowCredsForm] = useState(!sessionCreds);
  const [vaultSummary, setVaultSummary] = useState(() => getCredentialsSummary());

  const [auditData, setAuditData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [actionLoadingId, setActionLoadingId] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);
  const [confirmDeleteKey, setConfirmDeleteKey] = useState(null);
  const [activeSubSection, setActiveSubSection] = useState("projects");

  // Stable refs to prevent infinite re-render loops
  const onAuditCompletedRef = useRef(onAuditCompleted);
  useEffect(() => {
    onAuditCompletedRef.current = onAuditCompleted;
  }, [onAuditCompleted]);

  const hasAutoAuditedRef = useRef(false);

  // Sync when credentials are updated from another panel in the same session
  useEffect(() => {
    const handleSync = () => {
      const current = getSessionCredentials();
      setVaultSummary(getCredentialsSummary());
      if (current) {
        setAwsAccessKeyId(current.aws_access_key_id || "");
        setAwsSecretAccessKey(current.aws_secret_access_key || "");
        setAwsSessionToken(current.aws_session_token || "");
        setAwsRegion(current.aws_region || "us-east-1");
      }
    };
    window.addEventListener("cloudmove:credentials-updated", handleSync);
    return () =>
      window.removeEventListener("cloudmove:credentials-updated", handleSync);
  }, []);

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

  const getEffectiveCreds = useCallback(() => {
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
    const stored = getSessionCredentials();
    if (stored) return stored;
    return null;
  }, [awsAccessKeyId, awsSecretAccessKey, awsSessionToken, awsRegion]);

  const executeAudit = useCallback(async (explicitCreds = null, persistToSession = false) => {
    setLoading(true);
    setActionMessage(null);
    try {
      const creds = explicitCreds || getEffectiveCreds();
      if (persistToSession && creds) {
        const sum = saveSessionCredentials(creds);
        if (sum) setVaultSummary(sum);
      }

      const res = await apiFetch("/api/v1/migration/cloud-audit/aws", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credentials: creds }),
      });
      const data = await res.json();

      // Ensure underlying CloudMove control-plane resources remain strictly hidden
      if (data && typeof data === "object") {
        data.projects_deployed = (data.projects_deployed || []).filter(
          (p) => !p.is_control_plane && p.project_id !== "cloudmove-control-plane"
        );
        data.instances = (data.instances || []).filter((i) => !i.is_control_plane);
        data.volumes = (data.volumes || []).filter((v) => !v.is_control_plane);
        data.vpcs = (data.vpcs || []).filter((vp) => !vp.is_control_plane && !vp.is_default);
        data.security_groups = (data.security_groups || []).filter(
          (sg) => !sg.is_control_plane && !sg.is_default
        );
      }

      setAuditData(data);
      if (data?.authenticated && creds) {
        const sum = saveSessionCredentials(creds);
        if (sum) setVaultSummary(sum);
        setShowCredsForm(false);
      }
      if (typeof onAuditCompletedRef.current === "function") {
        onAuditCompletedRef.current(data);
      }
    } catch (err) {
      setAuditData({
        authenticated: false,
        error: `No se pudo completar la consulta de auditoría AWS: ${err.message}`,
        projects_deployed: [],
        instances: [],
        volumes: [],
        vpcs: [],
        workspaces: [],
      });
    } finally {
      setLoading(false);
    }
  }, [getEffectiveCreds]);

  // Run once on initial mount if session credentials exist
  useEffect(() => {
    if (hasAutoAuditedRef.current) return;
    hasAutoAuditedRef.current = true;
    const stored = getSessionCredentials();
    if (stored) {
      executeAudit(stored, false);
    }
  }, [executeAudit]);

  const handleDeleteResource = async (
    resourceType,
    resourceId,
    cleanupVpc = true
  ) => {
    setActionLoadingId(`${resourceType}:${resourceId}`);
    setActionMessage(null);
    try {
      const creds = getEffectiveCreds();
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
          text: (data.details || [`Operación completada sobre ${resourceId}.`]).join(" · "),
        });
        setConfirmDeleteKey(null);
        await executeAudit(creds, false);
      } else {
        setActionMessage({
          type: "error",
          text: data.error || `No se pudo procesar el recurso ${resourceId}.`,
        });
      }
    } catch (err) {
      setActionMessage({
        type: "error",
        text: `Error al ejecutar operación en AWS: ${err.message}`,
      });
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleClearSessionVault = () => {
    clearSessionCredentials();
    setAwsAccessKeyId("");
    setAwsSecretAccessKey("");
    setAwsSessionToken("");
    setRawPasteBlock("");
    setVaultSummary(getCredentialsSummary());
    setAuditData(null);
    setShowCredsForm(true);
  };

  const summary = auditData?.summary || {};
  const projectsDeployed = auditData?.projects_deployed || [];
  const instances = auditData?.instances || [];
  const workspaces = auditData?.workspaces || [];
  const volumes = auditData?.volumes || [];
  const vpcs = auditData?.vpcs || [];

  const renderProjectBadge = (pinfo) => {
    if (!pinfo) return <span className="cm-hint">Sin proyecto asignado</span>;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <div style={{ fontWeight: 700, color: "#000716", fontSize: 13 }}>
          {pinfo.project_name}
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <span className="cm-badge aws" style={{ fontSize: 11, padding: "1px 7px" }}>
            {pinfo.use_case_label}
          </span>
          {pinfo.migration_id && (
            <code style={{ fontSize: 11.5, color: "#545b64" }}>
              {pinfo.migration_id}
            </code>
          )}
        </div>
      </div>
    );
  };

  return (
    <AwsContainer
      title="Auditoría en vivo de recursos AWS y despliegues Terraform"
      description="Inspección directa de instancias EC2, volúmenes EBS, redes VPC y estados locales de Terraform asociados a tus proyectos migrados (Caso 1 y Caso 2)."
      actions={
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {vaultSummary.hasCredentials && (
            <span className="cm-badge observed" title="Credenciales cifradas en sessionStorage">
              Sesión cifrada: {vaultSummary.maskedAccessKey} ({vaultSummary.fingerprint})
            </span>
          )}
          <button
            type="button"
            className="cm-btn sm"
            onClick={() => setShowCredsForm((prev) => !prev)}
          >
            {showCredsForm ? "Ocultar credenciales" : "Configurar credenciales STS"}
          </button>
          <button
            type="button"
            className="cm-btn primary sm"
            disabled={loading}
            onClick={() => executeAudit(null, true)}
          >
            {loading ? "Consultando AWS..." : "Ejecutar auditoría AWS"}
          </button>
        </div>
      }
    >
      {/* Panel de Credenciales en Memoria de Sesión (sessionStorage con Hash) */}
      {showCredsForm && (
        <div
          className="cm-card-subtle"
          style={{ marginBottom: 16, borderLeft: "3px solid #0972d3" }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 8,
              marginBottom: 12,
            }}
          >
            <div>
              <strong style={{ fontSize: 14, color: "#000716" }}>
                Credenciales de sesión AWS STS (Almacenamiento efímero en navegador)
              </strong>
              <div className="cm-hint">
                Las credenciales se almacenan exclusivamente en <code>sessionStorage</code> ofuscadas en memoria con huella criptográfica y se destruyen al cerrar la pestaña. Nunca se guardan en texto plano ni en disco.
              </div>
            </div>
            {vaultSummary.hasCredentials && (
              <button
                type="button"
                className="cm-btn danger sm"
                onClick={handleClearSessionVault}
              >
                Purgar credenciales de sesión
              </button>
            )}
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
              gap: 14,
            }}
          >
            <div>
              <label className="cm-label" htmlFor="aws-audit-paste-block">
                Pegado rápido de bloque AWS Academy CLI
              </label>
              <textarea
                id="aws-audit-paste-block"
                rows={4}
                className="cm-input"
                placeholder={`[default]\naws_access_key_id=ASIA...\naws_secret_access_key=...\naws_session_token=...`}
                value={rawPasteBlock}
                onChange={(e) => handleParseRawBlock(e.target.value)}
                style={{
                  width: "100%",
                  height: "auto",
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                  marginTop: 4,
                }}
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <label className="cm-label" htmlFor="aws-audit-ak">
                  AWS Access Key ID
                </label>
                <input
                  id="aws-audit-ak"
                  type="text"
                  className="cm-input"
                  value={awsAccessKeyId}
                  onChange={(e) => setAwsAccessKeyId(e.target.value)}
                  placeholder="ASIA..."
                  style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 12.5, marginTop: 4 }}
                />
              </div>
              <div>
                <label className="cm-label" htmlFor="aws-audit-region">
                  Región AWS
                </label>
                <select
                  id="aws-audit-region"
                  className="cm-select"
                  value={awsRegion}
                  onChange={(e) => setAwsRegion(e.target.value)}
                  style={{ width: "100%", marginTop: 4 }}
                >
                  <option value="us-east-1">us-east-1 (N. Virginia)</option>
                  <option value="us-west-2">us-west-2 (Oregón)</option>
                  <option value="eu-west-1">eu-west-1 (Irlanda)</option>
                  <option value="sa-east-1">sa-east-1 (São Paulo)</option>
                </select>
              </div>
              <div>
                <label className="cm-label" htmlFor="aws-audit-sk">
                  AWS Secret Access Key
                </label>
                <input
                  id="aws-audit-sk"
                  type="password"
                  className="cm-input"
                  value={awsSecretAccessKey}
                  onChange={(e) => setAwsSecretAccessKey(e.target.value)}
                  placeholder="••••••••••••••••"
                  style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 12.5, marginTop: 4 }}
                />
              </div>
              <div>
                <label className="cm-label" htmlFor="aws-audit-st">
                  AWS Session Token
                </label>
                <input
                  id="aws-audit-st"
                  type="password"
                  className="cm-input"
                  value={awsSessionToken}
                  onChange={(e) => setAwsSessionToken(e.target.value)}
                  placeholder="IQoJb3JpZ2luX2Vj..."
                  style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 12.5, marginTop: 4 }}
                />
              </div>
            </div>
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
            <button
              type="button"
              className="cm-btn primary sm"
              disabled={loading || !awsAccessKeyId.trim() || !awsSecretAccessKey.trim()}
              onClick={() => executeAudit(null, true)}
            >
              {loading ? "Validando STS..." : "Guardar en sesión y auditar cuenta AWS"}
            </button>
          </div>
        </div>
      )}

      {auditData?.error && (
        <AwsAlert type="error" title="Error de autenticación o consulta AWS STS" style={{ marginBottom: 16 }}>
          {auditData.error}
        </AwsAlert>
      )}

      {actionMessage && (
        <AwsAlert
          type={actionMessage.type === "error" ? "error" : "success"}
          title={actionMessage.type === "error" ? "Error en operación AWS" : "Operación completada"}
          onDismiss={() => setActionMessage(null)}
          style={{ marginBottom: 16 }}
        >
          {actionMessage.text}
        </AwsAlert>
      )}

      {/* Métricas de Resumen de Cuenta AWS */}
      <AwsKeyValuePairs
        columns={4}
        items={[
          {
            label: "Identidad STS y cuenta",
            value: auditData?.authenticated ? `Cuenta ${auditData.account_id}` : "Sin sesión STS",
            subtext: auditData?.caller_arn
              ? maskSecretValue(auditData.caller_arn, 18, 14)
              : "Introduce tus credenciales temporales para auditar",
          },
          {
            label: "Proyectos desplegados",
            value: summary.projects_count ?? projectsDeployed.length,
            subtext: `${summary.active_workspaces_count ?? 0} workspace(s) con estado Terraform`,
          },
          {
            label: "Instancias EC2 de cargas migradas",
            value: `${summary.running_instances_count ?? 0} en ejecución`,
            subtext: `${summary.total_instances_count ?? 0} instancia(s) totales de usuario`,
          },
          {
            label: "Volúmenes EBS y redes VPC",
            value: `${summary.total_ebs_gb ?? 0} GiB / ${summary.academy_ebs_limit_gb ?? 150} GiB`,
            subtext: `${summary.total_volumes_count ?? 0} volumen(es) EBS · ${summary.custom_vpcs_count ?? 0} VPC(s) dedicadas`,
          },
        ]}
      />

      {/* Pestañas de Vistas de Auditoría */}
      <AwsTabs
        activeTabId={activeSubSection}
        onTabChange={setActiveSubSection}
        tabs={[
          {
            id: "projects",
            label: "Por proyecto o despliegue",
            count: projectsDeployed.length,
          },
          {
            id: "instances",
            label: "Instancias EC2",
            count: instances.filter((i) => i.state !== "terminated").length,
          },
          {
            id: "storage_network",
            label: "Volúmenes EBS y redes VPC",
            count: volumes.length + vpcs.length,
          },
          {
            id: "workspaces",
            label: "Workspaces Terraform",
            count: workspaces.length,
          },
        ]}
      />

      {/* VISTA 1: AGRUPACIÓN POR PROYECTO */}
      {activeSubSection === "projects" && (
        <div>
          {projectsDeployed.length === 0 ? (
            <AwsEmptyState
              title="No hay despliegues de usuario activos en la cuenta AWS"
              description={
                auditData?.authenticated
                  ? "No se detectaron instancias EC2, volúmenes EBS ni redes VPC asociadas a despliegues de migración activos."
                  : "Configura tus credenciales de sesión AWS STS y haz clic en 'Ejecutar auditoría AWS' para listar tus recursos."
              }
            />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {projectsDeployed.map((proj) => {
                const delKey = `project:${proj.project_id}`;
                const isDeleting =
                  actionLoadingId === delKey ||
                  actionLoadingId?.includes(proj.migration_id || "");

                return (
                  <div
                    key={proj.project_id}
                    className="cm-card"
                    style={{ padding: 16, borderLeft: "4px solid #0972d3" }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "flex-start",
                        flexWrap: "wrap",
                        gap: 12,
                        paddingBottom: 12,
                        borderBottom: "1px solid #e9ebed",
                      }}
                    >
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <strong style={{ fontSize: 15, color: "#000716" }}>
                            {proj.project_name}
                          </strong>
                          <span className="cm-badge aws">{proj.use_case_label}</span>
                          {proj.migration_id && (
                            <code style={{ fontSize: 12, color: "#545b64" }}>
                              ID: {proj.migration_id}
                            </code>
                          )}
                        </div>
                        {proj.source_detail && (
                          <div className="cm-hint" style={{ marginTop: 4 }}>
                            Origen: <strong>{proj.source_detail}</strong>
                          </div>
                        )}
                      </div>

                      <div>
                        {confirmDeleteKey === delKey ? (
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <button
                              type="button"
                              className="cm-btn danger sm"
                              disabled={isDeleting}
                              onClick={async () => {
                                if (proj.vpcs && proj.vpcs.length > 0) {
                                  await handleDeleteResource("vpc", proj.vpcs[0].vpc_id, true);
                                } else if (proj.instances && proj.instances.length > 0) {
                                  await handleDeleteResource(
                                    "ec2_instance",
                                    proj.instances[0].instance_id,
                                    true
                                  );
                                } else if (proj.migration_id) {
                                  await handleDeleteResource(
                                    "terraform_workspace",
                                    proj.migration_id,
                                    true
                                  );
                                }
                              }}
                            >
                              {isDeleting ? "Eliminando..." : "Confirmar eliminación total"}
                            </button>
                            <button
                              type="button"
                              className="cm-btn sm"
                              onClick={() => setConfirmDeleteKey(null)}
                            >
                              Cancelar
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="cm-btn danger sm"
                            onClick={() => setConfirmDeleteKey(delKey)}
                          >
                            Eliminar despliegue de AWS
                          </button>
                        )}
                      </div>
                    </div>

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                        gap: 12,
                        marginTop: 12,
                      }}
                    >
                      <div className="cm-card-subtle" style={{ padding: 12 }}>
                        <div style={{ fontSize: 12, fontWeight: 700, color: "#545b64", marginBottom: 6 }}>
                          Instancias EC2 ({proj.instances?.length || 0})
                        </div>
                        {(proj.instances || []).map((inst) => (
                          <div key={inst.instance_id} style={{ fontSize: 13, marginBottom: 6 }}>
                            <div style={{ display: "flex", justifyContent: "space-between" }}>
                              <code>{inst.instance_id}</code>
                              <AwsStatusIndicator
                                type={inst.state === "running" ? "success" : "warning"}
                              >
                                {inst.state}
                              </AwsStatusIndicator>
                            </div>
                            {inst.public_ip && (
                              <div style={{ fontSize: 12, color: "#0972d3", fontFamily: "var(--font-mono)" }}>
                                IP Pública: {inst.public_ip}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>

                      <div className="cm-card-subtle" style={{ padding: 12 }}>
                        <div style={{ fontSize: 12, fontWeight: 700, color: "#545b64", marginBottom: 6 }}>
                          Almacenamiento EBS ({proj.volumes?.length || 0} vol · {proj.total_ebs_gb || 0} GiB)
                        </div>
                        {(proj.volumes || []).map((vol) => (
                          <div key={vol.volume_id} style={{ fontSize: 12.5, marginBottom: 4 }}>
                            <code>{vol.volume_id}</code> — <strong>{vol.size_gb} GiB</strong> ({vol.volume_type})
                          </div>
                        ))}
                      </div>

                      <div className="cm-card-subtle" style={{ padding: 12 }}>
                        <div style={{ fontSize: 12, fontWeight: 700, color: "#545b64", marginBottom: 6 }}>
                          Redes VPC y Security Groups
                        </div>
                        {(proj.vpcs || []).map((vp) => (
                          <div key={vp.vpc_id} style={{ fontSize: 12.5, marginBottom: 4 }}>
                            <code>{vp.vpc_id}</code> ({vp.cidr_block}) · {vp.subnets?.length || 0} subredes
                          </div>
                        ))}
                        {(proj.security_groups || []).map((sg) => (
                          <div key={sg.group_id} style={{ fontSize: 12, color: "#545b64" }}>
                            SG: <code>{sg.group_id}</code> ({sg.group_name})
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* VISTA 2: INSTANCIAS EC2 */}
      {activeSubSection === "instances" && (
        <div className="cm-table-wrap">
          {instances.length === 0 ? (
            <AwsEmptyState
              title="Sin instancias EC2 registradas"
              description="No se encontraron instancias EC2 de cargas migradas en esta región."
            />
          ) : (
            <table className="cm-table">
              <thead>
                <tr>
                  <th>Instancia / Nombre</th>
                  <th>Proyecto asociado</th>
                  <th>Estado</th>
                  <th>Tipo / AZ</th>
                  <th>IP Pública / Privada</th>
                  <th style={{ textAlign: "right" }}>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {instances.map((inst) => {
                  const delKey = `ec2_instance:${inst.instance_id}`;
                  const isBusy = actionLoadingId?.includes(inst.instance_id);
                  return (
                    <tr key={inst.instance_id}>
                      <td>
                        <strong>{inst.name}</strong>
                        <div>
                          <code>{inst.instance_id}</code>
                        </div>
                      </td>
                      <td>{renderProjectBadge(inst.project_info)}</td>
                      <td>
                        <AwsStatusIndicator
                          type={
                            inst.state === "running"
                              ? "success"
                              : inst.state === "stopped"
                              ? "stopped"
                              : "warning"
                          }
                        >
                          {inst.state?.toUpperCase()}
                        </AwsStatusIndicator>
                      </td>
                      <td>
                        <code>{inst.instance_type}</code>
                        <div className="cm-hint">{inst.availability_zone}</div>
                      </td>
                      <td>
                        {inst.public_ip ? (
                          <div>
                            <strong style={{ fontFamily: "var(--font-mono)", color: "#0972d3" }}>
                              {inst.public_ip}
                            </strong>
                            <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                              {inst.frontend_url && (
                                <a
                                  href={inst.frontend_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{ fontSize: 11.5, color: "#0972d3", fontWeight: 600 }}
                                >
                                  Abrir :3000 ↗
                                </a>
                              )}
                              {inst.docs_url && (
                                <a
                                  href={inst.docs_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{ fontSize: 11.5, color: "#0972d3", fontWeight: 600 }}
                                >
                                  API :8000 ↗
                                </a>
                              )}
                            </div>
                          </div>
                        ) : (
                          <span className="cm-hint">Sin IP pública</span>
                        )}
                        <div className="cm-hint">Privada: {inst.private_ip || "—"}</div>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {inst.state === "terminated" ? (
                          <span className="cm-hint">Terminada</span>
                        ) : confirmDeleteKey === delKey ? (
                          <div style={{ display: "inline-flex", gap: 6 }}>
                            <button
                              type="button"
                              className="cm-btn danger sm"
                              disabled={isBusy}
                              onClick={() =>
                                handleDeleteResource("ec2_instance", inst.instance_id, true)
                              }
                            >
                              Confirmar
                            </button>
                            <button
                              type="button"
                              className="cm-btn sm"
                              onClick={() => setConfirmDeleteKey(null)}
                            >
                              Cancelar
                            </button>
                          </div>
                        ) : (
                          <div style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                            {inst.state === "stopped" && (
                              <button
                                type="button"
                                className="cm-btn sm"
                                disabled={isBusy}
                                onClick={() =>
                                  handleDeleteResource("start_instance", inst.instance_id, false)
                                }
                              >
                                Iniciar
                              </button>
                            )}
                            {inst.state === "running" && (
                              <button
                                type="button"
                                className="cm-btn sm"
                                disabled={isBusy}
                                onClick={() =>
                                  handleDeleteResource("stop_instance", inst.instance_id, false)
                                }
                              >
                                Detener
                              </button>
                            )}
                            <button
                              type="button"
                              className="cm-btn danger sm"
                              disabled={isBusy}
                              onClick={() => setConfirmDeleteKey(delKey)}
                            >
                              Terminar
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

      {/* VISTA 3: VOLÚMENES EBS Y REDES VPC */}
      {activeSubSection === "storage_network" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 16 }}>
          <div className="cm-table-wrap">
            <div style={{ padding: "10px 16px", backgroundColor: "#fafafa", borderBottom: "1px solid #e9ebed", fontWeight: 700, fontSize: 13.5 }}>
              Volúmenes Amazon EBS ({volumes.length})
            </div>
            {volumes.length === 0 ? (
              <AwsEmptyState title="Sin volúmenes EBS de usuario" description="No hay volúmenes adicionales registrados." />
            ) : (
              <table className="cm-table">
                <thead>
                  <tr>
                    <th>Volumen ID</th>
                    <th>Capacidad</th>
                    <th>Estado</th>
                    <th style={{ textAlign: "right" }}>Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {volumes.map((v) => (
                    <tr key={v.volume_id}>
                      <td>
                        <code>{v.volume_id}</code>
                        <div className="cm-hint">{v.attached_instance_id || "Desasociado"}</div>
                      </td>
                      <td>
                        <strong>{v.size_gb} GiB</strong> ({v.volume_type})
                      </td>
                      <td>
                        <AwsStatusIndicator type={v.state === "available" ? "warning" : "info"}>
                          {v.state}
                        </AwsStatusIndicator>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {v.state === "available" ? (
                          <button
                            type="button"
                            className="cm-btn danger sm"
                            disabled={actionLoadingId === `ebs_volume:${v.volume_id}`}
                            onClick={() => handleDeleteResource("ebs_volume", v.volume_id, false)}
                          >
                            Eliminar
                          </button>
                        ) : (
                          <span className="cm-hint">En uso por EC2</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="cm-table-wrap">
            <div style={{ padding: "10px 16px", backgroundColor: "#fafafa", borderBottom: "1px solid #e9ebed", fontWeight: 700, fontSize: 13.5 }}>
              Redes Amazon VPC dedicadas ({vpcs.length})
            </div>
            {vpcs.length === 0 ? (
              <AwsEmptyState title="Sin VPCs personalizadas" description="No hay redes VPC de despliegues activas." />
            ) : (
              <table className="cm-table">
                <thead>
                  <tr>
                    <th>VPC / Nombre</th>
                    <th>CIDR / Subredes</th>
                    <th style={{ textAlign: "right" }}>Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {vpcs.map((vp) => (
                    <tr key={vp.vpc_id}>
                      <td>
                        <strong>{vp.name}</strong>
                        <div>
                          <code>{vp.vpc_id}</code>
                        </div>
                      </td>
                      <td>
                        <code>{vp.cidr_block}</code>
                        <div className="cm-hint">{vp.subnets?.length || 0} subredes</div>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          type="button"
                          className="cm-btn danger sm"
                          disabled={actionLoadingId === `vpc:${vp.vpc_id}`}
                          onClick={() => handleDeleteResource("vpc", vp.vpc_id, true)}
                        >
                          Eliminar VPC
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* VISTA 4: WORKSPACES LOCALES DE TERRAFORM */}
      {activeSubSection === "workspaces" && (
        <div className="cm-table-wrap">
          {workspaces.length === 0 ? (
            <AwsEmptyState
              title="Sin workspaces locales de Terraform"
              description="Los directorios de despliegue se crean al ejecutar planes de migración."
            />
          ) : (
            <table className="cm-table">
              <thead>
                <tr>
                  <th>Workspace / Migration ID</th>
                  <th>Proyecto</th>
                  <th>Recursos en tfstate</th>
                  <th>Instancia / IP</th>
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
                        <strong>{ws.migration_id}</strong>
                        <div className="cm-hint">{ws.workspace_dir}</div>
                      </td>
                      <td>{renderProjectBadge(ws.project_info)}</td>
                      <td>
                        <strong>{ws.resource_count}</strong> recurso(s)
                      </td>
                      <td>
                        {ws.primary_instance_id ? (
                          <code>
                            {ws.primary_instance_id}{" "}
                            {ws.primary_public_ip ? `(${ws.primary_public_ip})` : ""}
                          </code>
                        ) : (
                          <span className="cm-hint">Sin instancia activa</span>
                        )}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {ws.resource_count === 0 ? (
                          <span className="cm-hint">Limpio (0 recursos)</span>
                        ) : confirmDeleteKey === delKey ? (
                          <div style={{ display: "inline-flex", gap: 6 }}>
                            <button
                              type="button"
                              className="cm-btn danger sm"
                              disabled={isDeleting}
                              onClick={() =>
                                handleDeleteResource("terraform_workspace", ws.migration_id, true)
                              }
                            >
                              Confirmar destrucción
                            </button>
                            <button
                              type="button"
                              className="cm-btn sm"
                              onClick={() => setConfirmDeleteKey(null)}
                            >
                              Cancelar
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="cm-btn danger sm"
                            onClick={() => setConfirmDeleteKey(delKey)}
                          >
                            Destruir workspace
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
    </AwsContainer>
  );
}
