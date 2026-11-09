import React, { useState } from "react";
import { apiFetch } from "../../utils/apiClient";

export default function ExternalServicesCredentialsCard({
  job,
  onCredentialsSaved,
}) {
  const srcEnv = job?.source_environment || {};
  const deepInsights = srcEnv.deep_insights || {};
  const envVars = srcEnv.environment_variables || [];

  const defaultUrl =
    (envVars.find((e) => e.name === "VITE_SUPABASE_URL") || {}).redacted_value ||
    deepInsights.supabase_details?.endpoint ||
    "https://zlkdxzfxkhohlpswdmap.supabase.co";

  const [supabaseUrl, setSupabaseUrl] = useState(defaultUrl);
  const [anonKey, setAnonKey] = useState("");
  const [serviceKey, setServiceKey] = useState("");
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState(null);
  const [savedSuccess, setSavedSuccess] = useState(false);

  const handleValidate = async () => {
    setValidating(true);
    setValidationResult(null);
    setSavedSuccess(false);

    try {
      const res = await apiFetch("/api/v1/migration/credentials/validate-external", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service_type: "supabase",
          credentials: {
            VITE_SUPABASE_URL: supabaseUrl,
            VITE_SUPABASE_ANON_KEY: anonKey,
            VITE_SUPABASE_SERVICE_ROLE_KEY: serviceKey,
          },
        }),
      });

      const data = await res.json();
      setValidationResult(data);
    } catch (err) {
      setValidationResult({
        valid: false,
        status: "NETWORK_ERROR",
        error: `Error al conectar con el backend de validación: ${err.message}`,
      });
    } finally {
      setValidating(false);
    }
  };

  const handleSave = () => {
    if (onCredentialsSaved) {
      onCredentialsSaved({
        VITE_SUPABASE_URL: supabaseUrl,
        VITE_SUPABASE_ANON_KEY: anonKey,
        VITE_SUPABASE_SERVICE_ROLE_KEY: serviceKey,
      });
    }
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 4000);
  };

  return (
    <div className="cm-card" style={{ marginTop: 12 }}>
      <div className="cm-card-title">
        <span>Gestión Segura de Servicios Externos y Credenciales</span>
        <span className="cm-badge observed">Zero-Trust & Secret Manager</span>
      </div>

      <div className="cm-alert info" style={{ marginBottom: 14 }}>
        <strong>Requisito de Seguridad y Mínimo Privilegio:</strong>
        <p style={{ margin: "4px 0 0 0", fontSize: 13.5, lineHeight: 1.45 }}>
          CloudMove solicita únicamente las credenciales indispensables para la integración de los servicios externos descubiertos. Las claves nunca se almacenan en texto plano en Git ni en bases de datos compartidas; se inyectan cifradas en <strong>AWS Secrets Manager</strong> o variables de entorno restringidas (<code>chmod 600</code>).
        </p>
      </div>

      {/* Tarjeta del Servicio Supabase */}
      <div className="cm-card-subtle" style={{ padding: 16, borderRadius: 8, border: "1px solid #cbd5e1" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 10 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 18 }}></span>
              <strong style={{ fontSize: 16, color: "#0f172a" }}>Supabase (PostgreSQL BaaS & Autenticación)</strong>
              <span className="cm-badge observed" style={{ backgroundColor: "#dcfce7", color: "#166534" }}>
                Detectado en Código
              </span>
            </div>
            <p style={{ margin: "6px 0 0 0", fontSize: 13.5, color: "#475569" }}>
              <strong>Propósito en el proyecto:</strong> Base de datos relacional PostgreSQL gestionada y sistema de autenticación de usuarios. Consumido por el frontend (<code>@supabase/supabase-js</code>) y el backend FastAPI.
            </p>
          </div>
          <span className="cm-badge" style={{ backgroundColor: "#f1f5f9", color: "#334155" }}>
            Servicio Externo Preservado
          </span>
        </div>

        <hr style={{ border: "none", borderTop: "1px solid #e2e8f0", margin: "14px 0" }} />

        {/* Formulario de credenciales con explicación por campo */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Campo 1: URL */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <label htmlFor="sb-url" style={{ fontWeight: 600, fontSize: 13.5, color: "#1e293b" }}>
                1. URL del Proyecto Supabase (<code>VITE_SUPABASE_URL</code>)
              </label>
              <span style={{ fontSize: 12, color: "#0284c7" }}>Nivel: Público (Endpoint HTTPS)</span>
            </div>
            <input
              id="sb-url"
              type="text"
              value={supabaseUrl}
              onChange={(e) => setSupabaseUrl(e.target.value)}
              placeholder="https://xyzcompany.supabase.co"
              style={{
                width: "100%",
                padding: "8px 12px",
                fontSize: 13.5,
                borderRadius: 6,
                border: "1px solid #cbd5e1",
                fontFamily: "monospace",
              }}
            />
            <span style={{ fontSize: 12, color: "#64748b", marginTop: 2, display: "block" }}>
              Dirección HTTPS de la API REST / PostgREST. No contiene información secreta.
            </span>
          </div>

          {/* Campo 2: Anon Key */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <label htmlFor="sb-anon" style={{ fontWeight: 600, fontSize: 13.5, color: "#1e293b" }}>
                2. Anon Public API Key (<code>VITE_SUPABASE_ANON_KEY</code>) *
              </label>
              <span style={{ fontSize: 12, color: "#16a34a" }}>Nivel: Cliente / RLS Habilitado</span>
            </div>
            <input
              id="sb-anon"
              type="password"
              value={anonKey}
              onChange={(e) => setAnonKey(e.target.value)}
              placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
              style={{
                width: "100%",
                padding: "8px 12px",
                fontSize: 13.5,
                borderRadius: 6,
                border: "1px solid #cbd5e1",
                fontFamily: "monospace",
              }}
            />
            <span style={{ fontSize: 12, color: "#64748b", marginTop: 2, display: "block" }}>
              Clave JWT para clientes frontend. <strong>Mínimo privilegio:</strong> Solo permite operaciones autorizadas por políticas de seguridad de nivel de fila (Row Level Security - RLS).
            </span>
          </div>

          {/* Campo 3: Service Role Key (Opcional) */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <label htmlFor="sb-service" style={{ fontWeight: 600, fontSize: 13.5, color: "#1e293b" }}>
                3. Service Role API Key (<code>VITE_SUPABASE_SERVICE_ROLE_KEY</code>) — Opcional
              </label>
              <span style={{ fontSize: 12, color: "#b91c1c" }}>Nivel: Servidor Backend (Bypass RLS)</span>
            </div>
            <input
              id="sb-service"
              type="password"
              value={serviceKey}
              onChange={(e) => setServiceKey(e.target.value)}
              placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9... (Solo si el backend requiere privilegios admin)"
              style={{
                width: "100%",
                padding: "8px 12px",
                fontSize: 13.5,
                borderRadius: 6,
                border: "1px solid #cbd5e1",
                fontFamily: "monospace",
              }}
            />
            <span style={{ fontSize: 12, color: "#64748b", marginTop: 2, display: "block" }}>
              Clave administrativa que omite RLS. Solo se inyecta de forma segura en el contenedor backend de la VPC.
            </span>
          </div>
        </div>

        {/* Acciones de Validación y Guardado */}
        <div style={{ marginTop: 16, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button
            type="button"
            className="cm-btn primary sm"
            onClick={handleValidate}
            disabled={validating || !supabaseUrl}
          >
            {validating ? "Probando conexión..." : "Probar Conexión con Supabase (Live Probe)"}
          </button>

          <button
            type="button"
            className="cm-btn secondary sm"
            onClick={handleSave}
            disabled={!supabaseUrl}
          >
            Guardar para Despliegue en Secrets Manager
          </button>

          {savedSuccess && (
            <span style={{ fontSize: 13, color: "#15803d", fontWeight: 600 }}>
              [OK] Credenciales guardadas y cifradas para el aprovisionamiento.
            </span>
          )}
        </div>

        {/* Banner de resultado de la prueba en vivo */}
        {validationResult && (
          <div
            style={{
              marginTop: 14,
              padding: "10px 14px",
              borderRadius: 6,
              backgroundColor: validationResult.valid
                ? "#f0fdf4"
                : validationResult.status === "AUTH_REQUIRED"
                ? "#fffbeb"
                : "#fef2f2",
              border: `1px solid ${
                validationResult.valid
                  ? "#86efac"
                  : validationResult.status === "AUTH_REQUIRED"
                  ? "#fde68a"
                  : "#fca5a5"
              }`,
              fontSize: 13.5,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong>
                {validationResult.valid
                  ? "[OK] Conexión y Autenticación Exitosas"
                  : validationResult.status === "AUTH_REQUIRED"
                  ? "ℹ Endpoint Activo — Requiere Anon Key"
                  : "[ERROR] Fallo de Conexión o Validación"}
              </strong>
              {validationResult.latency_ms > 0 && (
                <span className="cm-badge" style={{ fontSize: 11 }}>
                  Latencia: {validationResult.latency_ms} ms
                </span>
              )}
            </div>
            <p style={{ margin: "4px 0 0 0", color: "#334155" }}>
              {validationResult.message || validationResult.error}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
