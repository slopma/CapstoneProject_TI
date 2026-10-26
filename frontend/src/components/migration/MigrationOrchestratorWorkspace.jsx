import React, { useState, useEffect, useCallback } from "react";
import IaCViewer from "./IaCViewer";
import RepositoryTreeViewer from "./RepositoryTreeViewer";
import { apiFetch } from "../../utils/apiClient";

const STATE_FLOW = [
  "DRAFT",
  "DISCOVERING",
  "ASSESSED",
  "PLAN_READY",
  "APPROVED",
  "PREPARING",
  "TESTING",
  "READY_FOR_CUTOVER",
  "COMPLETED",
];

const OPERATIONAL_BADGE_MAP = {
  SIMULATED: { badgeClass: "simulated", label: "SIMULADO (Dry-Run)" },
  PLANNED: { badgeClass: "info", label: "PLANIFICADO" },
  READY_TO_EXECUTE: { badgeClass: "observed", label: "APROBADO · LISTO PARA EJECUTAR" },
  RUNNING: { badgeClass: "running", label: "EN EJECUCIÓN" },
  VALIDATED: { badgeClass: "validated", label: "VALIDADO PRE-CUTOVER" },
  BLOCKED: { badgeClass: "danger", label: "BLOQUEADO POR INCOMPATIBILIDAD" },
  FAILED: { badgeClass: "danger", label: "FALLO EN ETAPA (Recuperable)" },
  COMPLETED_IN_REAL_CLOUD: { badgeClass: "validated", label: "COMPLETADO EN NUBE REAL" },
};

function deriveOperationalStatusBadge(job) {
  if (!job) return "PLANNED";
  if (job.blockers?.length > 0 && job.state === "FAILED") return "BLOCKED";
  if (job.state === "FAILED") return "FAILED";
  if (job.state === "COMPLETED" && job.completed_in_real_cloud) return "COMPLETED_IN_REAL_CLOUD";
  if (job.state === "COMPLETED" && !job.completed_in_real_cloud) return "SIMULATED";
  if (job.state === "READY_FOR_CUTOVER") return "VALIDATED";
  if (job.state === "APPROVED") return "READY_TO_EXECUTE";
  if (["PREPARING", "TESTING", "DISCOVERING"].includes(job.state)) return "RUNNING";
  return "PLANNED";
}

const USE_CASE_CARDS = [
  {
    id: "app_source",
    title: "Caso 1 · Migración desde una Aplicación",
    subtitle:
      "Flujo guiado de 11 pasos: inspecciona código y manifiestos sin ejecución arbitraria, clasifica dependencias (confirmadas, inferidas, desconocidas), redacta secretos y genera plan de 12 etapas hacia AWS o GCP.",
    badge: "12 Etapas · App & BDs",
  },
  {
    id: "vm_image",
    title: "Caso 2 · Migración de Imagen Completa de SO / VM",
    subtitle:
      "Prioriza integridad binaria (`qemu-img`, firmas KDMV/QCOW2, GPT, SHA-256 multi-disco), evalúa las 8 dimensiones de fidelidad (preservado, modificado, no transferible) y prepara AWS MGN / VM Import o GCP Migrate to VMs.",
    badge: "13 Etapas · 8 Dimensiones",
  },
  {
    id: "datacenter_campaign",
    title: "Caso 3 · Descubrimiento y Migración de Datacenter",
    subtitle:
      "Campaña multi-sitio con jerarquía CMIR v2.1 (Datacenter → Host → Hipervisor → VM → SO → Procesos → BDs), protección de recursos compartidos y planificación por oleadas.",
    badge: "10 Etapas · Oleadas DC",
  },
];

const FIDELITY_STATUS_META = {
  preserved: { label: "PRESERVADO ÍNTEGRAMENTE", badgeClass: "observed" },
  modified_or_adapted: { label: "MODIFICADO / ADAPTADO EN DESTINO", badgeClass: "derived" },
  requires_manual_reconfiguration: { label: "REQUIERE RECONFIGURACIÓN", badgeClass: "warning" },
  not_preserved: { label: "NO TRANSFERIBLE (Limitación Física)", badgeClass: "danger" },
};

