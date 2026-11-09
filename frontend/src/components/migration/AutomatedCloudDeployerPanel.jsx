import React, { useState, useEffect, useRef, useCallback } from "react";
import { apiFetch } from "../../utils/apiClient";

const STATUS_BADGE_STYLE = {
  IDLE: { bg: "#e2e8f0", fg: "#334155", label: "EN ESPERA (IDLE)" },
  RUNNING: { bg: "#dbeafe", fg: "#1d4ed8", label: "⟳ EJECUTANDO TERRAFORM EN VIVO..." },
  SUCCESS: { bg: "#dcfce7", fg: "#166534", label: "[OK] EJECUCIÓN EXITOSA" },
  CANCELLED: { bg: "#fef3c7", fg: "#92400e", label: "CANCELADO POR EL OPERADOR" },
  FAILED: { bg: "#fee2e2", fg: "#991b1b", label: "[ERROR] ERROR EN COMANDO TERRAFORM" },
};

export default function AutomatedCloudDeployerPanel({ job, onDeploymentCompleted }) {
  const provider = (job?.target_provider || "aws").toUpperCase();
  const migrationId = job?.migration_id;

  // Credential input state
  const [authMode, setAuthMode] = useState("form"); // "form" | "env"
  const [awsAccessKeyId, setAwsAccessKeyId] = useState("");
  const [awsSecretAccessKey, setAwsSecretAccessKey] = useState("");
  const [awsRegion, setAwsRegion] = useState("us-east-1");
  const [awsSessionToken, setAwsSessionToken] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [showTokenField, setShowTokenField] = useState(true);
  const [rawCredsBlock, setRawCredsBlock] = useState("");

  const handleParseCredentialsBlock = (textValue) => {
    setRawCredsBlock(textValue);
    const text = String(textValue || "");
    const akMatch = text.match(/(?:aws_access_key_id|access\s*key(?:\s*id)?)\s*[:=]\s*([A-Z0-9]{16,32})/i);
    const skMatch = text.match(/(?:aws_secret_access_key|secret\s*access\s*key)\s*[:=]\s*([A-Za-z0-9/+=]{30,64})/i);
    const stMatch = text.match(/(?:aws_session_token|(?:aws\s*)?session\s*token)\s*[:=]\s*([A-Za-z0-9/+=]{80,})/i);
    if (akMatch) setAwsAccessKeyId(akMatch[1].trim());
    if (skMatch) setAwsSecretAccessKey(skMatch[1].trim());
    if (stMatch) {
      setAwsSessionToken(stMatch[1].trim());
      setShowTokenField(true);
    }
  };

  // Verification & Terraform Console state
  const [verifyingCaller, setVerifyingCaller] = useState(false);
  const [callerIdentity, setCallerIdentity] = useState(null);
  const [tfStatus, setTfStatus] = useState({
    is_running: false,
    active_command: null,
    status: "IDLE",
    stage: "READY",
    message: "",
    error: null,
    has_state_file: false,
    is_locked: false,
    resource_count: 0,
    managed_resources: [],
    primary_instance: null,
    outputs: {},
    logs: [],
    workspace_dir: "",
  });
  const [logSearch, setLogSearch] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const [showStateResources, setShowStateResources] = useState(true);
  const [confirmDestroy, setConfirmDestroy] = useState(false);
  const [copiedText, setCopiedText] = useState("");

  const logContainerRef = useRef(null);
  const prevRunningRef = useRef(false);

  // Build credentials dictionary if using form mode
  const getActiveCredentials = useCallback(() => {
    if (authMode === "env") return null;
    if (!awsAccessKeyId.trim() || !awsSecretAccessKey.trim()) return null;
    const creds = {
      aws_access_key_id: awsAccessKeyId.trim(),
      aws_secret_access_key: awsSecretAccessKey.trim(),
      aws_region: awsRegion.trim() || "us-east-1",
    };
    if (awsSessionToken.trim()) {
      creds.aws_session_token = awsSessionToken.trim();
    }
    return creds;
  }, [authMode, awsAccessKeyId, awsSecretAccessKey, awsRegion, awsSessionToken]);

  // Fetch current Terraform status, logs, and tfstate resources from backend
  const fetchTerraformStatus = useCallback(async () => {
    if (!migrationId) return;
    try {
      const res = await apiFetch(`/api/v1/migration/jobs/${migrationId}/terraform/status`);
      if (!res.ok) return;
      const data = await res.json();
      setTfStatus(data);

      // Detect transition from running -> finished
      if (prevRunningRef.current && !data.is_running) {
        if (data.status === "SUCCESS" && typeof onDeploymentCompleted === "function") {
          try {
            onDeploymentCompleted(data);
          } catch (cbErr) {
            console.warn("onDeploymentCompleted callback warning:", cbErr);
          }
        }
      }
      prevRunningRef.current = Boolean(data.is_running);
    } catch {
      // Ignore transient network errors while polling
    }
  }, [migrationId, onDeploymentCompleted]);

  // Initial fetch when job changes
  useEffect(() => {
    prevRunningRef.current = false;
    fetchTerraformStatus();
  }, [fetchTerraformStatus]);

  // Poll every 1.2s while a Terraform command is running
  useEffect(() => {
    if (!tfStatus.is_running) return undefined;
    const timer = setInterval(() => {
      fetchTerraformStatus();
    }, 1200);
    return () => clearInterval(timer);
  }, [tfStatus.is_running, fetchTerraformStatus]);

  // Auto-scroll terminal log viewer when new lines arrive
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [tfStatus.logs, autoScroll]);

  // Verify Cloud Provider Credentials (AWS STS)
  const handleVerifyCaller = async () => {
    if (authMode === "form" && (!awsAccessKeyId.trim() || !awsSecretAccessKey.trim())) {
      setCallerIdentity({
        valid: false,
        provider: "aws",
        error: "Por favor ingresa tu AWS Access Key ID y AWS Secret Access Key antes de verificar la identidad (o cambia a 'Variables de entorno locales').",
      });
      return;
    }

    setVerifyingCaller(true);
    setCallerIdentity(null);
    try {
      const creds = getActiveCredentials();
      const res = await apiFetch("/api/v1/migration/credentials/verify-cloud", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: job?.target_provider || "aws",
          credentials: creds,
        }),
      });
      const data = await res.json();
      setCallerIdentity(data);
    } catch (err) {
      setCallerIdentity({
        valid: false,
        provider: "aws",
        error: `Fallo de comunicación: ${err.message}`,
      });
    } finally {
      setVerifyingCaller(false);
    }
  };

  // Run any interactive Terraform command
  const handleRunCommand = async (action) => {
    if (!migrationId) return;
    const creds = getActiveCredentials();
    const requiresCloudAuth = ["apply", "continue", "full_deploy", "destroy", "refresh"].includes(action);

    if (requiresCloudAuth && authMode === "form" && !creds) {
      // Allow fallback if user wants to use server environment credentials or warn them
      const proceedWithEnv = window.confirm(
        "No has ingresado AWS Access Key ID / Secret Access Key en el formulario.\n\n¿Deseas continuar utilizando las credenciales configuradas en el entorno local del servidor (~/.aws o variables de entorno)?"
      );
      if (!proceedWithEnv) return;
      setAuthMode("env");
    }

    setConfirmDestroy(false);
    prevRunningRef.current = true;
    setTfStatus((prev) => ({
      ...prev,
      is_running: true,
      active_command: action,
      status: "RUNNING",
      message: `Iniciando comando 'terraform ${action}'...`,
    }));

    try {
      const res = await apiFetch(`/api/v1/migration/jobs/${migrationId}/terraform/command`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          credentials: creds,
          async_exec: true,
        }),
      });
      const data = await res.json();
      setTfStatus(data);
      prevRunningRef.current = Boolean(data.is_running);
    } catch (err) {
      prevRunningRef.current = false;
      setTfStatus((prev) => ({
        ...prev,
        is_running: false,
        status: "FAILED",
        error: `Error al invocar comando Terraform: ${err.message}`,
        logs: [...(prev.logs || []), `[ERROR DE COMUNICACIÓN] ${err.message}`],
      }));
    }
  };

  // Cancel active Terraform command immediately
  const handleCancelExecution = async () => {
    if (!migrationId) return;
    try {
      const res = await apiFetch(`/api/v1/migration/jobs/${migrationId}/terraform/cancel`, {
        method: "POST",
      });
      if (res.ok) {
        const data = await res.json();
        setTfStatus(data);
        prevRunningRef.current = false;
      }
    } catch (err) {
      setTfStatus((prev) => ({
        ...prev,
        logs: [...(prev.logs || []), `[ERROR AL CANCELAR] ${err.message}`],
      }));
    }
  };

  // Clear persisted and in-memory Terraform logs
  const handleClearLogs = async () => {
    if (!migrationId) return;
    try {
      const res = await apiFetch(`/api/v1/migration/jobs/${migrationId}/terraform/logs`, {
        method: "DELETE",
      });
      if (res.ok) {
        const data = await res.json();
        setTfStatus(data);
      }
    } catch {
      setTfStatus((prev) => ({ ...prev, logs: [] }));
    }
  };

  // Copy text helper
  const handleCopy = (text, label = "copiado") => {
    navigator.clipboard?.writeText(text);
    setCopiedText(label);
    setTimeout(() => setCopiedText(""), 2000);
  };

  // Download logs as .log file
  const handleDownloadLogs = () => {
    const content = (tfStatus.logs || []).join("\n");
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `terraform-${migrationId}.log`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const badgeMeta = STATUS_BADGE_STYLE[tfStatus.status] || STATUS_BADGE_STYLE.IDLE;
  const isRunning = Boolean(tfStatus.is_running);
  const logsList = tfStatus.logs || [];
  const filteredLogs = logSearch.trim()
    ? logsList.filter((line) => line.toLowerCase().includes(logSearch.trim().toLowerCase()))
    : logsList;

  const outputsMap = tfStatus.outputs || {};
  const managedResources = tfStatus.managed_resources || [];
  const primaryInst = tfStatus.primary_instance;
  const publicIp =
    primaryInst?.public_ip ||
    outputsMap.instance_public_ip?.value ||
    null;

  return (
    <div className="cm-card" style={{ marginTop: 14, border: "1px solid #cbd5e1" }}>
      <div className="cm-card-title" style={{ flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span>Consola Operativa y Centro de Control de Terraform ({provider})</span>
          <span
            className="cm-badge"
            style={{
              backgroundColor: badgeMeta.bg,
              color: badgeMeta.fg,
              fontWeight: 700,
              fontSize: 11.5,
              padding: "3px 10px",
              borderRadius: 999,
            }}
          >
            {badgeMeta.label}
          </span>
          {tfStatus.resource_count > 0 && (
            <span
              className="cm-badge observed"
              style={{ backgroundColor: "#0f766e", color: "#ffffff", fontWeight: 700, fontSize: 11.5 }}
            >
              {tfStatus.resource_count} Recurso(s) Activos en {provider}
            </span>
          )}
        </div>
        {tfStatus.workspace_dir && (
          <code style={{ fontSize: 11.5, color: "#64748b", backgroundColor: "#f1f5f9", padding: "2px 8px", borderRadius: 4 }}>
            Workspace: {tfStatus.workspace_dir.split("/").slice(-2).join("/")}
          </code>
        )}
      </div>

      <p style={{ margin: "4px 0 14px 0", fontSize: 13.5, color: "#475569" }}>
        Ejecuta comandos individuales o encadenados de Terraform (<code>init</code>, <code>validate</code>, <code>plan</code>, <code>apply</code>, <code>continue</code>, <code>refresh</code>, <code>output</code>, <code>state list</code> y <code>destroy</code>), inspecciona los logs en tiempo real, cancela procesos activos o destruye la infraestructura aprovisionada.
      </p>

      {/* 1. Panel de Configuración y Verificación de Credenciales Cloud */}
      <div className="cm-card-subtle" style={{ padding: 16, marginBottom: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
          <div>
            <strong style={{ fontSize: 14.5, color: "#0f172a" }}>
              1. Autenticación y Credenciales Cloud ({provider})
            </strong>
            <p style={{ margin: "3px 0 0 0", fontSize: 12.5, color: "#64748b" }}>
              Ingresa tus credenciales IAM en memoria o utiliza las credenciales locales del servidor (<code>~/.aws</code> / variables de entorno).
            </p>
          </div>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <label style={{ fontSize: 12.5, display: "flex", alignItems: "center", gap: 5, cursor: "pointer", fontWeight: authMode === "form" ? 700 : 400 }}>
              <input
                type="radio"
                name="authMode"
                value="form"
                checked={authMode === "form"}
                onChange={() => setAuthMode("form")}
              />
              Ingresar credenciales IAM
            </label>
            <label style={{ fontSize: 12.5, display: "flex", alignItems: "center", gap: 5, cursor: "pointer", fontWeight: authMode === "env" ? 700 : 400 }}>
              <input
                type="radio"
                name="authMode"
                value="env"
                checked={authMode === "env"}
                onChange={() => setAuthMode("env")}
              />
              Variables de entorno / ~/.aws locales
            </label>
          </div>
        </div>

        {authMode === "form" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 12, backgroundColor: "#ffffff", padding: 14, borderRadius: 6, border: "1px solid #e2e8f0" }}>
            <div style={{ backgroundColor: "#f8fafc", padding: "8px 10px", borderRadius: 4, border: "1px dashed #94a3b8" }}>
              <label style={{ display: "block", fontSize: 12, fontWeight: 700, color: "#0f172a", marginBottom: 4 }}>
                Pegado Rápido de Bloque AWS Academy / AWS CLI (Opcional — Rellena automáticamente los 3 campos):
              </label>
              <textarea
                rows={2}
                placeholder="Pega aquí el bloque completo de AWS Details -> AWS CLI: Show ([default] aws_access_key_id=... aws_secret_access_key=... aws_session_token=...)"
                value={rawCredsBlock}
                onChange={(e) => handleParseCredentialsBlock(e.target.value)}
                style={{ width: "100%", padding: "6px 8px", fontSize: 12, borderRadius: 4, border: "1px solid #cbd5e1", fontFamily: "monospace" }}
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
              <div>
                <label style={{ display: "block", fontSize: 12, fontWeight: 700, color: "#334155", marginBottom: 4 }}>
                  AWS Access Key ID *
                </label>
                <input
                  type="text"
                  placeholder="AKIAIOSFODNN7EXAMPLE"
                  value={awsAccessKeyId}
                  onChange={(e) => setAwsAccessKeyId(e.target.value)}
                  style={{ width: "100%", padding: "7px 10px", fontSize: 13, borderRadius: 4, border: "1px solid #cbd5e1", fontFamily: "monospace" }}
                />
              </div>

              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                  <label style={{ fontSize: 12, fontWeight: 700, color: "#334155" }}>
                    AWS Secret Access Key *
                  </label>
                  <button
                    type="button"
                    onClick={() => setShowSecret(!showSecret)}
                    style={{ background: "none", border: "none", fontSize: 11.5, color: "#0972d3", cursor: "pointer", padding: 0 }}
                  >
                    {showSecret ? "Ocultar" : "Mostrar"}
                  </button>
                </div>
                <input
                  type={showSecret ? "text" : "password"}
                  placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                  value={awsSecretAccessKey}
                  onChange={(e) => setAwsSecretAccessKey(e.target.value)}
                  style={{ width: "100%", padding: "7px 10px", fontSize: 13, borderRadius: 4, border: "1px solid #cbd5e1", fontFamily: "monospace" }}
                />
              </div>

              <div>
                <label style={{ display: "block", fontSize: 12, fontWeight: 700, color: "#334155", marginBottom: 4 }}>
                  Región AWS Destino
                </label>
                <select
                  value={awsRegion}
                  onChange={(e) => setAwsRegion(e.target.value)}
                  style={{ width: "100%", padding: "7px 10px", fontSize: 13, borderRadius: 4, border: "1px solid #cbd5e1" }}
                >
                  <option value="us-east-1">us-east-1 (N. Virginia)</option>
                  <option value="us-east-2">us-east-2 (Ohio)</option>
                  <option value="us-west-2">us-west-2 (Oregon)</option>
                  <option value="sa-east-1">sa-east-1 (São Paulo)</option>
                  <option value="eu-west-1">eu-west-1 (Ireland)</option>
                </select>
              </div>
            </div>

            <div>
              <button
                type="button"
                onClick={() => setShowTokenField(!showTokenField)}
                style={{ background: "none", border: "none", fontSize: 12, color: "#0972d3", cursor: "pointer", textDecoration: "underline", padding: 0 }}
              >
                {showTokenField ? "− Ocultar AWS Session Token" : "+ Agregar AWS Session Token (Cuentas temporales / AWS Academy / SSO)"}
              </button>
            </div>

            {showTokenField && (
              <div>
                <label style={{ display: "block", fontSize: 12, fontWeight: 700, color: "#334155", marginBottom: 4 }}>
                  AWS Session Token (Opcional)
                </label>
                <textarea
                  rows={2}
                  placeholder="IQoJb3JpZ2luX2VjEAEaCXVzLWVhc3QtMS..."
                  value={awsSessionToken}
                  onChange={(e) => setAwsSessionToken(e.target.value)}
                  style={{ width: "100%", padding: "6px 10px", fontSize: 12, borderRadius: 4, border: "1px solid #cbd5e1", fontFamily: "monospace" }}
                />
              </div>
            )}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
          <div style={{ fontSize: 12.5, color: "#64748b" }}>
            {callerIdentity?.valid ? (
              <span style={{ color: "#166534", fontWeight: 700 }}>
                [OK] Identidad verificada: Cuenta {callerIdentity.account} ({callerIdentity.arn})
              </span>
            ) : (
              <span>Las credenciales solo residen en memoria durante la sesión de Terraform.</span>
            )}
          </div>
          <button
            type="button"
            className="cm-btn sm secondary"
            onClick={handleVerifyCaller}
            disabled={verifyingCaller}
          >
            {verifyingCaller ? "Comprobando STS..." : "Comprobar Identidad AWS / STS"}
          </button>
        </div>

        {callerIdentity && !callerIdentity.valid && (
          <div
            style={{
              marginTop: 10,
              padding: "10px 14px",
              borderRadius: 6,
              fontSize: 13,
              backgroundColor: "#fef2f2",
              border: "1px solid #fca5a5",
              color: "#7f1d1d",
            }}
          >
            <strong>[ALERTA] Verificación STS:</strong> {callerIdentity.error}
          </div>
        )}
      </div>

      {/* 2. Botonera de Operaciones y Comandos de Terraform */}
      <div
        style={{
          padding: 16,
          marginBottom: 14,
          backgroundColor: "#f8fafc",
          borderRadius: 8,
          border: "1px solid #cbd5e1",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
          <strong style={{ fontSize: 14.5, color: "#0f172a" }}>
            2. Acciones Principales del Ciclo de Vida de Terraform
          </strong>
          {tfStatus.is_locked && (
            <span className="cm-badge warning" style={{ fontSize: 11.5 }}>
              Estado bloqueado (.terraform.tfstate.lock.info detectado)
            </span>
          )}
        </div>

        {/* Fila 1: Operaciones Principales (Desplegar, Continuar/Aplicar, Simular, Cancelar, Destruir) */}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
          <button
            type="button"
            className="cm-btn primary"
            onClick={() => handleRunCommand("full_deploy")}
            disabled={isRunning}
            style={{ backgroundColor: "#ff9900", color: "#000716", fontWeight: 700 }}
            title="Ejecuta secuencialmente: terraform init -> validate -> plan -> apply -auto-approve"
          >
            {isRunning && tfStatus.active_command === "full_deploy"
              ? "⟳ Aprovisionando en AWS..."
              : "Desplegar Flujo Completo (Init → Plan → Apply)"}
          </button>

          <button
            type="button"
            className="cm-btn primary"
            onClick={() => handleRunCommand("continue")}
            disabled={isRunning}
            style={{ backgroundColor: "#0f766e", color: "#ffffff", fontWeight: 700 }}
            title="Ejecuta 'terraform apply -auto-approve' retomando desde el estado actual (terraform.tfstate) sin recrear recursos ya existentes"
          >
            {isRunning && (tfStatus.active_command === "continue" || tfStatus.active_command === "apply")
              ? "⟳ Aplicando / Continuando..."
              : "Continuar / Aplicar (terraform apply)"}
          </button>

          <button
            type="button"
            className="cm-btn secondary"
            onClick={() => handleRunCommand("dry_run")}
            disabled={isRunning}
            title="Ejecuta 'terraform init', 'validate' y 'plan' sin crear recursos en la nube"
          >
            {isRunning && tfStatus.active_command === "dry_run"
              ? "⟳ Validando Dry-Run..."
              : "Simular y Validar (Dry-Run)"}
          </button>

          <button
            type="button"
            className="cm-btn"
            onClick={handleCancelExecution}
            disabled={!isRunning && !tfStatus.is_locked}
            style={{
              backgroundColor: isRunning ? "#dc2626" : "#f1f5f9",
              color: isRunning ? "#ffffff" : "#475569",
              border: isRunning ? "1px solid #b91c1c" : "1px solid #cbd5e1",
              fontWeight: 700,
              cursor: isRunning || tfStatus.is_locked ? "pointer" : "not-allowed",
            }}
            title="Envía SIGTERM/SIGKILL al proceso Terraform en curso y libera bloqueos de estado"
          >
            Cancelar Ejecución Activa
          </button>

          <button
            type="button"
            className="cm-btn danger"
            onClick={() => setConfirmDestroy(true)}
            disabled={isRunning}
            style={{ fontWeight: 700 }}
            title="Ejecuta 'terraform destroy -auto-approve' para eliminar todos los recursos creados en AWS"
          >
            {isRunning && tfStatus.active_command === "destroy"
              ? "⟳ Destruyendo Recursos..."
              : "Destruir Infraestructura (terraform destroy)"}
          </button>
        </div>

        {/* Confirmación explícita antes de ejecutar terraform destroy */}
        {confirmDestroy && (
          <div
            style={{
              marginBottom: 12,
              padding: "12px 16px",
              backgroundColor: "#fef2f2",
              border: "1px solid #f87171",
              borderRadius: 6,
            }}
          >
            <div style={{ fontWeight: 700, color: "#991b1b", fontSize: 13.5, marginBottom: 4 }}>
              [ALERTA] Confirmar Destrucción de Infraestructura en {provider} (<code>terraform destroy -auto-approve</code>)
            </div>
            <p style={{ margin: "0 0 10px 0", fontSize: 13, color: "#7f1d1d" }}>
              Esta acción eliminará permanentemente los <strong>{tfStatus.resource_count} recursos aprovisionados</strong> registrados en <code>terraform.tfstate</code> (instancia EC2 <code>{primaryInst?.id || ""}</code>, VPC, subredes, Internet Gateway y Security Groups). El repositorio original y los backups locales no sufren ningún cambio.
            </p>
            <div style={{ display: "flex", gap: 10 }}>
              <button
                type="button"
                className="cm-btn danger sm"
                onClick={() => handleRunCommand("destroy")}
                style={{ fontWeight: 700 }}
              >
                Sí, Ejecutar terraform destroy Ahora
              </button>
              <button
                type="button"
                className="cm-btn secondary sm"
                onClick={() => setConfirmDestroy(false)}
              >
                Cancelar
              </button>
            </div>
          </div>
        )}

        {/* Fila 2: Comandos Individuales Granulares de Terraform CLI */}
        <div style={{ borderTop: "1px solid #e2e8f0", paddingTop: 10 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#475569", marginBottom: 8 }}>
            Comandos Granulares de Terraform CLI y Diagnóstico de Estado:
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              className="cm-btn sm secondary"
              onClick={() => handleRunCommand("init")}
              disabled={isRunning}
            >
              terraform init
            </button>
            <button
              type="button"
              className="cm-btn sm secondary"
              onClick={() => handleRunCommand("validate")}
              disabled={isRunning}
            >
              [OK] terraform validate
            </button>
            <button
              type="button"
              className="cm-btn sm secondary"
              onClick={() => handleRunCommand("plan")}
              disabled={isRunning}
            >
              terraform plan
            </button>
            <button
              type="button"
              className="cm-btn sm secondary"
              onClick={() => handleRunCommand("output")}
              disabled={isRunning}
            >
              terraform output
            </button>
            <button
              type="button"
              className="cm-btn sm secondary"
              onClick={() => handleRunCommand("state")}
              disabled={isRunning}
            >
              terraform state list
            </button>
            <button
              type="button"
              className="cm-btn sm secondary"
              onClick={() => handleRunCommand("refresh")}
              disabled={isRunning}
            >
              terraform refresh
            </button>
            <button
              type="button"
              className="cm-btn sm secondary"
              onClick={() => handleRunCommand("unlock")}
              disabled={isRunning}
              title="Elimina el archivo .terraform.tfstate.lock.info si un proceso anterior se interrumpió"
            >
              Desbloquear Estado
            </button>
            <button
              type="button"
              className="cm-btn sm secondary"
              onClick={fetchTerraformStatus}
              title="Recarga el estado actual de terraform.tfstate y los logs desde el servidor"
            >
              ↻ Actualizar Vista
            </button>
          </div>
        </div>
      </div>

      {/* 3. Tarjeta de Recursos Aprovisionados y Endpoints en Vivo (si existen en terraform.tfstate) */}
      {(tfStatus.resource_count > 0 || Object.keys(outputsMap).length > 0) && (
        <div
          style={{
            marginBottom: 14,
            padding: 16,
            backgroundColor: "#f0fdf4",
            borderRadius: 8,
            border: "1px solid #86efac",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
            <div>
              <strong style={{ fontSize: 14.5, color: "#14532d" }}>
                Infraestructura Activa Detectada en {provider} (<code>terraform.tfstate</code> · {tfStatus.resource_count} recursos)
              </strong>
              {publicIp && (
                <div style={{ fontSize: 12.5, color: "#166534", marginTop: 2 }}>
                  Instancia EC2 Activa: <code>{primaryInst?.id || outputsMap.instance_id?.value}</code> · IPv4 Pública: <strong>{publicIp}</strong>
                </div>
              )}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {copiedText && (
                <span className="cm-badge observed" style={{ fontSize: 11 }}>
                  [OK] {copiedText}
                </span>
              )}
              <button
                type="button"
                className="cm-btn sm secondary"
                onClick={() => setShowStateResources(!showStateResources)}
              >
                {showStateResources ? "Ocultar Tabla de Recursos" : `Ver ${managedResources.length} Recursos Creados`}
              </button>
            </div>
          </div>

          {/*Accesos directos a la aplicación desplegada y SSH*/}
          {publicIp && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
                gap: 10,
                marginBottom: 12,
                padding: 12,
                backgroundColor: "#ffffff",
                borderRadius: 6,
                border: "1px solid #bbf7d0",
              }}
            >
              <div>
                <div style={{ fontSize: 11.5, fontWeight: 700, color: "#475569" }}>Frontend Web (Puerto 3000)</div>
                <a
                  href={`http://${publicIp}:3000`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ fontSize: 13, fontWeight: 700, color: "#0972d3", fontFamily: "monospace" }}
                >
                  http://{publicIp}:3000 ↗
                </a>
              </div>
              <div>
                <div style={{ fontSize: 11.5, fontWeight: 700, color: "#475569" }}>Backend API & Docs (Puerto 8000)</div>
                <a
                  href={`http://${publicIp}:8000/docs`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ fontSize: 13, fontWeight: 700, color: "#0972d3", fontFamily: "monospace" }}
                >
                  http://{publicIp}:8000/docs ↗
                </a>
              </div>
              <div>
                <div style={{ fontSize: 11.5, fontWeight: 700, color: "#475569" }}>Acceso SSH & Logs de Bootstrap</div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <code style={{ fontSize: 12 }}>ssh ubuntu@{publicIp}</code>
                  <button
                    type="button"
                    className="cm-btn sm secondary"
                    style={{ padding: "2px 6px", fontSize: 11 }}
                    onClick={() => handleCopy(`ssh ubuntu@${publicIp}`, "Comando SSH copiado")}
                  >
                    Copiar
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Salidas de Terraform (Outputs) */}
          {Object.keys(outputsMap).length > 0 && (
            <div style={{ marginBottom: showStateResources ? 12 : 0 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#166534", marginBottom: 6 }}>
                Salidas de Terraform (Outputs):
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
                {Object.entries(outputsMap).map(([k, v]) => {
                  const valStr = typeof v?.value === "object" ? JSON.stringify(v.value) : String(v?.value ?? "");
                  return (
                    <div
                      key={k}
                      style={{
                        backgroundColor: "#ffffff",
                        padding: "6px 10px",
                        borderRadius: 4,
                        border: "1px solid #dcfce7",
                        fontFamily: "monospace",
                        fontSize: 12,
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: 6,
                      }}
                    >
                      <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        <strong style={{ color: "#15803d" }}>{k}:</strong> {valStr}
                      </div>
                      <button
                        type="button"
                        onClick={() => handleCopy(valStr, `${k} copiado`)}
                        style={{ background: "none", border: "none", color: "#0972d3", cursor: "pointer", fontSize: 11 }}
                        title="Copiar valor"
                      >
                        
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Tabla detallada de los recursos en terraform.tfstate */}
          {showStateResources && managedResources.length > 0 && (
            <div style={{ overflowX: "auto", backgroundColor: "#ffffff", borderRadius: 6, border: "1px solid #bbf7d0" }}>
              <table className="cm-table" style={{ margin: 0, fontSize: 12.5 }}>
                <thead>
                  <tr>
                    <th>Recurso Terraform</th>
                    <th>Tipo AWS</th>
                    <th>ID Real en AWS</th>
                    <th>Detalles (IP / CIDR / Estado)</th>
                  </tr>
                </thead>
                <tbody>
                  {managedResources.map((r) => (
                    <tr key={r.address}>
                      <td>
                        <code>{r.address}</code>
                      </td>
                      <td>
                        <code>{r.type}</code>
                      </td>
                      <td>
                        <strong style={{ fontFamily: "monospace", color: "#0f172a" }}>{r.id}</strong>
                      </td>
                      <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                        {r.public_ip && <span style={{ color: "#15803d", fontWeight: 700 }}>IP Pública: {r.public_ip} · </span>}
                        {r.private_ip && <span>IP Privada: {r.private_ip} · </span>}
                        {r.instance_state && <span>Estado: {r.instance_state} · </span>}
                        {r.cidr_block && <span>CIDR: {r.cidr_block} · </span>}
                        {r.availability_zone && <span>AZ: {r.availability_zone}</span>}
                        {!r.public_ip && !r.cidr_block && !r.instance_state && <span>Activo</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* 4. Consola / Terminal de Logs de Terraform en Tiempo Real */}
      <div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 8,
            padding: "8px 12px",
            backgroundColor: "#1e293b",
            color: "#f8fafc",
            borderTopLeftRadius: 6,
            borderTopRightRadius: 6,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>
              Terminal de Logs de Terraform ({filteredLogs.length} líneas)
            </span>
            {isRunning && (
              <span
                style={{
                  fontSize: 11.5,
                  backgroundColor: "#2563eb",
                  color: "#ffffff",
                  padding: "2px 8px",
                  borderRadius: 999,
                  fontWeight: 700,
                }}
              >
                ● Ejecutando: terraform {tfStatus.active_command}...
              </span>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <input
              type="text"
              placeholder="Filtrar en logs (ej. aws_instance, error, vpc)..."
              value={logSearch}
              onChange={(e) => setLogSearch(e.target.value)}
              style={{
                padding: "4px 8px",
                fontSize: 12,
                borderRadius: 4,
                border: "1px solid #475569",
                backgroundColor: "#0f172a",
                color: "#f8fafc",
                width: 240,
              }}
            />
            <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 4, cursor: "pointer", color: "#cbd5e1" }}>
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
              />
              Auto-scroll
            </label>
            <button
              type="button"
              onClick={() => handleCopy(logsList.join("\n"), "Logs copiados")}
              disabled={logsList.length === 0}
              style={{
                backgroundColor: "#334155",
                color: "#f8fafc",
                border: "1px solid #475569",
                borderRadius: 4,
                padding: "4px 8px",
                fontSize: 11.5,
                cursor: "pointer",
              }}
            >
              Copiar
            </button>
            <button
              type="button"
              onClick={handleDownloadLogs}
              disabled={logsList.length === 0}
              style={{
                backgroundColor: "#334155",
                color: "#f8fafc",
                border: "1px solid #475569",
                borderRadius: 4,
                padding: "4px 8px",
                fontSize: 11.5,
                cursor: "pointer",
              }}
            >
              ⬇ Descargar .log
            </button>
            <button
              type="button"
              onClick={handleClearLogs}
              disabled={isRunning || logsList.length === 0}
              style={{
                backgroundColor: "#334155",
                color: "#fca5a5",
                border: "1px solid #475569",
                borderRadius: 4,
                padding: "4px 8px",
                fontSize: 11.5,
                cursor: "pointer",
              }}
            >
              Limpiar
            </button>
          </div>
        </div>

        <pre
          ref={logContainerRef}
          style={{
            margin: 0,
            padding: 14,
            backgroundColor: "#0f172a",
            color: "#e2e8f0",
            borderBottomLeftRadius: 6,
            borderBottomRightRadius: 6,
            fontSize: 12.5,
            minHeight: 180,
            maxHeight: 420,
            overflowY: "auto",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            fontFamily: "monospace",
            lineHeight: 1.5,
            border: "1px solid #1e293b",
          }}
        >
          {filteredLogs.length === 0 ? (
            <span style={{ color: "#64748b" }}>
              {logsList.length === 0
                ? "La consola de Terraform está lista. Haz clic en cualquiera de los botones superiores (ej. 'terraform plan', 'Continuar / Aplicar', 'terraform state list' o 'terraform output') para ver la salida en tiempo real..."
                : "No hay líneas que coincidan con el filtro de búsqueda."}
            </span>
          ) : (
            filteredLogs.map((log, idx) => {
              const isErr = log.includes("[ERROR") || log.includes("Error:") || log.includes("ERROR");
              const isSuccess = log.includes("Apply complete!") || log.includes("Destroy complete!") || log.includes("Success!") || log.includes("OK");
              const isCancel = log.includes("[CANCEL");
              return (
                <div
                  key={idx}
                  style={{
                    color: isErr ? "#fca5a5" : isSuccess ? "#86efac" : isCancel ? "#fcd34d" : "#f8fafc",
                    fontWeight: isErr || isSuccess ? 600 : 400,
                  }}
                >
                  {log}
                </div>
              );
            })
          )}
        </pre>
      </div>
    </div>
  );
}
