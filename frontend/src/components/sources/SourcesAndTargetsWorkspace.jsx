import React, { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../../utils/apiClient";
import {
  AwsPageHeader,
  AwsContainer,
  AwsKeyValuePairs,
  AwsTabs,
  AwsStatusIndicator,
  AwsAlert,
  AwsEmptyState,
} from "../cloudscape/AwsPrimitives";

export default function SourcesAndTargetsWorkspace() {
  const [connectors, setConnectors] = useState([]);
  const [providersData, setProvidersData] = useState(null);
  const [compatMatrix, setCompatMatrix] = useState(null);
  const [cloudSnapshots, setCloudSnapshots] = useState([]);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const [activeSubTab, setActiveSubTab] = useState("connectors-agents");

  // Connector registration form
  const [connName, setConnName] = useState("");
  const [connType, setConnType] = useState("vsphere");
  const [connEndpoint, setConnEndpoint] = useState(
    "https://vcenter-dc01.corp.local"
  );
  const [connUser, setConnUser] = useState("readonly-auditor@vsphere.local");
  const [connToken, setConnToken] = useState("");
  const [connFieldError, setConnFieldError] = useState("");

  // Live Cloud Discovery form
  const [cloudProvider, setCloudProvider] = useState("aws");
  const [cloudTarget, setCloudTarget] = useState("us-east-1");

  // CloudMove Agent Management states
  const [agents, setAgents] = useState([]);
  const [generatedToken, setGeneratedToken] = useState(null);
  const [generatingToken, setGeneratingToken] = useState(false);
  const [actionInProgress, setActionInProgress] = useState(null);

  const loadData = useCallback(async () => {
    try {
      const [cRes, pRes, mRes, sRes, agRes] = await Promise.all([
        apiFetch("/api/v1/connectors").catch(() => null),
        apiFetch("/api/v1/migration/providers").catch(() => null),
        apiFetch("/api/v1/migration/compatibility-matrix").catch(() => null),
        apiFetch("/api/v1/discovery/cloud/snapshots").catch(() => null),
        apiFetch("/api/v1/agents").catch(() => null),
      ]);
      if (cRes && cRes.ok) {
        const d = await cRes.json();
        setConnectors(d.connectors || []);
      }
      if (pRes && pRes.ok) {
        setProvidersData(await pRes.json());
      }
      if (mRes && mRes.ok) {
        const d = await mRes.json();
        setCompatMatrix(d.matrix || null);
      }
      if (sRes && sRes.ok) {
        const d = await sRes.json();
        setCloudSnapshots(d.snapshots || []);
      }
      if (agRes && agRes.ok) {
        const d = await agRes.json();
        setAgents(d.agents || []);
      }
    } catch {
      // Ignore transient errors
    }
  }, []);

  const handleGenerateEnrollmentToken = async () => {
    setGeneratingToken(true);
    setFeedback(null);
    try {
      const res = await apiFetch("/api/v1/agents/enrollment-tokens", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ttl_seconds: 86400,
          max_uses: 1,
          org_id: "default",
          created_by: "operator@cloudmove.local",
        }),
      });
      const data = await res.json();
      if (!res.ok)
        throw new Error(data.detail || "Error al generar token de inscripción.");
      setGeneratedToken(data);
      await loadData();
      setFeedback({
        type: "success",
        title: "Token de inscripción generado",
        message: `Token '${data.token_prefix}' generado (válido por 24 horas, 1 solo uso).`,
      });
    } catch (err) {
      setFeedback({
        type: "error",
        title: "Error al generar token",
        message: err.message,
      });
    } finally {
      setGeneratingToken(false);
    }
  };

  const handleDispatchAgentScan = async (agentId) => {
    setActionInProgress(agentId);
    setFeedback(null);
    try {
      const res = await apiFetch(`/api/v1/agents/${agentId}/dispatch-task`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "collect_inventory",
          parameters: {},
        }),
      });
      const data = await res.json();
      if (!res.ok)
        throw new Error(data.detail || "Error al despachar orden al agente.");
      setFeedback({
        type: "success",
        title: "Orden despachada al agente",
        message: `Tarea 'collect_inventory' asignada al agente '${agentId}'. El agente ejecutará el escaneo en su próximo ciclo de polling.`,
      });
    } catch (err) {
      setFeedback({
        type: "error",
        title: "Error al despachar orden",
        message: err.message,
      });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleRevokeAgent = async (agentId) => {
    if (
      !window.confirm(
        `¿Seguro que desea revocar el agente '${agentId}'? No podrá volver a conectarse.`
      )
    )
      return;
    setActionInProgress(agentId);
    setFeedback(null);
    try {
      const res = await apiFetch(`/api/v1/agents/${agentId}/revoke`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason: "Revocado por el operador desde el panel web",
          operator_id:
            (typeof window !== "undefined" &&
              window.localStorage?.getItem("cloudmove_operator_id")) ||
            "operator",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error al revocar agente.");
      await loadData();
      setFeedback({
        type: "warning",
        title: "Agente revocado",
        message: `El agente '${agentId}' ha sido revocado permanentemente.`,
      });
    } catch (err) {
      setFeedback({
        type: "error",
        title: "Error al revocar",
        message: err.message,
      });
    } finally {
      setActionInProgress(null);
    }
  };

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRegisterConnector = async (e) => {
    e.preventDefault();
    setConnFieldError("");
    setFeedback(null);

    if (!connName.trim()) {
      setConnFieldError(
        "Introduce un nombre descriptivo para el conector de origen."
      );
      return;
    }
    if (!connEndpoint.trim()) {
      setConnFieldError(
        "Especifica la URL o dirección IP del endpoint de origen."
      );
      return;
    }

    setLoading(true);
    try {
      const res = await apiFetch("/api/v1/connectors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: connName.trim(),
          type: connType,
          endpoint: connEndpoint.trim(),
          credentials: {
            username: connUser.trim() || "auditor",
            token: connToken || "readonly-session-token",
          },
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "No se pudo registrar el conector.");
      }
      setConnName("");
      setConnToken("");
      await loadData();
      setFeedback({
        type: "success",
        title: "Conector de origen registrado y verificado",
        message: `Se registró '${
          data.connector?.name || connName
        }' (${connType}) con estado ${data.connector?.status || "connected"}.`,
      });
    } catch (err) {
      setFeedback({
        type: "error",
        title: "Error al registrar conector de origen",
        message: err.message,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleLiveCloudDiscovery = async () => {
    setLoading(true);
    setFeedback(null);
    try {
      const endpoint = cloudProvider === "aws" ? "aws" : "gcp";
      const payload =
        cloudProvider === "aws"
          ? { regions: [cloudTarget || "us-east-1"] }
          : { project_id: cloudTarget || "cloudmove-prod-gcp" };

      const res = await apiFetch(`/api/v1/discovery/cloud/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        const detailMsg =
          data.detail?.message ||
          (typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail));
        throw new Error(`[HTTP ${res.status}] ${detailMsg}`);
      }
      await loadData();
      setFeedback({
        type: "success",
        title: `Descubrimiento cloud en vivo (${cloudProvider.toUpperCase()}) completado`,
        message: `Snapshot ${data.snapshot_id} almacenado con ${
          data.cmir?.resources?.length || 0
        } recursos normalizados.`,
      });
    } catch (err) {
      setFeedback({
        type: "warning",
        title: `Diagnóstico transparente de credenciales cloud (${cloudProvider.toUpperCase()})`,
        message: `${err.message}. CloudMove nunca simula una cuenta cloud en vivo como inventario vacío: configura credenciales IAM/ADC reales o utiliza el modo de evaluación Dry-Run.`,
      });
    } finally {
      setLoading(false);
    }
  };

  const awsInfo = providersData?.providers?.aws;
  const gcpInfo = providersData?.providers?.gcp;
  const onlineAgentsCount = agents.filter((a) => a.status === "ONLINE").length;

  return (
    <div className="tab-pane-view">
      <AwsPageHeader
        title="Orígenes y destinos"
        description="Conectores locales, agentes y cuentas destino en AWS y GCP."
        badges={
          <>
            <span className="cm-badge observed">
              Conectores activos: {connectors.length}
            </span>
            <span className="cm-badge aws">AWS soportado</span>
            <span className="cm-badge gcp">GCP soportado</span>
            <span className="cm-badge">Azure excluido (ADR-001)</span>
          </>
        }
        actions={
          <button
            type="button"
            className="cm-btn primary sm"
            onClick={handleGenerateEnrollmentToken}
            disabled={generatingToken}
          >
            {generatingToken ? "Generando..." : "Generar token de inscripción"}
          </button>
        }
      />

      {feedback && (
        <AwsAlert
          type={feedback.type}
          title={feedback.title}
          onDismiss={() => setFeedback(null)}
          style={{ marginBottom: 16 }}
        >
          {feedback.message}
        </AwsAlert>
      )}

      <AwsKeyValuePairs
        columns={4}
        items={[
          {
            label: "Conectores on-premise registrados",
            value: connectors.length,
            subtext: "vSphere, Proxmox VE, SSH+osquery, OpenStack, K8s",
          },
          {
            label: "Agentes CloudMove instalados",
            value: `${onlineAgentsCount} / ${agents.length}`,
            subtext: "Agentes activos en línea con heartbeat TLS",
          },
          {
            label: "Snapshots cloud en vivo",
            value: cloudSnapshots.length,
            subtext: "AWS boto3 y GCP Cloud Asset paginados",
          },
          {
            label: "Proveedores destino habilitados",
            value: "AWS · GCP",
            subtext: "Validación automática de Terraform CLI e IAM",
          },
        ]}
      />

      <AwsTabs
        activeTabId={activeSubTab}
        onTabChange={setActiveSubTab}
        tabs={[
          {
            id: "connectors-agents",
            label: "Conectores y agentes",
            count: connectors.length + agents.length,
          },
          {
            id: "live-cloud",
            label: "Descubrimiento cloud",
            count: cloudSnapshots.length,
          },
          {
            id: "prereqs-matrix",
            label: "IAM y compatibilidad",
          },
        ]}
      />

      {activeSubTab === "connectors-agents" && (
        <div className="cm-split-layout">
          <AwsContainer
            title="Registrar nuevo conector on-premise"
            description="Registra un endpoint de hipervisor o clúster en modo de solo lectura."
            actions={<span className="cm-badge info">Solo lectura</span>}
          >
            <form
              onSubmit={handleRegisterConnector}
              style={{ display: "flex", flexDirection: "column", gap: 12 }}
              noValidate
            >
              <div className="cm-field">
                <label htmlFor="conn-name" className="cm-label">
                  Nombre del conector *
                </label>
                <input
                  id="conn-name"
                  type="text"
                  className="cm-input"
                  placeholder="Ej. Proxmox VE Clúster Producción..."
                  value={connName}
                  onChange={(e) => setConnName(e.target.value)}
                  required
                />
              </div>

              <div className="cm-field">
                <label htmlFor="conn-type" className="cm-label">
                  Plataforma o protocolo de origen
                </label>
                <select
                  id="conn-type"
                  className="cm-select"
                  value={connType}
                  onChange={(e) => setConnType(e.target.value)}
                >
                  <option value="vsphere">VMware vSphere / vCenter API</option>
                  <option value="proxmox">Proxmox VE Cluster API</option>
                  <option value="ssh_osquery">
                    Linux Bare-Metal / VM (SSH + osquery)
                  </option>
                  <option value="openstack">OpenStack Nova / Neutron API</option>
                  <option value="kubernetes">Kubernetes Cluster API</option>
                </select>
              </div>

              <div className="cm-field">
                <label htmlFor="conn-endpoint" className="cm-label">
                  Endpoint / hostname / rango CIDR *
                </label>
                <input
                  id="conn-endpoint"
                  type="text"
                  className="cm-input"
                  value={connEndpoint}
                  onChange={(e) => setConnEndpoint(e.target.value)}
                  required
                />
                <span className="cm-hint">
                  Se verifica conectividad sin alterar cargas en ejecución.
                </span>
              </div>

              <div className="cm-field">
                <label htmlFor="conn-user" className="cm-label">
                  Cuenta de servicio o rol auditor
                </label>
                <input
                  id="conn-user"
                  type="text"
                  className="cm-input"
                  value={connUser}
                  onChange={(e) => setConnUser(e.target.value)}
                />
              </div>

              <div className="cm-field">
                <label htmlFor="conn-token" className="cm-label">
                  Token API o secreto (redactado en reposo)
                </label>
                <input
                  id="conn-token"
                  type="password"
                  className="cm-input"
                  placeholder="••••••••••••••••"
                  value={connToken}
                  onChange={(e) => setConnToken(e.target.value)}
                  autoComplete="off"
                />
              </div>

              {connFieldError && (
                <AwsAlert type="error" title="Campo requerido">
                  {connFieldError}
                </AwsAlert>
              )}

              <button type="submit" className="cm-btn primary" disabled={loading}>
                {loading
                  ? "Validando conector..."
                  : "Validar y registrar conector"}
              </button>
            </form>
          </AwsContainer>

          <div>
            <AwsContainer
              title="Agentes CloudMove instalados"
              counter={agents.length}
              description="Agentes registrados con telemetría y recolección osquery remota."
              noPadding={agents.length > 0 && !generatedToken}
              actions={
                <button
                  type="button"
                  className="cm-btn primary sm"
                  onClick={handleGenerateEnrollmentToken}
                  disabled={generatingToken}
                >
                  {generatingToken
                    ? "Generando..."
                    : "Generar token de inscripción"}
                </button>
              }
            >
              {generatedToken && (
                <div style={{ marginBottom: 14 }}>
                  <AwsAlert
                    type="success"
                    title={`Nuevo token generado: ${generatedToken.enrollment_token}`}
                  >
                    <div>Expira: {generatedToken.expires_at?.slice(0, 16)}</div>
                    <div style={{ marginTop: 8 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 700 }}>
                        Comando de instalación en Linux (systemd):
                      </div>
                      <pre
                        style={{
                          background: "#16191f",
                          color: "#f2f3f3",
                          padding: 8,
                          borderRadius: 4,
                          fontSize: 13.5,
                          overflowX: "auto",
                          margin: "4px 0 8px 0",
                        }}
                      >
                        {generatedToken.install_command_linux}
                      </pre>
                      <div style={{ fontSize: 13.5, fontWeight: 700 }}>
                        Comando de instalación en Windows (PowerShell):
                      </div>
                      <pre
                        style={{
                          background: "#16191f",
                          color: "#f2f3f3",
                          padding: 8,
                          borderRadius: 4,
                          fontSize: 13.5,
                          overflowX: "auto",
                          margin: "4px 0 0 0",
                        }}
                      >
                        {generatedToken.install_command_windows}
                      </pre>
                    </div>
                  </AwsAlert>
                </div>
              )}

              {agents.length === 0 ? (
                <AwsEmptyState
                  title="No hay agentes registrados todavía"
                  description="Genera un token de inscripción e instala el agente en tus servidores autorizados."
                />
              ) : (
                <div className="cm-table-wrap" style={{ border: "none", borderRadius: 0 }}>
                  <table className="cm-table">
                    <thead>
                      <tr>
                        <th>Agente / hostname</th>
                        <th>IP y sistema operativo</th>
                        <th>Estado y salud</th>
                        <th>Último heartbeat</th>
                        <th>Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {agents.map((ag) => (
                        <tr key={ag.agent_id}>
                          <td>
                            <strong>{ag.hostname}</strong>
                            <div className="cm-hint">
                              <code>{ag.agent_id}</code>
                            </div>
                          </td>
                          <td>
                            <div>
                              <code>{ag.ip_address}</code>
                            </div>
                            <span className="cm-hint">
                              {ag.os_name} {ag.os_version} ({ag.architecture})
                            </span>
                          </td>
                          <td>
                            <AwsStatusIndicator
                              type={
                                ag.status === "ONLINE"
                                  ? "success"
                                  : ag.status === "REVOKED"
                                  ? "error"
                                  : "warning"
                              }
                            >
                              {ag.status}
                            </AwsStatusIndicator>
                            {ag.health_metrics && (
                              <div className="cm-hint" style={{ marginTop: 2 }}>
                                CPU: {ag.health_metrics.cpu_percent || 0}% · RAM:{" "}
                                {ag.health_metrics.ram_percent || 0}%
                              </div>
                            )}
                          </td>
                          <td>
                            <span className="cm-hint">
                              {ag.last_heartbeat_at
                                ?.slice(0, 19)
                                .replace("T", " ")}
                            </span>
                          </td>
                          <td>
                            <div style={{ display: "flex", gap: 6 }}>
                              {ag.status === "ONLINE" && (
                                <button
                                  type="button"
                                  className="cm-btn sm"
                                  disabled={actionInProgress === ag.agent_id}
                                  onClick={() =>
                                    handleDispatchAgentScan(ag.agent_id)
                                  }
                                >
                                  Escanear
                                </button>
                              )}
                              {ag.status !== "REVOKED" && (
                                <button
                                  type="button"
                                  className="cm-btn danger sm"
                                  disabled={actionInProgress === ag.agent_id}
                                  onClick={() => handleRevokeAgent(ag.agent_id)}
                                >
                                  Revocar
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </AwsContainer>

            <AwsContainer
              title="Conectores de descubrimiento registrados"
              counter={connectors.length}
              description="Colectores autorizados por política para descubrimiento de infraestructura."
              noPadding={true}
            >
              <div className="cm-table-wrap" style={{ border: "none", borderRadius: 0 }}>
                <table className="cm-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Nombre y sitio</th>
                      <th>Tipo de colector</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {connectors.map((c) => (
                      <tr key={c.id}>
                        <td>
                          <code>{c.id}</code>
                        </td>
                        <td>
                          <strong>{c.name}</strong>
                          <div className="cm-hint">
                            Entorno: {c.environment_id || "env-datacenter-01"} ·
                            Sitio: {c.site_id || "site-primary"}
                          </div>
                        </td>
                        <td>
                          <code>{c.type}</code>
                        </td>
                        <td>
                          <AwsStatusIndicator type="success">
                            {c.status ||
                              (c.authorized ? "AUTORIZADO" : "PENDIENTE")}
                          </AwsStatusIndicator>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </AwsContainer>
          </div>
        </div>
      )}

      {activeSubTab === "live-cloud" && (
        <AwsContainer
          title="Descubrimiento cloud en vivo y reconciliación (AWS boto3 · GCP Cloud Asset)"
          counter={cloudSnapshots.length}
          description="Inspecciona cuentas cloud reales paginadas (STS/EC2/RDS/S3/IAM o Compute/Cloud SQL/GCS). Si las credenciales IAM/ADC no están presentes, informa el diagnóstico exacto."
        >
          <div className="cm-form-grid">
            <div className="cm-field">
              <label htmlFor="live-cloud-provider" className="cm-label">
                Proveedor cloud a inspeccionar
              </label>
              <select
                id="live-cloud-provider"
                className="cm-select"
                value={cloudProvider}
                onChange={(e) => {
                  setCloudProvider(e.target.value);
                  setCloudTarget(
                    e.target.value === "aws"
                      ? "us-east-1"
                      : "cloudmove-prod-gcp"
                  );
                }}
              >
                <option value="aws">
                  Amazon Web Services (AWS STS/EC2/RDS/S3)
                </option>
                <option value="gcp">
                  Google Cloud Platform (GCP Compute/SQL/GCS)
                </option>
              </select>
            </div>
            <div className="cm-field">
              <label htmlFor="live-cloud-target" className="cm-label">
                {cloudProvider === "aws"
                  ? "Región AWS objetivo"
                  : "GCP Project ID objetivo"}
              </label>
              <input
                id="live-cloud-target"
                type="text"
                className="cm-input"
                value={cloudTarget}
                onChange={(e) => setCloudTarget(e.target.value)}
              />
            </div>
            <div>
              <button
                type="button"
                className="cm-btn primary"
                onClick={handleLiveCloudDiscovery}
                disabled={loading}
              >
                Probar descubrimiento en vivo ({cloudProvider.toUpperCase()})
              </button>
            </div>
          </div>
        </AwsContainer>
      )}

      {activeSubTab === "prereqs-matrix" && (
        <>
          {providersData && (
            <AwsContainer
              title="Estado de prerrequisitos y capacidades por proveedor cloud destino"
              description="Verificación automática de herramientas locales (Terraform CLI) y permisos IAM requeridos."
            >
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
                  gap: 16,
                }}
              >
                {[
                  {
                    key: "aws",
                    label: "Amazon Web Services (AWS)",
                    badge: "aws",
                    data: awsInfo,
                  },
                  {
                    key: "gcp",
                    label: "Google Cloud Platform (GCP)",
                    badge: "gcp",
                    data: gcpInfo,
                  },
                ].map(({ key, label, badge, data }) => {
                  if (!data) return null;
                  const prereq = data.prerequisites || {};
                  const caps = data.config?.capabilities || {};
                  return (
                    <div key={key} className="cm-card-subtle">
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          marginBottom: 10,
                        }}
                      >
                        <strong style={{ fontSize: 15 }}>{label}</strong>
                        <span className={`cm-badge ${badge}`}>
                          Modo:{" "}
                          {prereq.execution_mode === "real_cloud"
                            ? "Nube real"
                            : "Dry-Run seguro"}
                        </span>
                      </div>
                      <div
                        style={{
                          display: "flex",
                          gap: 6,
                          flexWrap: "wrap",
                          marginBottom: 10,
                        }}
                      >
                        <span
                          className={`cm-badge ${
                            prereq.terraform_cli_installed
                              ? "observed"
                              : "warning"
                          }`}
                        >
                          Terraform CLI:{" "}
                          {prereq.terraform_cli_installed
                            ? "Instalado"
                            : "Ausente"}
                        </span>
                        <span
                          className={`cm-badge ${
                            prereq.live_credentials_verified
                              ? "observed"
                              : "simulated"
                          }`}
                        >
                          Credenciales en vivo:{" "}
                          {prereq.live_credentials_verified
                            ? "Verificadas"
                            : "Modo simulación"}
                        </span>
                      </div>
                      <div style={{ fontSize: 14, marginBottom: 8 }}>
                        <strong>Formatos de imagen soportados:</strong>{" "}
                        <code>
                          {(caps.SupportedImageFormats || []).join(", ")}
                        </code>
                      </div>
                      <div style={{ fontSize: 14, marginBottom: 8 }}>
                        <strong>Mecanismos de importación VM:</strong>{" "}
                        {(caps.vm_image_import || []).join(" · ")}
                      </div>
                      <div style={{ fontSize: 14, marginBottom: 8 }}>
                        <strong>Permisos IAM requeridos en destino:</strong>
                        <div
                          style={{
                            display: "flex",
                            flexWrap: "wrap",
                            gap: 4,
                            marginTop: 4,
                          }}
                        >
                          {(prereq.required_permissions || []).map((perm) => (
                            <code
                              key={perm}
                              style={{
                                fontSize: 13,
                                padding: "2px 6px",
                                background: "#ffffff",
                                border: "1px solid var(--color-border-subtle)",
                                borderRadius: 4,
                              }}
                            >
                              {perm}
                            </code>
                          ))}
                        </div>
                      </div>
                      {(prereq.notes || []).map((note, idx) => (
                        <div key={idx} className="cm-hint" style={{ marginTop: 4 }}>
                          • {note}
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            </AwsContainer>
          )}

          {compatMatrix && (
            <AwsContainer
              title="Matriz oficial de estrategias de replicación e importación de imágenes (AWS · GCP)"
              description="Formatos nativos, convertibles (qemu-img), modos de arranque y límites de almacenamiento por proveedor."
              noPadding={true}
            >
              <div className="cm-table-wrap" style={{ border: "none", borderRadius: 0 }}>
                <table className="cm-table">
                  <thead>
                    <tr>
                      <th>Proveedor y servicio oficial</th>
                      <th>Mecanismo</th>
                      <th>Formatos / fuentes soportadas</th>
                      <th>Boot y arquitectura</th>
                      <th>Límite disco</th>
                      <th>Requisitos de red y conversión</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(compatMatrix).flatMap(
                      ([provKey, services]) =>
                        Object.entries(services || {}).map(([srvKey, srv]) => (
                          <tr key={`${provKey}-${srvKey}`}>
                            <td>
                              <span
                                className={`cm-badge ${
                                  provKey === "gcp" ? "gcp" : "aws"
                                }`}
                                style={{ marginBottom: 4 }}
                              >
                                {provKey.toUpperCase()}
                              </span>
                              <div>
                                <strong>{srv.service_name}</strong>
                              </div>
                            </td>
                            <td>
                              <code>{srv.mechanism}</code>
                            </td>
                            <td>
                              {srv.native_formats ? (
                                <div>
                                  <strong>Nativos:</strong>{" "}
                                  <code>{srv.native_formats.join(", ")}</code>
                                  {srv.convertible_formats?.length > 0 && (
                                    <div className="cm-hint">
                                      Convertibles (qemu-img):{" "}
                                      <code>
                                        {srv.convertible_formats.join(", ")}
                                      </code>
                                    </div>
                                  )}
                                </div>
                              ) : (
                                <div>
                                  <strong>Orígenes:</strong>{" "}
                                  <code>
                                    {(srv.supported_source_types || []).join(
                                      ", "
                                    )}
                                  </code>
                                </div>
                              )}
                            </td>
                            <td>
                              <div>
                                Boot:{" "}
                                <code>
                                  {(srv.supported_boot_modes || []).join(" / ")}
                                </code>
                              </div>
                              <div className="cm-hint">
                                Arch:{" "}
                                {(srv.supported_architectures || []).join(", ")}
                              </div>
                            </td>
                            <td>
                              <strong>
                                {srv.max_disk_size_tib ||
                                  srv.max_boot_disk_size_tib ||
                                  16}{" "}
                                TiB
                              </strong>
                            </td>
                            <td>
                              {(srv.network_requirements || []).map((nr, i) => (
                                <div key={i} style={{ fontSize: 13.5 }}>
                                  • {nr}
                                </div>
                              ))}
                              {srv.staging_storage && (
                                <div style={{ fontSize: 13.5 }}>
                                  • Staging: {srv.staging_storage}
                                </div>
                              )}
                            </td>
                          </tr>
                        ))
                    )}
                  </tbody>
                </table>
              </div>
            </AwsContainer>
          )}
        </>
      )}
    </div>
  );
}
