import React, { useState, useEffect, useRef, useCallback } from "react";
import { apiFetch } from "../../utils/apiClient";
import AwsCloudAuditPanel from "../audit/AwsCloudAuditPanel";

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
  const [consultTab, setConsultTab] = useState("resources"); // "resources" | "endpoints" | "disks_users" | "processes_ports" | "files_services"
  const [liveHostProbe, setLiveHostProbe] = useState(null);
  const [probingLiveOs, setProbingLiveOs] = useState(false);
  const [instanceHealth, setInstanceHealth] = useState(null);
  const [probingHealth, setProbingHealth] = useState(false);

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

  const handleProbeInstanceHealth = useCallback(async (targetIp) => {
    const ipToCheck = targetIp || publicIp;
    if (!ipToCheck) return;
    setProbingHealth(true);
    try {
      const res = await apiFetch(`/api/v1/migration/probe-instance-status?ip=${encodeURIComponent(ipToCheck)}`);
      if (res.ok) {
        const data = await res.json();
        setInstanceHealth(data);
      }
    } catch (err) {
      console.warn("Probe health error:", err);
    } finally {
      setProbingHealth(false);
    }
  }, [publicIp]);

  // Auto-probe when publicIp is detected
  useEffect(() => {
    if (publicIp && (!instanceHealth || instanceHealth.ip !== publicIp)) {
      handleProbeInstanceHealth(publicIp);
    }
  }, [publicIp, handleProbeInstanceHealth, instanceHealth]);

  // Auto-recheck while booting every 6 seconds
  useEffect(() => {
    if (publicIp && instanceHealth?.phase === "booting" && !probingHealth) {
      const timer = setTimeout(() => {
        handleProbeInstanceHealth(publicIp);
      }, 6000);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [publicIp, instanceHealth?.phase, probingHealth, handleProbeInstanceHealth]);

  const isVmCase = job?.use_case === "vm_image";
  const srcEnv = job?.source_environment || {};

  // Parse Terraform Plan / Dry-Run & Live Apply progress directly from logs
  const parsedPlanInfo = React.useMemo(() => {
    const resourcesByAddr = {};
    const plannedOutputs = {};
    let planSummaryText = null;
    let currentBlockAddr = null;
    let inOutputsSection = false;

    for (const rawLine of logsList) {
      const line = String(rawLine || "");
      // 1. Detect "# <address> will be created / updated / destroyed"
      const headerMatch = line.match(/^\s*#\s+([a-zA-Z0-9_.-]+\.[a-zA-Z0-9_.-]+)\s+will be\s+(created|updated|destroyed|replaced)/i);
      if (headerMatch) {
        const addr = headerMatch[1];
        const actionWord = headerMatch[2].toLowerCase();
        const [rType, ...rNameParts] = addr.split(".");
        currentBlockAddr = addr;
        inOutputsSection = false;
        resourcesByAddr[addr] = {
          address: addr,
          type: rType,
          name: rNameParts.join("."),
          action: actionWord,
          liveState: "PLANNED",
          liveId: "(known after apply)",
          details: [],
          portsCount: 0,
        };
        continue;
      }

      // 2. Detect Plan summary line
      const planMatch = line.match(/Plan:\s*(\d+\s+to\s+add,\s*\d+\s+to\s+change,\s*\d+\s+to\s+destroy)/i);
      if (planMatch) {
        planSummaryText = planMatch[1];
        currentBlockAddr = null;
        continue;
      }

      // 3. Detect Changes to Outputs section
      if (line.includes("Changes to Outputs:")) {
        inOutputsSection = true;
        currentBlockAddr = null;
        continue;
      }
      if (inOutputsSection) {
        const outMatch = line.match(/^\s*[+~-]\s*([a-zA-Z0-9_]+)\s*=\s*(.+)$/);
        if (outMatch) {
          plannedOutputs[outMatch[1]] = outMatch[2].trim();
          continue;
        } else if (line.trim().startsWith("─") || line.trim().startsWith("[")) {
          inOutputsSection = false;
        }
      }

      // 4. Parse key attributes inside a planned resource block
      if (currentBlockAddr && resourcesByAddr[currentBlockAddr]) {
        const item = resourcesByAddr[currentBlockAddr];
        const attrMatch = line.match(/^\s*\+\s+(ami|instance_type|size|volume_size|type|cidr_block|availability_zone|boot_mode|name)\s*=\s*"?([^"\n]+)"?/);
        if (attrMatch) {
          const [, k, v] = attrMatch;
          if (!v.includes("known after apply") && item.details.length < 5) {
            item.details.push(`${k}: ${v.trim()}`);
          }
        }
        const portMatch = line.match(/^\s*\+\s+from_port\s*=\s*(\d+)/);
        if (portMatch && Number(portMatch[1]) > 0) {
          item.portsCount += 1;
        }
      }

      // 5. Detect live creation / modification lines from `terraform apply`
      const creatingMatch = line.match(/^([a-zA-Z0-9_.-]+\.[a-zA-Z0-9_.-]+):\s*(Creating|Still creating|Modifying)\.\.\./i);
      if (creatingMatch) {
        const addr = creatingMatch[1];
        const [rType, ...rNameParts] = addr.split(".");
        if (!resourcesByAddr[addr]) {
          resourcesByAddr[addr] = { address: addr, type: rType, name: rNameParts.join("."), action: "created", details: [], portsCount: 0 };
        }
        resourcesByAddr[addr].liveState = "CREATING";
      }
      const createdMatch = line.match(/^([a-zA-Z0-9_.-]+\.[a-zA-Z0-9_.-]+):\s*Creation complete after\s+[^\[]+\[id=([^\]]+)\]/i);
      if (createdMatch) {
        const addr = createdMatch[1];
        const createdId = createdMatch[2];
        const [rType, ...rNameParts] = addr.split(".");
        if (!resourcesByAddr[addr]) {
          resourcesByAddr[addr] = { address: addr, type: rType, name: rNameParts.join("."), action: "created", details: [], portsCount: 0 };
        }
        resourcesByAddr[addr].liveState = "CREATED";
        resourcesByAddr[addr].liveId = createdId;
      }
    }

    // Merge with actual `terraform.tfstate` managedResources if present
    for (const mr of managedResources) {
      const addr = mr.address;
      const existing = resourcesByAddr[addr] || {
        address: addr,
        type: mr.type,
        name: mr.name,
        action: "created",
        details: [],
        portsCount: 0,
      };
      existing.liveState = "CREATED";
      existing.liveId = mr.id || existing.liveId;
      if (mr.public_ip) existing.details = [`IP Pública: ${mr.public_ip}`, ...existing.details];
      if (mr.cidr_block && !existing.details.some((d) => d.includes("cidr_block"))) {
        existing.details.push(`CIDR: ${mr.cidr_block}`);
      }
      if (mr.instance_type && !existing.details.some((d) => d.includes("instance_type"))) {
        existing.details.push(`Tipo: ${mr.instance_type}`);
      }
      resourcesByAddr[addr] = existing;
    }

    // Fallback: if no logs yet, synthesize from job.cmir so the table is never empty
    if (Object.keys(resourcesByAddr).length === 0 && job?.cmir?.resources) {
      const baseDefaults = [
        { address: "aws_vpc.target_vpc", type: "aws_vpc", name: "target_vpc", details: ["cidr_block: 10.0.0.0/16"] },
        { address: "aws_internet_gateway.igw", type: "aws_internet_gateway", name: "igw", details: ["name: cloudmove-igw"] },
        { address: "aws_subnet.public_subnet", type: "aws_subnet", name: "public_subnet", details: ["cidr_block: 10.0.1.0/24", "AZ: us-east-1a"] },
        { address: "aws_security_group.app_sg", type: "aws_security_group", name: "app_sg", details: ["name: cloudmove-app-sg"], portsCount: (srcEnv.listening_ports || srcEnv.exposed_ports || []).length || 4 },
      ];
      for (const b of baseDefaults) {
        resourcesByAddr[b.address] = { ...b, action: "created", liveState: "SYNTHESIZED", liveId: "(definido en main.tf)" };
      }
    }

    return {
      resources: Object.values(resourcesByAddr),
      planSummaryText,
      plannedOutputs,
    };
  }, [logsList, managedResources, job, srcEnv]);

  const handleProbeLiveOsData = async () => {
    setProbingLiveOs(true);
    try {
      const res = await apiFetch("/api/v1/migration/use-case-2/probe-devices", { method: "POST" });
      if (res.ok) {
        setLiveHostProbe(await res.json());
      }
    } catch {
      // Ignore transient error
    } finally {
      setProbingLiveOs(false);
    }
  };

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

      {/* 3. Centro de Consulta de Datos y Recursos en Creación / Planificados (Caso 1 y Caso 2) */}
      <div
        style={{
          marginBottom: 14,
          padding: 16,
          backgroundColor: tfStatus.resource_count > 0 ? "#f0fdf4" : "#f8fafc",
          borderRadius: 8,
          border: tfStatus.resource_count > 0 ? "1.5px solid #86efac" : "1.5px solid #93c5fd",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span
                className="cm-badge"
                style={{
                  backgroundColor: tfStatus.resource_count > 0 ? "#166534" : "#0972d3",
                  color: "#ffffff",
                  fontWeight: 700,
                  fontSize: 11.5,
                }}
              >
                {tfStatus.resource_count > 0
                  ? `INFRAESTRUCTURA ACTIVA (${tfStatus.resource_count} RECURSOS)`
                  : parsedPlanInfo.planSummaryText
                  ? `PLAN DRY-RUN (${parsedPlanInfo.planSummaryText.toUpperCase()})`
                  : `${parsedPlanInfo.resources.length} RECURSOS DEFINIDOS EN TERRAFORM`}
              </span>
              <strong style={{ fontSize: 14.5, color: "#0f172a" }}>
                3. {isVmCase
                  ? `Recursos que se van Creando en ${provider} y Consulta de Datos del Sistema Operativo Capturado`
                  : `Recursos que se van Creando en ${provider} y Consulta de Datos de la Aplicación`}
              </strong>
            </div>
            <div style={{ fontSize: 12.5, color: "#475569", marginTop: 4 }}>
              {publicIp ? (
                <span>
                  Instancia Activa: <code>{primaryInst?.id || outputsMap.instance_id?.value}</code> · IPv4 Pública: <strong style={{ color: "#15803d" }}>{publicIp}</strong>
                </span>
              ) : (
                <span>
                  Inspecciona en tiempo real cada recurso que Terraform va creando o planificando (<code>plan</code> / <code>apply</code>) y consulta todos los datos capturados ({isVmCase ? "discos, particiones, procesos en ejecución, puertos, archivos /etc y usuarios" : "endpoints, contenedores y base de datos"}).
                </span>
              )}
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
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
              {showStateResources ? "Minimizar Panel (−)" : "Expandir Panel (+)"}
            </button>
          </div>
        </div>

        {showStateResources && (
          <>
            {/* Pestañas de Consulta en Tiempo Real */}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", borderBottom: "1px solid #cbd5e1", paddingBottom: 8, marginBottom: 12 }}>
              <button
                type="button"
                className={`cm-btn sm ${consultTab === "resources" ? "primary" : "secondary"}`}
                onClick={() => setConsultTab("resources")}
              >
                1. Recursos Terraform ({parsedPlanInfo.resources.length})
              </button>
              <button
                type="button"
                className={`cm-btn sm ${consultTab === "endpoints" ? "primary" : "secondary"}`}
                onClick={() => setConsultTab("endpoints")}
              >
                2. Cómo Consultar los Datos (Endpoints & CLI)
              </button>
              {isVmCase && (
                <>
                  <button
                    type="button"
                    className={`cm-btn sm ${consultTab === "disks_users" ? "primary" : "secondary"}`}
                    onClick={() => setConsultTab("disks_users")}
                  >
                    3. Discos ({(srcEnv.disks || []).length}) y Usuarios ({(srcEnv.local_users || []).length})
                  </button>
                  <button
                    type="button"
                    className={`cm-btn sm ${consultTab === "processes_ports" ? "primary" : "secondary"}`}
                    onClick={() => setConsultTab("processes_ports")}
                  >
                    4. Procesos ({(srcEnv.running_processes || []).length}) y Puertos ({(srcEnv.listening_ports || []).length})
                  </button>
                  <button
                    type="button"
                    className={`cm-btn sm ${consultTab === "files_services" ? "primary" : "secondary"}`}
                    onClick={() => setConsultTab("files_services")}
                  >
                    5. Archivos del SO (/etc, /var, /home) y Servicios ({(srcEnv.systemd_services || []).length})
                  </button>
                </>
              )}
              <button
                type="button"
                className={`cm-btn sm ${consultTab === "aws_audit" ? "primary" : "secondary"}`}
                onClick={() => setConsultTab("aws_audit")}
              >
                🛡️ Auditoría de Cuenta AWS (Consultar y Eliminar Recursos)
              </button>
            </div>

            {/* PESTAÑA 1: TABLA DE RECURSOS EN CREACIÓN / PLANIFICADOS Y OUTPUTS */}
            {consultTab === "resources" && (
              <div>
                <div style={{ overflowX: "auto", backgroundColor: "#ffffff", borderRadius: 6, border: "1px solid #cbd5e1", marginBottom: 12 }}>
                  <table className="cm-table" style={{ margin: 0, fontSize: 12.5 }}>
                    <thead>
                      <tr>
                        <th>Recurso Terraform</th>
                        <th>Tipo Cloud</th>
                        <th>Estado en Vivo / Plan</th>
                        <th>ID / Referencia</th>
                        <th>Configuración y Datos Asociados</th>
                      </tr>
                    </thead>
                    <tbody>
                      {parsedPlanInfo.resources.map((r) => {
                        const isCreated = r.liveState === "CREATED";
                        const isCreating = r.liveState === "CREATING";
                        return (
                          <tr key={r.address}>
                            <td>
                              <strong><code>{r.address}</code></strong>
                            </td>
                            <td>
                              <code>{r.type}</code>
                            </td>
                            <td>
                              <span
                                className="cm-badge"
                                style={{
                                  backgroundColor: isCreated ? "#dcfce7" : isCreating ? "#dbeafe" : "#eff6ff",
                                  color: isCreated ? "#166534" : isCreating ? "#1d4ed8" : "#1e40af",
                                  fontWeight: 700,
                                  fontSize: 11,
                                }}
                              >
                                {isCreated
                                  ? "[OK] CREADO EN NUBE"
                                  : isCreating
                                  ? "⟳ CREANDO EN VIVO..."
                                  : `+ PLANIFICADO (${r.action.toUpperCase()})`}
                              </span>
                            </td>
                            <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                              {r.liveId}
                            </td>
                            <td style={{ fontSize: 12 }}>
                              {r.details?.length > 0 ? r.details.join(" · ") : "Configurado en main.tf"}
                              {r.portsCount > 0 && (
                                <span style={{ marginLeft: 6, color: "#0972d3", fontWeight: 700 }}>
                                  ({r.portsCount} reglas de puerto TCP activas)
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Salidas de Terraform (Outputs Reales o Planificados en Dry-Run) */}
                {(Object.keys(outputsMap).length > 0 || Object.keys(parsedPlanInfo.plannedOutputs).length > 0) && (
                  <div style={{ backgroundColor: "#ffffff", padding: 12, borderRadius: 6, border: "1px solid #cbd5e1" }}>
                    <div style={{ fontSize: 12.5, fontWeight: 700, color: "#0f172a", marginBottom: 8 }}>
                      Salidas de Terraform (<code>Outputs</code> {Object.keys(outputsMap).length > 0 ? "Activos en Estado" : "Previstos al Aplicar"}):
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 8 }}>
                      {Object.entries(
                        Object.keys(outputsMap).length > 0
                          ? outputsMap
                          : Object.fromEntries(
                              Object.entries(parsedPlanInfo.plannedOutputs).map(([k, v]) => [k, { value: v }])
                            )
                      ).map(([k, v]) => {
                        const valStr = typeof v?.value === "object" ? JSON.stringify(v.value) : String(v?.value ?? "");
                        return (
                          <div
                            key={k}
                            style={{
                              backgroundColor: "#f8fafc",
                              padding: "6px 10px",
                              borderRadius: 4,
                              border: "1px solid #e2e8f0",
                              fontFamily: "monospace",
                              fontSize: 12,
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              gap: 6,
                            }}
                          >
                            <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              <strong style={{ color: "#0972d3" }}>{k}:</strong> {valStr}
                            </div>
                            <button
                              type="button"
                              onClick={() => handleCopy(valStr, `${k} copiado`)}
                              style={{ background: "none", border: "none", color: "#0972d3", cursor: "pointer", fontSize: 11 }}
                            >
                              Copiar
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* PESTAÑA 2: CÓMO CONSULTAR LOS DATOS CREADOS (ENDPOINTS CLOUD Y CONSULTA LOCAL) */}
            {consultTab === "endpoints" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {/* Monitor de Salud en Tiempo Real de la Instancia AWS */}
                {publicIp && (
                  <div
                    style={{
                      backgroundColor: instanceHealth?.all_ready
                        ? "#f0fdf4"
                        : instanceHealth?.phase === "booting"
                        ? "#fffbeb"
                        : "#f8fafc",
                      border: `1px solid ${
                        instanceHealth?.all_ready
                          ? "#86efac"
                          : instanceHealth?.phase === "booting"
                          ? "#fde047"
                          : "#cbd5e1"
                      }`,
                      borderRadius: 8,
                      padding: 14,
                      display: "flex",
                      flexDirection: "column",
                      gap: 10,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 18 }}>
                          {instanceHealth?.all_ready ? "🟢" : instanceHealth?.phase === "booting" ? "⏳" : "🔍"}
                        </span>
                        <strong style={{ fontSize: 13, color: "#0f172a" }}>
                          Sonda de Estado en Vivo en AWS (IP Pública: {publicIp})
                        </strong>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <button
                          type="button"
                          className="cm-btn sm secondary"
                          onClick={() => handleProbeInstanceHealth(publicIp)}
                          disabled={probingHealth}
                          style={{ fontSize: 11, padding: "3px 10px" }}
                        >
                          {probingHealth ? "Verificando..." : "↻ Probar Conectividad Ahora"}
                        </button>
                      </div>
                    </div>

                    <div
                      style={{
                        fontSize: 12.5,
                        fontWeight: 500,
                        color: instanceHealth?.all_ready
                          ? "#166534"
                          : instanceHealth?.phase === "booting"
                          ? "#854d0e"
                          : "#475569",
                      }}
                    >
                      {instanceHealth?.summary ||
                        (probingHealth
                          ? "Comprobando apertura de puertos y salud de contenedores en AWS..."
                          : "Haz clic en 'Probar Conectividad Ahora' para validar que los puertos 3000 y 8000 hayan terminado de iniciar.")}
                    </div>

                    {instanceHealth && (
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        <div
                          style={{
                            backgroundColor: instanceHealth.frontend?.online ? "#dcfce7" : "#f1f5f9",
                            border: `1px solid ${instanceHealth.frontend?.online ? "#86efac" : "#cbd5e1"}`,
                            borderRadius: 6,
                            padding: "4px 10px",
                            fontSize: 12,
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                        >
                          <span>{instanceHealth.frontend?.online ? "✅" : "⏳"}</span>
                          <strong>Frontend (Puerto 3000):</strong>
                          <span>
                            {instanceHealth.frontend?.online
                              ? `En línea (HTTP ${instanceHealth.frontend?.status || 200})`
                              : "Instalando / Esperando"}
                          </span>
                        </div>

                        <div
                          style={{
                            backgroundColor: instanceHealth.backend?.online ? "#dcfce7" : "#f1f5f9",
                            border: `1px solid ${instanceHealth.backend?.online ? "#86efac" : "#cbd5e1"}`,
                            borderRadius: 6,
                            padding: "4px 10px",
                            fontSize: 12,
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                        >
                          <span>{instanceHealth.backend?.online ? "✅" : "⏳"}</span>
                          <strong>Backend API (Puerto 8000):</strong>
                          <span>
                            {instanceHealth.backend?.online
                              ? `En línea (HTTP ${instanceHealth.backend?.status || 200})`
                              : "Instalando / Esperando"}
                          </span>
                        </div>

                        <div
                          style={{
                            backgroundColor: instanceHealth.ssh?.open ? "#dcfce7" : "#f1f5f9",
                            border: `1px solid ${instanceHealth.ssh?.open ? "#86efac" : "#cbd5e1"}`,
                            borderRadius: 6,
                            padding: "4px 10px",
                            fontSize: 12,
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                        >
                          <span>{instanceHealth.ssh?.open ? "✅" : "⏳"}</span>
                          <strong>SSH (Puerto 22):</strong>
                          <span>{instanceHealth.ssh?.open ? "Abierto" : "Cerrado"}</span>
                        </div>
                      </div>
                    )}

                    <div
                      style={{
                        backgroundColor: "#eff6ff",
                        border: "1px solid #bfdbfe",
                        borderRadius: 6,
                        padding: "8px 12px",
                        fontSize: 12,
                        color: "#1e40af",
                        lineHeight: 1.45,
                      }}
                    >
                      <strong>💡 Advertencia de Navegación (Firefox / Chrome):</strong>
                      <br />
                      Si tu navegador muestra el mensaje <em>"Firefox no puede conectarse al servidor"</em>:
                      <ol style={{ margin: "4px 0 0 18px", padding: 0 }}>
                        <li>
                          <strong>Tiempo de arranque inicial:</strong> Al lanzar una instancia en AWS, Cloud-Init tarda <strong>2 a 3 minutos</strong> en instalar Docker, clonar el repositorio y levantar los contenedores.
                        </li>
                        <li>
                          <strong>Modo Solo HTTPS de Firefox:</strong> El navegador a menudo intenta forzar <code>https://{publicIp}:3000</code>. Asegúrate de ingresar explícitamente con <strong>http://</strong> (sin la 's'), o desactiva temporalmente el Modo Solo HTTPS para esta IP.
                        </li>
                      </ol>
                    </div>
                  </div>
                )}

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
                    gap: 10,
                    padding: 12,
                    backgroundColor: "#ffffff",
                    borderRadius: 6,
                    border: "1px solid #cbd5e1",
                  }}
                >
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "#0f172a" }}>
                      {isVmCase ? "Portal Web y Explorador de Archivos del SO (Puerto 3000)" : "Aplicación Frontend (Puerto 3000)"}
                    </div>
                    <div style={{ fontSize: 12, color: "#475569", marginBottom: 4 }}>
                      {isVmCase
                        ? "Explorador interactivo de archivos reales subidos (/etc, /home), discos lsblk y procesos:"
                        : "Interfaz web principal desplegada en la instancia:"}
                    </div>
                    {publicIp ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                        <a
                          href={`http://${publicIp}:3000`}
                          target="_blank"
                          rel="noreferrer"
                          style={{ fontSize: 13, fontWeight: 700, color: "#0972d3", fontFamily: "monospace" }}
                        >
                          http://{publicIp}:3000 ↗ (Portal + Explorador)
                        </a>
                        {isVmCase && (
                          <a
                            href={`http://${publicIp}:3000/files`}
                            target="_blank"
                            rel="noreferrer"
                            style={{ fontSize: 12, fontWeight: 600, color: "#0284c7", fontFamily: "monospace" }}
                          >
                            http://{publicIp}:3000/files ↗ (JSON Archivos Subidos)
                          </a>
                        )}
                      </div>
                    ) : (
                      <code style={{ fontSize: 12, color: "#0369a1" }}>http://&lt;IP_PUBLICA_EC2&gt;:3000 (Disponible tras terraform apply)</code>
                    )}
                  </div>

                  <div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "#0f172a" }}>
                      {isVmCase ? "API JSON de Telemetría y Consultas Directas de Archivos" : "Backend API & Healthcheck (Puerto 8000)"}
                    </div>
                    <div style={{ fontSize: 12, color: "#475569", marginBottom: 4 }}>
                      {isVmCase
                        ? "Consulta directa de telemetría JSON y lectura de archivos reales en la VM:"
                        : "Documentación OpenAPI y sonda de salud:"}
                    </div>
                    {publicIp ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                        <a
                          href={`http://${publicIp}:8000/health`}
                          target="_blank"
                          rel="noreferrer"
                          style={{ fontSize: 13, fontWeight: 700, color: "#0972d3", fontFamily: "monospace" }}
                        >
                          http://{publicIp}:8000/health ↗
                        </a>
                        {isVmCase && (
                          <>
                            <a
                              href={`http://${publicIp}:3000/files/view?path=etc/os-release`}
                              target="_blank"
                              rel="noreferrer"
                              style={{ fontSize: 11.5, color: "#0369a1", fontFamily: "monospace" }}
                            >
                              Ver /etc/os-release en VM ↗
                            </a>
                            <a
                              href={`http://${publicIp}:3000/files/view?path=home/lacastrilp/archivos_usuario_origen.txt`}
                              target="_blank"
                              rel="noreferrer"
                              style={{ fontSize: 11.5, color: "#0369a1", fontFamily: "monospace" }}
                            >
                              Ver archivos de /home/lacastrilp en VM ↗
                            </a>
                          </>
                        )}
                      </div>
                    ) : (
                      <code style={{ fontSize: 12, color: "#0369a1" }}>http://&lt;IP_PUBLICA_EC2&gt;:8000/health</code>
                    )}
                  </div>

                  <div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "#0f172a" }}>
                      Acceso SSH y Consulta In-Guest de Archivos
                    </div>
                    <div style={{ fontSize: 12, color: "#475569", marginBottom: 4 }}>
                      Inspecciona <code>/opt/cloudmove/os_capture/image_manifest.json</code> y logs:
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <code style={{ fontSize: 12 }}>ssh ubuntu@{publicIp || "<IP_PUBLICA_EC2>"}</code>
                      <button
                        type="button"
                        className="cm-btn sm secondary"
                        style={{ padding: "2px 6px", fontSize: 11 }}
                        onClick={() => handleCopy(`ssh ubuntu@${publicIp || "<IP_PUBLICA_EC2>"}`, "SSH copiado")}
                      >
                        Copiar
                      </button>
                    </div>
                  </div>
                </div>

                {/* Nota de arranque Cloud-Init */}
                <div
                  style={{
                    backgroundColor: "#fefce8",
                    border: "1px solid #fef08a",
                    borderRadius: 6,
                    padding: "8px 12px",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 12.5,
                    color: "#854d0e",
                  }}
                >
                  <span style={{ fontSize: 16 }}>⏳</span>
                  <div>
                    <strong>Tiempo de arranque de la instancia:</strong> Tras completar Terraform, la máquina en AWS tarda <strong>2 a 3 minutos</strong> en instalar Docker y arrancar los contenedores en segundo plano. Asegúrate de ingresar con <code>http://</code> (sin HTTPS) o desactivar temporalmente el modo Solo HTTPS de Firefox.
                  </div>
                </div>

                {/* Comandos de Consulta Rápida (Funciona tanto en Dry-Run local como en Cloud) */}
                <div style={{ backgroundColor: "#ffffff", padding: 12, borderRadius: 6, border: "1px solid #cbd5e1" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                    <strong style={{ fontSize: 13, color: "#0f172a" }}>
                      Comandos para Consultar los Datos Capturados y el Estado de la Máquina (Local y Cloud):
                    </strong>
                    {isVmCase && (
                      <button
                        type="button"
                        className="cm-btn sm primary"
                        onClick={handleProbeLiveOsData}
                        disabled={probingLiveOs}
                      >
                        {probingLiveOs ? "Consultando SO en vivo..." : "Consultar Dispositivos y Estado del Host Ahora"}
                      </button>
                    )}
                  </div>
                  <pre
                    style={{
                      margin: 0,
                      padding: 10,
                      backgroundColor: "#0f172a",
                      color: "#e2e8f0",
                      borderRadius: 6,
                      fontSize: 12,
                      overflowX: "auto",
                    }}
                  >
{isVmCase
  ? `# 1. Abrir el Explorador Interactivo de Archivos Reales del SO en la VM (Puerto 3000):
curl -s http://${publicIp || "<IP_PUBLICA_EC2>"}:3000/files | python3 -m json.tool

# 2. Consultar archivos reales de tu SO (/etc/os-release, /etc/fstab, /home/lacastrilp) subidos a la VM en AWS:
curl -s "http://${publicIp || "<IP_PUBLICA_EC2>"}:3000/files/view?path=etc/os-release"
curl -s "http://${publicIp || "<IP_PUBLICA_EC2>"}:3000/files/view?path=etc/fstab"
curl -s "http://${publicIp || "<IP_PUBLICA_EC2>"}:3000/files/view?path=home/lacastrilp/archivos_usuario_origen.txt"

# 3. Consultar telemetría en vivo (discos EBS montados lsblk, procesos ps y manifiesto del SO):
curl -s http://${publicIp || "<IP_PUBLICA_EC2>"}:8000/health | python3 -m json.tool`
  : `# 1. Consultar recursos planificados / creados en el workspace de Terraform:
terraform -chdir=generated/deployments/${migrationId} state list
terraform -chdir=generated/deployments/${migrationId} output

# 2. Consultar salud de los contenedores desplegados:
curl -Iv http://${publicIp || "<IP_PUBLICA_EC2>"}:3000
curl -Iv http://${publicIp || "<IP_PUBLICA_EC2>"}:8000/docs`}
                  </pre>

                  {liveHostProbe?.host && (
                    <div style={{ marginTop: 10, padding: 10, backgroundColor: "#f0fdf4", borderRadius: 6, border: "1px solid #86efac", fontSize: 12.5 }}>
                      <strong style={{ color: "#166534" }}>
                        [OK] Consulta en Vivo Ejecutada ({new Date(liveHostProbe.queried_at).toLocaleTimeString()}):
                      </strong>{" "}
                      Host <code>{liveHostProbe.host.hostname}</code> · {liveHostProbe.host.distro} · Kernel <code>{liveHostProbe.host.kernel}</code> · RAM: {liveHostProbe.host.ram_total_gib} GiB · Dispositivos detectados: {(liveHostProbe.devices || []).map((d) => `${d.path} (${d.size_gib} GiB)`).join(", ")}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* PESTAÑA 3: DISCOS, PARTICIONES (LSBLK) Y USUARIOS LOCALES */}
            {consultTab === "disks_users" && isVmCase && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ backgroundColor: "#ffffff", padding: 12, borderRadius: 6, border: "1px solid #cbd5e1" }}>
                  <strong style={{ fontSize: 13, color: "#0f172a", display: "block", marginBottom: 8 }}>
                    Discos y Particiones Capturados del SO (Mapeados a <code>aws_ebs_volume</code> + <code>root_block_device</code>):
                  </strong>
                  <div style={{ overflowX: "auto" }}>
                    <table className="cm-table" style={{ margin: 0, fontSize: 12.5 }}>
                      <thead>
                        <tr>
                          <th>Dispositivo / Partición</th>
                          <th>Punto de Montaje</th>
                          <th>Sistema de Archivos</th>
                          <th>UUID Preservado en /etc/fstab</th>
                          <th>Tamaño / Uso</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(srcEnv.disks || []).flatMap((d) =>
                          (d.partitions || []).map((p, idx) => (
                            <tr key={`${d.device}-${idx}`}>
                              <td>
                                <strong><code>{p.device || p.name || `${d.device}p${idx + 1}`}</code></strong>
                              </td>
                              <td>
                                <code>{p.mount_point || "[SWAP / RAW]"}</code>
                              </td>
                              <td>
                                <code>{p.filesystem || "ext4"}</code>
                              </td>
                              <td>
                                <code>{p.uuid || "UUID verificado"}</code>
                              </td>
                              <td>
                                <strong>{p.size_gib ?? d.size_gib} GiB</strong>
                                {p.used_gib ? ` (${p.used_gib} GiB usados)` : ""}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div style={{ backgroundColor: "#ffffff", padding: 12, borderRadius: 6, border: "1px solid #cbd5e1" }}>
                  <strong style={{ fontSize: 13, color: "#0f172a", display: "block", marginBottom: 6 }}>
                    Cuentas de Usuario Locales Capturadas (Restauradas vía <code>user_data.sh</code>):
                  </strong>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {(srcEnv.local_users || ["root"]).map((u) => (
                      <span key={u} className="cm-badge info" style={{ fontSize: 12 }}>
                        <code>{u}</code>
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* PESTAÑA 4: PROCESOS CORRIENDO (PS AUX) Y PUERTOS ACTIVOS (SS -TULPN) */}
            {consultTab === "processes_ports" && isVmCase && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ backgroundColor: "#ffffff", padding: 12, borderRadius: 6, border: "1px solid #cbd5e1" }}>
                  <strong style={{ fontSize: 13, color: "#0f172a", display: "block", marginBottom: 6 }}>
                    Puertos TCP/UDP en Escucha Detectados en el SO y Abiertos en <code>aws_security_group.app_sg</code> ({(srcEnv.listening_ports || []).length}):
                  </strong>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {(srcEnv.listening_ports || [22, 80, 443, 3000, 8000]).map((port) => (
                      <span key={port} className="cm-badge observed" style={{ fontSize: 12 }}>
                        TCP <code>:{port}</code>
                      </span>
                    ))}
                  </div>
                </div>

                <div style={{ backgroundColor: "#ffffff", padding: 12, borderRadius: 6, border: "1px solid #cbd5e1" }}>
                  <strong style={{ fontSize: 13, color: "#0f172a", display: "block", marginBottom: 8 }}>
                    Procesos Activos Capturados en el Sistema Operativo ({(srcEnv.running_processes || []).length} procesos):
                  </strong>
                  <div style={{ maxHeight: 260, overflowY: "auto" }}>
                    <table className="cm-table" style={{ margin: 0, fontSize: 12 }}>
                      <thead>
                        <tr>
                          <th>PID</th>
                          <th>Usuario</th>
                          <th>Proceso</th>
                          <th>CPU %</th>
                          <th>MEM %</th>
                          <th>Comando Completo</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(srcEnv.running_processes || []).slice(0, 35).map((proc, pIdx) => (
                          <tr key={`${proc.pid}-${pIdx}`}>
                            <td><code>{proc.pid}</code></td>
                            <td><code>{proc.user}</code></td>
                            <td><strong>{proc.name}</strong></td>
                            <td>{proc.cpu_percent}%</td>
                            <td>{proc.mem_percent}%</td>
                            <td><code style={{ fontSize: 11.5 }}>{proc.command}</code></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {/* PESTAÑA 5: ARCHIVOS DEL SO (/ETC, /OPT, /VAR, /HOME) Y SERVICIOS SYSTEMD */}
            {consultTab === "files_services" && isVmCase && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ backgroundColor: "#f0fdf4", padding: 12, borderRadius: 6, border: "1px solid #86efac" }}>
                  <strong style={{ fontSize: 13, color: "#14532d", display: "block", marginBottom: 6 }}>
                    Archivos Reales Subidos de tu SO a la VM en AWS (<code>/opt/cloudmove/os_capture/rootfs</code> y EBS <code>/mnt/cloudmove_ebs/rootfs</code>):
                  </strong>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {[
                      "etc/os-release",
                      "etc/fstab",
                      "etc/hostname",
                      "etc/hosts",
                      "etc/passwd",
                      "etc/crontab",
                      "home/lacastrilp/archivos_usuario_origen.txt",
                      "home/lacastrilp/CapstoneProject_TI/README.md",
                      "var/log/cloudmove_source_lsblk_df.txt",
                      "var/log/cloudmove_source_dpkg_packages.txt",
                      "var/log/cloudmove_source_processes_ports.txt",
                    ].map((relPath) =>
                      publicIp ? (
                        <a
                          key={relPath}
                          href={`http://${publicIp}:3000/files/view?path=${encodeURIComponent(relPath)}`}
                          target="_blank"
                          rel="noreferrer"
                          className="cm-badge observed"
                          style={{ textDecoration: "none", fontSize: 12, cursor: "pointer" }}
                        >
                          <code>/{relPath}</code> ↗
                        </a>
                      ) : (
                        <span key={relPath} className="cm-badge neutral" style={{ fontSize: 12 }}>
                          <code>/{relPath}</code>
                        </span>
                      )
                    )}
                  </div>
                </div>

                <div style={{ backgroundColor: "#ffffff", padding: 12, borderRadius: 6, border: "1px solid #cbd5e1" }}>
                  <strong style={{ fontSize: 13, color: "#0f172a", display: "block", marginBottom: 8 }}>
                    Inventario de Directorios y Archivos Críticos del Sistema Operativo:
                  </strong>
                  <div style={{ overflowX: "auto" }}>
                    <table className="cm-table" style={{ margin: 0, fontSize: 12 }}>
                      <thead>
                        <tr>
                          <th>Directorio del SO</th>
                          <th>Archivos</th>
                          <th>Subcarpetas</th>
                          <th>Muestra de Archivos / Componentes Capturados</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(srcEnv.filesystem_inventory || srcEnv.filesystem_summary || []).map((dir) => (
                          <tr key={dir.path}>
                            <td><strong><code>{dir.path}</code></strong></td>
                            <td>{dir.files_count ?? 0}</td>
                            <td>{dir.subdirs_count ?? 0}</td>
                            <td>
                              <code>{(dir.sample_entries || []).slice(0, 8).join(", ") || "Directorio verificado"}</code>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div style={{ backgroundColor: "#ffffff", padding: 12, borderRadius: 6, border: "1px solid #cbd5e1" }}>
                  <strong style={{ fontSize: 13, color: "#0f172a", display: "block", marginBottom: 8 }}>
                    Servicios <code>systemd</code> Habilitados ({(srcEnv.systemd_services || []).length}) y Paquetes ({srcEnv.installed_packages_summary?.total_count || 0} instalados):
                  </strong>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {(srcEnv.systemd_services || []).slice(0, 30).map((svc) => (
                      <span key={svc.name} className="cm-badge neutral" style={{ fontSize: 11.5 }}>
                        <code>{svc.name}</code> ({svc.active_state || "enabled"})
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* PESTAÑA AUDITORÍA DE CUENTA AWS EN VIVO */}
            {consultTab === "aws_audit" && (
              <AwsCloudAuditPanel
                initialCredentials={getActiveCredentials()}
                onAuditCompleted={() => fetchTerraformStatus()}
              />
            )}
          </>
        )}
      </div>

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
