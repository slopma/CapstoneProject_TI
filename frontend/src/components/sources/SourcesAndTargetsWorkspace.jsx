import React, { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../../utils/apiClient";
import {
  saveSessionAgentToken,
  getSessionAgentToken,
  getCredentialsSummary,
  copyTextToClipboard,
} from "../../utils/credentialVault";
import {
  AwsPageHeader,
  AwsContainer,
  AwsKeyValuePairs,
  AwsTabs,
  AwsStatusIndicator,
  AwsAlert,
  AwsEmptyState,
} from "../cloudscape/AwsPrimitives";

export default function SourcesAndTargetsWorkspace({ onQuickStartUseCase }) {
  const [activeSubTab, setActiveSubTab] = useState("case2-agents");
  const [feedback, setFeedback] = useState(null);

  // Case 2: Remote Agents & Sequential Token Flow
  const [agents, setAgents] = useState([]);
  const [generatedToken, setGeneratedToken] = useState(() => getSessionAgentToken());
  const [generatingToken, setGeneratingToken] = useState(false);
  const [actionInProgress, setActionInProgress] = useState(null);
  const [copiedCmd, setCopiedCmd] = useState("");

  // Case 1: GitHub Repository Connector
  const [githubUrl, setGithubUrl] = useState("https://github.com/slopma/CocoaApp");
  const [githubToken, setGithubToken] = useState("");
  const [validatingRepo, setValidatingRepo] = useState(false);
  const [repoResult, setRepoResult] = useState(null);

  // AWS Target Provider Info
  const [providersData, setProvidersData] = useState(null);
  const [vaultSummary, setVaultSummary] = useState(() => getCredentialsSummary());

  const loadData = useCallback(async () => {
    try {
      const [pRes, agRes] = await Promise.all([
        apiFetch("/api/v1/migration/providers").catch(() => null),
        apiFetch("/api/v1/agents").catch(() => null),
      ]);
      if (pRes && pRes.ok) {
        setProvidersData(await pRes.json());
      }
      if (agRes && agRes.ok) {
        const d = await agRes.json();
        // Filter out any loopback/control-plane host for security
        const remoteAgents = (d.agents || []).filter(
          (a) =>
            a.hostname !== "cloudmove-server" &&
            !/^[0-9a-f]{12}$/i.test(a.hostname || "")
        );
        setAgents(remoteAgents);
      }
    } catch {
      // Ignore transient errors
    }
  }, []);

  useEffect(() => {
    loadData();
    const handleCredsUpdate = () => setVaultSummary(getCredentialsSummary());
    window.addEventListener("cloudmove:credentials-updated", handleCredsUpdate);
    return () =>
      window.removeEventListener("cloudmove:credentials-updated", handleCredsUpdate);
  }, [loadData]);

  const handleGenerateEnrollmentToken = async () => {
    setGeneratingToken(true);
    setFeedback(null);
    try {
      const res = await apiFetch("/api/v1/agents/enrollment-tokens", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ttl_seconds: 86400,
          max_uses: 5,
          org_id: "default",
          created_by: "operator@cloudmove.local",
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "No se pudo generar el token de inscripción.");
      }
      const normalized = saveSessionAgentToken(data) || data;
      setGeneratedToken(normalized);
      await loadData();
      setFeedback({
        type: "success",
        title: "Paso 1 completado: Token de inscripción generado",
        message: `Token '${normalized.token || normalized.enrollment_token || data.token_prefix}' activo en la sesión actual (válido por 24 horas). Ejecuta el comando del Paso 2 en el servidor objetivo.`,
      });
    } catch (err) {
      setFeedback({
        type: "error",
        title: "Error al generar token de agente",
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
      if (!res.ok) {
        throw new Error(data.detail || "No se pudo despachar la captura al agente.");
      }
      setFeedback({
        type: "success",
        title: "Captura de inventario despachada",
        message: `La orden 'collect_inventory' fue enviada al agente '${agentId}'.`,
      });
      await loadData();
    } catch (err) {
      setFeedback({
        type: "error",
        title: "Error al despachar captura",
        message: err.message,
      });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleRevokeAgent = async (agentId) => {
    if (!window.confirm(`¿Confirmas la revocación permanente del agente '${agentId}'?`)) {
      return;
    }
    setActionInProgress(agentId);
    setFeedback(null);
    try {
      const res = await apiFetch(`/api/v1/agents/${agentId}/revoke`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason: "Revocado desde la consola de administración",
          operator_id: "operator@cloudmove.local",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error al revocar el agente.");
      await loadData();
      setFeedback({
        type: "warning",
        title: "Agente revocado",
        message: `Las credenciales del agente '${agentId}' han sido revocadas.`,
      });
    } catch (err) {
      setFeedback({
        type: "error",
        title: "Error al revocar agente",
        message: err.message,
      });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleValidateGithubRepo = async (e) => {
    e.preventDefault();
    if (!githubUrl.trim()) return;
    setValidatingRepo(true);
    setFeedback(null);
    try {
      const res = await apiFetch("/api/v1/migration/github/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          github_url: githubUrl.trim(),
          github_token: githubToken.trim() || undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error al validar repositorio GitHub.");
      setRepoResult(data);
      setFeedback({
        type: "success",
        title: "Repositorio GitHub verificado para Caso 1",
        message: `Repositorio '${data.repository?.full_name}' conectado correctamente (${data.branches?.length || 1} ramas detectadas).`,
      });
    } catch (err) {
      setFeedback({
        type: "error",
        title: "No se pudo conectar al repositorio GitHub",
        message: err.message,
      });
    } finally {
      setValidatingRepo(false);
    }
  };

  const handleCopyCommand = async (cmd, key) => {
    if (!cmd) return;
    await copyTextToClipboard(cmd);
    setCopiedCmd(key);
    setTimeout(() => setCopiedCmd(""), 2000);
  };

  const onlineAgentsCount = agents.filter((a) => a.status === "ONLINE").length;
  const awsInfo = providersData?.providers?.aws;

  const rawTokenValue =
    generatedToken?.token || generatedToken?.enrollment_token || "";

  const linuxCommand =
    generatedToken?.install_command_linux ||
    generatedToken?.install_commands?.linux ||
    (rawTokenValue
      ? `curl -sSL ${window.location.origin}/api/v1/agents/install.sh | sudo bash -s -- --token ${rawTokenValue} --server ${window.location.origin}`
      : "");

  const windowsCommand =
    generatedToken?.install_command_windows ||
    generatedToken?.install_commands?.windows_powershell ||
    (rawTokenValue
      ? `Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('${window.location.origin}/api/v1/agents/install.ps1')) -Server '${window.location.origin}' -Token '${rawTokenValue}'`
      : "");

  return (
    <div className="tab-pane-view">
      <AwsPageHeader
        title="Orígenes, agentes y destino AWS"
        description="Configuración de fuentes para el Caso 1 (Repositorios GitHub) y el Caso 2 (Agentes Remotos de Sistema Operativo / VM) hacia Amazon Web Services (AWS)."
        badges={
          <>
            <span className="cm-badge aws">Destino exclusivo: AWS</span>
            <span className="cm-badge observed">
              Agentes remotos en línea: {onlineAgentsCount}
            </span>
            {generatedToken && (
              <span className="cm-badge info">
                Token activo: {generatedToken.token_prefix}
              </span>
            )}
          </>
        }
        actions={
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              className="cm-btn sm"
              onClick={loadData}
            >
              Actualizar estado
            </button>
            <button
              type="button"
              className="cm-btn primary sm"
              onClick={handleGenerateEnrollmentToken}
              disabled={generatingToken}
            >
              {generatingToken ? "Generando token..." : "Generar token de agente (Paso 1)"}
            </button>
          </div>
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
            label: "Origen Caso 1 (Código / GitHub)",
            value: repoResult?.repository?.full_name || "Conector GitHub API v3",
            subtext: "Inspección estática sin ejecución de código arbitrario",
          },
          {
            label: "Origen Caso 2 (Agentes Remotos)",
            value: `${onlineAgentsCount} / ${agents.length} en línea`,
            subtext: generatedToken
              ? `Token listo: ${generatedToken.token_prefix}`
              : "Paso 1 pendiente: Generar token de inscripción",
          },
          {
            label: "Nube de destino habilitada",
            value: "Amazon Web Services (AWS)",
            subtext: "Región predeterminada: us-east-1 (N. Virginia)",
          },
          {
            label: "Credenciales de sesión STS",
            value: vaultSummary.hasCredentials ? "Activas en sesión" : "No configuradas",
            subtext: vaultSummary.hasCredentials
              ? `${vaultSummary.maskedAccessKey} (${vaultSummary.fingerprint})`
              : "Almacenamiento seguro en sessionStorage",
          },
        ]}
      />

      <AwsTabs
        activeTabId={activeSubTab}
        onTabChange={setActiveSubTab}
        tabs={[
          {
            id: "case2-agents",
            label: "Caso 2 · Agentes remotos de SO / VM (Flujo secuencial)",
            count: agents.length,
          },
          {
            id: "case1-github",
            label: "Caso 1 · Conector de repositorios GitHub",
          },
          {
            id: "aws-target",
            label: "Destino AWS y equivalencias de servicios",
          },
        ]}
      />

      {/* PESTAÑA 1: FLUJO SECUENCIAL DE AGENTES PARA CASO 2 */}
      {activeSubTab === "case2-agents" && (
        <>
          <AwsContainer
            title="Flujo secuencial de conexión de agente para el Caso 2 (Imagen de SO / VM)"
            description="Por motivos de seguridad, la infraestructura donde se ejecuta CloudMove permanece aislada y oculta. Sigue estos 3 pasos en orden para conectar el servidor o máquina virtual que deseas migrar."
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                gap: 16,
              }}
            >
              {/* PASO 1 */}
              <div
                className="cm-card-subtle"
                style={{
                  borderTop: `3px solid ${generatedToken ? "#037f0c" : "#ff9900"}`,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                }}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <span className="cm-badge aws">Paso 1 (Obligatorio)</span>
                    <AwsStatusIndicator type={generatedToken ? "success" : "warning"}>
                      {generatedToken ? "Token generado" : "Pendiente"}
                    </AwsStatusIndicator>
                  </div>
                  <strong style={{ fontSize: 15, display: "block", marginBottom: 6 }}>
                    1. Generar token de inscripción del agente
                  </strong>
                  <p className="cm-hint" style={{ margin: "0 0 12px 0" }}>
                    Genera un token criptográfico temporal (`cmat_...`) para autorizar la conexión saliente desde tu máquina objetivo hacia CloudMove.
                  </p>
                  {rawTokenValue && (
                    <div
                      style={{
                        marginBottom: 10,
                        padding: "6px 8px",
                        backgroundColor: "#f8fafc",
                        border: "1px solid #cbd5e1",
                        borderRadius: 4,
                        fontSize: 12,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
                        <span style={{ fontWeight: 700, color: "#0f172a" }}>Token completo:</span>
                        <button
                          type="button"
                          className="awsui-crumb-link"
                          style={{ fontSize: 11.5 }}
                          onClick={() => handleCopyCommand(rawTokenValue, "token")}
                        >
                          {copiedCmd === "token" ? "Token copiado" : "Copiar token"}
                        </button>
                      </div>
                      <code style={{ wordBreak: "break-all", fontSize: 11.5, color: "#0972d3" }}>
                        {rawTokenValue}
                      </code>
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  className="cm-btn primary sm"
                  onClick={handleGenerateEnrollmentToken}
                  disabled={generatingToken}
                >
                  {generatingToken
                    ? "Generando..."
                    : generatedToken
                    ? "Regenerar token de inscripción"
                    : "Generar token de inscripción"}
                </button>
              </div>

              {/* PASO 2 */}
              <div
                className="cm-card-subtle"
                style={{
                  borderTop: `3px solid ${generatedToken ? "#0972d3" : "#d5dbdb"}`,
                  opacity: generatedToken ? 1 : 0.6,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <span className="cm-badge info">Paso 2</span>
                  <AwsStatusIndicator type={generatedToken ? "info" : "pending"}>
                    {generatedToken ? "Listo para instalar" : "Requiere Paso 1"}
                  </AwsStatusIndicator>
                </div>
                <strong style={{ fontSize: 15, display: "block", marginBottom: 6 }}>
                  2. Ejecutar instalador en el servidor origen
                </strong>
                {!generatedToken ? (
                  <p className="cm-hint">
                    Genera primero el token en el Paso 1 para desbloquear los comandos de instalación para Linux y Windows.
                  </p>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 700, marginBottom: 4 }}>
                        <span>Linux (Ubuntu, Debian, Kali, RHEL):</span>
                        <button
                          type="button"
                          className="awsui-crumb-link"
                          style={{ fontSize: 12 }}
                          onClick={() => handleCopyCommand(linuxCommand, "linux")}
                        >
                          {copiedCmd === "linux" ? "Copiado" : "Copiar comando"}
                        </button>
                      </div>
                      <pre
                        style={{
                          margin: 0,
                          padding: 8,
                          backgroundColor: "#16191f",
                          color: "#f2f3f3",
                          borderRadius: 4,
                          fontSize: 11.5,
                          overflowX: "auto",
                        }}
                      >
                        {linuxCommand}
                      </pre>
                    </div>
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 700, marginBottom: 4 }}>
                        <span>Windows Server (PowerShell Admin):</span>
                        <button
                          type="button"
                          className="awsui-crumb-link"
                          style={{ fontSize: 12 }}
                          onClick={() => handleCopyCommand(windowsCommand, "win")}
                        >
                          {copiedCmd === "win" ? "Copiado" : "Copiar comando"}
                        </button>
                      </div>
                      <pre
                        style={{
                          margin: 0,
                          padding: 8,
                          backgroundColor: "#16191f",
                          color: "#f2f3f3",
                          borderRadius: 4,
                          fontSize: 11.5,
                          overflowX: "auto",
                        }}
                      >
                        {windowsCommand}
                      </pre>
                    </div>
                  </div>
                )}
              </div>

              {/* PASO 3 */}
              <div
                className="cm-card-subtle"
                style={{
                  borderTop: `3px solid ${onlineAgentsCount > 0 ? "#037f0c" : "#d5dbdb"}`,
                  opacity: generatedToken || onlineAgentsCount > 0 ? 1 : 0.6,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                }}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <span className="cm-badge observed">Paso 3</span>
                    <AwsStatusIndicator type={onlineAgentsCount > 0 ? "success" : "pending"}>
                      {onlineAgentsCount > 0
                        ? `${onlineAgentsCount} agente(s) conectado(s)`
                        : "Esperando conexión"}
                    </AwsStatusIndicator>
                  </div>
                  <strong style={{ fontSize: 15, display: "block", marginBottom: 6 }}>
                    3. Capturar sistema operativo y migrar a AWS
                  </strong>
                  <p className="cm-hint" style={{ margin: "0 0 12px 0" }}>
                    Una vez inscrito el agente (o generado tu token), continúa al asistente del Caso 2 para capturar el sistema y generar el plan Terraform hacia AWS.
                  </p>
                </div>
                <button
                  type="button"
                  className="cm-btn primary sm"
                  disabled={!generatedToken && onlineAgentsCount === 0}
                  onClick={() =>
                    onQuickStartUseCase && onQuickStartUseCase("vm_image")
                  }
                >
                  Continuar al Caso 2 en Orquestador →
                </button>
              </div>
            </div>
          </AwsContainer>

          <AwsContainer
            title="Agentes remotos inscritos"
            counter={agents.length}
            description="Máquinas externas conectadas a CloudMove mediante token de inscripción. El servidor propio de CloudMove nunca se incluye en esta lista."
            noPadding={true}
            actions={
              <button type="button" className="cm-btn sm" onClick={loadData}>
                Refrescar lista
              </button>
            }
          >
            {agents.length === 0 ? (
              <AwsEmptyState
                title="No hay agentes remotos inscritos todavía"
                description="Completa el Paso 1 (Generar token) y ejecuta el comando del Paso 2 en la máquina Linux o Windows que deseas migrar."
                action={
                  <button
                    type="button"
                    className="cm-btn primary sm"
                    onClick={handleGenerateEnrollmentToken}
                    disabled={generatingToken}
                  >
                    Generar token de inscripción ahora
                  </button>
                }
              />
            ) : (
              <div className="cm-table-wrap" style={{ border: "none", borderRadius: 0 }}>
                <table className="cm-table">
                  <thead>
                    <tr>
                      <th>Hostname / Agent ID</th>
                      <th>IP y Sistema Operativo</th>
                      <th>Estado y telemetría</th>
                      <th>Último heartbeat</th>
                      <th style={{ textAlign: "right" }}>Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.map((ag) => (
                      <tr key={ag.agent_id}>
                        <td>
                          <strong>{ag.hostname}</strong>
                          <div>
                            <code>{ag.agent_id}</code>
                          </div>
                        </td>
                        <td>
                          <code>{ag.ip_address}</code>
                          <div className="cm-hint">
                            {ag.os_name} {ag.os_version} ({ag.architecture})
                          </div>
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
                            <div className="cm-hint">
                              CPU: {ag.health_metrics.cpu_percent ?? 0}% · RAM:{" "}
                              {ag.health_metrics.memory_percent ?? 0}%
                            </div>
                          )}
                        </td>
                        <td>
                          <code>
                            {ag.last_heartbeat_at
                              ? ag.last_heartbeat_at.replace("T", " ").slice(0, 19)
                              : "—"}
                          </code>
                        </td>
                        <td style={{ textAlign: "right" }}>
                          {ag.status !== "REVOKED" && (
                            <div style={{ display: "inline-flex", gap: 6 }}>
                              <button
                                type="button"
                                className="cm-btn sm"
                                disabled={actionInProgress === ag.agent_id}
                                onClick={() => handleDispatchAgentScan(ag.agent_id)}
                              >
                                Capturar inventario
                              </button>
                              <button
                                type="button"
                                className="cm-btn primary sm"
                                onClick={() =>
                                  onQuickStartUseCase && onQuickStartUseCase("vm_image")
                                }
                              >
                                Migrar a AWS
                              </button>
                              <button
                                type="button"
                                className="cm-btn danger sm"
                                disabled={actionInProgress === ag.agent_id}
                                onClick={() => handleRevokeAgent(ag.agent_id)}
                              >
                                Revocar
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </AwsContainer>
        </>
      )}

      {/* PESTAÑA 2: CONECTOR DE REPOSITORIOS GITHUB PARA CASO 1 */}
      {activeSubTab === "case1-github" && (
        <AwsContainer
          title="Conector de repositorios GitHub para el Caso 1 (Aplicación desde Código)"
          description="Verifica la accesibilidad de cualquier repositorio público o privado en GitHub antes de iniciar la síntesis de contenedores y Terraform hacia AWS."
        >
          <form
            onSubmit={handleValidateGithubRepo}
            style={{
              display: "grid",
              gridTemplateColumns: "2fr 1.5fr auto",
              gap: 12,
              alignItems: "end",
            }}
          >
            <div>
              <label className="cm-label" htmlFor="src-github-url">
                URL del repositorio GitHub
              </label>
              <input
                id="src-github-url"
                type="url"
                className="cm-input"
                style={{ width: "100%", marginTop: 4 }}
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
                placeholder="https://github.com/organizacion/proyecto"
                required
              />
            </div>
            <div>
              <label className="cm-label" htmlFor="src-github-token">
                Personal Access Token (Opcional para repositorios privados)
              </label>
              <input
                id="src-github-token"
                type="password"
                className="cm-input"
                style={{ width: "100%", marginTop: 4 }}
                value={githubToken}
                onChange={(e) => setGithubToken(e.target.value)}
                placeholder="ghp_••••••••••••••••••••"
              />
            </div>
            <button
              type="submit"
              className="cm-btn primary"
              disabled={validatingRepo}
            >
              {validatingRepo ? "Verificando..." : "Verificar repositorio"}
            </button>
          </form>

          {repoResult?.repository && (
            <div className="cm-card-subtle" style={{ marginTop: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
                <div>
                  <strong style={{ fontSize: 15, color: "#000716" }}>
                    {repoResult.repository.full_name}
                  </strong>
                  <div className="cm-hint">
                    Rama predeterminada: <code>{repoResult.default_branch}</code> · Lenguaje principal:{" "}
                    <strong>{repoResult.repository.language || "Multi-lenguaje"}</strong> · Archivos:{" "}
                    <strong>{repoResult.tree?.summary?.total_files || 0}</strong>
                  </div>
                </div>
                <button
                  type="button"
                  className="cm-btn primary sm"
                  onClick={() =>
                    onQuickStartUseCase && onQuickStartUseCase("app_source")
                  }
                >
                  Iniciar migración Caso 1 con este repositorio →
                </button>
              </div>
            </div>
          )}
        </AwsContainer>
      )}

      {/* PESTAÑA 3: DESTINO AWS Y EQUIVALENCIAS */}
      {activeSubTab === "aws-target" && (
        <AwsContainer
          title="Configuración de destino Amazon Web Services (AWS) y catálogo de servicios"
          description="El proyecto está acotado exclusivamente a Amazon Web Services (AWS), garantizando compatibilidad total con cuentas estándar y AWS Academy Learner Lab."
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16, marginBottom: 16 }}>
            <div className="cm-card-subtle">
              <strong style={{ display: "block", marginBottom: 6 }}>Estado de herramientas locales</strong>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13.5 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span>Terraform CLI:</span>
                  <AwsStatusIndicator type="success">
                    {awsInfo?.prerequisites?.terraform_cli ? "Instalado y activo" : "Verificado"}
                  </AwsStatusIndicator>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span>Proveedor HashiCorp AWS:</span>
                  <AwsStatusIndicator type="success">~&gt; 5.0 Habilitado</AwsStatusIndicator>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span>Región predeterminada:</span>
                  <code>us-east-1 (N. Virginia)</code>
                </div>
              </div>
            </div>

            <div className="cm-card-subtle">
              <strong style={{ display: "block", marginBottom: 6 }}>Servicios AWS para Caso 1 (Aplicaciones)</strong>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "#545b64", lineHeight: 1.5 }}>
                <li><code>aws_vpc</code>, <code>aws_subnet</code> y <code>aws_internet_gateway</code></li>
                <li><code>aws_instance</code> con Docker Compose + IMDSv2 IP Sync</li>
                <li><code>aws_lb</code> + <code>aws_autoscaling_group</code> (Opción Alta Disponibilidad)</li>
                <li><code>aws_db_instance</code> (Amazon RDS PostgreSQL / PostGIS)</li>
              </ul>
            </div>

            <div className="cm-card-subtle">
              <strong style={{ display: "block", marginBottom: 6 }}>Servicios AWS para Caso 2 (SO / VM)</strong>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "#545b64", lineHeight: 1.5 }}>
                <li><code>aws_instance</code> con perfil de hardware adaptado (<code>t3.micro</code> / <code>t3.medium</code>)</li>
                <li><code>aws_ebs_volume</code> (gp3 cifrado, ajustado a cuota de 150 GiB)</li>
                <li><code>aws_security_group</code> con deduplicación automática de puertos</li>
                <li><code>user_data.sh</code> para rehidratación de servicios <code>systemd</code> y usuarios</li>
              </ul>
            </div>
          </div>
        </AwsContainer>
      )}
    </div>
  );
}
