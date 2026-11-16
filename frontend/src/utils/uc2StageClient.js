/**
 * Shared Case 2 staging transfer client used by both UserFileSelectionPanel
 * and Case2AwsValidationView to avoid duplicating chunked upload or agent-sync logic.
 */

import { apiFetch } from "./apiClient";

const SKIP_DIRS = new Set([".git", "node_modules", "__pycache__", ".cache", ".venv", "venv"]);
const MAX_SINGLE_FILE_BYTES = 150 * 1024 * 1024; // 150 MiB per file cap
const MAX_STAGE_TOTAL_BYTES = 1450 * 1024 * 1024; // ~1.45 GiB safe staging cap
const BATCH_MAX_BYTES = 6 * 1024 * 1024;
const BATCH_MAX_FILES = 25;

async function fileToBase64(file) {
  const buf = await file.arrayBuffer();
  const bytes = new Uint8Array(buf);
  const chunk = 0x4000;
  const parts = [];
  for (let i = 0; i < bytes.length; i += chunk) {
    parts.push(String.fromCharCode.apply(null, bytes.subarray(i, i + chunk)));
  }
  return btoa(parts.join(""));
}

export function resolveBrowserRelativePath(file, selectedPaths = []) {
  const rawRel = String(file?.webkitRelativePath || file?.name || "").replace(/\\/g, "/").replace(/^\/+/, "");
  const cleanSegs = rawRel.split("/").filter((s) => s && s !== "." && s !== "..");
  if (cleanSegs.length === 0) return null;

  const firstSeg = cleanSegs[0];
  const matchedRoot = (selectedPaths || []).find((sp) => {
    const cleanSp = String(sp || "").trim().replace(/\/+$/, "");
    const base = cleanSp.split("/").filter(Boolean).pop();
    return base && base === firstSeg;
  });

  if (matchedRoot) {
    const parentPrefix = matchedRoot.trim().replace(/^\/+/, "").replace(/\/+$/, "");
    const suffix = cleanSegs.slice(1).join("/");
    return suffix ? `${parentPrefix}/${suffix}` : parentPrefix;
  }

  const fallbackHome = (selectedPaths || []).find((sp) => String(sp || "").includes("/home/"));
  if (fallbackHome) {
    const homeParts = fallbackHome.trim().replace(/^\/+/, "").split("/");
    const userHome = homeParts.length >= 2 ? `${homeParts[0]}/${homeParts[1]}` : "home/user";
    return `${userHome}/${cleanSegs.join("/")}`;
  }
  return cleanSegs.join("/");
}

export async function fetchUc2StageStatus({ stageId, migrationId, selectedPaths } = {}) {
  const params = new URLSearchParams();
  if (stageId) params.set("stage_id", stageId);
  if (migrationId) params.set("migration_id", migrationId);
  if (selectedPaths && selectedPaths.length > 0) {
    params.set("paths", JSON.stringify(selectedPaths));
  }
  const res = await apiFetch(`/api/v1/migration/uc2-stage/status?${params.toString()}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Error HTTP ${res.status} consultando estado de staging.`);
  }
  return res.json();
}

export async function dispatchUc2AgentStage({ selectedPaths, migrationId, agentId } = {}) {
  const res = await apiFetch("/api/v1/migration/uc2-stage/dispatch-agent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      selected_paths: selectedPaths || [],
      migration_id: migrationId || null,
      agent_id: agentId || null,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Error HTTP ${res.status} despachando sincronización al agente.`);
  }
  return data;
}

export async function uploadBrowserFolderToStage({
  fileList,
  selectedPaths = [],
  migrationId = null,
  ec2Ip = null,
  stageId = null,
  onProgress,
}) {
  const rawFiles = Array.from(fileList || []);
  const accepted = [];
  const skipped = [];
  let accBytes = 0;

  // Sort smallest first so documents/configs are never starved if folder contains huge binaries
  const prepared = rawFiles
    .map((f) => ({
      file: f,
      rel: resolveBrowserRelativePath(f, selectedPaths),
      size: Number(f.size || 0),
    }))
    .filter((item) => {
      if (!item.rel) return false;
      const segs = item.rel.split("/");
      return !segs.some((s) => SKIP_DIRS.has(s));
    })
    .sort((a, b) => a.size - b.size);

  for (const item of prepared) {
    if (item.size > MAX_SINGLE_FILE_BYTES) {
      skipped.push({ path: `/${item.rel}`, size: item.size, reason: "exceeds_150mb" });
      continue;
    }
    if (accBytes + item.size > MAX_STAGE_TOTAL_BYTES) {
      skipped.push({ path: `/${item.rel}`, size: item.size, reason: "exceeds_stage_cap" });
      continue;
    }
    accepted.push(item);
    accBytes += item.size;
  }

  if (accepted.length === 0) {
    throw new Error("No se encontraron archivos válidos (<= 150 MiB c/u) dentro de la selección.");
  }

  const initRes = await apiFetch("/api/v1/migration/uc2-stage/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      stage_id: stageId || null,
      selected_paths: selectedPaths,
      migration_id: migrationId || null,
    }),
  });
  const initData = await initRes.json().catch(() => ({}));
  if (!initRes.ok) {
    throw new Error(initData.detail || "No se pudo inicializar la sesión de staging.");
  }
  const activeStageId = initData.stage_id;

  let uploadedCount = 0;
  let uploadedBytes = 0;
  let cursor = 0;
  while (cursor < accepted.length) {
    const batch = [];
    let batchBytes = 0;
    while (
      cursor < accepted.length &&
      batch.length < BATCH_MAX_FILES &&
      (batch.length === 0 || batchBytes + accepted[cursor].size <= BATCH_MAX_BYTES)
    ) {
      batch.push(accepted[cursor]);
      batchBytes += accepted[cursor].size;
      cursor += 1;
    }

    const encodedFiles = await Promise.all(
      batch.map(async (b) => ({
        rel_path: b.rel,
        content_b64: await fileToBase64(b.file),
      }))
    );

    const upRes = await apiFetch(`/api/v1/migration/uc2-stage/${encodeURIComponent(activeStageId)}/upload-files`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        files: encodedFiles,
        selected_paths: selectedPaths,
      }),
    });
    const upData = await upRes.json().catch(() => ({}));
    if (!upRes.ok) {
      throw new Error(upData.detail || `Error subiendo lote (${uploadedCount}/${accepted.length}).`);
    }
    uploadedCount += batch.length;
    uploadedBytes += batchBytes;
    if (onProgress) {
      onProgress({
        phase: "uploading",
        uploadedFiles: uploadedCount,
        totalFiles: accepted.length,
        uploadedBytes,
        totalBytes: accBytes,
        percent: Math.round((uploadedCount / accepted.length) * 100),
      });
    }
  }

  if (onProgress) {
    onProgress({
      phase: "committing",
      uploadedFiles: accepted.length,
      totalFiles: accepted.length,
      uploadedBytes: accBytes,
      totalBytes: accBytes,
      percent: 100,
    });
  }

  const commitRes = await apiFetch(`/api/v1/migration/uc2-stage/${encodeURIComponent(activeStageId)}/commit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      selected_paths: selectedPaths,
      migration_id: migrationId || null,
      ec2_ip: ec2Ip || null,
    }),
  });
  const commitData = await commitRes.json().catch(() => ({}));
  if (!commitRes.ok) {
    throw new Error(commitData.detail || "Error al empaquetar archivos en staging.");
  }

  return {
    ...commitData,
    skipped_client_files: skipped,
  };
}
