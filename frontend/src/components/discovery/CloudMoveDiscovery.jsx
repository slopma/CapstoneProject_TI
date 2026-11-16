import React, { useState, useEffect, useCallback } from "react";
import { getApiBase, buildUrl, apiFetch } from "../../utils/apiClient";

const AGENT_URL = "http://127.0.0.1:8765";

async function fetchWithTimeout(url, options = {}, timeoutMs = 4000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export default function CloudMoveDiscovery({
  apiBaseUrl = "",
  onInventoryDiscovered,
  onClose,
}) {
  const [status, setStatus] = useState("idle"); // "idle" | "checking" | "scanning" | "completed" | "error"
  const [message, setMessage] = useState(
    "Inicia el descubrimiento para detectar tu sistema operativo, preparar osquery, ejecutar la prueba funcional y escanear este equipo."
  );
  const [agentOnline, setAgentOnline] = useState(false);
  const [catalogData, setCatalogData] = useState(null);
  const [showAllAssets, setShowAllAssets] = useState(false);
  const [lastResult, setLastResult] = useState(null);

  const loadCatalog = useCallback(async () => {
    // 1. Intentar primero con el agente local desacoplado en 127.0.0.1:8765
    try {
      const res = await fetchWithTimeout(`${AGENT_URL}/catalog`, {}, 2500);
      if (res.ok) {
        const data = await res.json();
        setCatalogData(data);
        setAgentOnline(true);
        return;
      }
    } catch {
      setAgentOnline(false);
    }

    // 2. Fallback al endpoint de catálogo del backend principal
    try {
      const res = await apiFetch("/api/v1/discovery/osquery-catalog", { timeoutMs: 12000 });
      if (res.ok) {
        const data = await res.json();
        setCatalogData(data);
      }
    } catch {
      // ignore offline
    }
  }, []);

  useEffect(() => {
    loadCatalog();
  }, [loadCatalog]);

  async function startDiscovery() {
    setStatus("checking");
    setMessage("Etapa 1/2: Comprobando agente local, detectando OS/arquitectura y verificando osquery...");

    try {
      let usedStandaloneAgent = false;

      // Intentar flujo a través del agente local desacoplado (http://127.0.0.1:8765)
      try {
        const healthResponse = await fetchWithTimeout(`${AGENT_URL}/health`, {}, 2500);
        if (healthResponse.ok) {
          usedStandaloneAgent = true;
          setAgentOnline(true);
          const health = await healthResponse.json();

          if (!health.collector_exists) {
            throw new Error(
              "No se encontró el recolector Python (cloudmove_osquery_export.py) en la instalación."
            );
          }

          const assetName = health.recommended_asset_for_pc?.name || "osquery";
          setStatus("scanning");
          setMessage(
            health.osquery_installed
              ? `osquery detectado (${health.osquery_binary_path}). Ejecutando prueba funcional y escaneando el equipo...`
              : `Descargando e instalando paquete oficial '${assetName}' para tu PC y ejecutando escaneo...`
          );

          const response = await fetchWithTimeout(`${AGENT_URL}/discover`, {
            method: "POST",
          }, 30000);
          const result = await response.json();

          if (!response.ok) {
            throw new Error(result.detail || "No se pudo completar el descubrimiento en el agente local.");
          }

          setLastResult(result);

          // Obtener el JSON del agente (/inventory) y enviarlo al parser de CloudMove para actualizar todas las vistas
          const invResponse = await fetchWithTimeout(`${AGENT_URL}/inventory`, {}, 10000);
          if (invResponse.ok) {
            const rawJsonText = await invResponse.text();
            try {
              const importRes = await apiFetch("/api/v1/discovery/import", {
                method: "POST",
                timeoutMs: 30000,
                headers: {
                  "Content-Type": "application/json",
                  "X-Filename": `agent-osquery-${result.hostname || "pc"}.json`,
                },
                body: rawJsonText,
              });
              if (importRes.ok) {
                const sessionPayload = await importRes.json();
                if (onInventoryDiscovered) {
                  onInventoryDiscovered(sessionPayload);
                }
              }
            } catch {
              // ignore backend sync transient error
            }
          }

          setStatus("completed");
          setMessage(
            result.message ||
              "osquery está preparado, superó la prueba funcional y el inventario fue importado en CloudMove."
          );
          await loadCatalog();
          return;
        }
      } catch (agentErr) {
        if (usedStandaloneAgent) {
          throw agentErr;
        }
      }

      // Si el servicio en 8765 no está levantado por separado, usar el puente integrado del backend local
      setStatus("scanning");
      const assetName = catalogData?.recommended_asset_for_pc?.name || "osquery";
      setMessage(
        catalogData?.osquery_installed
          ? `osquery verificado (${catalogData.osquery_binary_path}). Ejecutando prueba funcional y escaneando este equipo...`
          : `Preparando e instalando '${assetName}' para este PC, ejecutando prueba funcional y generando inventario JSON...`
      );

      const bridgeRes = await apiFetch("/api/v1/discovery/collect-device", {
        method: "POST",
        timeoutMs: 45000,
      });

      const sessionJson = await bridgeRes.json().catch(() => ({}));
      if (!bridgeRes.ok) {
        throw new Error(
          sessionJson.detail?.message ||
            sessionJson.detail ||
            "No se pudo completar el descubrimiento del equipo."
        );
      }

      setLastResult({
        status: "completed",
        hostname: sessionJson.hostname,
        smoke_test: sessionJson.agent_smoke_test,
        session_id: sessionJson.session_id,
      });

      if (onInventoryDiscovered) {
        onInventoryDiscovered(sessionJson);
      }

      setStatus("completed");
      setMessage(
        `Descubrimiento completado en '${sessionJson.hostname}' (Sesión ${sessionJson.session_id}). ` +
          `osquery superó la prueba funcional y el inventario ya está cargado en CloudMove.`
      );
      await loadCatalog();
    } catch (error) {
      setStatus("error");
      if (error instanceof TypeError) {
        setMessage(
          "No se pudo conectar con el agente local (127.0.0.1:8765) ni con el backend. Comprueba que CloudMove Agent esté iniciado en este computador."
        );
      } else {
        setMessage(error instanceof Error ? error.message : "Error inesperado.");
      }
    }
  }

  async function downloadInventory() {
    try {
      // 1. Intentar descargar desde el agente local (http://127.0.0.1:8765/inventory)
      try {
        const response = await fetch(`${AGENT_URL}/inventory`);
        if (response.ok) {
          const blob = await response.blob();
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = "cloudmove-osquery-inventory.json";
          document.body.appendChild(link);
          link.click();
          link.remove();
          URL.revokeObjectURL(url);
          return;
        }
      } catch {
        // Fallback a exportación de la sesión activa en backend
      }

      if (lastResult?.session_id) {
        const exportUrl = buildUrl(apiBaseUrl, `/api/v1/discovery/sessions/${lastResult.session_id}/export?format=json`);
        window.open(
          exportUrl,
          "_blank",
          "noopener,noreferrer"
        );
        return;
      }

      throw new Error("Todavía no hay un inventario generado para descargar.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Error al descargar el JSON.");
    }
  }

  const pc = catalogData?.pc_platform;
  const recommended = catalogData?.recommended_asset_for_pc;
  const smoke = lastResult?.smoke_test || catalogData?.smoke_test;

  return (
    <section
      className="cm-card"
      style={{
        margin: "12px 18px",
        border: "1px solid var(--color-primary-border)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "12px", flexWrap: "wrap" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
            <h3 style={{ margin: 0, fontSize: "1.02rem", color: "var(--color-text-primary)" }}>
              Descubrimiento Automático de Equipos (Agente Local + Instalador osquery Multi-OS)
            </h3>
            <span className={`cm-badge ${agentOnline ? "observed" : "info"}`}>
              {agentOnline ? "Agente 127.0.0.1:8765 Conectado" : "Agente Integrado Activo"}
            </span>
          </div>
          <p className="cm-hint" style={{ margin: "6px 0 0", fontSize: "0.84rem" }}>
            CloudMove consulta el catálogo oficial de descargas de osquery, selecciona el paquete compatible con el sistema
            operativo y arquitectura de tu equipo, verifica su firma SHA-256, ejecuta una prueba funcional y escanea el host.
          </p>
        </div>

        {onClose && (
          <button type="button" className="cm-btn sm" onClick={onClose}>
            Cerrar panel
          </button>
        )}
      </div>

      {catalogData && (
        <div className="cm-kpi-grid" style={{ marginTop: "14px", marginBottom: 0 }}>
          <div className="cm-kpi-card">
            <span className="cm-kpi-label">1. Equipo Detectado</span>
            <span className="cm-kpi-value" style={{ fontSize: "0.98rem" }}>
              {pc?.os_label} ({pc?.raw_machine})
            </span>
            <span className="cm-kpi-meta">
              Host: <code>{pc?.hostname}</code> · Kernel: <code>{pc?.release}</code>
            </span>
          </div>

          <div className="cm-kpi-card">
            <span className="cm-kpi-label">2. Paquete Seleccionado</span>
            <span className="cm-kpi-value" style={{ fontSize: "0.92rem", color: "var(--color-primary)", wordBreak: "break-all" }}>
              {recommended ? recommended.name : "No disponible"}
            </span>
            <span className="cm-kpi-meta">
              Formato: <code>{recommended?.format}</code> · SHA-256:{" "}
              <code>{recommended?.sha256 ? `${recommended.sha256.slice(0, 12)}...` : "N/A"}</code>
            </span>
          </div>

          <div className="cm-kpi-card">
            <span className="cm-kpi-label">3. Estado y Smoke Test</span>
            <span
              className="cm-kpi-value"
              style={{
                fontSize: "0.92rem",
                color: smoke?.verified ? "#15803d" : "#b45309",
              }}
            >
              {smoke?.verified
                ? `Verificado (${smoke.osquery_info?.version || catalogData.osquery_version_target})`
                : "Pendiente de instalar / verificar"}
            </span>
            <span className="cm-kpi-meta" style={{ wordBreak: "break-all" }}>
              Binario: <code>{catalogData.osquery_binary_path || "Se instalará en ~/.local/share/cloudmove"}</code>
            </span>
          </div>
        </div>
      )}

      <div
        className={`cm-alert ${
          status === "error" ? "error" : status === "completed" ? "success" : "info"
        }`}
        style={{ marginTop: "14px" }}
        aria-live="polite"
      >
        <p style={{ margin: 0, fontWeight: 500 }}>{message}</p>
        {(status === "checking" || status === "scanning") && (
          <p className="cm-hint" style={{ margin: "6px 0 0" }}>
            El proceso está en ejecución: preparando osquery, ejecutando prueba SQL y escaneando tablas del sistema...
          </p>
        )}
      </div>

      <div style={{ marginTop: "14px", display: "flex", flexWrap: "wrap", gap: "10px", alignItems: "center" }}>
        <button
          type="button"
          onClick={startDiscovery}
          disabled={status === "checking" || status === "scanning"}
          className="cm-btn primary"
        >
          {status === "checking" || status === "scanning"
            ? "Descubriendo..."
            : "Instalar y descubrir"}
        </button>

        <button
          type="button"
          onClick={downloadInventory}
          disabled={status !== "completed" && !lastResult}
          className="cm-btn"
        >
          Descargar inventario JSON
        </button>

        {catalogData?.available_web_assets?.length > 0 && (
          <button
            type="button"
            className="cm-btn"
            onClick={() => setShowAllAssets((v) => !v)}
          >
            {showAllAssets
              ? "Ocultar catálogo web de sistemas operativos"
              : `Ver sistemas operativos disponibles en la web (${catalogData.available_web_assets_count})`}
          </button>
        )}
      </div>

      {showAllAssets && catalogData?.available_web_assets && (
        <div className="cm-table-wrap" style={{ marginTop: "14px" }}>
          <table className="cm-table">
            <thead>
              <tr>
                <th>Archivo en Web Oficial</th>
                <th>OS</th>
                <th>Arquitectura</th>
                <th>Formato</th>
                <th>Modo</th>
                <th>Checksum SHA-256 Oficial</th>
                <th>Selección para este PC</th>
              </tr>
            </thead>
            <tbody>
              {catalogData.available_web_assets.map((asset) => {
                const isSelected = recommended && asset.name === recommended.name;
                return (
                  <tr
                    key={asset.name}
                    style={
                      isSelected
                        ? { background: "var(--color-primary-subtle)", fontWeight: 600 }
                        : undefined
                    }
                  >
                    <td>
                      <a
                        href={asset.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: "var(--color-primary)", textDecoration: "none", fontWeight: 600 }}
                      >
                        {asset.name}
                      </a>
                    </td>
                    <td>{asset.os}</td>
                    <td>{asset.arch}</td>
                    <td>
                      <code>{asset.format}</code>
                    </td>
                    <td>{asset.portable ? "Portable (Sin root)" : "Instalador de sistema"}</td>
                    <td>
                      <code>{asset.sha256 ? `${asset.sha256.slice(0, 16)}…` : "—"}</code>
                    </td>
                    <td>
                      {isSelected ? (
                        <span className="cm-badge observed">[OK] Elegido para tu PC</span>
                      ) : (
                        <span className="cm-hint">Otro OS/Arch</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