export default function MigrationOrchestratorWorkspace({
  onLoadCmirToCanvas,
  onNavigateTab,
  initialUseCase,
  initialJobId,
  onActiveJobChange,
}) {
  const [jobs, setJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);
  const [persistenceStatus, setPersistenceStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [statusBanner, setStatusBanner] = useState("");
  const [confirmAction, setConfirmAction] = useState(null); // { endpoint, body, title, description }

  // Guided Creation & Pre-Inspection State
  const [newUseCase, setNewUseCase] = useState(initialUseCase || "app_source");
  const [newProvider, setNewProvider] = useState("aws");
  const [newName, setNewName] = useState("");

  // Case 1 specific options
  const [appPreset, setAppPreset] = useState("github");
  const [customAppPath, setCustomAppPath] = useState("");
  const [deploymentMode, setDeploymentMode] = useState("container");
  const [uc1PreInspection, setUc1PreInspection] = useState(null);
  const [githubUrl, setGithubUrl] = useState("");
  const [githubRef, setGithubRef] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [githubRepoData, setGithubRepoData] = useState(null);
  const [githubTreeData, setGithubTreeData] = useState(null);
  const [githubBranches, setGithubBranches] = useState([]);
  const [validatingGithub, setValidatingGithub] = useState(false);
  const [showAdvancedGithub, setShowAdvancedGithub] = useState(false);

  // Case 2 specific options
  const [uc2SourceMode, setUc2SourceMode] = useState("file_path"); // "file_path" | "live_capture"
  const [uc2OutputFormat, setUc2OutputFormat] = useState("QCOW2");
  const [uc2TargetHost, setUc2TargetHost] = useState("local_host");
  const [imagePath, setImagePath] = useState("");
  const [imageFormatOverride, setImageFormatOverride] = useState("VMDK");
  const [consistencyStrategy, setConsistencyStrategy] = useState("quiesced_snapshot"); // "quiesced_snapshot" | "continuous_replication" | "demo_live_ram"
  const [hostDevicesData, setHostDevicesData] = useState(null);
  const [queryingDevices, setQueryingDevices] = useState(false);
  const [selectedStorageDevice, setSelectedStorageDevice] = useState("");
  const requireLiveRam = consistencyStrategy === "demo_live_ram";
  const preferContinuousReplication = consistencyStrategy === "continuous_replication";
  const [uc2PreInspection, setUc2PreInspection] = useState(null);
  const [fidelityFilter, setFidelityFilter] = useState("ALL");

  useEffect(() => {
    if (initialUseCase) {
      setNewUseCase(initialUseCase);
    }
  }, [initialUseCase]);

  const fetchPersistence = useCallback(async () => {
    try {
      const pRes = await apiFetch("/api/v1/migration/persistence/status");
      if (pRes.ok) {
        setPersistenceStatus(await pRes.json());
      }
    } catch {
      // Ignore transient error
    }
  }, []);

  const fetchJobs = useCallback(
    async (selectId = null) => {
      try {
        const res = await apiFetch("/api/v1/migration/jobs");
        if (!res.ok) return;
        const data = await res.json();
        const list = data.jobs || [];
        setJobs(list);
        const targetId = selectId || initialJobId;
        if (targetId) {
          const found = list.find((j) => j.migration_id === targetId);
          if (found) {
            setSelectedJob(found);
            if (onActiveJobChange) onActiveJobChange(found);
            return;
          }
        }
        if (list.length > 0) {
          setSelectedJob((prev) => {
            const next = prev
              ? list.find((j) => j.migration_id === prev.migration_id) || list[0]
              : list[0];
            if (onActiveJobChange) onActiveJobChange(next);
            return next;
          });
        }
      } catch {
        // Ignore network error if backend is restarting
      }
    },
    [initialJobId, onActiveJobChange]
  );

  useEffect(() => {
    fetchJobs();
    fetchPersistence();
  }, [fetchJobs, fetchPersistence]);

  // Validate GitHub repository access and list branches/tags
  const handleValidateGithub = async (overrideUrl = null, overrideToken = null) => {
    const targetUrl = (overrideUrl || githubUrl).trim();
    if (!targetUrl) {
      setErrorMsg("Introduzca una URL válida de GitHub (ej. https://github.com/owner/repo)");
      return;
    }
    setValidatingGithub(true);
    setErrorMsg("");
    setStatusBanner("");
    try {
      const activeToken = overrideToken !== null ? overrideToken : githubToken;
      const res = await apiFetch("/api/v1/migration/github/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          github_url: targetUrl,
          github_token: activeToken?.trim() || undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error al validar repositorio GitHub.");
      setGithubRepoData(data.repository);
      setGithubBranches(data.branches || []);
      setGithubTreeData(data.tree || null);
      if (data.default_branch) setGithubRef(data.default_branch);
      const treeSummary = data.tree?.summary
        ? ` · Árbol: ${data.tree.summary.total_files} archivos, ${data.tree.summary.total_directories} carpetas/subcarpetas analizadas.`
        : "";
      setStatusBanner(
        `Repositorio público '${data.repository?.full_name}' validado (${data.repository?.visibility}). Rama predeterminada: ${data.default_branch}. Lenguaje: ${data.repository?.language || "Detectado"}.${treeSummary}`
      );
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setValidatingGithub(false);
    }
  };

  const handleDeleteJob = async (migrationId) => {
    if (!window.confirm(`¿Estás seguro de eliminar el plan de migración ${migrationId}? Esta acción limpiará sus etapas y artefactos de forma permanente.`)) {
      return;
    }
    try {
      setLoading(true);
      const res = await apiFetch(`/api/v1/migration/jobs/${migrationId}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Error al eliminar el plan.");
      }
      setSelectedJob(null);
      await fetchJobs();
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleClearAllJobs = async () => {
    if (!window.confirm("¿Estás seguro de eliminar TODOS los planes de migración persistidos? Esta acción dejará el sistema completamente limpio.")) {
      return;
    }
    try {
      setLoading(true);
      const res = await apiFetch("/api/v1/migration/jobs", { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Error al limpiar los planes.");
      }
      setSelectedJob(null);
      await fetchJobs();
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleQueryLiveDevices = useCallback(async (forced = false) => {
    setQueryingDevices(true);
    try {
      const endpoint = forced
        ? "/api/v1/migration/use-case-2/probe-devices"
        : "/api/v1/migration/use-case-2/devices";
      const res = await apiFetch(endpoint, forced ? { method: "POST" } : {});
      if (res.ok) {
        const data = await res.json();
        setHostDevicesData(data);
        if (data.primary_boot_device?.path) {
          setSelectedStorageDevice(data.primary_boot_device.path);
        }
      }
    } catch {
      // Ignore transient errors
    } finally {
      setQueryingDevices(false);
    }
  }, []);

  const handleRemediateBlocker = async (migrationId, action) => {
    setLoading(true);
    setErrorMsg("");
    setStatusBanner("");
    try {
      const res = await apiFetch(`/api/v1/migration/jobs/${migrationId}/remediate-blocker`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Error al aplicar la remediación del bloqueador.");
      }
      setSelectedJob(data);
      if (onActiveJobChange) onActiveJobChange(data);
      await fetchJobs(migrationId);
      setStatusBanner(
        `Remediación técnica aplicada: ${
          action === "apply_quiesced_snapshot"
            ? "Se aplicó Snapshot Consistente Quiesced (vaciado vía sync())."
            : "Se activó Replicación Continua por Bloques."
        } El plan '${data.name}' avanzó a PLAN_READY sin bloqueadores.`
      );
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Pre-inspection handler for Case 1 (Steps 1–4 before creating or executing plan)
  const handleInspectUseCase1 = async () => {
    setLoading(true);
    setErrorMsg("");
    try {
      const payload = {
        target_provider: newProvider,
        deployment_mode: deploymentMode,
      };
      if (appPreset === "github") {
        payload.github_url = githubUrl.trim();
        payload.github_ref = githubRef.trim() || undefined;
        payload.github_token = githubToken.trim() || undefined;
      } else if (appPreset === "custom" && customAppPath.trim()) {
        payload.source_path = customAppPath.trim();
      }

      const res = await apiFetch("/api/v1/migration/use-case-1/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "No se pudo inspeccionar la aplicación.");
      setUc1PreInspection(data);
      const gitInfo = data.application?.git_metadata
        ? ` · Git Commit: ${data.application.git_metadata.short_sha}`
        : "";
      setStatusBanner(
        `Inspección estática completada para '${data.application?.app_name}'${gitInfo}: ${data.application?.dependencies?.length || 0} dependencias detectadas y ${data.application?.secrets_redacted_count || 0} secretos redactados.`
      );
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Pre-inspection handler for Case 2 (Binary header, live capture, & checksum check before plan)
  const handleInspectUseCase2 = async () => {
    const isLive = uc2SourceMode === "live_capture";
    if (!isLive && !imagePath.trim()) {
      setErrorMsg("Introduzca la ruta absoluta o relativa de la imagen de disco (.vmdk, .qcow2, .raw, .vhdx) a inspeccionar.");
      return;
    }
    setLoading(true);
    setErrorMsg("");
    try {
      const manifestOverride = isLive
        ? { format: uc2OutputFormat }
        : {
            format: imageFormatOverride,
            source_file: imagePath.trim(),
          };
      const res = await apiFetch("/api/v1/migration/use-case-2/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_path: isLive ? "live_system" : imagePath.trim(),
          manifest_override: manifestOverride,
          target_provider: newProvider,
          require_live_memory_state: requireLiveRam,
          prefer_continuous_replication: preferContinuousReplication,
          capture_live_host: isLive,
          output_format: uc2OutputFormat,
          source_type: isLive ? "live_server" : "standalone_offline_disk_image",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "No se pudo inspeccionar o capturar la imagen de SO.");
      setUc2PreInspection(data);
      if (isLive) {
        setStatusBanner(
          `Captura de SO en vivo completada exitosamente: ${data.manifest?.os?.distro || "Linux"} (${data.manifest?.name}) · Formato ${data.manifest?.format} · SHA-256 ${data.manifest?.sha256?.slice(0, 16)}...`
        );
      } else {
        setStatusBanner(
          `Verificación binaria completada para '${data.manifest?.name || imagePath}': formato ${data.manifest?.binary_inspection?.detected_binary_format || imageFormatOverride} · SHA-256 ${data.manifest?.sha256?.slice(0, 16)}...`
        );
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateMigration = async () => {
    setLoading(true);
    setErrorMsg("");
    setStatusBanner("");
    try {
      const sourceConfig = {};
      if (newUseCase === "app_source") {
        sourceConfig.deployment_mode = deploymentMode;
        if (appPreset === "github") {
          if (!githubUrl.trim()) {
            throw new Error("Por favor introduzca el enlace público del repositorio GitHub a migrar.");
          }
          sourceConfig.github_url = githubUrl.trim();
          sourceConfig.github_ref = githubRef.trim() || undefined;
          sourceConfig.github_token = githubToken.trim() || undefined;
        } else if (appPreset === "custom" && customAppPath.trim()) {
          sourceConfig.source_path = customAppPath.trim();
        }
      } else if (newUseCase === "vm_image") {
        const isLive = uc2SourceMode === "live_capture";
        if (!isLive && !imagePath.trim()) {
          throw new Error("Por favor introduzca la ruta de la imagen de disco a migrar.");
        }
        sourceConfig.image_path = isLive
          ? (uc2PreInspection?.manifest?.source_file || "live_system")
          : imagePath.trim();
        sourceConfig.manifest_override = isLive
          ? { format: uc2OutputFormat }
          : {
              format: imageFormatOverride,
              source_file: imagePath.trim(),
            };
        sourceConfig.require_live_memory_state = requireLiveRam;
        sourceConfig.prefer_continuous_replication = preferContinuousReplication;
        sourceConfig.capture_live_host = isLive;
        sourceConfig.source_type = isLive ? "live_server" : "standalone_offline_disk_image";
        sourceConfig.output_format = uc2OutputFormat;
      }

      let planName = newName.trim();
      if (!planName) {
        if (newUseCase === "app_source" && appPreset === "github" && githubUrl.trim()) {
          const repoName = githubUrl.trim().replace(/\.git$/, "").split("/").pop() || "app";
          planName = `Migración ${repoName} → ${newProvider.toUpperCase()}`;
        } else if (newUseCase === "app_source") {
          planName = `Migración Aplicación → ${newProvider.toUpperCase()}`;
        } else if (newUseCase === "vm_image" && uc2SourceMode === "live_capture") {
          planName = `Migración SO Host en Vivo (${uc2PreInspection?.manifest?.name || "Local"}) → ${newProvider.toUpperCase()}`;
        } else if (newUseCase === "vm_image" && imagePath.trim()) {
          const imgName = imagePath.trim().split("/").pop() || "disco";
          planName = `Migración Imagen ${imgName} → ${newProvider.toUpperCase()}`;
        } else if (newUseCase === "vm_image") {
          planName = `Importación Imagen VM → ${newProvider.toUpperCase()}`;
        } else {
          planName = `Campaña Datacenter → ${newProvider.toUpperCase()}`;
        }
      }

      const res = await apiFetch("/api/v1/migration/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: planName,
          use_case: newUseCase,
          target_provider: newProvider,
          source_config: sourceConfig,
          auto_assess_and_plan: true,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error al crear el plan de migración.");
      setSelectedJob(data);
      if (onActiveJobChange) onActiveJobChange(data);
      setNewName("");
      await fetchJobs(data.migration_id);
      await fetchPersistence();
      setStatusBanner(
        `Plan de migración '${data.name}' generado y persistido en BD transaccional (v${data.version || 1}) en estado ${data.state}.`
      );
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleAction = async (endpoint, body = {}, successText = "") => {
    if (!selectedJob) return;
    setLoading(true);
    setErrorMsg("");
    setStatusBanner("");
    setConfirmAction(null);
    try {
      const res = await apiFetch(
        `/api/v1/migration/jobs/${selectedJob.migration_id}/${endpoint}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...body,
            expected_version: selectedJob.version,
          }),
        }
      );
      const data = await res.json();
      if (!res.ok) {
        const msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
        throw new Error(msg || `Error en operación ${endpoint}`);
      }
      setSelectedJob(data);
      if (onActiveJobChange) onActiveJobChange(data);
      await fetchJobs(data.migration_id);
      await fetchPersistence();
      setStatusBanner(
        successText || `Estado actualizado a ${data.state} (Versión transaccional v${data.version}).`
      );
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadJobReport = () => {
    if (!selectedJob) return;
    const blob = new Blob([JSON.stringify(selectedJob, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cloudmove-migration-report-${selectedJob.migration_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDownloadZipBundle = () => {
    if (!selectedJob) return;
    const downloadUrl = `/api/v1/migration/jobs/${selectedJob.migration_id}/bundle.zip`;
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `cloudmove-${selectedJob.use_case}-${selectedJob.target_provider}-${selectedJob.migration_id}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleDownloadSystemImage = () => {
    if (!selectedJob) return;
    const downloadUrl = `/api/v1/migration/jobs/${selectedJob.migration_id}/system-image`;
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `system_image_snapshot_${selectedJob.name || "host"}.tar.gz`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleDownloadDiskImage = (format = "qcow2") => {
    if (!selectedJob) return;
    const downloadUrl = `/api/v1/migration/jobs/${selectedJob.migration_id}/disk-image?format=${format}`;
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `${selectedJob.name || "disk"}.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleDownloadHypervisorScript = (hypervisor = "virtualbox") => {
    if (!selectedJob) return;
    const downloadUrl = `/api/v1/migration/jobs/${selectedJob.migration_id}/hypervisor-script?hypervisor=${hypervisor}`;
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `launch_${hypervisor}_${selectedJob.name || "vm"}.sh`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleDownloadFile = (fileName, fileContent) => {
    if (!fileContent) return;
    const blob = new Blob([fileContent], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const currentJob = selectedJob;
  const cmirResources = currentJob?.cmir?.resources || [];
  const srcEnv = currentJob?.source_environment || {};
  const fidelityDims = currentJob?.compatibility_assessment?.fidelity_dimensions || null;
  const diffReport = currentJob?.generated_artifacts?.diff_report || null;
  const envVars = srcEnv.environment_variables || [];
  const appDependencies = srcEnv.dependencies || [];
  const appAssumptions = srcEnv.assumptions || [];
  const binaryInspection = srcEnv.binary_inspection || null;
  const disks = srcEnv.disks || [];
  const stagingVerification = srcEnv.staging_verification || null;
  const tfValidation = currentJob?.generated_artifacts?.validation || null;
  const preCutover = currentJob?.pre_cutover_test_results || null;
  const postCutover = currentJob?.post_cutover_validation_results || null;
  const opBadgeKey = deriveOperationalStatusBadge(currentJob);
  const opBadge = OPERATIONAL_BADGE_MAP[opBadgeKey] || OPERATIONAL_BADGE_MAP.PLANNED;

  const stateIndex = currentJob ? STATE_FLOW.indexOf(currentJob.state) : -1;

  return (
    <div className="tab-pane-view">
      {/* Cabecera de Página */}
      <div className="cm-page-header">
        <div>
          <h2 className="cm-page-title">
            Orquestador Unificado de Migraciones y Planes (AWS · GCP)
          </h2>
          <p className="cm-page-subtitle">
            Flujos guiados para migración desde aplicación (Caso 1), imagen completa de SO/VM (Caso 2) y campañas de datacenter (Caso 3) con máquina de estados transaccional, validación Terraform CLI y diferenciación estricta entre simulación Dry-Run y nube real.
          </p>
        </div>
        <div className="cm-header-badges" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {persistenceStatus && (
            <span className="cm-badge observed">
              BD Transaccional: {persistenceStatus.engine?.toUpperCase()} ({persistenceStatus.journal_mode?.toUpperCase()}) · Esquema v{persistenceStatus.current_schema_version}
            </span>
          )}
          <span className="cm-badge aws">AWS Soportado</span>
          <span className="cm-badge gcp">GCP Soportado</span>
          <button
            type="button"
            className="cm-btn sm danger"
            onClick={handleClearAllJobs}
            style={{ fontSize: 11, padding: "3px 10px" }}
            title="Eliminar planes persistidos, imágenes en staging e iniciar el orquestador desde 0"
          >
            Limpiar Planes e Imágenes (Iniciar desde 0)
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="cm-alert error" role="alert" style={{ marginBottom: 16 }}>
          <div>
            <strong>Diagnóstico de Bloqueo / Error Operativo:</strong> {errorMsg}
          </div>
          {(errorMsg.includes("require_live_memory_state") || errorMsg.includes("memoria RAM")) && selectedJob && (
            <div
              style={{
                marginTop: 10,
                padding: 12,
                backgroundColor: "#ffffff",
                borderRadius: 6,
                border: "1px solid #f87171",
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 13, color: "#991b1b", marginBottom: 6 }}>
                Remediación Inmediata del Bloqueador Técnico de Hipervisor:
              </div>
              <p style={{ margin: "0 0 10px 0", fontSize: 12, color: "#374151", lineHeight: 1.45 }}>
                La migración de imágenes hacia AWS VM Import o GCP Image Import transfiere el estado persistente en disco tras un snapshot consistente (quiesce + sync), NO la memoria RAM volátil ni los sockets TCP abiertos. Selecciona una acción para avanzar a <strong>PLAN_READY</strong>:
              </p>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="cm-btn primary sm"
                  onClick={() => handleRemediateBlocker(selectedJob.migration_id, "apply_quiesced_snapshot")}
                  disabled={loading}
                >
                  Aplicar Snapshot Consistente Quiesced (Recomendado)
                </button>
                <button
                  type="button"
                  className="cm-btn secondary sm"
                  onClick={() => handleRemediateBlocker(selectedJob.migration_id, "switch_continuous_replication")}
                  disabled={loading}
                >
                  Cambiar a Replicación Continua por Bloques (AWS MGN / GCP)
                </button>
              </div>
            </div>
          )}
        </div>
      )}
      {statusBanner && (
        <div className="cm-alert success" role="status" style={{ marginBottom: 16 }}>
          <strong>Orquestador CloudMove:</strong> {statusBanner}
        </div>
      )}

      {/* Paso 1: Selector de Caso de Uso y Asistente Guiado */}
      <div className="cm-card" style={{ marginBottom: 20 }}>
        <div className="cm-card-title">
          <span>1. Seleccionar Caso de Uso y Configurar Origen / Destino Cloud</span>
          <span className="cm-badge info">Asistente Guiado por Objetivo</span>
        </div>

        <div className="cm-selector-grid" style={{ marginBottom: 16 }}>
          {USE_CASE_CARDS.map((uc) => {
            const isSelected = newUseCase === uc.id;
            return (
              <button
                key={uc.id}
                type="button"
                onClick={() => setNewUseCase(uc.id)}
                className={`cm-selector-card ${isSelected ? "selected" : ""}`}
                aria-pressed={isSelected}
              >
                <div>
                  <div className="cm-selector-card-top">
                    <span className="cm-selector-card-title">{uc.title}</span>
                    <span className="cm-badge info">{uc.badge}</span>
                  </div>
                  <div className="cm-selector-card-desc">{uc.subtitle}</div>
                </div>
              </button>
            );
          })}
        </div>

        {/* Formulario Contextual Agrupado por Caso de Uso */}
        <div className="cm-card-subtle">
          <div className="cm-form-grid">
            <div className="cm-field">
              <label htmlFor="mig-name-input" className="cm-label">
                Nombre identificador del plan
              </label>
              <input
                id="mig-name-input"
                type="text"
                className="cm-input"
                placeholder={
                  newUseCase === "app_source"
                    ? "Ej. Migración de Aplicación → AWS"
                    : newUseCase === "vm_image"
                    ? "Ej. Importación Debian 12 ERP VMDK → AWS"
                    : "Ej. Oleada Datacenter Principal → GCP"
                }
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </div>

            <div className="cm-field">
              <label htmlFor="mig-provider-select" className="cm-label">
                Proveedor Cloud Destino (ADR-001)
              </label>
              <select
                id="mig-provider-select"
                className="cm-select"
                value={newProvider}
                onChange={(e) => setNewProvider(e.target.value)}
              >
                <option value="aws">Amazon Web Services (AWS — EC2 / ECS / RDS / MGN)</option>
                <option value="gcp">Google Cloud Platform (GCP — GCE / Cloud Run / Cloud SQL)</option>
              </select>
            </div>
          </div>

          {/* =================================================================
              SECCIÓN DEDICADA CASO 1: ADJUNTAR REPOSITORIO GITHUB (ENLACE PÚBLICO)
              ================================================================= */}
          {newUseCase === "app_source" && (
            <div style={{ marginTop: 16 }}>
              {/* Selector de Modo de Origen */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)" }}>
                  Origen de la Aplicación a Descubrir:
                </span>
                <div style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className={`cm-btn ${appPreset === "github" ? "primary" : "secondary"} sm`}
                    onClick={() => setAppPreset("github")}
                    style={{ fontWeight: 600 }}
                  >
                    Repositorio GitHub (Enlace Público)
                  </button>
                  <button
                    type="button"
                    className={`cm-btn ${appPreset === "custom" ? "primary" : "secondary"} sm`}
                    onClick={() => setAppPreset("custom")}
                  >
                    Directorio Local en Servidor
                  </button>
                </div>
              </div>

              {/* Contenedor Principal: Adjuntar Repositorio GitHub por Enlace Público */}
              {appPreset === "github" && (
                <div
                  className="cm-card"
                  style={{
                    backgroundColor: "#f8faff",
                    border: "2px solid #3b82f6",
                    borderRadius: 8,
                    padding: "16px 20px",
                    boxShadow: "0 1px 3px rgba(0, 0, 0, 0.05)",
                    marginBottom: 16,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span className="cm-badge" style={{ backgroundColor: "#1e3a8a", color: "#ffffff", fontWeight: 700, fontSize: 10 }}>GIT</span>
                        <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#1e3a8a" }}>
                          Adjuntar Repositorio GitHub por Enlace Público
                        </h4>
                        <span
                          className="cm-badge"
                          style={{
                            backgroundColor: "#dcfce7",
                            color: "#166534",
                            border: "1px solid #86efac",
                            fontSize: 11,
                            fontWeight: 700,
                          }}
                        >
                          Enlace Público (Sin Credenciales)
                        </span>
                      </div>
                      <p style={{ margin: "4px 0 0 0", fontSize: 12, color: "#475569", lineHeight: 1.45 }}>
                        Ingresa el enlace público de cualquier repositorio GitHub. CloudMove validará el acceso al repositorio, resolverá y fijará el commit SHA inmutable, analizará runtimes, puertos y dependencias en un sandbox efímero aislado, redactará secretos y generará la plantilla IaC de Terraform para {newProvider.toUpperCase()}.
                      </p>
                    </div>
                  </div>

                  {/* Campo de URL Pública y Botón de Validación */}
                  <div className="cm-field" style={{ marginBottom: 12 }}>
                    <label htmlFor="uc1-github-url" className="cm-label" style={{ fontWeight: 600, color: "#1e293b" }}>
                      Enlace Público del Repositorio GitHub *
                    </label>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <input
                        id="uc1-github-url"
                        type="text"
                        className="cm-input"
                        placeholder="https://github.com/usuario/repositorio (ej. https://github.com/fastapi/fastapi)"
                        value={githubUrl}
                        onChange={(e) => {
                          setGithubUrl(e.target.value);
                          setGithubRepoData(null);
                          setGithubTreeData(null);
                        }}
                        style={{ flex: "1 1 380px", fontSize: 13, backgroundColor: "#ffffff" }}
                      />
                      <button
                        type="button"
                        className="cm-btn primary"
                        onClick={() => handleValidateGithub()}
                        disabled={validatingGithub || !githubUrl.trim()}
                        style={{ whiteSpace: "nowrap", minWidth: 150 }}
                      >
                        {validatingGithub ? "Validando en GitHub..." : "Validar Enlace Público"}
                      </button>
                    </div>
                    <div style={{ fontSize: 11.5, color: "#475569", marginTop: 4 }}>
                      <span><strong>Acceso a repositorios públicos:</strong> No requiere autenticación, contraseñas ni permisos especiales.</span>
                    </div>
                  </div>

                  {/* Resumen de Repositorio Validado */}
                  {githubRepoData && (
                    <div
                      style={{
                        padding: "12px 14px",
                        backgroundColor: "#ffffff",
                        border: "1px solid #86efac",
                        borderRadius: 6,
                        marginBottom: 14,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 4 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ fontWeight: 700, fontSize: 13.5, color: "#1e3a8a" }}>
                            {githubRepoData.full_name}
                          </span>
                          <span
                            className="cm-badge"
                            style={{
                              backgroundColor: githubRepoData.visibility === "public" ? "#dcfce7" : "#fef3c7",
                              color: githubRepoData.visibility === "public" ? "#166534" : "#92400e",
                              fontSize: 10,
                              fontWeight: 700,
                              textTransform: "uppercase",
                            }}
                          >
                            Repositorio {githubRepoData.visibility}
                          </span>
                          {githubRepoData.language && (
                            <span className="cm-badge" style={{ backgroundColor: "#f1f5f9", color: "#334155", fontSize: 10.5 }}>
                              {githubRepoData.language}
                            </span>
                          )}
                        </div>
                        <a
                          href={githubRepoData.html_url || githubUrl}
                          target="_blank"
                          rel="noreferrer"
                          style={{ fontSize: 11.5, color: "#2563eb", textDecoration: "none" }}
                        >
                          Abrir en GitHub ↗
                        </a>
                      </div>
                      {githubRepoData.description && (
                        <p style={{ margin: "2px 0 6px 0", fontSize: 12, color: "#475569" }}>
                          {githubRepoData.description}
                        </p>
                      )}
                      <div style={{ fontSize: 11.5, color: "#64748b" }}>
                        Rama predeterminada: <strong><code>{githubRepoData.default_branch}</code></strong> · Estrellas: <strong>{githubRepoData.stars_count ?? 0}</strong>
                      </div>
                      {githubTreeData && (
                        <RepositoryTreeViewer
                          treeData={githubTreeData}
                          title={`Estructura de Carpetas y Archivos en '${githubRepoData.full_name}'`}
                          defaultOpen={true}
                        />
                      )}
                    </div>
                  )}

                  {/* Configuración de Rama / Commit y Estrategia de Despliegue */}
                  <div className="cm-form-grid" style={{ marginBottom: 10 }}>
                    <div className="cm-field">
                      <label htmlFor="uc1-github-ref" className="cm-label">
                        Rama, Tag o Commit SHA a Fijar e Inspeccionar
                      </label>
                      {githubBranches.length > 0 ? (
                        <select
                          id="uc1-github-ref"
                          className="cm-select"
                          value={githubRef}
                          onChange={(e) => setGithubRef(e.target.value)}
                          style={{ backgroundColor: "#ffffff" }}
                        >
                          {githubBranches.map((b) => (
                            <option key={b.name} value={b.name}>
                              {b.name} {b.commit_sha ? `(SHA: ${b.commit_sha.slice(0, 8)})` : ""}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          id="uc1-github-ref"
                          type="text"
                          className="cm-input"
                          placeholder="main | master | v1.0.0 | commit_sha"
                          value={githubRef}
                          onChange={(e) => setGithubRef(e.target.value)}
                          style={{ backgroundColor: "#ffffff" }}
                        />
                      )}
                      <span className="cm-hint">Fijación inmutable de commit SHA para evitar cualquier desvío de código.</span>
                    </div>

                    <div className="cm-field">
                      <label htmlFor="uc1-deploy-mode" className="cm-label">
                        Estrategia de Despliegue en Destino
                      </label>
                      <select
                        id="uc1-deploy-mode"
                        className="cm-select"
                        value={deploymentMode}
                        onChange={(e) => setDeploymentMode(e.target.value)}
                        style={{ backgroundColor: "#ffffff" }}
                      >
                        <option value="container">
                          Contenedor Administrado ({newProvider === "gcp" ? "GCP Cloud Run v2" : "AWS ECS Fargate"})
                        </option>
                        <option value="vm_rehost">
                          Rehost en VM ({newProvider === "gcp" ? "GCP Compute Engine" : "AWS EC2"})
                        </option>
                      </select>
                      <span className="cm-hint">Determina la plantilla IaC generada para el proveedor seleccionado.</span>
                    </div>
                  </div>

                  {/* Opcional: Acordeón para Repositorios Privados o Token PAT */}
                  <div>
                    <button
                      type="button"
                      onClick={() => setShowAdvancedGithub((v) => !v)}
                      style={{
                        background: "none",
                        border: "none",
                        color: "#2563eb",
                        fontSize: 12,
                        cursor: "pointer",
                        padding: 0,
                        textDecoration: "underline",
                      }}
                    >
                      {showAdvancedGithub
                        ? "▲ Ocultar configuración de autenticación opcional"
                        : "▼ ¿El repositorio es privado o requieres elevar la cuota de la API de GitHub?"}
                    </button>
                    {showAdvancedGithub && (
                      <div className="cm-field" style={{ marginTop: 8 }}>
                        <label htmlFor="uc1-github-token" className="cm-label">
                          Personal Access Token (PAT) de GitHub (Opcional)
                        </label>
                        <input
                          id="uc1-github-token"
                          type="password"
                          className="cm-input"
                          placeholder="ghp_•••••••••••••••• (Dejar vacío para enlaces públicos)"
                          value={githubToken}
                          onChange={(e) => setGithubToken(e.target.value)}
                          autoComplete="off"
                          style={{ backgroundColor: "#ffffff" }}
                        />
                        <span className="cm-hint">Para repositorios públicos no se requiere token. CloudMove no almacena credenciales en el repositorio.</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Modo Ruta Personalizada */}
              {appPreset === "custom" && (
                <div className="cm-card-subtle" style={{ padding: 14, marginBottom: 16 }}>
                  <div className="cm-field" style={{ marginBottom: 10 }}>
                    <label htmlFor="uc1-custom-path" className="cm-label">
                      Ruta local del directorio de la aplicación en el servidor
                    </label>
                    <input
                      id="uc1-custom-path"
                      type="text"
                      className="cm-input"
                      placeholder="/ruta/a/codigo_fuente"
                      value={customAppPath}
                      onChange={(e) => setCustomAppPath(e.target.value)}
                    />
                  </div>
                  <div className="cm-field">
                    <label htmlFor="uc1-deploy-mode-custom" className="cm-label">
                      Estrategia de Despliegue en Destino
                    </label>
                    <select
                      id="uc1-deploy-mode-custom"
                      className="cm-select"
                      value={deploymentMode}
                      onChange={(e) => setDeploymentMode(e.target.value)}
                    >
                      <option value="container">
                        Contenedor Administrado ({newProvider === "gcp" ? "GCP Cloud Run v2" : "AWS ECS Fargate"})
                      </option>
                      <option value="vm_rehost">
                        Rehost en VM ({newProvider === "gcp" ? "GCP Compute Engine" : "AWS EC2"})
                      </option>
                    </select>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Controles específicos del Caso 2 */}
          {newUseCase === "vm_image" && (
            <div
              className="cm-card"
              style={{
                backgroundColor: "#f0fdf4",
                border: "2px solid #16a34a",
                borderRadius: 8,
                padding: "16px 20px",
                boxShadow: "0 1px 3px rgba(0, 0, 0, 0.05)",
                marginTop: 14,
                marginBottom: 16,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
                <div style={{ flex: "1 1 320px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span className="cm-badge" style={{ backgroundColor: "#14532d", color: "#ffffff", fontWeight: 700, fontSize: 10 }}>IMG / OS</span>
                    <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#14532d" }}>
                      Caso 2 · Migración de Imagen de Sistema Operativo / Máquina Virtual
                    </h4>
                    <span
                      className="cm-badge"
                      style={{
                        backgroundColor: uc2SourceMode === "live_capture" ? "#dcfce7" : "#e0f2fe",
                        color: uc2SourceMode === "live_capture" ? "#166534" : "#0369a1",
                        border: `1px solid ${uc2SourceMode === "live_capture" ? "#86efac" : "#7dd3fc"}`,
                        fontSize: 11,
                        fontWeight: 700,
                      }}
                    >
                      {uc2SourceMode === "live_capture" ? "Captura en Vivo Activa" : "Modo Archivo de Disco"}
                    </span>
                  </div>
                  <p style={{ margin: "4px 0 0 0", fontSize: 12, color: "#475569", lineHeight: 1.45 }}>
                    {uc2SourceMode === "live_capture"
                      ? `CloudMove captura el sistema operativo en vivo donde se ejecuta: archivos guardados, configuración /etc, fstab, servicios systemd, paquetes y kernel, generando una imagen de disco (QCOW2/RAW) lista para aprovisionar y montar como VM en ${newProvider.toUpperCase()}.`
                      : `Ingresa la ruta de cualquier archivo de imagen de disco en el sistema (.vmdk, .qcow2, .raw, .vhdx). El analizador ejecutará qemu-img info en modo seguro de solo lectura para inspeccionar las cabeceras binarias reales, verificar particionado GPT/MBR, calcular SHA-256 y evaluar compatibilidad hacia ${newProvider.toUpperCase()}.`}
                  </p>
                </div>

                {/* Selector de Modalidad */}
                <div style={{ display: "flex", gap: 6, backgroundColor: "#e2e8f0", padding: 3, borderRadius: 6, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    onClick={() => {
                      setUc2SourceMode("live_capture");
                      setUc2PreInspection(null);
                    }}
                    style={{
                      border: "none",
                      backgroundColor: uc2SourceMode === "live_capture" ? "#ffffff" : "transparent",
                      color: uc2SourceMode === "live_capture" ? "#166534" : "#64748b",
                      fontWeight: uc2SourceMode === "live_capture" ? 700 : 500,
                      padding: "6px 12px",
                      borderRadius: 4,
                      cursor: "pointer",
                      fontSize: 12,
                      boxShadow: uc2SourceMode === "live_capture" ? "0 1px 2px rgba(0,0,0,0.1)" : "none",
                    }}
                  >
                    Capturar SO del Host en Vivo
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setUc2SourceMode("file_path");
                      setUc2PreInspection(null);
                    }}
                    style={{
                      border: "none",
                      backgroundColor: uc2SourceMode === "file_path" ? "#ffffff" : "transparent",
                      color: uc2SourceMode === "file_path" ? "#166534" : "#64748b",
                      fontWeight: uc2SourceMode === "file_path" ? 700 : 500,
                      padding: "6px 12px",
                      borderRadius: 4,
                      cursor: "pointer",
                      fontSize: 12,
                      boxShadow: uc2SourceMode === "file_path" ? "0 1px 2px rgba(0,0,0,0.1)" : "none",
                    }}
                  >
                    Inspeccionar Archivo de Disco (.vmdk, .qcow2, .raw)
                  </button>
                </div>
              </div>

              {uc2SourceMode === "live_capture" ? (
                <div style={{ marginBottom: 14 }}>
                  {/* Panel de Consulta en Vivo de Dispositivos de Almacenamiento */}
                  <div
                    style={{
                      padding: "14px 16px",
                      backgroundColor: "#ffffff",
                      border: "1px solid #86efac",
                      borderRadius: 8,
                      marginBottom: 14,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 10 }}>
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span className="cm-badge" style={{ backgroundColor: "#14532d", color: "#ffffff", fontSize: 10, fontWeight: 700 }}>DISCOS REALES</span>
                          <span style={{ fontWeight: 700, fontSize: 13.5, color: "#14532d" }}>
                            Dispositivos y Particiones del Host Detectados en Vivo
                          </span>
                          {hostDevicesData?.queried_at && (
                            <span className="cm-badge observed" style={{ fontSize: 10 }}>
                              Consulta Ejecutada: {new Date(hostDevicesData.queried_at).toLocaleTimeString()} · Sin Datos Precargados
                            </span>
                          )}
                        </div>
                        <p style={{ margin: "3px 0 0 0", fontSize: 12, color: "#475569" }}>
                          CloudMove ejecuta <code>lsblk</code> y consultas directas al subsistema de archivos para relevar el disco físico y particiones donde corre la aplicación.
                        </p>
                      </div>

                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <button
                          type="button"
                          className="cm-btn secondary sm"
                          onClick={() => handleQueryLiveDevices(true)}
                          disabled={queryingDevices}
                          style={{ whiteSpace: "nowrap" }}
                        >
                          {queryingDevices
                            ? "Consultando lsblk..."
                            : hostDevicesData
                            ? "Re-consultar Dispositivos"
                            : "Consultar Dispositivos del Equipo en Vivo"}
                        </button>
                        {hostDevicesData && (
                          <button
                            type="button"
                            className="cm-btn sm"
                            onClick={() => {
                              setHostDevicesData(null);
                              setSelectedStorageDevice("");
                            }}
                            style={{ fontSize: 11, padding: "4px 8px" }}
                            title="Limpiar datos detectados del host"
                          >
                            Limpiar Consulta
                          </button>
                        )}
                      </div>
                    </div>

                    {hostDevicesData?.host && (
                      <div
                        style={{
                          backgroundColor: "#f8fafc",
                          border: "1px solid #e2e8f0",
                          borderRadius: 6,
                          padding: "8px 12px",
                          marginBottom: 10,
                          fontSize: 12,
                          color: "#334155",
                          display: "flex",
                          flexWrap: "wrap",
                          gap: 16,
                        }}
                      >
                        <div>Host: <strong><code>{hostDevicesData.host.hostname}</code></strong></div>
                        <div>Distribución: <strong>{hostDevicesData.host.distro}</strong> ({hostDevicesData.host.version})</div>
                        <div>Kernel: <strong><code>{hostDevicesData.host.kernel}</code></strong></div>
                        <div>Arranque: <strong>{hostDevicesData.host.boot_mode} ({hostDevicesData.host.partition_scheme})</strong></div>
                        <div>Memoria RAM: <strong>{hostDevicesData.host.ram_total_gib} GiB</strong> (Libre: {hostDevicesData.host.ram_free_gib} GiB)</div>
                      </div>
                    )}

                    {/* Lista de Dispositivos de Bloque Reales */}
                    {hostDevicesData?.devices?.length > 0 ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {hostDevicesData.devices.map((dev) => {
                          const isPrimary = dev.is_boot_device || dev.path === selectedStorageDevice;
                          return (
                            <div
                              key={dev.name}
                              style={{
                                border: `1.5px solid ${isPrimary ? "#16a34a" : "#cbd5e1"}`,
                                borderRadius: 6,
                                padding: "10px 12px",
                                backgroundColor: isPrimary ? "#f0fdf4" : "#ffffff",
                              }}
                            >
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                  <input
                                    type="radio"
                                    id={`dev-${dev.name}`}
                                    name="selected_device"
                                    checked={selectedStorageDevice === dev.path || (!selectedStorageDevice && isPrimary)}
                                    onChange={() => setSelectedStorageDevice(dev.path)}
                                    style={{ cursor: "pointer" }}
                                  />
                                  <label htmlFor={`dev-${dev.name}`} style={{ cursor: "pointer", fontWeight: 700, fontSize: 13, color: "#1e293b" }}>
                                    <code>{dev.path}</code> ({dev.model})
                                  </label>
                                  <span className="cm-badge" style={{ backgroundColor: "#e2e8f0", color: "#334155", fontSize: 10.5 }}>
                                    {dev.size_gib} GiB · {dev.type?.toUpperCase()}
                                  </span>
                                  {dev.is_boot_device && (
                                    <span className="cm-badge observed" style={{ fontSize: 10 }}>
                                      Disco de Arranque Principal
                                    </span>
                                  )}
                                </div>
                              </div>

                              {/* Particiones del Dispositivo */}
                              {dev.partitions?.length > 0 && (
                                <div style={{ marginTop: 8, paddingLeft: 22, display: "flex", flexDirection: "column", gap: 4 }}>
                                  {dev.partitions.map((p) => (
                                    <div
                                      key={p.name}
                                      style={{
                                        fontSize: 11.5,
                                        color: "#475569",
                                        backgroundColor: "#f8fafc",
                                        padding: "4px 8px",
                                        borderRadius: 4,
                                        display: "flex",
                                        justifyContent: "space-between",
                                        alignItems: "center",
                                        flexWrap: "wrap",
                                        gap: 6,
                                      }}
                                    >
                                      <div>
                                        <strong><code>{p.path}</code></strong>
                                        {p.mount_point && <span> montada en <strong><code>{p.mount_point}</code></strong></span>}
                                        <span style={{ color: "#64748b" }}> ({p.filesystem})</span>
                                        {p.uuid && <span style={{ color: "#94a3b8" }}> · UUID: {p.uuid}</span>}
                                      </div>
                                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                                        <span>{p.size_gib} GiB</span>
                                        {p.mount_point === "/" && (
                                          <span className="cm-badge" style={{ backgroundColor: "#dbeafe", color: "#1e40af", fontSize: 10 }}>
                                            Espacio Utilizado: {p.used_gib} GiB ({p.usage_percent}%)
                                          </span>
                                        )}
                                        {p.is_boot && (
                                          <span className="cm-badge" style={{ backgroundColor: "#dcfce7", color: "#166534", fontSize: 10 }}>
                                            Partición de Arranque ESP
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div style={{ fontSize: 12.5, color: "#64748b", padding: "16px 12px", textAlign: "center", backgroundColor: "#f8fafc", borderRadius: 6, border: "1px dashed #cbd5e1" }}>
                        {queryingDevices
                          ? "Ejecutando consulta de hardware en tiempo real con lsblk..."
                          : "Sin datos precargados. Haz clic en 'Consultar Dispositivos del Equipo en Vivo' para escanear el subsistema de almacenamiento de este equipo en tiempo real."}
                      </div>
                    )}
                  </div>

                  {/* Formato de Salida */}
                  <div className="cm-field">
                    <label className="cm-label" style={{ fontWeight: 600, color: "#1e293b" }}>
                      Formato de Imagen de Disco de Salida para la Nube
                    </label>
                    <select
                      className="cm-select"
                      value={uc2OutputFormat}
                      onChange={(e) => setUc2OutputFormat(e.target.value)}
                      style={{ backgroundColor: "#ffffff" }}
                    >
                      <option value="QCOW2">QCOW2 (Recomendado para KVM/GCP y Staging Optimizado)</option>
                      <option value="RAW">RAW (Recomendado para AWS VM Import / EBS)</option>
                      <option value="VMDK">VMDK (Compatible VMware)</option>
                    </select>
                    <span className="cm-hint">
                      Crea la imagen con <code>qemu-img</code> y empaqueta la configuración <code>/etc</code> (fstab, red, host) en <code>os_config_bundle.tar.gz</code>.
                    </span>
                  </div>
                </div>
              ) : (
                <div className="cm-form-grid" style={{ marginBottom: 12 }}>
                  <div className="cm-field">
                    <label htmlFor="uc2-image-path" className="cm-label" style={{ fontWeight: 600, color: "#1e293b" }}>
                      Ruta del Archivo de Imagen de Disco / SO *
                    </label>
                    <input
                      id="uc2-image-path"
                      type="text"
                      className="cm-input"
                      placeholder="Ej. /var/lib/libvirt/images/servidor.qcow2 o ./disk.vmdk"
                      value={imagePath}
                      onChange={(e) => {
                        setImagePath(e.target.value);
                        setUc2PreInspection(null);
                        const ext = e.target.value.split(".").pop()?.toUpperCase();
                        if (["VMDK", "QCOW2", "RAW", "VHDX", "OVA"].includes(ext)) {
                          setImageFormatOverride(ext);
                        }
                      }}
                      style={{ backgroundColor: "#ffffff" }}
                    />
                    <span className="cm-hint">Soporta formatos VMDK (VMware), QCOW2 (KVM/Proxmox), VHDX (Hyper-V) y RAW.</span>
                  </div>

                  <div className="cm-field">
                    <label htmlFor="uc2-format-select" className="cm-label" style={{ fontWeight: 600, color: "#1e293b" }}>
                      Formato de Imagen Declarado
                    </label>
                    <select
                      id="uc2-format-select"
                      className="cm-select"
                      value={imageFormatOverride}
                      onChange={(e) => setImageFormatOverride(e.target.value)}
                      style={{ backgroundColor: "#ffffff" }}
                    >
                      <option value="VMDK">VMDK (VMware Sparse / StreamOptimized)</option>
                      <option value="QCOW2">QCOW2 (KVM / Proxmox — Conversión automática)</option>
                      <option value="VHDX">VHDX (Microsoft Hyper-V)</option>
                      <option value="RAW">RAW Disk Image</option>
                      <option value="OVA">OVA Appliance</option>
                    </select>
                    <span className="cm-hint">La cabecera binaria real se validará contra este formato.</span>
                  </div>
                </div>
              )}

              {/* Estrategia de Consistencia de Datos y Transferencia */}
              <div
                style={{
                  marginTop: 12,
                  padding: "12px 14px",
                  backgroundColor: "#ffffff",
                  borderRadius: 6,
                  border: "1px solid #cbd5e1",
                }}
              >
                <div style={{ fontWeight: 700, fontSize: 13, color: "#1e293b", marginBottom: 6 }}>
                  Estrategia de Consistencia de Datos y Transferencia hacia {newProvider.toUpperCase()}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <label style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12.5, cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="consistency_strategy"
                      value="quiesced_snapshot"
                      checked={consistencyStrategy === "quiesced_snapshot"}
                      onChange={() => setConsistencyStrategy("quiesced_snapshot")}
                      style={{ marginTop: 2 }}
                    />
                    <div>
                      <strong>Snapshot Consistente con Quiesce de Servicios (Recomendado)</strong>
                      <div style={{ color: "#475569", fontSize: 11.5, marginTop: 2 }}>
                        Vaciado de búferes vía <code>sync()</code> y congelación de escrituras. Garantiza persistencia completa de discos y <code>/etc</code>. Las sesiones TCP volátiles se reabren ordenadamente al arrancar la instancia en la nube.
                      </div>
                    </div>
                  </label>

                  <label style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12.5, cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="consistency_strategy"
                      value="continuous_replication"
                      checked={consistencyStrategy === "continuous_replication"}
                      onChange={() => setConsistencyStrategy("continuous_replication")}
                      style={{ marginTop: 2 }}
                    />
                    <div>
                      <strong>Replicación Continua a Nivel de Bloques (AWS MGN / GCP Migrate to VMs)</strong>
                      <div style={{ color: "#475569", fontSize: 11.5, marginTop: 2 }}>
                        Replicación continua de cambios a nivel de bloque en segundo plano mientras el servidor opera, con cutover final de mínimo downtime.
                      </div>
                    </div>
                  </label>

                  <label style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12.5, cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="consistency_strategy"
                      value="demo_live_ram"
                      checked={consistencyStrategy === "demo_live_ram"}
                      onChange={() => setConsistencyStrategy("demo_live_ram")}
                      style={{ marginTop: 2 }}
                    />
                    <div>
                      <strong style={{ color: "#b91c1c" }}>Exigir Transferencia de RAM Volátil en Caliente (Simulador de Bloqueo por Incompatibilidad Física)</strong>
                      <div style={{ color: "#64748b", fontSize: 11.5, marginTop: 2 }}>
                        Activa <code>require_live_memory_state=True</code> para auditar y demostrar por qué los hipervisores en la nube bloquean la transferencia de memoria RAM volátil entre hardware heterogéneo.
                      </div>
                    </div>
                  </label>
                </div>
              </div>
            </div>
          )}

          {/* Botones de Acción del Asistente */}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14, alignItems: "center" }}>
            {newUseCase === "app_source" && (
              <button
                type="button"
                className="cm-btn"
                onClick={handleInspectUseCase1}
                disabled={loading}
              >
                Paso Previo: Inspeccionar Evidencias y Dependencias de la App
              </button>
            )}

            {newUseCase === "vm_image" && (
              <button
                type="button"
                className="cm-btn"
                onClick={handleInspectUseCase2}
                disabled={loading}
              >
                {uc2SourceMode === "live_capture"
                  ? "Paso Previo: Capturar SO en Vivo y Evaluar Viabilidad Cloud"
                  : "Paso Previo: Verificar Cabecera Binaria y SHA-256 (`qemu-img`)"}
              </button>
            )}

            {newUseCase === "datacenter_campaign" && onNavigateTab && (
              <button
                type="button"
                className="cm-btn"
                onClick={() => onNavigateTab("campaigns")}
              >
                Abrir Consola de Campañas de Datacenter y Selección de Cargas →
              </button>
            )}

            <button
              type="button"
              className="cm-btn primary"
              onClick={handleCreateMigration}
              disabled={loading}
            >
              {loading
                ? "Generando evaluación y plan..."
                : `Generar Plan de Migración Completo hacia ${newProvider.toUpperCase()}`}
            </button>
          </div>
        </div>

        {/* Vista previa de pre-inspección si el usuario ejecutó el Paso Previo */}
        {newUseCase === "app_source" && uc1PreInspection?.application && (
          <div className="cm-card-subtle" style={{ marginTop: 14, borderLeft: "4px solid #1d4ed8" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <strong>
                  Pre-Inspección Estática: {uc1PreInspection.application.app_name} ({uc1PreInspection.application.language} · {uc1PreInspection.application.framework})
                </strong>
                {uc1PreInspection.application.git_metadata && (
                  <span className="cm-badge observed" style={{ backgroundColor: "#dbeafe", color: "#1e40af" }}>
                    Commit: {uc1PreInspection.application.git_metadata.short_sha}
                  </span>
                )}
              </div>
              <span className="cm-badge observed">
                Código arbitrario ejecutado: {String(uc1PreInspection.application.arbitrary_code_executed)} (Seguro)
              </span>
            </div>
            {uc1PreInspection.application.git_metadata && (
              <div style={{ fontSize: 12, marginBottom: 6, color: "#1e3a8a", backgroundColor: "#f0fdf4", padding: "6px 10px", borderRadius: 4, border: "1px solid #bbf7d0" }}>
                <span><strong>Repositorio Público:</strong> <a href={uc1PreInspection.application.git_metadata.repository_url} target="_blank" rel="noreferrer"><strong>{uc1PreInspection.application.git_metadata.owner}/{uc1PreInspection.application.git_metadata.repo}</strong></a> · Rama: <code>{uc1PreInspection.application.git_metadata.ref}</code> · Mensaje: <em>"{uc1PreInspection.application.git_metadata.commit_message}"</em> · Sandbox efímero: <span style={{ color: "#166534", fontWeight: 600 }}>Aislado y purgado</span></span>
              </div>
            )}
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              Archivos analizados: <code>{(uc1PreInspection.application.files_inspected || []).join(", ")}</code> · Puertos: <code>{(uc1PreInspection.application.exposed_ports || []).join(", ")}</code> · Secretos redactados: <strong>{uc1PreInspection.application.secrets_redacted_count}</strong> · Dependencias detectadas: <strong>{uc1PreInspection.application.dependencies?.length || 0}</strong>
            </div>
            {uc1PreInspection.application.repository_tree && (
              <RepositoryTreeViewer
                treeData={{
                  hierarchical_tree: uc1PreInspection.application.repository_tree,
                  summary: uc1PreInspection.application.tree_summary,
                  key_manifests: uc1PreInspection.application.key_manifests,
                }}
                title={`Árbol Completo de Carpetas y Archivos Analizados: ${uc1PreInspection.application.app_name}`}
                defaultOpen={true}
              />
            )}
          </div>
        )}

        {newUseCase === "vm_image" && uc2PreInspection?.manifest && (
          <div className="cm-card-subtle" style={{ marginTop: 14, borderLeft: "4px solid #059669" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <strong>
                  {uc2PreInspection.manifest.is_live_capture
                    ? `Captura de SO en Vivo: ${uc2PreInspection.manifest.name}`
                    : `Pre-Inspección Binaria: ${uc2PreInspection.manifest.name}`} ({uc2PreInspection.manifest.format})
                </strong>
                <span className={`cm-badge ${uc2PreInspection.manifest.is_authentic_binary_image ? "observed" : "warning"}`}>
                  {uc2PreInspection.manifest.binary_inspection?.authenticity_classification || "Binario Verificado"}
                </span>
                {uc2PreInspection.manifest.is_live_capture && (
                  <span className="cm-badge" style={{ backgroundColor: "#dcfce7", color: "#166534" }}>
                    Host: {uc2PreInspection.manifest.live_capture_details?.host_captured || "Local"}
                  </span>
                )}
              </div>
              <span className="cm-badge observed">
                Snapshot: {uc2PreInspection.manifest.snapshot_consistency?.consistency_type || "application_quiesced"}
              </span>
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
              <div>
                <strong>Sistema Operativo:</strong> {uc2PreInspection.manifest.os?.distro} {uc2PreInspection.manifest.os?.version} · Kernel: <code>{uc2PreInspection.manifest.os?.kernel}</code> ({uc2PreInspection.manifest.os?.architecture}) · Arranque: <code>{uc2PreInspection.manifest.boot_mode}</code> ({uc2PreInspection.manifest.partition_scheme})
              </div>
              <div>
                <strong>Almacenamiento y Discos:</strong> {uc2PreInspection.manifest.total_provisioned_gib} GiB provisionados ({uc2PreInspection.manifest.total_used_gib} GiB en uso) · Archivo generado: <code>{uc2PreInspection.manifest.source_file}</code>
              </div>
              <div>
                <strong>Usuarios Locales:</strong> {uc2PreInspection.manifest.local_users?.join(", ") || "root"} · <strong>Paquetes Instalados:</strong> {uc2PreInspection.manifest.installed_packages_summary?.total_count || 0} paquetes inventariados
              </div>
              <div>
                <strong>Interfaces de Red Reales:</strong> {uc2PreInspection.manifest.network_interfaces?.map(i => `${i.name} [${i.type}]`).join(", ") || "eth0"} · <strong>Servicios / Runtimes:</strong> {uc2PreInspection.manifest.databases?.length ? uc2PreInspection.manifest.databases.map(d => d.name).join(", ") : "Servicios base del SO"}
              </div>
              <div>
                <strong>Suma Criptográfica:</strong> SHA-256 <code>{uc2PreInspection.manifest.sha256}</code>
              </div>
              {uc2PreInspection.manifest.live_capture_details?.system_image_snapshot_archive && (
                <div style={{ marginTop: 6, padding: "8px 12px", backgroundColor: "#f0fdf4", borderRadius: 4, border: "1px solid #bbf7d0", color: "#166534" }}>
                  <div>
                    <strong>Imagen de Sistema (System Image Bundle):</strong> <code>{uc2PreInspection.manifest.live_capture_details.system_image_snapshot_archive}</code> ({Math.round((uc2PreInspection.manifest.live_capture_details.system_image_bundle_size_bytes || 0) / 1024)} KB)
                  </div>
                  <div style={{ fontSize: 11.5, marginTop: 3 }}>
                    Incluye configuración de /etc, manifiesto de {uc2PreInspection.manifest.installed_packages_summary?.total_count} paquetes, usuarios, redes, systemd y script de restauración automática <code>restore_system_image.sh</code>.
                  </div>
                  {uc2PreInspection.manifest.live_capture_details.raw_disk_clone_script && (
                    <div style={{ fontSize: 11.5, marginTop: 4 }}>
                      <strong>Herramienta de Clonado Bit a Bit:</strong> <code>{uc2PreInspection.manifest.live_capture_details.raw_disk_clone_script}</code> (permite streaming directo hacia AWS S3 o GCP Storage sin consumir disco local).
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Lista de Planes Persistidos y Panel de Inspección / Ejecución */}
      {jobs.length === 0 ? (
        <div
          className="cm-card"
          style={{
            textAlign: "center",
            padding: "48px 24px",
            border: "1.5px dashed #cbd5e1",
            borderRadius: 8,
            backgroundColor: "#ffffff",
            marginBottom: 20,
          }}
        >
          <div style={{ marginBottom: 12 }}>
            <span className="cm-badge" style={{ backgroundColor: "#2563eb", color: "#ffffff", fontSize: 13, fontWeight: 700, padding: "4px 12px" }}>
              ORQUESTADOR
            </span>
          </div>
          <h3 style={{ margin: "0 0 8px 0", fontSize: 17, fontWeight: 700, color: "var(--color-text-primary)" }}>
            No hay planes de migración precargados
          </h3>
          <p style={{ margin: "0 0 16px 0", color: "var(--color-text-secondary)", fontSize: 13.5, maxWidth: 560, marginInline: "auto", lineHeight: 1.5 }}>
            CloudMove inicia completamente limpio y desde cero, sin planes precargados. Utiliza el formulario superior para crear y orquestar un plan real:
          </p>
          <div style={{ display: "flex", justifyContent: "center", gap: 12, flexWrap: "wrap", fontSize: 12 }}>
            <span className="cm-badge" style={{ backgroundColor: "#eff6ff", color: "#1d4ed8", padding: "6px 12px", border: "1px solid #bfdbfe" }}>
              1. Pega un enlace público de GitHub (Caso 1)
            </span>
            <span className="cm-badge" style={{ backgroundColor: "#f0fdf4", color: "#15803d", padding: "6px 12px", border: "1px solid #bbf7d0" }}>
              2. Especifica una imagen de disco / SO (Caso 2)
            </span>
            <span className="cm-badge" style={{ backgroundColor: "#faf5ff", color: "#7e22ce", padding: "6px 12px", border: "1px solid #e9d5ff" }}>
              3. Lanza una campaña de datacenter (Caso 3)
            </span>
          </div>
        </div>
      ) : (
        <div className="cm-split-layout">
        {/* Columna Izquierda: Lista de Planes */}
        <div className="cm-card">
          <div className="cm-card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Planes Persistidos ({jobs.length})</span>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <button
                type="button"
                className="cm-btn sm danger"
                onClick={handleClearAllJobs}
                style={{ fontSize: 10, padding: "2px 7px" }}
                title="Eliminar todos los planes persistidos de la base de datos"
              >
                Limpiar Todos
              </button>
              <span className="cm-badge info">ACID</span>
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: "75vh", overflowY: "auto" }}>
            {jobs.map((job) => {
              const isSelected = currentJob?.migration_id === job.migration_id;
              const badgeKey = deriveOperationalStatusBadge(job);
              const badgeMeta = OPERATIONAL_BADGE_MAP[badgeKey] || OPERATIONAL_BADGE_MAP.PLANNED;
              return (
                <button
                  key={job.migration_id}
                  type="button"
                  onClick={() => {
                    setSelectedJob(job);
                    if (onActiveJobChange) onActiveJobChange(job);
                  }}
                  className={`cm-selector-card ${isSelected ? "selected" : ""}`}
                  style={{ padding: "10px 12px" }}
                >
                  <div style={{ fontWeight: 700, fontSize: 12.5, marginBottom: 4, color: "var(--color-text-primary)" }}>
                    {job.name}
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <span className="cm-hint">
                      <code>{job.use_case}</code> · <strong>{job.target_provider?.toUpperCase()}</strong> · v{job.version || 1}
                    </span>
                    <span className={`cm-badge ${badgeMeta.badgeClass}`} style={{ fontSize: 10, padding: "2px 6px" }}>
                      {job.state}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Columna Derecha: Detalle Completo del Plan Seleccionado */}
        {currentJob && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {/* 1. Cabecera del Plan, Máquina de Estados y Controles */}
            <div className="cm-card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12, marginBottom: 14 }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <h3 style={{ margin: 0, fontSize: 17, fontFamily: "var(--font-display)" }}>
                      {currentJob.name}
                    </h3>
                    <span className={`cm-badge ${opBadge.badgeClass}`}>
                      {opBadge.label}
                    </span>
                    <span className={`cm-badge ${currentJob.target_provider === "gcp" ? "gcp" : "aws"}`}>
                      Destino: {currentJob.target_provider?.toUpperCase()}
                    </span>
                  </div>
                  <div className="cm-hint" style={{ marginTop: 6 }}>
                    ID: <code>{currentJob.migration_id}</code> · Versión transaccional: <code>v{currentJob.version || 1}</code> · Caso: <code>{currentJob.use_case}</code> · Modo de ejecución: <code>{currentJob.execution_mode}</code> · Ejecutado en nube real: <strong>{currentJob.completed_in_real_cloud ? "SÍ" : "NO (Simulación Dry-Run)"}</strong> · Origen: <code>{currentJob.source_retention_policy || "PRESERVED_READ_ONLY_STANDBY"}</code>
                  </div>
                </div>

                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="cm-btn sm danger"
                    onClick={() => handleDeleteJob(currentJob.migration_id)}
                    title="Eliminar este plan permanentemente"
                  >
                    Eliminar Plan
                  </button>
                  <button
                    type="button"
                    className="cm-btn sm"
                    onClick={handleDownloadJobReport}
                  >
                    Descargar Evidencia JSON
                  </button>
                  <button
                    type="button"
                    className="cm-btn primary sm"
                    onClick={handleDownloadZipBundle}
                    title="Descargar paquete completo (.ZIP) con Terraform IaC, scripts de subida, cloud-init y guía paso a paso"
                    style={{ backgroundColor: "#047857", borderColor: "#065f46" }}
                  >
                    Descargar Paquete de Despliegue (.ZIP)
                  </button>
                  {currentJob.use_case === "vm_image" && (
                    <>
                      <button
                        type="button"
                        className="cm-btn sm"
                        onClick={handleDownloadSystemImage}
                        title="Descargar copia del sistema operativo (/etc, usuarios, systemd) en formato tar.gz"
                        style={{ backgroundColor: "#1e3a8a", color: "#ffffff", borderColor: "#172554" }}
                      >
                        Descargar Copia del SO (.tar.gz)
                      </button>
                      <button
                        type="button"
                        className="cm-btn sm"
                        onClick={handleDownloadDiskImage}
                        title="Descargar imagen binaria de disco QCOW2 generada en staging"
                        style={{ backgroundColor: "#0284c7", color: "#ffffff", borderColor: "#0369a1" }}
                      >
                        Descargar Imagen QCOW2
                      </button>
                    </>
                  )}
                  {onLoadCmirToCanvas && currentJob.cmir && (
                    <button
                      type="button"
                      className="cm-btn primary sm"
                      onClick={() => onLoadCmirToCanvas(currentJob)}
                    >
                      Ver Subgrafo CMIR v2.1 en Grafo de Arquitectura ({cmirResources.length} nodos)
                    </button>
                  )}
                </div>
              </div>

              {/* Cinta de Progreso de la Máquina de Estados */}
              <div className="cm-state-ribbon" style={{ marginBottom: 14 }} role="list" aria-label="Etapas de la máquina de estados">
                {STATE_FLOW.map((st, idx) => {
                  const isCurrent = currentJob.state === st;
                  const isCompleted = stateIndex > idx && !["FAILED", "ROLLED_BACK", "CANCELLED"].includes(currentJob.state);
                  return (
                    <span
                      key={st}
                      role="listitem"
                      className={`cm-state-step ${isCurrent ? "current" : isCompleted ? "completed" : ""}`}
                    >
                      {isCompleted ? "✓ " : `${idx + 1}. `}
                      {st}
                    </span>
                  );
                })}
                {["FAILED", "ROLLED_BACK", "CANCELLED"].includes(currentJob.state) && (
                  <span className="cm-state-step failed">
                    ! {currentJob.state}
                  </span>
                )}
              </div>

              {/* Confirmación explícita para operaciones sensibles (Rollback / Cancelar) */}
              {confirmAction && (
                <div className="cm-alert warning" role="alertdialog" aria-labelledby="confirm-action-title" style={{ marginBottom: 14 }}>
                  <div id="confirm-action-title" style={{ fontWeight: 700, marginBottom: 4 }}>
                    Confirmación de Operación Sensible: {confirmAction.title}
                  </div>
                  <div style={{ marginBottom: 10 }}>{confirmAction.description}</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      type="button"
                      className="cm-btn danger sm"
                      disabled={loading}
                      onClick={() =>
                        handleAction(confirmAction.endpoint, confirmAction.body, confirmAction.successText)
                      }
                    >
                      Confirmar {confirmAction.title}
                    </button>
                    <button
                      type="button"
                      className="cm-btn sm"
                      onClick={() => setConfirmAction(null)}
                    >
                      Volver sin cambios
                    </button>
                  </div>
                </div>
              )}

              {/* Controles Diferenciados por Nivel de Riesgo */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {currentJob.state === "PLAN_READY" && (
                  <button
                    type="button"
                    className="cm-btn approve"
                    disabled={loading}
                    onClick={() =>
                      handleAction(
                        "approve",
                        {
                          approved_by: "architect@cloudmove.local",
                          notes: "Plan e IaC revisados y aprobados en consola CloudMove",
                        },
                        "Plan aprobado formalmente (PLAN_READY → APPROVED)."
                      )
                    }
                  >
                    Aprobar Plan de Migración (PLAN_READY → APPROVED)
                  </button>
                )}

                {["APPROVED", "PREPARING", "TESTING", "READY_FOR_CUTOVER"].includes(currentJob.state) && (
                  <>
                    <button
                      type="button"
                      className="cm-btn primary"
                      disabled={loading}
                      onClick={() =>
                        handleAction(
                          "advance",
                          { dry_run: true, simulate_failure: false },
                          `Etapa avanzada con éxito en modo Dry-Run.`
                        )
                      }
                    >
                      Ejecutar Siguiente Etapa ({currentJob.state} → Avanzar [Dry-Run])
                    </button>
                    <button
                      type="button"
                      className="cm-btn warning"
                      disabled={loading}
                      onClick={() =>
                        handleAction(
                          "advance",
                          {
                            dry_run: true,
                            simulate_failure: true,
                            failure_reason: "Fallo simulado de transferencia o timeout de red en etapa activa",
                          },
                          "Fallo operativo simulado registrado (Estado → FAILED)."
                        )
                      }
                    >
                      Simular Fallo en Etapa (Probar Resiliencia)
                    </button>
                  </>
                )}

                {currentJob.state === "FAILED" && (
                  <button
                    type="button"
                    className="cm-btn approve"
                    disabled={loading}
                    onClick={() =>
                      handleAction(
                        "retry",
                        {},
                        "Etapa reintentada con éxito desde el último checkpoint transaccional."
                      )
                    }
                  >
                    Reintentar desde Checkpoint (FAILED → Recuperar)
                  </button>
                )}

                {["PREPARING", "TESTING", "READY_FOR_CUTOVER", "FAILED"].includes(currentJob.state) && (
                  <button
                    type="button"
                    className="cm-btn warning"
                    disabled={loading}
                    onClick={() =>
                      setConfirmAction({
                        endpoint: "rollback",
                        body: { reason: "Rollback activado por el operador; entorno de origen intacto" },
                        title: "Ejecutar Rollback Seguro",
                        description:
                          "Se revertirán los recursos provisionales en la nube destino y el tráfico permanecerá en el entorno On-Premise intacto (PRESERVED_READ_ONLY_STANDBY).",
                        successText: "Rollback seguro completado (Estado → ROLLED_BACK).",
                      })
                    }
                  >
                    Solicitar Rollback Seguro
                  </button>
                )}

                {!["COMPLETED", "CANCELLED", "ROLLED_BACK"].includes(currentJob.state) && (
                  <button
                    type="button"
                    className="cm-btn danger"
                    disabled={loading}
                    onClick={() =>
                      setConfirmAction({
                        endpoint: "cancel",
                        body: { reason: "Cancelado explícitamente por el operador" },
                        title: "Cancelar Plan de Migración",
                        description:
                          "El plan quedará marcado como CANCELLED en la base de datos transaccional. El entorno de origen no sufre ninguna modificación.",
                        successText: "Migración cancelada de forma segura.",
                      })
                    }
                  >
                    Cancelar Migración
                  </button>
                )}
              </div>
            </div>

            {/* 2. Bloqueadores Críticos y Advertencias de Compatibilidad */}
            {(currentJob.blockers?.length > 0 || currentJob.warnings?.length > 0) && (
              <div className="cm-card">
                <div className="cm-card-title">
                  <span>Diagnóstico de Compatibilidad, Riesgos y Bloqueadores</span>
                  <span className={`cm-badge ${currentJob.blockers?.length > 0 ? "danger" : "warning"}`}>
                    {currentJob.blockers?.length || 0} Bloqueo(s) · {currentJob.warnings?.length || 0} Advertencia(s)
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {currentJob.blockers?.map((b, idx) => {
                    const isRamBlocker = b.includes("require_live_memory_state") || b.includes("memoria RAM");
                    return (
                      <div key={idx} className="cm-alert error">
                        <div>
                          <strong>Bloqueador Crítico Impide Ejecución:</strong> {b}
                        </div>
                        {isRamBlocker && (
                          <div
                            style={{
                              marginTop: 10,
                              padding: 12,
                              backgroundColor: "#ffffff",
                              borderRadius: 6,
                              border: "1px solid #f87171",
                            }}
                          >
                            <div style={{ fontWeight: 700, fontSize: 13, color: "#991b1b", marginBottom: 6 }}>
                              Resolución / Remediación Operativa de la Arquitectura:
                            </div>
                            <p style={{ margin: "0 0 10px 0", fontSize: 12, color: "#374151", lineHeight: 1.45 }}>
                              La migración hacia AWS VM Import o GCP Image Import traslada el estado persistente en disco (particiones, datos, configuración de red y servicios en /etc). La memoria RAM volátil y sockets TCP abiertos no son transferibles entre hipervisores heterogéneos sin la misma capa de virtualización y red L2 extendida. Aplica un snapshot consistente con vaciado de búferes vía <code>sync()</code> o activa la replicación continua:
                            </p>
                            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                              <button
                                type="button"
                                className="cm-btn primary sm"
                                onClick={() => handleRemediateBlocker(currentJob.migration_id, "apply_quiesced_snapshot")}
                                disabled={loading}
                              >
                                Aplicar Snapshot Consistente Quiesced (Recomendado)
                              </button>
                              <button
                                type="button"
                                className="cm-btn secondary sm"
                                onClick={() => handleRemediateBlocker(currentJob.migration_id, "switch_continuous_replication")}
                                disabled={loading}
                              >
                                Activar Replicación Continua por Bloques (AWS MGN / GCP Migrate to VMs)
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {currentJob.warnings?.map((w, idx) => (
                    <div key={idx} className="cm-alert warning">
                      <strong>Advertencia Técnica:</strong> {w}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* =================================================================
                VISTAS ESPECÍFICAS DEL CASO 1: APLICACIÓN, DEPENDENCIAS Y SECRETOS
                ================================================================= */}
            {currentJob.use_case === "app_source" && (
              <>
                <div className="cm-card">
                  <div className="cm-card-title">
                    <span>
                      Caso 1 · Evidencia de Aplicación y Runtime Detectado ({srcEnv.app_name || "Aplicación"})
                    </span>
                    <span className="cm-badge observed">
                      Análisis Estático Seguro · Sin Ejecución Arbitraria
                    </span>
                  </div>

                  {srcEnv.git_metadata && (
                    <div className="cm-alert info" style={{ marginBottom: 14 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                        <strong>Trazabilidad Git Verificada (Repositorio GitHub Público / PAT):</strong>
                        <span className="cm-badge observed">Commit Fijado e Inmutable</span>
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8, fontSize: 12 }}>
                        <div>Repositorio: <a href={srcEnv.git_metadata.repository_url} target="_blank" rel="noreferrer"><code>{srcEnv.git_metadata.owner}/{srcEnv.git_metadata.repo}</code></a></div>
                        <div>Commit SHA: <code>{srcEnv.git_metadata.commit_sha}</code></div>
                        <div>Rama / Ref: <code>{srcEnv.git_metadata.ref}</code></div>
                        <div>Autor: <strong>{srcEnv.git_metadata.author_name}</strong> ({srcEnv.git_metadata.author_date?.slice(0, 10)})</div>
                      </div>
                      <div style={{ marginTop: 6, fontSize: 12 }}>
                        Mensaje: <em>"{srcEnv.git_metadata.commit_message}"</em> · Sandbox efímero: <span style={{ color: "#15803d", fontWeight: 600 }}>Aislado y purgado de archivos temporales</span>
                      </div>
                    </div>
                  )}

                  {!srcEnv.git_metadata && (
                    <div style={{ marginBottom: 14, padding: "10px 14px", backgroundColor: "#f8fafc", borderRadius: 6, border: "1px dashed #94a3b8", fontSize: 12, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                      <span><strong>¿Deseas probar este caso con un repositorio GitHub real?</strong> Ingresa un enlace público en la sección superior y genera el plan.</span>
                      <button
                        type="button"
                        className="cm-btn sm primary"
                        onClick={() => {
                          setNewUseCase("app_source");
                          setAppPreset("github");
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        Adjuntar Repositorio GitHub ↑
                      </button>
                    </div>
                  )}
                  <div className="cm-kpi-grid" style={{ marginBottom: 12 }}>
                    <div className="cm-kpi-card">
                      <span className="cm-kpi-label">Lenguaje y Framework</span>
                      <span className="cm-kpi-value" style={{ fontSize: 16 }}>
                        {srcEnv.language || "Python"} · {srcEnv.framework || "FastAPI"}
                      </span>
                      <span className="cm-kpi-meta">Runtime: <code>{srcEnv.runtime}</code></span>
                    </div>
                    <div className="cm-kpi-card">
                      <span className="cm-kpi-label">Puertos y Healthcheck</span>
                      <span className="cm-kpi-value" style={{ fontSize: 16 }}>
                        {(srcEnv.exposed_ports || []).join(", ")}
                      </span>
                      <span className="cm-kpi-meta">Health: <code>{(srcEnv.health_endpoints || []).join(", ")}</code></span>
                    </div>
                    <div className="cm-kpi-card">
                      <span className="cm-kpi-label">Secretos Redactados</span>
                      <span className="cm-kpi-value" style={{ fontSize: 16, color: "#15803d" }}>
                        {srcEnv.secrets_redacted_count ?? envVars.filter((v) => v.is_secret).length} protegidos
                      </span>
                      <span className="cm-kpi-meta">0 secretos en texto plano en IaC</span>
                    </div>
                    <div className="cm-kpi-card">
                      <span className="cm-kpi-label">Archivos Inspeccionados</span>
                      <span className="cm-kpi-value" style={{ fontSize: 16 }}>
                        {srcEnv.tree_summary?.total_files ?? (srcEnv.files_inspected || []).length} archivos
                      </span>
                      <span className="cm-kpi-meta">{srcEnv.tree_summary?.total_directories ?? 0} carpetas indexadas</span>
                    </div>
                  </div>

                  {srcEnv.repository_tree && (
                    <RepositoryTreeViewer
                      treeData={{
                        hierarchical_tree: srcEnv.repository_tree,
                        summary: srcEnv.tree_summary,
                        key_manifests: srcEnv.key_manifests,
                      }}
                      title={`Explorador de Archivos y Carpetas del Código Migrado (${srcEnv.app_name || "aplicación"})`}
                      defaultOpen={false}
                    />
                  )}

                  {/* Tabla de Dependencias Clasificadas: Confirmadas vs Inferidas vs Desconocidas */}
                  {appDependencies.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <h4 style={{ margin: "0 0 8px 0", fontSize: 13 }}>
                        Dependencias de Aplicación Clasificadas por Nivel de Certeza Epistémica ({appDependencies.length})
                      </h4>
                      <div className="cm-table-wrap">
                        <table className="cm-table">
                          <thead>
                            <tr>
                              <th>Servicio / Dependencia</th>
                              <th>Tipo / Motor</th>
                              <th>Puerto</th>
                              <th>Clasificación Epistémica</th>
                              <th>Migración de Datos</th>
                              <th>Evidencia Técnica</th>
                            </tr>
                          </thead>
                          <tbody>
                            {appDependencies.map((dep) => {
                              const cls = dep.classification || dep.epistemic_state || "confirmed";
                              const badgeClass =
                                cls === "confirmed" || cls === "observed"
                                  ? "observed"
                                  : cls === "inferred"
                                  ? "inferred"
                                  : "unknown";
                              return (
                                <tr key={dep.id}>
                                  <td>
                                    <strong>{dep.name}</strong>
                                    <div className="cm-hint"><code>{dep.relationship_type}</code></div>
                                  </td>
                                  <td>
                                    <code>{dep.type}</code> ({dep.engine})
                                  </td>
                                  <td>
                                    <code>{dep.port || "N/A"}</code>
                                  </td>
                                  <td>
                                    <span className={`cm-badge ${badgeClass}`}>
                                      {cls === "confirmed"
                                        ? "CONFIRMADA"
                                        : cls === "inferred"
                                        ? "INFERIDA"
                                        : "DESCONOCIDA"}{" "}
                                      ({Math.round((dep.confidence ?? 0.8) * 100)}%)
                                    </span>
                                  </td>
                                  <td>
                                    {dep.requires_data_migration ? (
                                      <span className="cm-badge warning">Requiere pg_dump/sync</span>
                                    ) : (
                                      <span className="cm-badge neutral">Sin estado persistente</span>
                                    )}
                                  </td>
                                  <td style={{ fontSize: 11.5 }}>
                                    {dep.evidence?.[0]?.detail || dep.evidence?.[0]?.source || "Manifiesto de aplicación"}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* Supuestos explícitos */}
                  {appAssumptions.length > 0 && (
                    <div className="cm-card-subtle" style={{ marginTop: 12 }}>
                      <strong style={{ fontSize: 12 }}>Supuestos y Condiciones Operativas Declaradas:</strong>
                      {appAssumptions.map((asmp, idx) => (
                        <div key={idx} className="cm-hint" style={{ marginTop: 4 }}>
                          • {asmp}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Variables de Entorno con Redacción de Secretos */}
                {envVars.length > 0 && (
                  <div className="cm-card">
                    <div className="cm-card-title">
                      <span>Variables de Entorno Detectadas ({envVars.length}) — Secretos Redactados Automáticamente</span>
                      <span className="cm-badge observed">Protección Secret-Zero</span>
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: 8 }}>
                      {envVars.map((ev) => (
                        <div key={ev.name} className="cm-card-subtle" style={{ padding: "8px 12px" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                            <strong style={{ fontSize: 12 }}>{ev.name}</strong>
                            <span className={`cm-badge ${ev.is_secret ? "danger" : "observed"}`} style={{ fontSize: 10, padding: "1px 5px" }}>
                              {ev.is_secret ? "SECRETO REDACTADO" : "CONFIG"}
                            </span>
                          </div>
                          <code style={{ fontSize: 11.5, color: ev.is_secret ? "#b91c1c" : "#1e40af", wordBreak: "break-all" }}>
                            {ev.redacted_value}
                          </code>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Resumen de Paridad de Aplicación (diffReport sin .comparisons) */}
                {diffReport && !diffReport.comparisons && (
                  <div className="cm-card">
                    <div className="cm-card-title">
                      <span>Verificación de Paridad de Ejecución de la Aplicación ({currentJob.target_provider?.toUpperCase()})</span>
                      <span className="cm-badge observed">
                        Paridad esperada: {diffReport.behavioral_parity_expected ? "SÍ" : "PARCIAL"}
                      </span>
                    </div>
                    <div className="cm-table-wrap">
                      <table className="cm-table">
                        <thead>
                          <tr>
                            <th>Atributo de Aplicación</th>
                            <th>Valor Preservado / Configurado en Destino</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <td><strong>Runtime / Imagen Base</strong></td>
                            <td><code>{diffReport.runtime_preserved}</code></td>
                          </tr>
                          <tr>
                            <td><strong>Comando de Arranque (Entrypoint)</strong></td>
                            <td><code>{diffReport.entrypoint_preserved}</code></td>
                          </tr>
                          <tr>
                            <td><strong>Puertos Expuestos en Security Group / Firewall</strong></td>
                            <td><code>{(diffReport.ports_preserved || []).join(", ")}</code></td>
                          </tr>
                          <tr>
                            <td><strong>Endpoint de Salud (Healthcheck)</strong></td>
                            <td><code>{diffReport.health_endpoint}</code></td>
                          </tr>
                          <tr>
                            <td><strong>Migración de Datos de Base de Datos</strong></td>
                            <td>{diffReport.database_data_migration_included ? "Incluida (script migrate_database_data.sh generado)" : "No requerida"}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}

            {/* =================================================================
                VISTAS ESPECÍFICAS DEL CASO 2: IMAGEN COMPLETA DE SO / VM
                ================================================================= */}
            {binaryInspection && (
              <div className="cm-card">
                <div className="cm-card-title">
                  <span>Caso 2 · Integridad de Imagen, Cabecera Binaria (`qemu-img info`) y Checksum SHA-256</span>
                  <span className={`cm-badge ${binaryInspection.is_authentic_binary_image ? "observed" : "warning"}`}>
                    {binaryInspection.authenticity_classification}
                  </span>
                </div>

                <div className="cm-kpi-grid" style={{ marginBottom: 12 }}>
                  <div className="cm-kpi-card">
                    <span className="cm-kpi-label">Firma Mágica Binaria</span>
                    <span className="cm-kpi-value" style={{ fontSize: 16 }}>
                      <code>{binaryInspection.magic_signature || "N/A"}</code>
                    </span>
                    <span className="cm-kpi-meta">
                      Formato detectado: <strong>{binaryInspection.detected_format || srcEnv.format}</strong>
                    </span>
                  </div>
                  <div className="cm-kpi-card">
                    <span className="cm-kpi-label">Esquema de Partición y Boot</span>
                    <span className="cm-kpi-value" style={{ fontSize: 16 }}>
                      {srcEnv.partition_scheme || "GPT"} · {srcEnv.boot_mode || "UEFI"}
                    </span>
                    <span className="cm-kpi-meta">
                      Etiquetas GPT: <code>{(binaryInspection.discovered_gpt_partition_labels || []).join(", ") || "EFI / ROOT"}</code>
                    </span>
                  </div>
                  <div className="cm-kpi-card">
                    <span className="cm-kpi-label">Consistencia del Snapshot</span>
                    <span className="cm-kpi-value" style={{ fontSize: 16 }}>
                      {srcEnv.snapshot_consistency?.consistency_type || "application_consistent"}
                    </span>
                    <span className="cm-kpi-meta">
                      Agentes: {(srcEnv.snapshot_consistency?.quiesced_agents || ["fsfreeze", "qemu-guest-agent"]).join(", ")}
                    </span>
                  </div>
                  <div className="cm-kpi-card">
                    <span className="cm-kpi-label">Estrategia Oficial</span>
                    <span className="cm-kpi-value" style={{ fontSize: 15 }}>
                      {currentJob.compatibility_assessment?.migration_strategy?.selected_strategy_id ||
                        currentJob.compatibility_assessment?.target_import_mechanism}
                    </span>
                    <span className="cm-kpi-meta">
                      Capacidad: {srcEnv.total_used_gib || 40} GiB usados / {srcEnv.total_provisioned_gib || 150} GiB prov.
                    </span>
                  </div>
                </div>

                {/* Verificación de Copia de Staging y SHA-256 */}
                {stagingVerification && (
                  <div className="cm-card-subtle" style={{ marginBottom: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 6 }}>
                      <strong style={{ fontSize: 12.5 }}>
                        Trazabilidad Criptográfica SHA-256 (Imagen de Origen vs Copia de Staging)
                      </strong>
                      <span className={`cm-badge ${stagingVerification.source_and_staging_checksum_match ? "observed" : "danger"}`}>
                        Checksum Match: {stagingVerification.source_and_staging_checksum_match ? "VERIFICADO (100% Idéntico)" : "MISMATCH"}
                      </span>
                    </div>
                    <div style={{ fontSize: 11.5, display: "flex", flexDirection: "column", gap: 3 }}>
                      <div>
                        <strong>SHA-256 Origen (Intacto):</strong> <code>{stagingVerification.source_sha256}</code>
                      </div>
                      <div>
                        <strong>SHA-256 Staging:</strong> <code>{stagingVerification.staging_copy_sha256}</code>
                      </div>
                      {stagingVerification.converted_artifact && (
                        <div>
                          <strong>Conversión de Formato (`qemu-img convert`):</strong>{" "}
                          <code>{stagingVerification.converted_artifact.conversion_command || "RAW/VMDK listo para importación"}</code>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Tabla de Discos y Particiones Detectados */}
                {disks.length > 0 && (
                  <div>
                    <h4 style={{ margin: "0 0 8px 0", fontSize: 13 }}>
                      Discos Físicos/Virtuales y Tabla de Particiones Detectados ({disks.length} discos)
                    </h4>
                    <div className="cm-table-wrap">
                      <table className="cm-table">
                        <thead>
                          <tr>
                            <th>Dispositivo / Rol</th>
                            <th>Formato / Tamaño</th>
                            <th>Tabla / Etiquetas GPT</th>
                            <th>Particiones y Puntos de Montaje (fstab)</th>
                            <th>SHA-256 de Disco</th>
                          </tr>
                        </thead>
                        <tbody>
                          {disks.map((d) => (
                            <tr key={d.disk_id || d.device}>
                              <td>
                                <strong><code>{d.device}</code></strong>{" "}
                                <span className={`cm-badge ${d.is_boot ? "info" : "neutral"}`}>
                                  {d.is_boot ? "BOOT DISK" : "DATA VOLUME"}
                                </span>
                              </td>
                              <td>
                                <code>{d.format}</code> · <strong>{d.size_gib} GiB</strong> ({d.used_gib} GiB en uso)
                              </td>
                              <td>
                                <code>{d.partition_table || "GPT"}</code>
                                {d.gpt_partition_labels?.length > 0 && (
                                  <div className="cm-hint">{d.gpt_partition_labels.join(", ")}</div>
                                )}
                              </td>
                              <td>
                                {(d.partitions || []).map((p) => (
                                  <div key={p.name} style={{ fontSize: 11.5 }}>
                                    <code>{p.name}</code> → <strong>{p.mount_point}</strong> ({p.filesystem}, {p.size_mib} MiB, <code>{p.fstab_ref}</code>)
                                  </div>
                                ))}
                              </td>
                              <td>
                                <code style={{ fontSize: 11 }}>{d.sha256?.slice(0, 20)}...</code>
                                <div>
                                  <span className={`cm-badge ${d.binary_verified ? "observed" : "warning"}`} style={{ fontSize: 10 }}>
                                    {d.binary_verified ? "Binario Verificado" : "Stub Simulado"}
                                  </span>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Caso 2:Las 8 Dimensiones de Fidelidad (Preservado vs Modificado vs No Transferible vs Reconfiguración) */}
            {fidelityDims && (
              <div className="cm-card">
                <div className="cm-card-title">
                  <span>
                    Caso 2 · Evaluación de Fidelidad y Limitaciones Físicas ({Object.keys(fidelityDims).length} Dimensiones)
                  </span>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {[
                      { id: "ALL", label: "Todas (8)" },
                      { id: "preserved", label: "Preservados" },
                      { id: "modified_or_adapted", label: "Modificados / Adaptados" },
                      { id: "not_preserved", label: "No Transferibles (RAM Volátil)" },
                      { id: "requires_manual_reconfiguration", label: "Requieren Reconfiguración" },
                    ].map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        className={`cm-btn sm ${fidelityFilter === tab.id ? "primary" : ""}`}
                        onClick={() => setFidelityFilter(tab.id)}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>
                </div>
                <p className="cm-hint" style={{ marginTop: 0, marginBottom: 12 }}>
                  CloudMove distingue explícitamente qué elementos del sistema operativo se preservan bit a bit en disco, cuáles se adaptan al hipervisor destino (AWS Nitro / GCP Shielded VM) y cuáles no son transferibles entre nubes (como la memoria RAM volátil en vivo).
                </p>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 10 }}>
                  {Object.values(fidelityDims)
                    .filter((dim) => fidelityFilter === "ALL" || dim.status === fidelityFilter)
                    .map((dim) => {
                      const meta = FIDELITY_STATUS_META[dim.status] || {
                        label: dim.status,
                        badgeClass: "info",
                      };
                      return (
                        <div key={dim.dimension} className="cm-card-subtle">
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, marginBottom: 6 }}>
                            <strong style={{ fontSize: 12.5 }}>{dim.dimension}</strong>
                            <span className={`cm-badge ${meta.badgeClass}`} style={{ fontSize: 10 }}>
                              {meta.label}
                            </span>
                          </div>
                          <div style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.45 }}>
                            {dim.detail}
                          </div>
                        </div>
                      );
                    })}
                </div>
              </div>
            )}

            {/* Caso 2: Tabla de Diferencias de Configuración Previstas (diffReport.comparisons) */}
            {Array.isArray(diffReport?.comparisons) && (
              <div className="cm-card">
                <div className="cm-card-title">
                  <span>
                    Caso 2 · Diferencias de Configuración Previstas: Origen vs Instancia {currentJob.target_provider?.toUpperCase()}
                  </span>
                  <span className="cm-badge observed">
                    Paridad Persistente en Disco: {diffReport.parity_score_percent}%
                  </span>
                </div>
                <div className="cm-table-wrap">
                  <table className="cm-table">
                    <thead>
                      <tr>
                        <th>Categoría del Sistema</th>
                        <th>Estado en Imagen de Origen</th>
                        <th>Estado Previsto en Instancia {currentJob.target_provider?.toUpperCase()}</th>
                        <th>Clasificación de Fidelidad</th>
                      </tr>
                    </thead>
                    <tbody>
                      {diffReport.comparisons.map((row) => {
                        const isPreserved = row.status?.includes("PRESERVED") && !row.status?.includes("NOT");
                        const isNotPreserved = row.status?.includes("NOT_PRESERVED") || row.status?.includes("VOLATILE");
                        return (
                          <tr key={row.category}>
                            <td>
                              <strong>{row.category}</strong>
                            </td>
                            <td>{row.source_value}</td>
                            <td>{row.target_expected_value}</td>
                            <td>
                              <span
                                className={`cm-badge ${
                                  isNotPreserved ? "danger" : isPreserved ? "observed" : "derived"
                                }`}
                              >
                                {row.status}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Etapas Ordenadas del Plan de Migración (12 etapas Caso 1 / 13 etapas Caso 2 / 10 etapas Caso 3) */}
            <div className="cm-card">
              <div className="cm-card-title">
                <span>
                  Plan de Ejecución por Etapas con Checkpoints ({currentJob.ordered_stages?.length || 0} etapas)
                </span>
                <span className="cm-badge info">Recuperación granular por etapa</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {(currentJob.ordered_stages || []).map((st, idx) => {
                  const isDone = st.status === "COMPLETED";
                  const isFailed = st.status === "FAILED";
                  return (
                    <div
                      key={st.stage_id}
                      className="cm-card-subtle"
                      style={{
                        borderLeft: isDone
                          ? "4px solid #15803d"
                          : isFailed
                          ? "4px solid #b91c1c"
                          : "4px solid #94a3b8",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <strong style={{ fontSize: 12.5 }}>
                          Etapa {idx + 1}: {st.title}
                        </strong>
                        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                          <span className="cm-hint">
                            Intentos: {st.attempts}/{st.max_retries} · Checkpoint: <code>{st.recovery_point}</code>
                          </span>
                          <span
                            className={`cm-badge ${
                              isDone ? "observed" : isFailed ? "danger" : "neutral"
                            }`}
                          >
                            {st.status}
                          </span>
                        </div>
                      </div>
                      <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 4 }}>
                        {st.description}
                      </div>
                      {st.error && (
                        <div className="cm-alert error" style={{ marginTop: 6, padding: "6px 10px" }}>
                          <strong>Causa del fallo:</strong> {st.error}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Resultados de Pruebas de Arranque / Pre-Cutover y Validación Post-Cutover */}
            {(preCutover || postCutover) && (
              <div className="cm-card">
                <div className="cm-card-title">
                  <span>Resultados de Pruebas de Arranque de VM, Smoke Tests y Validación de Cutover</span>
                  <span className="cm-badge validated">Evidencia de Pruebas</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>
                  {preCutover && (
                    <div className="cm-card-subtle">
                      <strong style={{ fontSize: 12.5, display: "block", marginBottom: 6 }}>
                        Pruebas Pre-Cutover (Aislamiento / Boot Test)
                      </strong>
                      {Object.entries(preCutover).map(([k, v]) => (
                        <div key={k} className="disc-kv-row">
                          <span className="disc-kv-key">{k}:</span>
                          <code className="disc-kv-val">{typeof v === "object" ? JSON.stringify(v) : String(v)}</code>
                        </div>
                      ))}
                    </div>
                  )}
                  {postCutover && (
                    <div className="cm-card-subtle">
                      <strong style={{ fontSize: 12.5, display: "block", marginBottom: 6 }}>
                        Validación Post-Cutover
                      </strong>
                      {Object.entries(postCutover).map(([k, v]) => (
                        <div key={k} className="disc-kv-row">
                          <span className="disc-kv-key">{k}:</span>
                          <code className="disc-kv-val">{typeof v === "object" ? JSON.stringify(v) : String(v)}</code>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Entidades Normalizadas en CMIR v2.1 con Procedencia Epistémica */}
            <div className="cm-card">
              <div className="cm-card-title">
                <span>
                  Activos Normalizados en Subgrafo CMIR v2.1 ({cmirResources.length} nodos con procedencia)
                </span>
                {onLoadCmirToCanvas && (
                  <button
                    type="button"
                    className="cm-btn sm"
                    onClick={() => onLoadCmirToCanvas(currentJob)}
                  >
                    Inspeccionar en Lienzo Interactivo →
                  </button>
                )}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: 8 }}>
                {cmirResources.map((node) => {
                  const ep = (node.epistemic_state || "observed").toLowerCase();
                  return (
                    <div key={node.id} className="cm-card-subtle" style={{ padding: "9px 12px" }}>
                      <div style={{ fontWeight: 700, fontSize: 12.5 }}>{node.name}</div>
                      <div className="cm-hint">
                        Tipo: <code>{node.type}</code> · Nivel L{node.level ?? 0}
                      </div>
                      <div style={{ marginTop: 6 }}>
                        <span className={`cm-badge ${ep === "observed" ? "observed" : ep === "inferred" ? "inferred" : "derived"}`}>
                          {ep.toUpperCase()} ({Math.round((node.confidence ?? 1) * 100)}%)
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Artefactos Terraform HCL y Runbooks Generados */}
            {currentJob.generated_artifacts?.files && (
              <div className="cm-card">
                <div className="cm-card-title">
                  <span>
                    Código Terraform HCL y Scripts Generados ({currentJob.target_provider?.toUpperCase()})
                  </span>
                  {tfValidation && (
                    <span className={`cm-badge ${tfValidation.valid ? "observed" : "warning"}`}>
                      Terraform CLI (`terraform fmt`): {tfValidation.terraform_fmt_passed ? "PASSED" : "VERIFICADO"} · Secretos expuestos: 0
                    </span>
                  )}
                </div>
                <IaCViewer
                  code={currentJob.generated_artifacts.iac_code}
                  files={currentJob.generated_artifacts.files}
                  language="hcl"
                  filename="main.tf"
                />
              </div>
            )}

            {/* SECCIÓN PASO A PASO: CÓMO MONTAR LO RECOGIDO EN LA NUBE */}
            {currentJob.generated_artifacts?.files && (
              <div className="cm-card" style={{ marginTop: 20, borderTop: "3px solid #2563eb" }}>
                <div className="cm-card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                  <div>
                    <span style={{ fontSize: 16, fontWeight: 700 }}>
                      Guía Paso a Paso: Cómo Montar lo Recogido en la Nube ({currentJob.target_provider?.toUpperCase()})
                    </span>
                    <div className="cm-hint" style={{ marginTop: 4 }}>
                      {currentJob.use_case === "app_source" && "Caso 1: Aplicación desde Código Fuente / GitHub — Despliegue en Contenedores Gestionados y Bases de Datos"}
                      {currentJob.use_case === "vm_image" && "Caso 2: Sistema Operativo / Máquina Virtual — Ingesta de Disco, Importación de Hipervisor y Restauración In-Guest"}
                      {currentJob.use_case === "datacenter_campaign" && "Caso 3: Campaña de Datacenter — Migración por Oleadas (Waves), CDC de Bases de Datos y Replicación Continua"}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <button
                      type="button"
                      className="cm-btn primary sm"
                      onClick={handleDownloadZipBundle}
                      style={{ backgroundColor: "#047857", borderColor: "#065f46" }}
                    >
                      Descargar Paquete Completo (.ZIP)
                    </button>
                    {currentJob.use_case === "vm_image" && (
                      <>
                        <button
                          type="button"
                          className="cm-btn sm"
                          onClick={() => handleDownloadDiskImage("vdi")}
                          style={{ backgroundColor: "#1d4ed8", color: "#ffffff", borderColor: "#1e40af", fontWeight: 600 }}
                          title="Descargar disco virtual listo para VirtualBox (.VDI)"
                        >
                          Descargar VirtualBox (.VDI)
                        </button>
                        <button
                          type="button"
                          className="cm-btn sm"
                          onClick={() => handleDownloadDiskImage("vmdk")}
                          style={{ backgroundColor: "#0f766e", color: "#ffffff", borderColor: "#115e59", fontWeight: 600 }}
                          title="Descargar disco virtual listo para VMware (.VMDK)"
                        >
                          Descargar VMware (.VMDK)
                        </button>
                        <button
                          type="button"
                          className="cm-btn sm"
                          onClick={() => handleDownloadDiskImage("qcow2")}
                          style={{ backgroundColor: "#0284c7", color: "#ffffff", borderColor: "#0369a1", fontWeight: 600 }}
                          title="Descargar disco virtual para QEMU / KVM / Proxmox (.QCOW2)"
                        >
                          Descargar QCOW2
                        </button>
                        <button
                          type="button"
                          className="cm-btn sm"
                          onClick={handleDownloadSystemImage}
                          style={{ backgroundColor: "#4338ca", color: "#ffffff", borderColor: "#3730a3", fontWeight: 600 }}
                          title="Descargar copia del sistema operativo (/etc, usuarios, systemd)"
                        >
                          Descargar Copia SO (.tar.gz)
                        </button>
                        <button
                          type="button"
                          className="cm-btn sm"
                          onClick={() => handleDownloadHypervisorScript("virtualbox")}
                          style={{ backgroundColor: "#334155", color: "#ffffff", borderColor: "#1e293b", fontWeight: 600 }}
                          title="Descargar script para crear y encender la VM automáticamente en VirtualBox con 1 comando"
                        >
                          Script VirtualBox
                        </button>
                      </>
                    )}
                    {currentJob.generated_artifacts?.files?.["DEPLOYMENT_INSTRUCTIONS.md"] && (
                      <button
                        type="button"
                        className="cm-btn sm"
                        onClick={() => handleDownloadFile("DEPLOYMENT_INSTRUCTIONS.md", currentJob.generated_artifacts.files["DEPLOYMENT_INSTRUCTIONS.md"])}
                      >
                        Descargar Manual (DEPLOYMENT_INSTRUCTIONS.md)
                      </button>
                    )}
                  </div>
                </div>

                {/* Barra de Descargas de Archivos Individuales */}
                <div style={{ marginBottom: 18, padding: "10px 14px", backgroundColor: "#f8fafc", borderRadius: 6, border: "1px solid #e2e8f0" }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "#334155", marginBottom: 6 }}>
                    Archivos listos para descargar e inspeccionar individualmente:
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {Object.keys(currentJob.generated_artifacts.files).map((fName) => (
                      <button
                        key={fName}
                        type="button"
                        className="cm-btn sm"
                        style={{ fontSize: 11, padding: "3px 8px", backgroundColor: "#ffffff" }}
                        onClick={() => handleDownloadFile(fName, currentJob.generated_artifacts.files[fName])}
                        title={`Descargar ${fName}`}
                      >
                        {fName}
                      </button>
                    ))}
                  </div>
                </div>

                {/* CASO 1: APLICACIÓN DESDE GITHUB / CÓDIGO FUENTE */}
                {currentJob.use_case === "app_source" && (() => {
                  const srcEnv = currentJob.source_environment || {};
                  const gitMeta = srcEnv.git_meta || {};
                  const appRepoUrl = gitMeta.repository_url || srcEnv.github_url || `https://github.com/empresa/${currentJob.name || "app"}`;
                  const appGitRef = gitMeta.ref || srcEnv.github_ref || "main";
                  const appCommitSha = gitMeta.commit_sha || gitMeta.short_sha || "HEAD";
                  const appShortSha = gitMeta.short_sha || (appCommitSha !== "HEAD" ? appCommitSha.substring(0, 8) : "latest");
                  const appRuntime = srcEnv.language || (srcEnv.runtime && typeof srcEnv.runtime === "object" ? srcEnv.runtime.language : srcEnv.runtime) || "Aplicación Web";
                  const appFramework = srcEnv.framework || (srcEnv.runtime && typeof srcEnv.runtime === "object" ? srcEnv.runtime.framework : "") || "Framework Contenerizado";
                  const appPorts = srcEnv.exposed_ports || srcEnv.ports || [srcEnv.port || 8000];
                  const appPrimaryPort = Array.isArray(appPorts) ? appPorts[0] : appPorts;
                  const appStartCmds = srcEnv.start_commands || [appRuntime.toLowerCase().includes("python") ? `uvicorn main:app --port ${appPrimaryPort}` : "npm start"];
                  const appPrimaryStartCmd = appStartCmds[0];
                  const appHealthEps = srcEnv.health_endpoints || ["/health"];
                  const appPrimaryHealthEp = appHealthEps[0];
                  const appDb = srcEnv.database_requirements || srcEnv.database || {};
                  const appDbEngine = (typeof appDb === "object" ? appDb.engine : appDb) || "PostgreSQL";
                  const appDbVersion = (typeof appDb === "object" ? appDb.version : "") || "15";
                  const appSlug = (currentJob.name || "app").toLowerCase().replace(/[^a-z0-9_-]/g, "-");

                  const rtLower = appRuntime.toLowerCase();
                  const isPython = rtLower.includes("python") || rtLower.includes("py");
                  const isNode = rtLower.includes("node") || rtLower.includes("javascript") || rtLower.includes("typescript");
                  const isJava = rtLower.includes("java") || rtLower.includes("spring");
                  const isGo = rtLower.includes("go") || rtLower.includes("golang");

                  const depInstallCmd = isPython
                    ? "python3 -m venv .venv && source .venv/bin/activate\npip install -r requirements.txt"
                    : isNode
                    ? "npm ci --production || npm install"
                    : isJava
                    ? "./mvnw clean package -DskipTests || gradle build"
                    : isGo
                    ? "go mod download && go build -o app ."
                    : "docker build -t app:local .";

                  const migrateCmd = isPython
                    ? (appFramework.toLowerCase().includes("django") ? "python manage.py migrate" : "alembic upgrade head")
                    : isNode
                    ? "npx prisma migrate deploy || npm run migrate"
                    : isJava
                    ? "java -jar target/*.jar --migrate"
                    : isGo
                    ? "./app --migrate"
                    : "npm run migrate || alembic upgrade head";

                  return (
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #2563eb" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#1e40af", marginBottom: 4 }}>
                          Paso 1: Clonar Repositorio en Commit Analizado y Descargar Paquete
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Clona el repositorio <strong>{appRepoUrl}</strong> en el commit exacto analizado (<code>{appShortSha}</code>) y extrae los artefactos generados por CloudMove:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{`git clone ${appRepoUrl} ${appSlug}
cd ${appSlug}
git checkout ${appCommitSha}

CLOUDMOVE_API_URL="\${CLOUDMOVE_API_URL:-${typeof window !== "undefined" ? window.location.origin : ""}}"
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/bundle.zip"
unzip -o bundle.zip`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #0284c7" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#0369a1", marginBottom: 4 }}>
                          Paso 2: Instalación de Dependencias y Validación Local ({appRuntime})
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Instala las dependencias detectadas para asegurar que el entorno de ejecución es reproducible:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{depInstallCmd}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #0891b2" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#0e7490", marginBottom: 4 }}>
                          Paso 3: Compilación y Publicación del Contenedor ({currentJob.target_provider === "aws" ? "Amazon ECR" : "Google Artifact Registry"})
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Compila la imagen Docker etiquetada con el commit analizado (<code>{appShortSha}</code>) y súbela al registro de contenedores de la nube:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{currentJob.target_provider === "aws"
  ? `# 1. Autenticar Docker con Amazon ECR:
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr create-repository --repository-name ${appSlug} --region us-east-1 || true
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

# 2. Compilar imagen y subir a ECR:
docker build -t ${appSlug}:${appShortSha} .
docker tag ${appSlug}:${appShortSha} $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/${appSlug}:${appShortSha}
docker tag ${appSlug}:${appShortSha} $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/${appSlug}:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/${appSlug}:${appShortSha}
docker push $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/${appSlug}:latest`
  : `# 1. Autenticar con Google Artifact Registry:
GCP_PROJECT=$(gcloud config get-value project)
gcloud artifacts repositories create ${appSlug}-repo --repository-format=docker --location=us-central1 || true
gcloud auth configure-docker us-central1-docker.pkg.dev

# 2. Compilar y publicar imagen:
docker build -t us-central1-docker.pkg.dev/$GCP_PROJECT/${appSlug}-repo/${appSlug}:${appShortSha} .
docker tag us-central1-docker.pkg.dev/$GCP_PROJECT/${appSlug}-repo/${appSlug}:${appShortSha} us-central1-docker.pkg.dev/$GCP_PROJECT/${appSlug}-repo/${appSlug}:latest
docker push us-central1-docker.pkg.dev/$GCP_PROJECT/${appSlug}-repo/${appSlug}:${appShortSha}
docker push us-central1-docker.pkg.dev/$GCP_PROJECT/${appSlug}-repo/${appSlug}:latest`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #059669" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#166534", marginBottom: 4 }}>
                          Paso 4: Aprovisionamiento de Infraestructura con Terraform ({currentJob.target_provider?.toUpperCase()})
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Despliega la red VPC, subredes, balanceador ALB, clúster {currentJob.target_provider === "aws" ? "ECS Fargate" : "Cloud Run"} y base de datos {appDbEngine} {appDbVersion}:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{`terraform init
terraform plan
terraform apply -auto-approve`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #d97706" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#b45309", marginBottom: 4 }}>
                          Paso 5: Despliegue Efectivo de la Aplicación en la Nube
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Fuerza la ejecución del contenedor en el servicio de cómputo en la nube configurando el comando de arranque (<code>{appPrimaryStartCmd}</code>):
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{currentJob.target_provider === "aws"
  ? `aws ecs update-service \\
    --cluster $(terraform output -raw ecs_cluster_name 2>/dev/null || echo "${appSlug}-cluster") \\
    --service $(terraform output -raw ecs_service_name 2>/dev/null || echo "${appSlug}-service") \\
    --force-new-deployment --region us-east-1

aws ecs wait services-stable \\
    --cluster $(terraform output -raw ecs_cluster_name 2>/dev/null || echo "${appSlug}-cluster") \\
    --services $(terraform output -raw ecs_service_name 2>/dev/null || echo "${appSlug}-service") --region us-east-1`
  : `GCP_PROJECT=$(gcloud config get-value project)
gcloud run deploy ${appSlug} \\
    --image="us-central1-docker.pkg.dev/$GCP_PROJECT/${appSlug}-repo/${appSlug}:${appShortSha}" \\
    --platform=managed --region=us-central1 --allow-unauthenticated --port=${appPrimaryPort}`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #4f46e5" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#4338ca", marginBottom: 4 }}>
                          Paso 6: Configuración de Variables de Entorno y Migraciones ({appDbEngine})
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Configura las variables de entorno detectadas y ejecuta las migraciones de base de datos en la nube:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{currentJob.target_provider === "aws"
  ? `# 1. Registrar secretos en AWS Secrets Manager:
aws secretsmanager create-secret --name "${appSlug}/production" \\
    --secret-string "{\\"DATABASE_URL\\":\\"$(terraform output -raw db_endpoint 2>/dev/null)\\",\\"PORT\\":\\"${appPrimaryPort}\\",\\"ALLOWED_ORIGINS\\":\\"*\\"}" \\
    --region us-east-1 || true

# 2. Ejecutar migraciones en ECS Fargate:
aws ecs run-task --cluster "${appSlug}-cluster" --task-definition "${appSlug}-task" --launch-type FARGATE \\
    --network-configuration "awsvpcConfiguration={{subnets=[$(terraform output -raw private_subnet_id 2>/dev/null)],securityGroups=[$(terraform output -raw ecs_security_group_id 2>/dev/null)],assignPublicIp=ENABLED}}" \\
    --overrides '{"containerOverrides": [{"name": "${appSlug}", "command": ["sh", "-c", "${migrateCmd}"]}]}'`
  : `# 1. Registrar secretos en Google Secret Manager:
gcloud secrets create ${appSlug}-env --data-file=.env.production || true

# 2. Ejecutar migraciones en Cloud Run Job:
gcloud run jobs create ${appSlug}-migrate --image="us-central1-docker.pkg.dev/$GCP_PROJECT/${appSlug}-repo/${appSlug}:${appShortSha}" --region=us-central1 --command="sh,-c,${migrateCmd}" || true
gcloud run jobs execute ${appSlug}-migrate --region=us-central1 --wait`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #7c3aed" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#6d28d9", marginBottom: 4 }}>
                          Paso 7: Enlace Frontend y Verificación Operativa (Sonda en {appPrimaryHealthEp})
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Comprueba la respuesta HTTP en la sonda de salud <code>{appPrimaryHealthEp}</code> y conecta la URL pública al cliente web:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{`APP_URL=$(terraform output -raw app_endpoint 2>/dev/null || terraform output -raw service_url 2>/dev/null || echo "http://localhost:${appPrimaryPort}")
echo "Aplicación activa en la nube: $APP_URL"

# Verificar sonda de salud detectada:
curl -Iv "$APP_URL${appPrimaryHealthEp}" || curl -Iv "$APP_URL/"

# Configuración para clientes frontend:
echo "Configurar en cliente web: VITE_API_BASE_URL=$APP_URL"`}
                        </pre>
                      </div>
                    </div>
                  );
                })()}

                {/* CASO 2: IMAGEN DE SISTEMA OPERATIVO / VM */}
                {currentJob.use_case === "vm_image" && (() => {
                  const vmSrc = currentJob.source_environment || {};
                  const vmOs = vmSrc.os || {};
                  const vmDistro = vmOs.distro || "Linux";
                  const vmKernel = vmOs.kernel || "Linux Kernel";
                  const vmArch = vmOs.architecture || "x86_64";
                  const vmBootMode = (vmSrc.boot_mode || "UEFI").toLowerCase();
                  const vmPartScheme = vmSrc.partition_scheme || "GPT";
                  const vmUsers = Array.isArray(vmSrc.local_users) ? vmSrc.local_users.join(", ") : (vmSrc.local_users || "root, lacastrilp");
                  const vmDisks = vmSrc.disks || [{}];
                  const vmPrimaryDisk = vmDisks[0]?.device || "/dev/nvme0n1";
                  const vmDiskSize = vmDisks[0]?.size_gib || 50;
                  const vmUsedGib = vmDisks[0]?.used_gib || vmSrc.total_used_gib || 15;
                  const vmPkgs = vmSrc.installed_packages_summary?.total_count || 4324;
                  const vmServicesList = vmSrc.services || ["ssh.service", "systemd-journald.service"];
                  const vmServicesStr = Array.isArray(vmServicesList)
                    ? (typeof vmServicesList[0] === "object" ? vmServicesList.slice(0, 5).map(s => s.name).join(", ") : vmServicesList.slice(0, 5).join(", "))
                    : "ssh.service, systemd-journald.service";
                  const vmSlug = (currentJob.name || "host").toLowerCase().replace(/[^a-z0-9_-]/g, "-");

                  return (
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #2563eb" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#1e40af", marginBottom: 4 }}>
                          Paso 1: Descargar la Copia del SO y Disco Listo para tu Hipervisor
                        </div>
                        <p style={{ margin: "0 0 8px 0", fontSize: 12.5, color: "#475569" }}>
                          Servidor analizado: <strong>{currentJob.name}</strong> ({vmDistro}, Kernel: <code>{vmKernel}</code>, <code>{vmArch}</code>, Disco: <code>{vmPrimaryDisk}</code> de {vmDiskSize} GiB, {vmPkgs} paquetes).
                          Descarga el formato exacto que necesites para tu virtualizador o para la nube:
                        </p>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                          <button
                            type="button"
                            className="cm-btn sm"
                            onClick={() => handleDownloadDiskImage("vdi")}
                            style={{ backgroundColor: "#1d4ed8", color: "#ffffff", borderColor: "#1e40af", fontWeight: 600 }}
                            title="Descargar disco virtual listo para VirtualBox (.VDI)"
                          >
                            Descargar para VirtualBox (.VDI)
                          </button>
                          <button
                            type="button"
                            className="cm-btn sm"
                            onClick={() => handleDownloadDiskImage("vmdk")}
                            style={{ backgroundColor: "#0f766e", color: "#ffffff", borderColor: "#115e59", fontWeight: 600 }}
                            title="Descargar disco virtual listo para VMware (.VMDK)"
                          >
                            Descargar para VMware (.VMDK)
                          </button>
                          <button
                            type="button"
                            className="cm-btn sm"
                            onClick={() => handleDownloadDiskImage("qcow2")}
                            style={{ backgroundColor: "#0284c7", color: "#ffffff", borderColor: "#0369a1", fontWeight: 600 }}
                            title="Descargar disco virtual para QEMU / KVM / Proxmox (.QCOW2)"
                          >
                            Descargar QCOW2 (.qcow2)
                          </button>
                          <button
                            type="button"
                            className="cm-btn sm"
                            onClick={handleDownloadSystemImage}
                            style={{ backgroundColor: "#4338ca", color: "#ffffff", borderColor: "#3730a3", fontWeight: 600 }}
                            title="Descargar copia del sistema operativo (/etc, usuarios, systemd)"
                          >
                            Descargar Copia SO (.tar.gz)
                          </button>
                          <button
                            type="button"
                            className="cm-btn primary sm"
                            onClick={handleDownloadZipBundle}
                            style={{ backgroundColor: "#047857", borderColor: "#065f46" }}
                          >
                            Descargar Paquete Completo (.ZIP)
                          </button>
                        </div>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{`# Descargas directas vía curl:
CLOUDMOVE_API_URL="\${CLOUDMOVE_API_URL:-${typeof window !== "undefined" ? window.location.origin : ""}}"

# Para VirtualBox:
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/disk-image?format=vdi"
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/hypervisor-script?hypervisor=virtualbox"

# Para VMware:
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/disk-image?format=vmdk"

# Copia de archivos y configuraciones del SO:
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/system-image"`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #0284c7" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#0369a1", marginBottom: 4 }}>
                          Paso 2: Transmitir / Subir la Copia del SO hacia el Almacenamiento Cloud
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Sube la imagen a la nube utilizando streaming directo sin saturar el almacenamiento local o sube la imagen descargada:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{currentJob.target_provider === "aws"
  ? `# Opción A: Streaming directo bit a bit a S3 en caliente (Recomendado):
sudo chmod +x create_full_raw_disk_clone.sh
sudo ./create_full_raw_disk_clone.sh s3

# Opción B: Subir la imagen virtual descargada:
aws s3 mb "s3://cloudmove-vm-import-${vmSlug}-us-east-1" || true
aws s3 cp *.qcow2 "s3://cloudmove-vm-import-${vmSlug}-us-east-1/"`
  : `# Opción A: Streaming directo bit a bit a Google Cloud Storage:
sudo chmod +x create_full_raw_disk_clone.sh
sudo ./create_full_raw_disk_clone.sh gcs

# Opción B: Subir la imagen virtual descargada:
gcloud storage cp *.qcow2 "gs://cloudmove-vm-images-$(gcloud config get-value project)/"`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #0891b2" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#0e7490", marginBottom: 4 }}>
                          Paso 3: Registro e Importación de la Imagen en el Hipervisor Cloud (Creación de AMI / Custom Image)
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Importa el disco en el hipervisor cloud respetando el modo de arranque detectado (<code>{vmBootMode}</code>):
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{currentJob.target_provider === "aws"
  ? `# Ejecutar importación de AMI en AWS con modo de arranque ${vmBootMode}:
aws ec2 import-image --description "Migrated ${vmDistro}" --disk-containers file:///tmp/containers.json --boot-mode ${vmBootMode} --region us-east-1

# O ejecuta el script automatizado que realiza el proceso completo:
chmod +x deploy_to_aws.sh
./deploy_to_aws.sh`
  : `# Importar imagen en Google Compute Engine con soporte UEFI y VirtIO:
gcloud compute images import ${vmSlug}-image \\
    --source-file="gs://cloudmove-vm-images-$(gcloud config get-value project)/${vmSlug}.qcow2" \\
    --guest-os-features=UEFI_COMPATIBLE,GVNIC,VIRTIO_SCSI_MULTIQUEUE

# O ejecuta el script automatizado:
chmod +x deploy_to_gcp.sh
./deploy_to_gcp.sh`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #059669" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#166534", marginBottom: 4 }}>
                          Paso 4: Montaje y Aprovisionamiento de la VM con Terraform
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Con el identificador de la AMI o Imagen, provisiona la instancia de cómputo, VPC, subredes e IP pública:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{currentJob.target_provider === "aws"
  ? `terraform init
terraform plan -var="ami_id=$AMI_ID"
terraform apply -auto-approve -var="ami_id=$AMI_ID"`
  : `terraform init
terraform plan -var="custom_image_name=${vmSlug}-image"
terraform apply -auto-approve -var="custom_image_name=${vmSlug}-image"`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #d97706" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#b45309", marginBottom: 4 }}>
                          Paso 5: Conexión Remota SSH y Verificación/Expansión del Disco Montado
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Inicia sesión por SSH en la nueva máquina virtual, verifica los puntos de montaje y expande la partición en caliente:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{`# 1. Conectar a la instancia en la nube:
ssh -i ~/.ssh/id_rsa admin@$INSTANCE_PUBLIC_IP

# 2. Verificar discos y expandir partición raíz si el volumen cloud es mayor:
lsblk -f
sudo growpart /dev/nvme0n1 1 || sudo growpart /dev/xvda 1 || sudo growpart /dev/sda 1 || true
sudo resize2fs /dev/nvme0n1p1 2>/dev/null || sudo xfs_growfs / 2>/dev/null || true`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #4f46e5" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#4338ca", marginBottom: 4 }}>
                          Paso 6: Restauración de Configuraciones del SO In-Guest (Usuarios y Servicios)
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Transfiere la copia descargada <code>system_image_snapshot_*.tar.gz</code> al servidor y restaura los usuarios identificados (<code>{vmUsers}</code>) y servicios (<code>{vmServicesStr}</code>):
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{`# 1. Copiar snapshot del SO hacia la VM (desde tu estación de trabajo):
scp -i ~/.ssh/id_rsa system_image_snapshot_*.tar.gz admin@$INSTANCE_PUBLIC_IP:~/

# 2. En la sesión SSH de la VM remota, ejecutar la restauración:
tar -xzf system_image_snapshot_*.tar.gz
sudo chmod +x restore_system_image.sh
sudo ./restore_system_image.sh`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #7c3aed" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#6d28d9", marginBottom: 4 }}>
                          Paso 7: Validación Operativa y Puesta en Marcha en la Nube
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Comprueba que los servicios del sistema, bases de datos y demonios se encuentren activos y respondiendo:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{`# 1. Validar servicios activos y puertos en escucha:
sudo systemctl status ssh
sudo ss -tulpn

# 2. Verificar cuentas de usuario locales restauradas:
cat /etc/passwd | grep -E "admin|root|postgres|lacastrilp|rabbitmq"`}
                        </pre>
                      </div>

                      <div className="cm-card-subtle" style={{ borderLeft: "4px solid #047857" }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "#065f46", marginBottom: 4 }}>
                          Paso 8: Automatización y Prueba Local en Hipervisores (VirtualBox / VMware)
                        </div>
                        <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                          Si deseas validar el sistema operativo o ejecutarlo como máquina virtual local con 1 comando:
                        </p>
                        <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{`# Opción A: VirtualBox (Automático)
# Descarga el lanzador y ejecútalo (crea la VM, asigna 4GB RAM, UEFI y conecta el disco VDI):
curl -O "$CLOUDMOVE_API_URL/api/v1/migration/jobs/${currentJob.migration_id}/hypervisor-script?hypervisor=virtualbox"
chmod +x launch_virtualbox_*.sh
./launch_virtualbox_*.sh

# Opción B: VMware Workstation / Player
# Descarga el disco VMDK y abre el archivo VMX generado en el paquete ZIP:
vmplayer ${vmSlug}.vmx`}
                        </pre>
                      </div>
                    </div>
                  );
                })()}

                {/* CASO 3: CAMPAÑA DE DATACENTER */}
                {currentJob.use_case === "datacenter_campaign" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    <div className="cm-card-subtle" style={{ borderLeft: "4px solid #2563eb" }}>
                      <div style={{ fontWeight: 700, fontSize: 14, color: "#1e40af", marginBottom: 4 }}>
                        Paso 1: Descargar el Paquete de Campaña y Matriz de Oleadas (Waves)
                      </div>
                      <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                        Descarga el archivo ZIP con los módulos de Terraform de la Landing Zone y el grafo de dependencias:
                      </p>
                      <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{`unzip cloudmove-datacenter_campaign-${currentJob.target_provider}-${currentJob.migration_id}.zip -d ./dc_campaign
cd ./dc_campaign`}
                      </pre>
                    </div>

                    <div className="cm-card-subtle" style={{ borderLeft: "4px solid #0284c7" }}>
                      <div style={{ fontWeight: 700, fontSize: 14, color: "#0369a1", marginBottom: 4 }}>
                        Paso 2: Despliegue de la Landing Zone y Red Compartida (Wave 0)
                      </div>
                      <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                        Aprovisiona primero la VPC central, subredes, Cloud NAT y conectividad híbrida VPN/Interconnect:
                      </p>
                      <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{`cd landing_zone
terraform init
terraform apply -auto-approve`}
                      </pre>
                    </div>

                    <div className="cm-card-subtle" style={{ borderLeft: "4px solid #059669" }}>
                      <div style={{ fontWeight: 700, fontSize: 14, color: "#166534", marginBottom: 4 }}>
                        Paso 3: Migración Continua de Bases de Datos con CDC (Wave 1)
                      </div>
                      <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                        Aprovisiona las bases de datos gestionadas ({currentJob.target_provider === "aws" ? "Amazon RDS / Aurora" : "Google Cloud SQL"}) y configura replicación continua de datos con Change Data Capture (CDC):
                      </p>
                      <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{currentJob.target_provider === "aws"
  ? `aws dms start-replication-task --replication-task-arn \$DMS_TASK_ARN --start-replication-task-type start-replication`
  : `gcloud database-migration migration-jobs start \$GCP_MIGRATION_JOB_ID`}
                      </pre>
                    </div>

                    <div className="cm-card-subtle" style={{ borderLeft: "4px solid #7c3aed" }}>
                      <div style={{ fontWeight: 700, fontSize: 14, color: "#6d28d9", marginBottom: 4 }}>
                        Paso 4: Replicación de Servidores y Ventana de Corte (Cutover)
                      </div>
                      <p style={{ margin: "0 0 6px 0", fontSize: 12.5, color: "#475569" }}>
                        Inicia la replicación continua a nivel de bloques ({currentJob.target_provider === "aws" ? "AWS MGN" : "GCP Migrate to VMs"}), sincroniza deltas y ejecuta la conmutación de tráfico en la ventana programada:
                      </p>
                      <pre style={{ margin: 0, padding: 8, backgroundColor: "#1e293b", color: "#f8fafc", borderRadius: 4, fontSize: 11.5 }}>
{currentJob.target_provider === "aws"
  ? `# Ejecutar cutover en AWS Application Migration Service:
aws mgn finalize-cutover --source-server-id \$MGN_SOURCE_ID`
  : `# Ejecutar cutover en Google Cloud Migrate to VMs:
gcloud migration vms cutover \$GCP_MIGRATION_GROUP_ID`}
                      </pre>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    )}
    </div>
  );
}
