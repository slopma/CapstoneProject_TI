import React, { useState, useEffect, useRef, useCallback } from "react";
import { AwsStatusIndicator, AwsAlert } from "../cloudscape/AwsPrimitives";
import {
  dispatchUc2AgentStage,
  fetchUc2StageStatus,
  uploadBrowserFolderToStage,
} from "../../utils/uc2StageClient";

function fmtBytes(bytes) {
  const n = Number(bytes || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KiB`;
  if (n < 1073741824) return `${(n / 1048576).toFixed(1)} MiB`;
  return `${(n / 1073741824).toFixed(2)} GiB`;
}

export default function Uc2StageTransferBox({
  selectedPaths = [],
  migrationId = null,
  ec2Ip = null,
  agentId = null,
  onStageReady,
  onCopy,
}) {
  const pathsKey = (selectedPaths || []).join("|");
  const [statusData, setStatusData] = useState(null);
  const [busyMode, setBusyMode] = useState(""); // "" | "agent" | "browser"
  const [progress, setProgress] = useState(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [infoMsg, setInfoMsg] = useState("");
  const [upgradeCmd, setUpgradeCmd] = useState("");
  const folderInputRef = useRef(null);
  const pollRef = useRef(null);

  const loadStatus = useCallback(async () => {
    if (!selectedPaths || selectedPaths.length === 0) {
      setStatusData(null);
      return null;
    }
    try {
      const res = await fetchUc2StageStatus({
        migrationId,
        selectedPaths,
      });
      setStatusData(res);
      if (res?.ready && res?.stage && onStageReady) {
        onStageReady(res.stage);
      }
      return res;
    } catch {
      return null;
    }
  }, [pathsKey, migrationId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (folderInputRef.current) {
      folderInputRef.current.webkitdirectory = true;
      folderInputRef.current.directory = true;
    }
  }, [pathsKey]);

  useEffect(() => {
    loadStatus();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadStatus]);

  const handleAgentSync = async () => {
    setErrorMsg("");
    setInfoMsg("");
    setUpgradeCmd("");
    setBusyMode("agent");
    try {
      const res = await dispatchUc2AgentStage({
        selectedPaths,
        migrationId,
        agentId,
      });
      if (res.upgrade_required) {
        setUpgradeCmd(res.upgrade_command_linux || "");
        setInfoMsg(res.message || "Actualiza el agente o sube la carpeta desde el navegador.");
        setBusyMode("");
        return;
      }
      if (res.dispatched) {
        setInfoMsg("Tarea enviada al agente remoto. Empaquetando y subiendo archivos seleccionados...");
        let attempts = 0;
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = setInterval(async () => {
          attempts += 1;
          const st = await fetchUc2StageStatus({
            stageId: res.stage?.stage_id,
            migrationId,
            selectedPaths,
          }).catch(() => null);
          if (st?.ready && st?.stage) {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setStatusData(st);
            setBusyMode("");
            setInfoMsg(
              `Archivos sincronizados vía agente (${st.stage.files_count} archivos · ${fmtBytes(st.stage.bundle_size_bytes)} comprimidos).`
            );
            if (onStageReady) onStageReady(st.stage);
          } else if (attempts >= 45) {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setBusyMode("");
            setInfoMsg("El agente sigue transfiriendo en segundo plano. Pulsa 'Actualizar' en unos segundos.");
          }
        }, 3000);
      }
    } catch (err) {
      setErrorMsg(err.message);
      setBusyMode("");
    }
  };

  const handleFolderChosen = async (e) => {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;
    setErrorMsg("");
    setInfoMsg("");
    setUpgradeCmd("");
    setBusyMode("browser");
    setProgress({ phase: "preparing", uploadedFiles: 0, totalFiles: fileList.length, percent: 0 });
    try {
      const committed = await uploadBrowserFolderToStage({
        fileList,
        selectedPaths,
        migrationId,
        ec2Ip,
        onProgress: setProgress,
      });
      await loadStatus();
      const ec2Synced = committed?.ec2_sync?.ok;
      const skippedCount = (committed?.skipped_client_files || []).length;
      let msg = `Carpeta cargada a Staging AWS (${committed.files_count || 0} archivos · ${fmtBytes(committed.bundle_size_bytes)}).`;
      if (skippedCount > 0) {
        msg += ` (${skippedCount} archivo(s) >150 MiB omitidos).`;
      }
      if (ec2Ip && ec2Synced) {
        msg += ` Sincronizado en vivo hacia EC2 (${ec2Ip}).`;
      } else if (ec2Ip) {
        msg += " Ejecuta 'Terraform Apply' arriba para aplicar el paquete actualizado en EC2 y EBS.";
      }
      setInfoMsg(msg);
      if (onStageReady) onStageReady(committed);
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setBusyMode("");
      setProgress(null);
      if (folderInputRef.current) folderInputRef.current.value = "";
    }
  };

  if (!selectedPaths || selectedPaths.length === 0) {
    return null;
  }

  const readyStage = statusData?.ready ? statusData.stage : null;
  const agSupports = Boolean(statusData?.supports_file_staging);

  return (
    <div
      style={{
        marginTop: 10,
        padding: "10px 12px",
        borderRadius: 6,
        border: `1px solid ${readyStage ? "#a7f3d0" : "#cbd5e1"}`,
        backgroundColor: readyStage ? "#f6fef9" : "#f8fafc",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <AwsStatusIndicator type={readyStage ? "success" : "pending"}>
            {readyStage
              ? `Staging listo: ${readyStage.files_count} archivos reales (${fmtBytes(readyStage.bundle_size_bytes)} .tar.gz)`
              : "Contenido real pendiente de carga a Staging AWS"}
          </AwsStatusIndicator>
          {statusData?.agent_connected && (
            <span className="cm-badge neutral" style={{ fontSize: 11 }}>
              Agente {statusData.agent_hostname} v{statusData.agent_version}
            </span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <button
            type="button"
            className="cm-btn sm secondary"
            onClick={handleAgentSync}
            disabled={Boolean(busyMode)}
            title={agSupports ? "Empaquetar y subir rutas automáticamente desde el agente" : "Sincronizar vía agente (requiere v2.2+)"}
          >
            {busyMode === "agent" ? "Sincronizando agente..." : "Sincronizar vía Agente"}
          </button>

          <button
            type="button"
            className="cm-btn sm primary"
            onClick={() => folderInputRef.current && folderInputRef.current.click()}
            disabled={Boolean(busyMode)}
          >
            {busyMode === "browser" ? "Subiendo carpeta..." : "Subir carpeta local desde navegador"}
          </button>

          <input
            ref={folderInputRef}
            type="file"
            multiple
            style={{ display: "none" }}
            onChange={handleFolderChosen}
          />
        </div>
      </div>

      {progress && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 12, color: "#0972d3", fontWeight: 600 }}>
            {progress.phase === "committing"
              ? "Empaquetando bundle .tar.gz en CloudMove..."
              : `Subiendo archivos reales: ${progress.uploadedFiles}/${progress.totalFiles} (${progress.percent}%)`}
          </div>
          <div style={{ height: 6, backgroundColor: "#e2e8f0", borderRadius: 999, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${progress.percent}%`, backgroundColor: "#0972d3" }} />
          </div>
        </div>
      )}

      {upgradeCmd && (
        <AwsAlert
          type="info"
          title={`Agente actual en v${statusData?.agent_version || "2.1.0"} — Actualiza en 1 comando o usa 'Subir carpeta local desde navegador'`}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
            <code style={{ fontSize: 11.5 }}>{upgradeCmd}</code>
            {onCopy && (
              <button
                type="button"
                className="cm-btn sm secondary"
                style={{ padding: "2px 8px", fontSize: 11 }}
                onClick={() => onCopy(upgradeCmd, "Comando de actualización copiado")}
              >
                Copiar comando
              </button>
            )}
          </div>
        </AwsAlert>
      )}

      {infoMsg && <div style={{ fontSize: 12, color: "#037f0c", fontWeight: 600 }}>{infoMsg}</div>}
      {errorMsg && <div style={{ fontSize: 12, color: "#d91515", fontWeight: 600 }}>{errorMsg}</div>}
    </div>
  );
}
