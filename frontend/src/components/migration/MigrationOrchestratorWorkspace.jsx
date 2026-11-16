import React, { useState, useEffect, useCallback, useRef } from "react";
import IaCViewer from "./IaCViewer";
import ExternalServicesCredentialsCard from "./ExternalServicesCredentialsCard";
import TargetArchitectureView from "./TargetArchitectureView";
import AutomatedCloudDeployerPanel from "./AutomatedCloudDeployerPanel";
import { loadSavedSelectedUserPaths } from "./UserFileSelectionPanel";
import { apiFetch } from "../../utils/apiClient";
import {
  getSessionAgentToken,
  saveSessionAgentToken,
} from "../../utils/credentialVault";
import {
  AwsPageHeader,
  AwsKeyValuePairs,
  AwsStatusIndicator,
  AwsTabs,
} from "../cloudscape/AwsPrimitives";

import VmOsToCloudTransformationMap from "./VmOsToCloudTransformationMap";
import CloudRunbookGuidePanel from "./CloudRunbookGuidePanel";
import {
  Case1SourceInspectionPanel,
  Case1CompatibilityInspectionPanel,
} from "./Case1InspectionPanels";
import {
  Case2SourceInspectionPanel,
  Case2CompatibilityInspectionPanel,
} from "./Case2InspectionPanels";
import UseCaseWizardPanel from "./UseCaseWizardPanel";
import {
  STATE_FLOW,
  OPERATIONAL_BADGE_MAP,
  deriveOperationalStatusBadge,
} from "./orchestratorConstants";

