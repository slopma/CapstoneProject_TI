import React, { useState } from "react";
import { apiFetch } from "../../utils/apiClient";

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
  const [showTokenField, setShowTokenField] = useState(false);

  // Verification & Execution state
  const [verifyingCaller, setVerifyingCaller] = useState(false);
  const [callerIdentity, setCallerIdentity] = useState(null);
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState(null);
  const [terminalLogs, setTerminalLogs] = useState([]);
  const [activeMode, setActiveMode] = useState("dry_run");

  // Get current active credentials payload
  const getActiveCredentials = () => {
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
  };

  // Verify Cloud Provider Credentials (AWS STS)
  const handleVerifyCaller = async () => {
    if (authMode === "form" && (!awsAccessKeyId.trim() || !awsSecretAccessKey.trim())) {
      setCallerIdentity({
        valid: false,
        provider: "aws",
        error: "Por favor ingresa tu AWS Access Key ID y AWS Secret Access Key antes de verificar la identidad.",
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

  // Execute Terraform Deployment (Dry-Run or Live)
  const handleExecuteDeploy = async (isDryRun = true) => {
    const creds = getActiveCredentials();
    if (!isDryRun && authMode === "form" && !creds) {
      alert("Para aprovisionar infraestructura real en AWS, debes proporcionar tus credenciales de AWS (Access Key y Secret Key) o seleccionar el modo de variables de entorno locales.");
      return;
    }

    setDeploying(true);
    setActiveMode(isDryRun ? "dry_run" : "live");
    setDeployResult(null);
    setTerminalLogs([
      `[CloudMove Runner] Iniciando proceso de despliegue para ${migrationId}...`,
      `[CloudMove Runner] Modo: ${isDryRun ? "SIMULACIÓN Y VALIDACIÓN (DRY-RUN - No requiere credenciales reales)" : "APROVISIONAMIENTO REAL EN LA NUBE"}`,
      `[CloudMove Runner] Proveedor destino: ${provider}`,
      creds ? `[CloudMove Runner] Credenciales aplicadas en memoria para sesión Terraform.` : `[CloudMove Runner] Usando entorno predeterminado del sistema.`,
    ]);

    try {
      const res = await apiFetch(`/api/v1/migration/jobs/${migrationId}/deploy-live`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dry_run: isDryRun,
          credentials: creds,
        }),
      });

      const data = await res.json();
      setDeployResult(data);
      if (data.logs && data.logs.length > 0) {
        setTerminalLogs(data.logs);
      }
      if (data.success && !isDryRun && onDeploymentCompleted) {
        onDeploymentCompleted(data);
      }
    } catch (err) {
      setDeployResult({
        success: false,
        error: `Error de ejecución: ${err.message}`,
      });
      setTerminalLogs((prev) => [...prev, `[ERROR FATAL] ${err.message}`]);
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div className="cm-card" style={{ marginTop: 14 }}>
      <div className="cm-card-title">
        <span>Despliegue Cloud Automatizado desde CloudMove</span>
        <span className="cm-badge observed" style={{ backgroundColor: "#1e293b", color: "#f8fafc" }}>
          Terraform Engine Runner
        </span>
      </div>

      <p style={{ margin: "4px 0 14px 0", fontSize: 13.5, color: "#475569" }}>
        Ejecuta el aprovisionamiento de infraestructura en la nube, la configuración de red y el despliegue contenerizado directamente desde CloudMove sin requerir ejecución manual en terminal.
      </p>

      {/* Panel de Configuración y Verificación de Credenciales Cloud */}
      <div className="cm-card-subtle" style={{ padding: 16, marginBottom: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
          <div>
            <strong style={{ fontSize: 14.5, color: "#0f172a" }}>
              🔑 Configuración y Validación de Credenciales ({provider})
            </strong>
            <p style={{ margin: "3px 0 0 0", fontSize: 12.5, color: "#64748b" }}>
              Para ejecutar en tu cuenta de AWS, ingresa tus credenciales IAM o utiliza las variables de entorno locales del servidor.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <label style={{ fontSize: 12.5, display: "flex", alignItems: "center", gap: 5, cursor: "pointer" }}>
              <input
                type="radio"
                name="authMode"
                value="form"
                checked={authMode === "form"}
                onChange={() => setAuthMode("form")}
              />
              Ingresar credenciales IAM
            </label>
            <label style={{ fontSize: 12.5, display: "flex", alignItems: "center", gap: 5, cursor: "pointer" }}>
              <input
                type="radio"
                name="authMode"
                value="env"
                checked={authMode === "env"}
                onChange={() => setAuthMode("env")}
              />
              Variables de entorno locales
            </label>
          </div>
        </div>

        {/* Formulario de Credenciales si authMode === 'form' */}
        {authMode === "form" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 12, backgroundColor: "#ffffff", padding: 14, borderRadius: 6, border: "1px solid #e2e8f0" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
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
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1.8fr", gap: 12, alignItems: "center" }}>
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

              <div>
                <button
                  type="button"
                  onClick={() => setShowTokenField(!showTokenField)}
                  style={{ background: "none", border: "none", fontSize: 12, color: "#0972d3", cursor: "pointer", textDecoration: "underline", padding: "16px 0 0 0" }}
                >
                  {showTokenField ? "− Ocultar AWS Session Token" : "+ Agregar AWS Session Token (Cuentas temporales / AWS Academy / SSO)"}
                </button>
              </div>
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

            <div style={{ fontSize: 11.5, color: "#64748b", marginTop: 2 }}>
              🔒 <strong>Seguridad Zero-Trust:</strong> Las credenciales se transmiten cifradas por TLS y solo residen en memoria durante la ejecución de Terraform. Nunca se escriben en disco ni se guardan en logs.
            </div>
          </div>
        )}

        {/* Botón de Comprobar Identidad */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
          <div style={{ fontSize: 12.5, color: "#64748b" }}>
            {callerIdentity?.valid ? (
              <span style={{ color: "#166534", fontWeight: 700 }}>✓ Credenciales autenticadas en AWS</span>
            ) : (
              <span>Valida que las credenciales tengan acceso a AWS STS antes de aprovisionar.</span>
            )}
          </div>
          <button
            type="button"
            className="cm-btn sm secondary"
            onClick={handleVerifyCaller}
            disabled={verifyingCaller}
          >
            {verifyingCaller ? "Comprobando..." : "🔑 Comprobar Identidad AWS / STS"}
          </button>
        </div>

        {callerIdentity && (
          <div
            style={{
              marginTop: 10,
              padding: "10px 14px",
              borderRadius: 6,
              fontSize: 13,
              backgroundColor: callerIdentity.valid ? "#f0fdf4" : "#fef2f2",
              border: `1px solid ${callerIdentity.valid ? "#86efac" : "#fca5a5"}`,
            }}
          >
            {callerIdentity.valid ? (
              <div>
                <strong style={{ color: "#166534" }}>✓ Identidad Cloud Verificada:</strong>
                <div style={{ marginTop: 4, fontFamily: "monospace", fontSize: 12 }}>
                  <div>Cuenta AWS: <strong>{callerIdentity.account}</strong></div>
                  <div>ARN: <code>{callerIdentity.arn}</code></div>
                </div>
              </div>
            ) : (
              <div>
                <strong style={{ color: "#991b1b" }}>⚠ Verificación de Credenciales:</strong>
                <div style={{ marginTop: 2, color: "#7f1d1d" }}>{callerIdentity.error}</div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Botones de Acción de Despliegue */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
        <button
          type="button"
          className="cm-btn secondary"
          onClick={() => handleExecuteDeploy(true)}
          disabled={deploying}
        >
          {deploying && activeMode === "dry_run" ? "Validando..." : "🔍 Validar Plan de Infraestructura (Dry-Run)"}
        </button>

        <button
          type="button"
          className="cm-btn primary"
          onClick={() => {
            if (window.confirm("¿Confirmas que deseas aprovisionar la infraestructura y desplegar la carga de trabajo en AWS?")) {
              handleExecuteDeploy(false);
            }
          }}
          disabled={deploying}
          style={{ backgroundColor: "#ff9900", color: "#000716", fontWeight: 700 }}
        >
          {deploying && activeMode === "live" ? "Aprovisionando en AWS..." : "🚀 Aprovisionar Infraestructura en AWS (Terraform Apply)"}
        </button>
      </div>

      <div style={{ fontSize: 12, color: "#64748b", marginBottom: 12 }}>
        💡 <strong>Recomendación:</strong> Puedes ejecutar <strong>Validar Plan (Dry-Run)</strong> para verificar el plan de Terraform (`terraform plan`) y la estructura de archivos sin requerir una cuenta de AWS activa.
      </div>

      {/* Consola / Terminal de Ejecución en Tiempo Real */}
      {terminalLogs.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "#334155" }}>
              Terminal de Ejecución de Despliegue
            </span>
            {deployResult && (
              <span
                className={`cm-badge ${deployResult.success ? "observed" : "danger"}`}
                style={{ fontSize: 11 }}
              >
                {deployResult.success ? "✓ Ejecución Exitosa" : "✗ Error en Despliegue"}
              </span>
            )}
          </div>

          <pre
            style={{
              padding: 14,
              backgroundColor: "#0f172a",
              color: "#f8fafc",
              borderRadius: 6,
              fontSize: 12.5,
              maxHeight: 280,
              overflowY: "auto",
              whiteSpace: "pre-wrap",
              fontFamily: "monospace",
              lineHeight: 1.45,
            }}
          >
            {terminalLogs.map((log, idx) => (
              <div key={idx}>{log}</div>
            ))}
          </pre>

          {deployResult?.outputs && Object.keys(deployResult.outputs).length > 0 && (
            <div
              style={{
                marginTop: 10,
                padding: 12,
                backgroundColor: "#f0fdf4",
                borderRadius: 6,
                border: "1px solid #86efac",
                fontSize: 13,
              }}
            >
              <strong style={{ color: "#166534" }}>Recursos Aprovisionados en AWS:</strong>
              <div style={{ marginTop: 6, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 8 }}>
                {Object.entries(deployResult.outputs).map(([k, v]) => (
                  <div key={k} style={{ fontFamily: "monospace", fontSize: 12 }}>
                    <strong>{k}:</strong> {typeof v.value === "object" ? JSON.stringify(v.value) : String(v.value)}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
