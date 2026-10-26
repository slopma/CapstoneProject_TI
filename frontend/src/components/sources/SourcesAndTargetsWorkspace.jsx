import React, { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../../utils/apiClient";

export default function SourcesAndTargetsWorkspace() {
  const [connectors, setConnectors] = useState([]);
  const [providersData, setProvidersData] = useState(null);
  const [compatMatrix, setCompatMatrix] = useState(null);
  const [cloudSnapshots, setCloudSnapshots] = useState([]);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState(null);

  // Connector registration form
  const [connName, setConnName] = useState("");
  const [connType, setConnType] = useState("vsphere");
  const [connEndpoint, setConnEndpoint] = useState("https://vcenter-dc01.corp.local");
  const [connUser, setConnUser] = useState("readonly-auditor@vsphere.local");
  const [connToken, setConnToken] = useState("");
  const [connFieldError, setConnFieldError] = useState("");

  // Live Cloud Discovery form
  const [cloudProvider, setCloudProvider] = useState("aws");
  const [cloudTarget, setCloudTarget] = useState("us-east-1");

  // CloudMove Agent Management states
  const [agents, setAgents] = useState([]);
  const [enrollmentTokens, setEnrollmentTokens] = useState([]);
  const [generatedToken, setGeneratedToken] = useState(null);
  const [generatingToken, setGeneratingToken] = useState(false);
  const [actionInProgress, setActionInProgress] = useState(null);

  const loadData = useCallback(async () => {
    try {
      const [cRes, pRes, mRes, sRes, agRes, tokRes] = await Promise.all([
        apiFetch("/api/v1/connectors").catch(() => null),
        apiFetch("/api/v1/migration/providers").catch(() => null),
        apiFetch("/api/v1/migration/compatibility-matrix").catch(() => null),
        apiFetch("/api/v1/discovery/cloud/snapshots").catch(() => null),
        apiFetch("/api/v1/agents").catch(() => null),
        apiFetch("/api/v1/agents/enrollment-tokens").catch(() => null),
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
      if (tokRes && tokRes.ok) {
        const d = await tokRes.json();
        setEnrollmentTokens(d.tokens || []);
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
      if (!res.ok) throw new Error(data.detail || "Error al generar token de inscripción.");
      setGeneratedToken(data);
      await loadData();
      setFeedback({
        type: "success",
        title: "Token de Inscripción Generado",
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
      if (!res.ok) throw new Error(data.detail || "Error al despachar orden al agente.");
      setFeedback({
        type: "success",
        title: "Orden Despachada al Agente",
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
    if (!window.confirm(`¿Seguro que desea revocar el agente '${agentId}'? No podrá volver a conectarse.`)) return;
    setActionInProgress(agentId);
    setFeedback(null);
    try {
      const res = await apiFetch(`/api/v1/agents/${agentId}/revoke`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason: "Revocado por el operador desde el panel web",
          operator_id: (typeof window !== "undefined" && window.localStorage?.getItem("cloudmove_operator_id")) || "operator",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error al revocar agente.");
      await loadData();
      setFeedback({
        type: "warning",
        title: "Agente Revocado",
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
      setConnFieldError("Introduce un nombre descriptivo para el conector de origen.");
      return;
    }
    if (!connEndpoint.trim()) {
      setConnFieldError("Especifica la URL o dirección IP del endpoint de origen.");
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
        message: `Se registró '${data.connector?.name || connName}' (${connType}) con estado ${data.connector?.status || "connected"}.`,
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
          (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
        throw new Error(`[HTTP ${res.status}] ${detailMsg}`);
      }
      await loadData();
      setFeedback({
        type: "success",
        title: `Descubrimiento Cloud en Vivo (${cloudProvider.toUpperCase()}) completado`,
        message: `Snapshot ${data.snapshot_id} almacenado con ${data.cmir?.resources?.length || 0} recursos normalizados.`,
      });
    } catch (err) {
      setFeedback({
        type: "warning",
        title: `Diagnóstico transparente de credenciales Cloud (${cloudProvider.toUpperCase()})`,
        message: `${err.message}. CloudMove nunca simula una cuenta cloud en vivo como inventario vacío: configura credenciales IAM/ADC reales o utiliza el modo de evaluación Dry-Run.`,
      });
    } finally {
      setLoading(false);
    }
  };

  const awsInfo = providersData?.providers?.aws;
  const gcpInfo = providersData?.providers?.gcp;

  return (
    <div className="tab-pane-view">
      <div className="cm-page-header">
        <div>
          <h2 className="cm-page-title">
            Configuración de Orígenes On-Premise y Destinos Cloud (AWS · GCP)
          </h2>
          <p className="cm-page-subtitle">
            Gestiona conectores de descubrimiento de infraestructura local, verifica prerrequisitos reales de cuentas destino en AWS y Google Cloud Platform y consulta la matriz oficial de compatibilidad de formatos e hipervisores.
          </p>
        </div>
        <div className="cm-header-badges">
          <span className="cm-badge observed">Conectores Activos: {connectors.length}</span>
          <span className="cm-badge aws">AWS Soportado</span>
          <span className="cm-badge gcp">GCP Soportado</span>
          <span className="cm-badge neutral">Azure Excluido (ADR-001)</span>
        </div>
      </div>

      {feedback && (
        <div className={`cm-alert ${feedback.type}`} role="status" style={{ marginBottom: 18 }}>
          <strong>{feedback.title}:</strong> {feedback.message}
        </div>
      )}

      {/* Sección 1: Conectores On-Premise */}
      <div className="cm-split-layout" style={{ marginBottom: 20 }}>
        <div className="cm-card">
          <h3 className="cm-card-title">
            <span>Registrar Nuevo Conector On-Premise</span>
            <span className="cm-badge info">Solo lectura</span>
          </h3>
          <form onSubmit={handleRegisterConnector} style={{ display: "flex", flexDirection: "column", gap: 12 }} noValidate>
            <div className="cm-field">
              <label htmlFor="conn-name" className="cm-label">
                Nombre del Conector *
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
                Plataforma / Protocolo de Origen
              </label>
              <select
                id="conn-type"
                className="cm-select"
                value={connType}
                onChange={(e) => setConnType(e.target.value)}
              >
                <option value="vsphere">VMware vSphere / vCenter API</option>
                <option value="proxmox">Proxmox VE Cluster API</option>
                <option value="ssh_osquery">Linux Bare-Metal / VM (SSH + osquery)</option>
                <option value="openstack">OpenStack Nova / Neutron API</option>
                <option value="kubernetes">Kubernetes Cluster API</option>
              </select>
            </div>

            <div className="cm-field">
              <label htmlFor="conn-endpoint" className="cm-label">
                Endpoint / Hostname / Rango CIDR *
              </label>
              <input
                id="conn-endpoint"
                type="text"
                className="cm-input"
                value={connEndpoint}
                onChange={(e) => setConnEndpoint(e.target.value)}
                required
              />
              <span className="cm-hint">Se verifica conectividad sin alterar cargas en ejecución.</span>
            </div>

            <div className="cm-field">
              <label htmlFor="conn-user" className="cm-label">
                Cuenta de Servicio / Rol Auditor
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
                Token API / Secreto (Redactado en reposo)
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
              <div className="cm-alert error" role="alert">
                {connFieldError}
              </div>
            )}

            <button type="submit" className="cm-btn primary" disabled={loading}>
              {loading ? "Validando conector..." : "Validar y Registrar Conector"}
            </button>
          </form>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Sección de Agentes CloudMove Instalados */}
          <div className="cm-card">
            <div className="cm-card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <span>Agentes CloudMove Instalados ({agents.length})</span>
                <span className="cm-badge observed" style={{ marginLeft: 8 }}>
                  {agents.filter((a) => a.status === "ONLINE").length} Activos en Línea
                </span>
              </div>
              <button
                type="button"
                className="cm-btn primary"
                onClick={handleGenerateEnrollmentToken}
                disabled={generatingToken}
                style={{ fontSize: 12, padding: "6px 12px" }}
              >
                {generatingToken ? "Generando..." : "+ Generar Token de Inscripción"}
              </button>
            </div>

            {generatedToken && (
              <div className="cm-alert success" style={{ marginBottom: 14 }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>
                  Nuevo Token Generado: <code>{generatedToken.enrollment_token}</code> (Expira: {generatedToken.expires_at?.slice(0, 16)})
                </div>
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)" }}>Comando de instalación en Linux (systemd):</div>
                  <pre style={{ background: "var(--color-bg-subtle)", padding: 8, borderRadius: 4, fontSize: 11.5, overflowX: "auto", margin: "4px 0 8px 0" }}>
                    {generatedToken.install_command_linux}
                  </pre>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)" }}>Comando de instalación en Windows (PowerShell):</div>
                  <pre style={{ background: "var(--color-bg-subtle)", padding: 8, borderRadius: 4, fontSize: 11.5, overflowX: "auto", margin: "4px 0 0 0" }}>
                    {generatedToken.install_command_windows}
                  </pre>
                </div>
              </div>
            )}

            {agents.length === 0 ? (
              <p className="cm-hint" style={{ margin: "12px 0 0 0" }}>
                No hay agentes registrados todavía. Genera un token de inscripción e instala el agente en tus servidores autorizados usando el script oficial.
              </p>
            ) : (
              <div className="cm-table-wrap" style={{ marginTop: 12 }}>
                <table className="cm-table">
                  <thead>
                    <tr>
                      <th>Agente / Hostname</th>
                      <th>IP & OS</th>
                      <th>Estado & Salud</th>
                      <th>Último Heartbeat</th>
                      <th>Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.map((ag) => (
                      <tr key={ag.agent_id}>
                        <td>
                          <div style={{ fontWeight: 700 }}>{ag.hostname}</div>
                          <span className="cm-hint"><code>{ag.agent_id}</code></span>
                        </td>
                        <td>
                          <div><code>{ag.ip_address}</code></div>
                          <span className="cm-hint">{ag.os_name} {ag.os_version} ({ag.architecture})</span>
                        </td>
                        <td>
                          <span className={`cm-badge ${ag.status === "ONLINE" ? "observed" : ag.status === "REVOKED" ? "danger" : "warning"}`}>
                            {ag.status}
                          </span>
                          {ag.health_metrics && (
                            <div className="cm-hint" style={{ marginTop: 2 }}>
                              CPU: {ag.health_metrics.cpu_percent || 0}% · RAM: {ag.health_metrics.ram_percent || 0}%
                            </div>
                          )}
                        </td>
                        <td>
                          <span className="cm-hint">{ag.last_heartbeat_at?.slice(0, 19).replace("T", " ")}</span>
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 6 }}>
                            {ag.status === "ONLINE" && (
                              <button
                                type="button"
                                className="cm-btn secondary"
                                style={{ fontSize: 11, padding: "4px 8px" }}
                                disabled={actionInProgress === ag.agent_id}
                                onClick={() => handleDispatchAgentScan(ag.agent_id)}
                              >
                                Escanear
                              </button>
                            )}
                            {ag.status !== "REVOKED" && (
                              <button
                                type="button"
                                className="cm-btn danger"
                                style={{ fontSize: 11, padding: "4px 8px" }}
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
          </div>

          <div className="cm-card">
            <h3 className="cm-card-title">
              <span>Conectores de Descubrimiento Registrados ({connectors.length})</span>
              <span className="cm-badge observed">Autorizados por Política</span>
            </h3>
            <div className="cm-table-wrap">
              <table className="cm-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Nombre / Sitio</th>
                    <th>Tipo de Colector</th>
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
                        <div style={{ fontWeight: 700 }}>{c.name}</div>
                        <span className="cm-hint">
                          Entorno: {c.environment_id || "env-datacenter-01"} · Sitio: {c.site_id || "site-primary"}
                        </span>
                      </td>
                      <td>
                        <code>{c.type}</code>
                      </td>
                      <td>
                        <span className="cm-badge observed">
                          {c.status || (c.authorized ? "AUTORIZADO" : "PENDIENTE")}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Descubrimiento Cloud en Vivo */}
          <div className="cm-card">
            <h3 className="cm-card-title">
              <span>Descubrimiento Cloud en Vivo y Reconciliación (AWS boto3 · GCP Cloud Asset)</span>
              <span className="cm-badge derived">Snapshots: {cloudSnapshots.length}</span>
            </h3>
            <p className="cm-hint" style={{ marginTop: 0, marginBottom: 12 }}>
              Inspecciona cuentas cloud reales paginadas (STS/EC2/RDS/S3/IAM o Compute/Cloud SQL/GCS). Si las credenciales IAM/ADC no están presentes en el entorno, informa el bloqueo exacto sin fingir éxito.
            </p>
            <div className="cm-form-grid">
              <div className="cm-field">
                <label htmlFor="live-cloud-provider" className="cm-label">
                  Proveedor Cloud a Inspeccionar
                </label>
                <select
                  id="live-cloud-provider"
                  className="cm-select"
                  value={cloudProvider}
                  onChange={(e) => {
                    setCloudProvider(e.target.value);
                    setCloudTarget(e.target.value === "aws" ? "us-east-1" : "cloudmove-prod-gcp");
                  }}
                >
                  <option value="aws">Amazon Web Services (AWS STS/EC2/RDS/S3)</option>
                  <option value="gcp">Google Cloud Platform (GCP Compute/SQL/GCS)</option>
                </select>
              </div>
              <div className="cm-field">
                <label htmlFor="live-cloud-target" className="cm-label">
                  {cloudProvider === "aws" ? "Región AWS Objetivo" : "GCP Project ID Objetivo"}
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
                  Probar Descubrimiento en Vivo ({cloudProvider.toUpperCase()})
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Sección 2: Prerrequisitos y Capacidades de AWS y GCP */}
      {providersData && (
        <div className="cm-card" style={{ marginBottom: 20 }}>
          <h3 className="cm-card-title">
            <span>Estado de Prerrequisitos y Capacidades por Proveedor Cloud Destino</span>
            <span className="cm-badge info">Verificación de Herramientas Locales y Permisos IAM</span>
          </h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
            {[
              { key: "aws", label: "Amazon Web Services (AWS)", badge: "aws", data: awsInfo },
              { key: "gcp", label: "Google Cloud Platform (GCP)", badge: "gcp", data: gcpInfo },
            ].map(({ key, label, badge, data }) => {
              if (!data) return null;
              const prereq = data.prerequisites || {};
              const caps = data.config?.capabilities || {};
              return (
                <div key={key} className="cm-card-subtle">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                    <strong style={{ fontSize: 14 }}>{label}</strong>
                    <span className={`cm-badge ${badge}`}>
                      Modo: {prereq.execution_mode === "real_cloud" ? "Nube Real" : "Dry-Run Seguro"}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                    <span className={`cm-badge ${prereq.terraform_cli_installed ? "observed" : "warning"}`}>
                      Terraform CLI: {prereq.terraform_cli_installed ? "INSTALADO" : "AUSENTE"}
                    </span>
                    <span className={`cm-badge ${prereq.live_credentials_verified ? "observed" : "simulated"}`}>
                      Credenciales en Vivo: {prereq.live_credentials_verified ? "VERIFICADAS" : "NO CONFIGURADAS (Modo Simulación)"}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, marginBottom: 8 }}>
                    <strong>Formatos de Imagen Soportados:</strong>{" "}
                    <code>{(caps.SupportedImageFormats || []).join(", ")}</code>
                  </div>
                  <div style={{ fontSize: 12, marginBottom: 8 }}>
                    <strong>Mecanismos de Importación VM:</strong>{" "}
                    {(caps.vm_image_import || []).join(" · ")}
                  </div>
                  <div style={{ fontSize: 12, marginBottom: 8 }}>
                    <strong>Permisos IAM Requeridos en Destino:</strong>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                      {(prereq.required_permissions || []).map((perm) => (
                        <code
                          key={perm}
                          style={{
                            fontSize: 10.5,
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
        </div>
      )}

      {/* Sección 3: Matriz Oficial de Compatibilidad */}
      {compatMatrix && (
        <div className="cm-card">
          <h3 className="cm-card-title">
            <span>Matriz Oficial de Estrategias de Replicación e Importación de Imágenes (AWS · GCP)</span>
            <span className="cm-badge observed">Caso 2 y Caso 3</span>
          </h3>
          <div className="cm-table-wrap">
            <table className="cm-table">
              <thead>
                <tr>
                  <th>Proveedor / Servicio Oficial</th>
                  <th>Mecanismo</th>
                  <th>Formatos / Fuentes Soportadas</th>
                  <th>Boot & Arquitectura</th>
                  <th>Límite Disco</th>
                  <th>Requisitos de Red / Conversión</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(compatMatrix).flatMap(([provKey, services]) =>
                  Object.entries(services || {}).map(([srvKey, srv]) => (
                    <tr key={`${provKey}-${srvKey}`}>
                      <td>
                        <span className={`cm-badge ${provKey === "gcp" ? "gcp" : "aws"}`} style={{ marginBottom: 4 }}>
                          {provKey.toUpperCase()}
                        </span>
                        <div style={{ fontWeight: 700 }}>{srv.service_name}</div>
                      </td>
                      <td>
                        <code>{srv.mechanism}</code>
                      </td>
                      <td>
                        {srv.native_formats ? (
                          <div>
                            <strong>Nativos:</strong> <code>{srv.native_formats.join(", ")}</code>
                            {srv.convertible_formats?.length > 0 && (
                              <div className="cm-hint">
                                Convertibles (`qemu-img`): <code>{srv.convertible_formats.join(", ")}</code>
                              </div>
                            )}
                          </div>
                        ) : (
                          <div>
                            <strong>Orígenes:</strong> <code>{(srv.supported_source_types || []).join(", ")}</code>
                          </div>
                        )}
                      </td>
                      <td>
                        <div>Boot: <code>{(srv.supported_boot_modes || []).join(" / ")}</code></div>
                        <div className="cm-hint">Arch: {(srv.supported_architectures || []).join(", ")}</div>
                      </td>
                      <td>
                        <strong>{srv.max_disk_size_tib || srv.max_boot_disk_size_tib || 16} TiB</strong>
                      </td>
                      <td>
                        {(srv.network_requirements || []).map((nr, i) => (
                          <div key={i} style={{ fontSize: 11.5 }}>• {nr}</div>
                        ))}
                        {srv.staging_storage && (
                          <div style={{ fontSize: 11.5 }}>• Staging: {srv.staging_storage}</div>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