export default function MigrationOrchestratorWorkspace({
  onLoadCmirToCanvas,
  initialUseCase,
  initialJobId,
  onActiveJobChange,
}) {
  const [jobs, setJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);
  const [persistenceStatus, setPersistenceStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [refreshingJobs, setRefreshingJobs] = useState(false);
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
  const [uc1Decisions, setUc1Decisions] = useState({});
  const [jobDecisions, setJobDecisions] = useState({});
  const [updatingDecisions, setUpdatingDecisions] = useState(false);
  const [githubUrl, setGithubUrl] = useState("");
  const [githubRef, setGithubRef] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [githubRepoData, setGithubRepoData] = useState(null);
  const [githubTreeData, setGithubTreeData] = useState(null);
  const [githubBranches, setGithubBranches] = useState([]);
  const [validatingGithub, setValidatingGithub] = useState(false);
  const [showAdvancedGithub, setShowAdvancedGithub] = useState(false);

  // Case 2 specific options & Sequential Agent Token Flow
  const [uc2SourceMode, setUc2SourceMode] = useState("live_capture"); // "file_path" | "live_capture"
  const [uc2OutputFormat, setUc2OutputFormat] = useState("QCOW2");
  const [agentTokenData, setAgentTokenData] = useState(() => getSessionAgentToken());
  const [generatingAgentToken, setGeneratingAgentToken] = useState(false);
  const [enrolledAgents, setEnrolledAgents] = useState([]);
  const [copiedAgentCmd, setCopiedAgentCmd] = useState("");
  const [imagePath, setImagePath] = useState("");
  const [imageFormatOverride, setImageFormatOverride] = useState("VMDK");
  const [consistencyStrategy, setConsistencyStrategy] = useState("quiesced_snapshot"); // "quiesced_snapshot" | "continuous_replication" | "demo_live_ram"
  const [hostDevicesData, setHostDevicesData] = useState(null);
  const [queryingDevices, setQueryingDevices] = useState(false);
  const [selectedStorageDevice, setSelectedStorageDevice] = useState("");
  const [selectedUserPaths, setSelectedUserPaths] = useState(
    () => loadSavedSelectedUserPaths() || []
  );
  const [uc2StageMeta, setUc2StageMeta] = useState(null);
  const [showCase2HelpModal, setShowCase2HelpModal] = useState(false);
  const requireLiveRam = consistencyStrategy === "demo_live_ram";
  const preferContinuousReplication = consistencyStrategy === "continuous_replication";
  const [uc2PreInspection, setUc2PreInspection] = useState(null);
  const [uc2Decisions, setUc2Decisions] = useState({
    ebs_storage_sizing: "aws_academy_30gb",
    compute_provisioning_mode: "autonomous_cloud_init",
    instance_sizing_profile: "free_tier_t3_micro",
    security_group_ports_policy: "curated_deduplicated_ports",
  });
  const [fidelityFilter, setFidelityFilter] = useState("ALL");
  const [showDeploymentGuide, setShowDeploymentGuide] = useState(true);

  // Progressive disclosure: one focused task per screen (AWS Console Tabs)
  const [mainTab, setMainTab] = useState(initialJobId ? "inspector" : "wizard"); // "wizard" | "inspector" | "plans"
  const [inspectorTab, setInspectorTab] = useState("execution"); // "execution" | "source" | "compatibility" | "iac" | "guide"

  useEffect(() => {
    if (initialUseCase) {
      setNewUseCase(initialUseCase);
      setMainTab("wizard");
    }
  }, [initialUseCase]);

  useEffect(() => {
    if (initialJobId) {
      setMainTab("inspector");
      setInspectorTab("execution");
    }
  }, [initialJobId]);

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

  const onActiveJobChangeRef = useRef(onActiveJobChange);
  useEffect(() => {
    onActiveJobChangeRef.current = onActiveJobChange;
  }, [onActiveJobChange]);

  useEffect(() => {
    if (selectedJob && typeof onActiveJobChangeRef.current === "function") {
      onActiveJobChangeRef.current(selectedJob);
    }
  }, [selectedJob]);

  const fetchJobs = useCallback(
    async (selectId = null, manual = false) => {
      if (manual) setRefreshingJobs(true);
      try {
        const res = await apiFetch("/api/v1/migration/jobs", { timeoutMs: 20000 });
        if (!res.ok) {
          if (manual) {
            setErrorMsg(`Error HTTP ${res.status} al actualizar la lista de planes de migración.`);
          }
          return;
        }
        const data = await res.json();
        const list = (data.jobs || []).filter(
          (j) => j.use_case === "app_source" || j.use_case === "vm_image"
        );
        setJobs(list);
        const targetId = selectId || initialJobId;
        if (targetId) {
          const found = list.find((j) => j.migration_id === targetId);
          if (found) {
            setSelectedJob(found);
            return;
          }
        }
        if (list.length > 0) {
          setSelectedJob((prev) =>
            prev
              ? list.find((j) => j.migration_id === prev.migration_id) || list[0]
              : list[0]
          );
        }
      } catch (err) {
        if (manual) {
          setErrorMsg(err.message || "No se pudo conectar con el servidor al actualizar los planes.");
        }
      } finally {
        if (manual) setRefreshingJobs(false);
      }
    },
    [initialJobId]
  );

  useEffect(() => {
    fetchJobs();
    fetchPersistence();
  }, [fetchJobs, fetchPersistence]);

  useEffect(() => {
    if (initialUseCase === "app_source" || initialUseCase === "vm_image") {
      setNewUseCase(initialUseCase);
    }
    if (initialJobId) {
      setMainTab("inspector");
    } else if (initialUseCase) {
      setMainTab("wizard");
    }
  }, [initialUseCase, initialJobId]);

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
      const branchToUse = data.default_branch || githubRef || "main";
      if (data.default_branch) setGithubRef(data.default_branch);
      const treeSummary = data.tree?.summary
        ? ` · Árbol: ${data.tree.summary.total_files} archivos, ${data.tree.summary.total_directories} carpetas/subcarpetas analizadas.`
        : "";

      // Automatically inspect the repository to populate the GitHub -> Cloud transformation map and decision options
      try {
        const inspectRes = await apiFetch("/api/v1/migration/use-case-1/inspect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_provider: newProvider,
            deployment_mode: deploymentMode,
            github_url: targetUrl,
            github_ref: branchToUse,
            github_token: activeToken?.trim() || undefined,
          }),
        });
        if (inspectRes.ok) {
          const inspectData = await inspectRes.json();
          setUc1PreInspection(inspectData);
          const catalogDecisions =
            inspectData.transformation_catalog?.applied_decisions ||
            inspectData.application?.transformation_catalog?.applied_decisions ||
            {};
          setUc1Decisions(catalogDecisions);
        }
      } catch {
        // Non-blocking if user wants to run manual inspect later
      }

      setStatusBanner(
        `Repositorio público '${data.repository?.full_name}' validado (${data.repository?.visibility}). Rama predeterminada: ${data.default_branch}. Lenguaje: ${data.repository?.language || "Detectado"}.${treeSummary} Revisa abajo el Mapa de Transformación GitHub → ${newProvider.toUpperCase()} y elige tus opciones.`
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

  const fetchEnrolledAgents = useCallback(async () => {
    try {
      const res = await apiFetch("/api/v1/agents");
      if (res.ok) {
        const data = await res.json();
        const remoteList = (data.agents || []).filter((a) => {
          if (a.is_control_plane) return false;
          const h = String(a.hostname || "").toLowerCase();
          if (
            h === "cloudmove-server" ||
            h === "localhost" ||
            /^[0-9a-f]{12}$/i.test(h)
          ) {
            return false;
          }
          return true;
        });
        setEnrolledAgents(remoteList);
      }
    } catch {
      // Ignore transient error
    }
  }, []);

  const handleGenerateAgentToken = async () => {
    setGeneratingAgentToken(true);
    setErrorMsg("");
    try {
      const res = await apiFetch("/api/v1/agents/enrollment-tokens", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ttl_seconds: 86400,
          max_uses: 10,
          org_id: "default",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "No se pudo generar el token del agente.");
      const saved = saveSessionAgentToken(data);
      setAgentTokenData(saved || data);
      await fetchEnrolledAgents();
      setStatusBanner(
        "Paso 1 completado: Token de agente remoto generado y almacenado de forma segura en la sesión del navegador. Ahora ejecuta el comando de instalación en el equipo origen (Paso 2)."
      );
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setGeneratingAgentToken(false);
    }
  };

  const handleQueryLiveDevices = useCallback(async (forced = false) => {
    setQueryingDevices(true);
    if (forced) setErrorMsg("");
    try {
      await fetchEnrolledAgents();
      const endpoint = forced
        ? "/api/v1/migration/use-case-2/probe-devices"
        : "/api/v1/migration/use-case-2/devices";
      const res = await apiFetch(endpoint, {
        ...(forced ? { method: "POST" } : {}),
        timeoutMs: 25000,
      });
      if (res.ok) {
        const data = await res.json();
        setHostDevicesData(data);
        if (data.primary_boot_device?.path) {
          setSelectedStorageDevice(data.primary_boot_device.path);
        }
      } else if (forced) {
        const err = await res.json().catch(() => ({}));
        setErrorMsg(err.detail || `Error HTTP ${res.status} consultando dispositivos del agente.`);
      }
    } catch (err) {
      if (forced) {
        setErrorMsg(err.message || "No se pudo consultar los dispositivos del agente remoto.");
      }
    } finally {
      setQueryingDevices(false);
    }
  }, [fetchEnrolledAgents]);

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
    setInspecting(true);
    setErrorMsg("");
    try {
      const payload = {
        target_provider: newProvider,
        deployment_mode: deploymentMode,
        user_decisions: Object.keys(uc1Decisions).length > 0 ? uc1Decisions : undefined,
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
        timeoutMs: 60000,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "No se pudo inspeccionar la aplicación.");
      setUc1PreInspection(data);
      const catalogDecisions =
        data.transformation_catalog?.applied_decisions ||
        data.application?.transformation_catalog?.applied_decisions ||
        {};
      setUc1Decisions(catalogDecisions);
      const gitInfo = data.application?.git_metadata
        ? ` · Git Commit: ${data.application.git_metadata.short_sha}`
        : "";
      setStatusBanner(
        `Inspección estática completada para '${data.application?.app_name}'${gitInfo}: ${data.application?.dependencies?.length || 0} dependencias detectadas y ${data.application?.secrets_redacted_count || 0} secretos redactados. Puedes personalizar abajo cómo se transformará cada elemento en ${newProvider.toUpperCase()}.`
      );
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setInspecting(false);
    }
  };

  // Pre-inspection handler for Case 2 (Binary header, live capture, & checksum check before plan)
  const handleInspectUseCase2 = async () => {
    const isLive = uc2SourceMode === "live_capture";
    if (!isLive && !imagePath.trim()) {
      setErrorMsg("Introduzca la ruta absoluta o relativa de la imagen de disco (.vmdk, .qcow2, .raw, .vhdx) a inspeccionar.");
      return;
    }
    setInspecting(true);
    setErrorMsg("");
    try {
      const activeAgentId = hostDevicesData?.agent_id || enrolledAgents[0]?.agent_id || undefined;
      const manifestOverride = isLive
        ? {
            format: uc2OutputFormat,
            selected_user_paths: selectedUserPaths,
            ...(uc2StageMeta?.stage_id ? { stage_id: uc2StageMeta.stage_id } : {}),
          }
        : {
            format: imageFormatOverride,
            source_file: imagePath.trim(),
          };
      const res = await apiFetch("/api/v1/migration/use-case-2/inspect", {
        method: "POST",
        timeoutMs: 60000,
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
          agent_id: isLive ? activeAgentId : undefined,
          user_decisions: uc2Decisions,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "No se pudo inspeccionar o capturar la imagen de SO.");
      setUc2PreInspection(data);
      const catDecisions =
        data.transformation_catalog?.applied_decisions ||
        data.manifest?.transformation_catalog?.applied_decisions;
      if (catDecisions) {
        setUc2Decisions((prev) => ({ ...prev, ...catDecisions }));
      }
      if (isLive) {
        let extra = "";
        if (data.stage_status?.ready && data.stage_status?.stage) {
          setUc2StageMeta(data.stage_status.stage);
          extra = ` · Archivos en Staging: ${data.stage_status.stage.files_count || 0} OK`;
        } else if (data.stage_status?.dispatched) {
          extra = " · Sincronización automática de archivos seleccionada iniciada en el agente.";
        } else if (data.stage_status?.upgrade_required) {
          extra = ` · Aviso: actualiza el agente (v${data.stage_status.agent_version}) o sube la carpeta/archivo desde el navegador para incluirlos en AWS.`;
        }
        setStatusBanner(
          `Captura de SO en vivo completada exitosamente: ${data.manifest?.os?.distro || "Linux"} (${data.manifest?.name}) · Formato ${data.manifest?.format} · SHA-256 ${data.manifest?.sha256?.slice(0, 16)}...${extra}`
        );
      } else {
        setStatusBanner(
          `Verificación binaria completada para '${data.manifest?.name || imagePath}': formato ${data.manifest?.binary_inspection?.detected_binary_format || imageFormatOverride} · SHA-256 ${data.manifest?.sha256?.slice(0, 16)}...`
        );
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setInspecting(false);
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
        if (Object.keys(uc1Decisions).length > 0) {
          sourceConfig.user_decisions = uc1Decisions;
        }
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
        const activeAgentId = hostDevicesData?.agent_id || enrolledAgents[0]?.agent_id || undefined;
        sourceConfig.image_path = isLive
          ? (uc2PreInspection?.manifest?.source_file || "live_system")
          : imagePath.trim();
        sourceConfig.manifest_override = isLive
          ? {
              format: uc2OutputFormat,
              selected_user_paths: selectedUserPaths,
              ...(uc2StageMeta?.stage_id ? { stage_id: uc2StageMeta.stage_id } : {}),
            }
          : {
              format: imageFormatOverride,
              source_file: imagePath.trim(),
            };
        sourceConfig.selected_user_paths = selectedUserPaths;
        if (isLive && activeAgentId) sourceConfig.agent_id = activeAgentId;
        if (isLive && uc2StageMeta?.stage_id) sourceConfig.stage_id = uc2StageMeta.stage_id;
        sourceConfig.require_live_memory_state = requireLiveRam;
        sourceConfig.prefer_continuous_replication = preferContinuousReplication;
        sourceConfig.capture_live_host = isLive;
        sourceConfig.source_type = isLive ? "live_server" : "standalone_offline_disk_image";
        sourceConfig.output_format = uc2OutputFormat;
        if (Object.keys(uc2Decisions).length > 0) {
          sourceConfig.user_decisions = uc2Decisions;
        }
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
        } else {
          planName = `Importación Imagen VM → ${newProvider.toUpperCase()}`;
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
      setMainTab("inspector");
      setInspectorTab("execution");
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

  useEffect(() => {
    if (newUseCase === "vm_image") {
      fetchEnrolledAgents();
      handleQueryLiveDevices(false);
    }
  }, [newUseCase, fetchEnrolledAgents, handleQueryLiveDevices]);

  useEffect(() => {
    if (selectedJob?.use_case === "app_source" || selectedJob?.use_case === "vm_image") {
      const cat = selectedJob?.source_environment?.transformation_catalog;
      const savedDecisions =
        cat?.applied_decisions ||
        selectedJob?.source_environment?.user_decisions ||
        selectedJob?.source_config?.user_decisions ||
        {};
      setJobDecisions(savedDecisions);
    }
  }, [selectedJob]);

  const handleUpdateJobDecisions = async () => {
    if (!selectedJob) return;
    setUpdatingDecisions(true);
    setErrorMsg("");
    setStatusBanner("");
    try {
      const res = await apiFetch(`/api/v1/migration/jobs/${selectedJob.migration_id}/decisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_decisions: jobDecisions }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "No se pudieron aplicar las decisiones de arquitectura.");
      }
      setSelectedJob(data);
      if (onActiveJobChange) onActiveJobChange(data);
      await fetchJobs(data.migration_id);
      setStatusBanner(
        `Decisiones de transformación GitHub → ${data.target_provider?.toUpperCase()} aplicadas. Se regeneró el subgrafo CMIR v2.1 y el código Terraform (main.tf, outputs.tf, user_data.sh).`
      );
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setUpdatingDecisions(false);
    }
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
      {/* Cabecera de Recurso AWS Cloudscape */}
      <AwsPageHeader
        title="Orquestador de migraciones"
        subtitle="Crea un plan, revísalo y ejecútalo paso a paso hacia Amazon Web Services (AWS)."
        badges={[
          ...(persistenceStatus
            ? [
                {
                  label: `BD: ${persistenceStatus.engine?.toUpperCase()} · v${persistenceStatus.current_schema_version}`,
                  className: "observed",
                },
              ]
            : []),
        ]}
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button
              type="button"
              className="cm-btn secondary"
              onClick={() => fetchJobs(null, true)}
              disabled={loading || inspecting || refreshingJobs}
            >
              {refreshingJobs ? "Actualizando..." : "Actualizar"}
            </button>
            <button
              type="button"
              className="cm-btn primary"
              onClick={() => setMainTab("wizard")}
            >
              Nueva migración
            </button>
          </div>
        }
      />

      {/* Resumen General del Orquestador (KeyValuePairs AWS Cloudscape) */}
      <AwsKeyValuePairs
        columns={3}
        items={[
          {
            label: "Planes registrados",
            value: `${jobs.length}`,
          },
          {
            label: "Plan activo",
            value: currentJob ? currentJob.name : "Ninguno",
          },
          {
            label: "Estado",
            value: currentJob ? (
              <AwsStatusIndicator
                type={
                  currentJob.state === "FAILED"
                    ? "error"
                    : currentJob.state === "COMPLETED" || currentJob.state === "READY_FOR_CUTOVER"
                    ? "success"
                    : "info"
                }
              >
                {currentJob.state}
              </AwsStatusIndicator>
            ) : (
              <AwsStatusIndicator type="pending">SIN PLAN ACTIVO</AwsStatusIndicator>
            ),
            subtext: currentJob ? opBadge.label : "Listo para iniciar evaluación",
          },
        ]}
      />

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
              <div style={{ fontWeight: 700, fontSize: 14, color: "#991b1b", marginBottom: 6 }}>
                Remediación Inmediata del Bloqueador Técnico de Hipervisor:
              </div>
              <p style={{ margin: "0 0 10px 0", fontSize: 13.5, color: "#374151", lineHeight: 1.45 }}>
                La migración de imágenes hacia AWS VM Import transfiere el estado persistente en disco tras un snapshot consistente (quiesce + sync), NO la memoria RAM volátil ni los sockets TCP abiertos. Selecciona una acción para avanzar a <strong>PLAN_READY</strong>:
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
                  Cambiar a Replicación Continua por Bloques (AWS MGN)
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

      {/* Navegación principal por tareas: una sola tarea visible a la vez */}
      <AwsTabs
        ariaLabel="Tareas del orquestador"
        activeTabId={mainTab}
        onTabChange={setMainTab}
        tabs={[
          { id: "wizard", label: "1. Crear migración" },
          { id: "inspector", label: "2. Plan activo", disabled: jobs.length === 0 },
          { id: "plans", label: "3. Historial de planes", count: jobs.length },
        ]}
      />

      {/* Paso 1: Selector de Caso de Uso y Asistente Guiado */}
      {mainTab === "wizard" && (
        <UseCaseWizardPanel
          wizardCollapsed={false}
          newUseCase={newUseCase}
          setNewUseCase={setNewUseCase}
          newName={newName}
          setNewName={setNewName}
          newProvider={newProvider}
          setNewProvider={setNewProvider}
          setGithubToken={setGithubToken}
          setShowAdvancedGithub={setShowAdvancedGithub}
          setStatusBanner={setStatusBanner}
          loading={loading}
          inspecting={inspecting}
          handleInspectUseCase1={handleInspectUseCase1}
          handleInspectUseCase2={handleInspectUseCase2}
          handleCreateMigration={handleCreateMigration}
          case1Props={{
            appPreset,
            setAppPreset,
            githubUrl,
            setGithubUrl,
            setGithubRepoData,
            setGithubTreeData,
            validatingGithub,
            handleValidateGithub,
            githubRepoData,
            githubTreeData,
            githubBranches,
            githubRef,
            setGithubRef,
            deploymentMode,
            setDeploymentMode,
            showAdvancedGithub,
            setShowAdvancedGithub,
            githubToken,
            setGithubToken,
            customAppPath,
            setCustomAppPath,
            uc1PreInspection,
            uc1Decisions,
            setUc1Decisions,
          }}
          case2Props={{
            showCase2HelpModal,
            setShowCase2HelpModal,
            uc2SourceMode,
            setUc2SourceMode,
            setUc2PreInspection,
            agentTokenData,
            enrolledAgents,
            generatingAgentToken,
            handleGenerateAgentToken,
            copiedAgentCmd,
            setCopiedAgentCmd,
            hostDevicesData,
            setHostDevicesData,
            selectedStorageDevice,
            setSelectedStorageDevice,
            queryingDevices,
            handleQueryLiveDevices,
            selectedUserPaths,
            setSelectedUserPaths,
            uc2Decisions,
            setUc2Decisions,
            setUc2StageMeta,
            uc2OutputFormat,
            setUc2OutputFormat,
            imagePath,
            setImagePath,
            imageFormatOverride,
            setImageFormatOverride,
            consistencyStrategy,
            setConsistencyStrategy,
            uc2PreInspection,
          }}
        />
      )}

      {/* Estado vacío: aún no hay planes (pestañas 2 y 3) */}
      {mainTab !== "wizard" && jobs.length === 0 && (
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
            <span className="cm-badge" style={{ backgroundColor: "#2563eb", color: "#ffffff", fontSize: 14, fontWeight: 700, padding: "4px 12px" }}>
              ORQUESTADOR
            </span>
          </div>
          <h3 style={{ margin: "0 0 8px 0", fontSize: 17, fontWeight: 700, color: "var(--color-text-primary)" }}>
            No hay planes de migración precargados
          </h3>
          <p style={{ margin: "0 0 16px 0", color: "var(--color-text-secondary)", fontSize: 15, maxWidth: 560, marginInline: "auto", lineHeight: 1.5 }}>
            Crea tu primer plan desde la pestaña «1. Crear migración».
          </p>
          <button type="button" className="cm-btn primary" onClick={() => setMainTab("wizard")}>
            Crear migración
          </button>
        </div>
      )}

      {/* Pestaña 3: Historial de planes registrados */}
      {mainTab === "plans" && jobs.length > 0 && (
        <div className="cm-card">
          <div className="cm-card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <span>Planes registrados ({jobs.length})</span>
            <button
              type="button"
              className="cm-btn sm danger"
              onClick={handleClearAllJobs}
              title="Eliminar todos los planes persistidos de la base de datos"
            >
              Eliminar todos
            </button>
          </div>
          <div className="cm-table-wrap">
            <table className="cm-table">
              <thead>
                <tr>
                  <th>Nombre</th>
                  <th>Caso</th>
                  <th>Destino</th>
                  <th>Estado</th>
                  <th style={{ textAlign: "right" }}>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => {
                  const isSelected = currentJob?.migration_id === job.migration_id;
                  const badgeKey = deriveOperationalStatusBadge(job);
                  const badgeMeta = OPERATIONAL_BADGE_MAP[badgeKey] || OPERATIONAL_BADGE_MAP.PLANNED;
                  const caseLabel =
                    job.use_case === "app_source"
                      ? "Caso 1 · Aplicación"
                      : "Caso 2 · Imagen SO/VM";
                  return (
                    <tr key={job.migration_id} style={isSelected ? { backgroundColor: "#F2F8FD" } : undefined}>
                      <td>
                        <strong>{job.name}</strong>
                        <div className="cm-hint">v{job.version || 1}</div>
                      </td>
                      <td>{caseLabel}</td>
                      <td>{job.target_provider?.toUpperCase()}</td>
                      <td>
                        <span className={`cm-badge ${badgeMeta.badgeClass}`}>{job.state}</span>
                      </td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        <button
                          type="button"
                          className="cm-btn sm primary"
                          onClick={() => {
                            setSelectedJob(job);
                            if (onActiveJobChange) onActiveJobChange(job);
                            setInspectorTab("execution");
                            setMainTab("inspector");
                          }}
                        >
                          Abrir
                        </button>{" "}
                        <button
                          type="button"
                          className="cm-btn sm danger"
                          onClick={() => handleDeleteJob(job.migration_id)}
                        >
                          Eliminar
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pestaña 2: Plan activo en inspección (ancho completo) */}
      {mainTab === "inspector" && jobs.length > 0 && currentJob && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {/* 1. Cabecera del Plan */}
            <div className="cm-card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
                <div style={{ flex: "1 1 360px", minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <h3 style={{ margin: 0, fontSize: 20, fontFamily: "var(--font-display)" }}>
                      {currentJob.name}
                    </h3>
                    <span className={`cm-badge ${opBadge.badgeClass}`}>
                      {opBadge.label}
                    </span>
                    <span className="cm-badge aws">
                      AWS
                    </span>
                  </div>
                  <div className="cm-hint" style={{ marginTop: 6 }}>
                    ID <code>{currentJob.migration_id}</code> · v{currentJob.version || 1} · {currentJob.completed_in_real_cloud ? "Ejecutado en nube real" : "Simulación (Dry-Run)"}
                  </div>
                  {jobs.length > 1 && (
                    <div className="cm-field" style={{ marginTop: 10, maxWidth: 480 }}>
                      <label htmlFor="mig-active-plan-select" className="cm-label">
                        Cambiar plan
                      </label>
                      <select
                        id="mig-active-plan-select"
                        className="cm-select"
                        value={currentJob.migration_id}
                        onChange={(e) => {
                          const next = jobs.find((j) => j.migration_id === e.target.value);
                          if (next) {
                            setSelectedJob(next);
                            if (onActiveJobChange) onActiveJobChange(next);
                          }
                        }}
                      >
                        {jobs.map((j) => (
                          <option key={j.migration_id} value={j.migration_id}>
                            {j.name} — {j.state}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>

                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="cm-btn sm danger"
                    onClick={() => handleDeleteJob(currentJob.migration_id)}
                    title="Eliminar este plan permanentemente"
                  >
                    Eliminar
                  </button>
                  <button
                    type="button"
                    className="cm-btn sm"
                    onClick={handleDownloadJobReport}
                  >
                    Evidencia JSON
                  </button>
                  <button
                    type="button"
                    className="cm-btn primary sm"
                    onClick={handleDownloadZipBundle}
                    title="Descargar paquete completo (.ZIP) con Terraform IaC, scripts de subida, cloud-init y guía paso a paso"
                  >
                    Descargar paquete (.ZIP)
                  </button>
                </div>
              </div>
            </div>

            {/* Sub-pestañas del plan: una sección enfocada a la vez */}
            <AwsTabs
              ariaLabel="Secciones del plan activo"
              activeTabId={inspectorTab}
              onTabChange={setInspectorTab}
              style={{ marginBottom: 0 }}
              tabs={[
                {
                  id: "execution",
                  label: "Ejecución y Despliegue",
                  badge:
                    currentJob.blockers?.length > 0 ? `${currentJob.blockers.length} bloqueo(s)` : undefined,
                },
                { id: "terraform_ops", label: "Consola Operativa Terraform" },
                { id: "target_arch", label: "Arquitectura Objetivo (Cloud)" },
                { id: "credentials", label: "Servicios Externos y Credenciales" },
                {
                  id: "source",
                  label:
                    currentJob.use_case === "app_source"
                      ? "GitHub → Nube"
                      : currentJob.use_case === "vm_image"
                      ? "SO / VM → Nube (Datos)"
                      : "Origen",
                },
                { id: "compatibility", label: "Fidelidad y pruebas" },
                { id: "iac", label: "Terraform y CMIR" },
                { id: "guide", label: "Guía de despliegue" },
              ]}
            />

            {inspectorTab === "execution" && (
            <div className="cm-card">
              <div className="cm-card-title">
                <span>Máquina de estados y acciones</span>
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
                      {isCompleted ? "[OK] " : `${idx + 1}. `}
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
            )}

            {/* 2. Bloqueadores Críticos y Advertencias de Compatibilidad */}
            {inspectorTab === "execution" && (currentJob.blockers?.length > 0 || currentJob.warnings?.length > 0) && (
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
                            <div style={{ fontWeight: 700, fontSize: 13.5, color: "#991b1b", marginBottom: 4 }}>
                              Remediación Operativa Requerida
                            </div>
                            <p style={{ margin: "0 0 10px 0", fontSize: 13, color: "#374151" }}>
                              La memoria RAM volátil no es transferible entre hipervisores. Selecciona el método de captura de disco:
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
                                Activar Replicación Continua por Bloques (AWS MGN)
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

            {/* Mapa de Transformación SO / VM -> Nube en Ejecución (Caso 2) */}
            {inspectorTab === "execution" && currentJob.use_case === "vm_image" && srcEnv && (
              <VmOsToCloudTransformationMap
                manifest={srcEnv}
                targetProvider={currentJob.target_provider}
              />
            )}

            {/* Ejecutor y Consola Operativa de Despliegue Automatizado Terraform */}
            {(inspectorTab === "execution" || inspectorTab === "terraform_ops") && (
              <AutomatedCloudDeployerPanel
                job={currentJob}
                onDeploymentCompleted={() => {
                  fetchJobs(currentJob.migration_id);
                  fetchPersistence();
                }}
              />
            )}

            {/* Vista de Arquitectura Objetivo en la Nube */}
            {inspectorTab === "target_arch" && (
              <TargetArchitectureView job={currentJob} />
            )}

            {/* Vista de Servicios Externos y Gestión de Credenciales */}
            {inspectorTab === "credentials" && (
              <ExternalServicesCredentialsCard
                job={currentJob}
                onCredentialsSaved={(creds) => {
                  setJobDecisions((prev) => ({ ...prev, ...creds }));
                }}
              />
            )}

            {/* =================================================================
                VISTAS ESPECÍFICAS DEL CASO 1: APLICACIÓN, DEPENDENCIAS Y SECRETOS
                ================================================================= */}
            {inspectorTab === "source" && currentJob.use_case === "app_source" && (
              <Case1SourceInspectionPanel
                currentJob={currentJob}
                srcEnv={srcEnv}
                envVars={envVars}
                appDependencies={appDependencies}
                appAssumptions={appAssumptions}
                jobDecisions={jobDecisions}
                onSelectDecision={(itemId, optId) =>
                  setJobDecisions((prev) => ({ ...prev, [itemId]: optId }))
                }
                onApplyToExistingJob={handleUpdateJobDecisions}
                updatingDecisions={updatingDecisions}
                onAttachGithub={() => {
                  setNewUseCase("app_source");
                  setAppPreset("github");
                  setMainTab("wizard");
                }}
              />
            )}

            {inspectorTab === "compatibility" && currentJob.use_case === "app_source" && (
              <Case1CompatibilityInspectionPanel
                currentJob={currentJob}
                diffReport={diffReport}
              />
            )}

            {/* =================================================================
                VISTAS ESPECÍFICAS DEL CASO 2: IMAGEN COMPLETA DE SO / VM
                ================================================================= */}
            {inspectorTab === "source" && binaryInspection && (
              <Case2SourceInspectionPanel
                currentJob={currentJob}
                srcEnv={srcEnv}
                binaryInspection={binaryInspection}
                stagingVerification={stagingVerification}
                disks={disks}
                jobDecisions={jobDecisions}
                onSelectDecision={(itemId, optId) =>
                  setJobDecisions((prev) => ({ ...prev, [itemId]: optId }))
                }
                onApplyToExistingJob={handleUpdateJobDecisions}
                updatingDecisions={updatingDecisions}
              />
            )}

            {inspectorTab === "compatibility" && (
              <Case2CompatibilityInspectionPanel
                currentJob={currentJob}
                fidelityDims={fidelityDims}
                fidelityFilter={fidelityFilter}
                setFidelityFilter={setFidelityFilter}
                diffReport={diffReport}
              />
            )}

            {/* Etapas Ordenadas del Plan de Migración (12 etapas Caso 1 / 13 etapas Caso 2) */}
            {inspectorTab === "execution" && (
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
                      className="cm-step-card"
                      style={{
                        borderColor: isDone
                          ? "var(--color-health-healthy-border)"
                          : isFailed
                          ? "var(--color-health-error-border)"
                          : "var(--color-border-subtle)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <strong style={{ fontSize: 14 }}>
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
                      <div style={{ fontSize: 13.5, color: "var(--color-text-secondary)", marginTop: 4 }}>
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
            )}

            {/* Resultados de Pruebas de Arranque / Pre-Cutover y Validación Post-Cutover */}
            {inspectorTab === "compatibility" && !fidelityDims && !diffReport && !preCutover && !postCutover && (
              <div className="cm-alert info">
                Aún no hay resultados de fidelidad ni pruebas para este plan. Aparecerán al avanzar las etapas desde la pestaña «Ejecución».
              </div>
            )}
            {inspectorTab === "compatibility" && (preCutover || postCutover) && (
              <div className="cm-card">
                <div className="cm-card-title">
                  <span>Resultados de Pruebas de Arranque de VM, Smoke Tests y Validación de Cutover</span>
                  <span className="cm-badge validated">Evidencia de Pruebas</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>
                  {preCutover && (
                    <div className="cm-card-subtle">
                      <strong style={{ fontSize: 14, display: "block", marginBottom: 6 }}>
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
                      <strong style={{ fontSize: 14, display: "block", marginBottom: 6 }}>
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
            {inspectorTab === "iac" && (
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
                      <div style={{ fontWeight: 700, fontSize: 14 }}>{node.name}</div>
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
            )}

            {/* Artefactos Terraform HCL y Runbooks Generados */}
            {inspectorTab === "iac" && currentJob.generated_artifacts?.files && (
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
            {inspectorTab === "guide" && !currentJob.generated_artifacts?.files && (
              <div className="cm-alert info">
                La guía de despliegue estará disponible cuando el plan genere sus artefactos (Terraform y scripts).
              </div>
            )}
            {inspectorTab === "guide" && currentJob.generated_artifacts?.files && (
              <CloudRunbookGuidePanel
                currentJob={currentJob}
                showDeploymentGuide={showDeploymentGuide}
                setShowDeploymentGuide={setShowDeploymentGuide}
                handleDownloadZipBundle={handleDownloadZipBundle}
                handleDownloadDiskImage={handleDownloadDiskImage}
                handleDownloadSystemImage={handleDownloadSystemImage}
                handleDownloadHypervisorScript={handleDownloadHypervisorScript}
                handleDownloadFile={handleDownloadFile}
              />
            )}
          </div>
      )}
    </div>
  );
}
