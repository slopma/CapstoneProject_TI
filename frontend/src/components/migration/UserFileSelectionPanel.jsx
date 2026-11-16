import React, { useState, useMemo, useEffect } from "react";
import { AwsStatusIndicator, AwsAlert } from "../cloudscape/AwsPrimitives";
import Uc2StageTransferBox from "./Uc2StageTransferBox";

const SELECTED_PATHS_STORAGE_KEY = "cm_case2_selected_user_paths_v1";

export function loadSavedSelectedUserPaths() {
  if (typeof window === "undefined" || !window.sessionStorage) return null;
  try {
    const raw = window.sessionStorage.getItem(SELECTED_PATHS_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function saveSelectedUserPathsToSession(paths) {
  if (typeof window === "undefined" || !window.sessionStorage) return;
  try {
    window.sessionStorage.setItem(SELECTED_PATHS_STORAGE_KEY, JSON.stringify(paths));
  } catch {
    // Ignore storage error
  }
}

function formatSizeHuman(bytes) {
  const b = Number(bytes || 0);
  if (b <= 0) return "0 KB";
  if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(2)} GiB`;
  if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(2)} MiB`;
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KiB`;
  return `${b} B`;
}

function flattenTreeMap(nodes, map = new Map()) {
  (nodes || []).forEach((n) => {
    if (!n || !n.path) return;
    map.set(n.path, n);
    if (Array.isArray(n.children) && n.children.length > 0) {
      flattenTreeMap(n.children, map);
    }
  });
  return map;
}

export default function UserFileSelectionPanel({
  filesystemTree = [],
  selectedPaths = [],
  onChangeSelectedPaths,
  maxAwsStorageGib = 30.0,
  baseOsOverheadGib = 2.5,
  awsAcademyAccountLimitGib = 150.0,
  onUpgradeStorageProfile,
  onRefreshAgentInventory,
  refreshing = false,
  onProceedToMigration,
  hostname = "dispositivo-local",
  agentId = null,
  onStageReady,
}) {
  const [expandedPaths, setExpandedPaths] = useState(() => {
    const init = new Set();
    (filesystemTree || []).forEach((r) => {
      if (r?.path) init.add(r.path);
    });
    return init;
  });
  const [searchFilter, setSearchFilter] = useState("");
  const [customPathInput, setCustomPathInput] = useState("");
  const [customNodes, setCustomNodes] = useState([]);
  const [quotaError, setQuotaError] = useState("");

  useEffect(() => {
    if (filesystemTree && filesystemTree.length > 0) {
      setExpandedPaths((prev) => {
        const next = new Set(prev);
        filesystemTree.forEach((r) => {
          if (r?.path) next.add(r.path);
        });
        return next;
      });
    }
  }, [filesystemTree]);

  const combinedTree = useMemo(() => {
    return [...(filesystemTree || []), ...customNodes];
  }, [filesystemTree, customNodes]);

  const nodeByPath = useMemo(() => flattenTreeMap(combinedTree), [combinedTree]);

  // Auto-initialize default selection (first user home subfolders that fit in quota) if empty
  useEffect(() => {
    if (combinedTree.length > 0 && (!selectedPaths || selectedPaths.length === 0)) {
      const saved = loadSavedSelectedUserPaths();
      if (saved && saved.length > 0) {
        const validSaved = saved.filter((p) => nodeByPath.has(p));
        if (validSaved.length > 0 && onChangeSelectedPaths) {
          onChangeSelectedPaths(validSaved);
          return;
        }
      }
      const defaults = [];
      let runningBytes = 0;
      const maxBytes = Math.max(0, (maxAwsStorageGib - baseOsOverheadGib) * 1024 ** 3);
      combinedTree.forEach((root) => {
        if (root.category === "user_home" && Array.isArray(root.children) && root.children.length > 0) {
          root.children.forEach((child) => {
            const sz = Number(child.size_bytes || 0);
            if (runningBytes + sz <= maxBytes) {
              defaults.push(child.path);
              runningBytes += sz;
            }
          });
        } else if (root.category === "system_config") {
          const sz = Number(root.size_bytes || 0);
          if (runningBytes + sz <= maxBytes) {
            defaults.push(root.path);
            runningBytes += sz;
          }
        }
      });
      if (defaults.length > 0 && onChangeSelectedPaths) {
        saveSelectedUserPathsToSession(defaults);
        onChangeSelectedPaths(defaults);
      }
    }
  }, [combinedTree, nodeByPath, maxAwsStorageGib, baseOsOverheadGib]);

  const selectedSet = useMemo(() => new Set(selectedPaths || []), [selectedPaths]);

  // Calculate deduplicated size (if parent folder is selected, don't double-count its child)
  const selectionStats = useMemo(() => {
    const activePaths = Array.from(selectedSet);
    const effectivePaths = activePaths.filter((p) => {
      return !activePaths.some(
        (other) => other !== p && p.startsWith(other.endsWith("/") ? other : `${other}/`)
      );
    });
    let totalBytes = 0;
    let totalFiles = 0;
    const itemsDetail = [];
    effectivePaths.forEach((p) => {
      const node = nodeByPath.get(p);
      if (node) {
        totalBytes += Number(node.size_bytes || 0);
        totalFiles += Number(node.files_count || 1);
        itemsDetail.push({
          path: node.path,
          name: node.name,
          type: node.type,
          size_bytes: node.size_bytes || 0,
          size_mb: node.size_mb || 0,
          size_gib: node.size_gib || 0,
          files_count: node.files_count || 1,
        });
      } else {
        itemsDetail.push({
          path: p,
          name: p.split("/").pop() || p,
          type: "custom_path",
          size_bytes: 0,
          size_mb: 0,
          size_gib: 0,
          files_count: 1,
        });
      }
    });
    const totalMb = totalBytes / (1024 * 1024);
    const totalGib = totalBytes / 1024 ** 3;
    const totalWithOsGib = baseOsOverheadGib + totalGib;
    const remainingGib = Math.max(0, maxAwsStorageGib - totalWithOsGib);
    const percentUsed = Math.min(100, Math.round((totalWithOsGib / maxAwsStorageGib) * 100));
    const exceedsQuota = totalWithOsGib > maxAwsStorageGib;

    return {
      count: effectivePaths.length,
      totalBytes,
      totalMb,
      totalGib,
      totalWithOsGib,
      remainingGib,
      percentUsed,
      exceedsQuota,
      itemsDetail,
    };
  }, [selectedSet, nodeByPath, baseOsOverheadGib, maxAwsStorageGib]);

  const updateSelection = (nextPathsArray) => {
    saveSelectedUserPathsToSession(nextPathsArray);
    if (onChangeSelectedPaths) {
      onChangeSelectedPaths(nextPathsArray);
    }
  };

  const handleTogglePath = (node) => {
    setQuotaError("");
    const path = node.path;
    const next = new Set(selectedSet);

    if (next.has(path)) {
      next.delete(path);
      // Also uncheck any children inside it
      Array.from(next).forEach((p) => {
        if (p.startsWith(`${path}/`)) next.delete(p);
      });
      updateSelection(Array.from(next));
      return;
    }

    // Check if adding this node would exceed the AWS EBS storage limit
    const nodeGib = Number(node.size_bytes || 0) / 1024 ** 3;
    if (selectionStats.totalWithOsGib + nodeGib > maxAwsStorageGib) {
      setQuotaError(
        `No se puede agregar '${node.path}' (${formatSizeHuman(
          node.size_bytes
        )}) porque superaría el límite de almacenamiento AWS EBS configurado (${maxAwsStorageGib} GiB). Desmarca otros archivos o amplía el perfil de volumen EBS.`
      );
      return;
    }

    // Remove redundant child paths if selecting a parent directory
    Array.from(next).forEach((p) => {
      if (p.startsWith(`${path}/`)) next.delete(p);
    });
    next.add(path);
    updateSelection(Array.from(next));
  };

  const handleSelectAllUserHome = () => {
    setQuotaError("");
    const next = [];
    let accBytes = 0;
    const maxUserBytes = Math.max(0, (maxAwsStorageGib - baseOsOverheadGib) * 1024 ** 3);
    let skipped = 0;

    combinedTree.forEach((root) => {
      if (root.category === "user_home" && Array.isArray(root.children)) {
        root.children.forEach((ch) => {
          const sz = Number(ch.size_bytes || 0);
          if (accBytes + sz <= maxUserBytes) {
            next.push(ch.path);
            accBytes += sz;
          } else {
            skipped += 1;
          }
        });
      }
    });
    if (skipped > 0) {
      setQuotaError(
        `Se seleccionaron las carpetas que caben dentro del límite de ${maxAwsStorageGib} GiB en AWS. ${skipped} carpeta(s) pesada(s) se omitieron para no exceder la cuota.`
      );
    }
    updateSelection(next);
  };

  const handleAddCustomPath = (e) => {
    e.preventDefault();
    const clean = customPathInput.trim();
    if (!clean || !clean.startsWith("/")) return;
    if (!nodeByPath.has(clean)) {
      setCustomNodes((prev) => [
        ...prev,
        {
          id: clean,
          path: clean,
          name: clean.split("/").pop() || clean,
          type: "directory",
          category: "custom",
          owner: "user",
          size_bytes: 50 * 1024 * 1024,
          size_mb: 50,
          size_gib: 0.05,
          files_count: 1,
          children: [],
        },
      ]);
    }
    const next = new Set(selectedSet);
    next.add(clean);
    updateSelection(Array.from(next));
    setCustomPathInput("");
  };

  const toggleExpand = (path) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const renderNodeRow = (node, depth = 0) => {
    if (!node || !node.path) return null;
    const q = searchFilter.trim().toLowerCase();
    const selfMatches =
      !q ||
      node.path.toLowerCase().includes(q) ||
      (node.name || "").toLowerCase().includes(q);
    const matchingChildren = (node.children || []).filter(
      (c) =>
        !q ||
        c.path?.toLowerCase().includes(q) ||
        c.name?.toLowerCase().includes(q) ||
        (c.children || []).some(
          (gc) => gc.path?.toLowerCase().includes(q) || gc.name?.toLowerCase().includes(q)
        )
    );
    if (!selfMatches && matchingChildren.length === 0) return null;

    const isChecked =
      selectedSet.has(node.path) ||
      Array.from(selectedSet).some((p) => node.path.startsWith(`${p}/`));
    const isParentChecked =
      !selectedSet.has(node.path) &&
      Array.from(selectedSet).some((p) => node.path.startsWith(`${p}/`));
    const hasChildren = Array.isArray(node.children) && node.children.length > 0;
    const isExpanded = expandedPaths.has(node.path) || Boolean(q);

    return (
      <React.Fragment key={node.path}>
        <tr
          style={{
            backgroundColor: isChecked ? "#f2f8fd" : depth === 0 ? "#fafafa" : "#ffffff",
            borderBottom: "1px solid #eaeded",
          }}
        >
          <td style={{ paddingLeft: 12 + depth * 22 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={isChecked}
                disabled={isParentChecked}
                onChange={() => handleTogglePath(node)}
                style={{ cursor: isParentChecked ? "not-allowed" : "pointer" }}
                aria-label={`Seleccionar ${node.path}`}
              />
              {hasChildren ? (
                <button
                  type="button"
                  onClick={() => toggleExpand(node.path)}
                  style={{
                    border: "1px solid #d5dbdb",
                    background: "#ffffff",
                    borderRadius: 3,
                    width: 20,
                    height: 20,
                    fontSize: 11,
                    lineHeight: 1,
                    cursor: "pointer",
                    color: "#0972d3",
                    fontWeight: 700,
                  }}
                  title={isExpanded ? "Contraer carpeta" : "Ver archivos y subcarpetas"}
                >
                  {isExpanded ? "▾" : "▸"}
                </button>
              ) : (
                <span style={{ display: "inline-block", width: 20, textAlign: "center", color: "#5f6b7a" }}>
                  {node.type === "file" ? "·" : "▸"}
                </span>
              )}
              <div>
                <strong style={{ fontSize: 13.5, color: "#000716" }}>{node.name}</strong>
                {node.label && (
                  <span className="cm-badge info" style={{ marginLeft: 8, fontSize: 11 }}>
                    {node.label}
                  </span>
                )}
                <div style={{ fontSize: 11.5, color: "#5f6b7a", fontFamily: "monospace" }}>
                  {node.path}
                </div>
              </div>
            </div>
          </td>
          <td>
            <span className={`cm-badge ${node.type === "file" ? "simulated" : "observed"}`}>
              {node.type === "file" ? "Archivo" : "Carpeta"}
            </span>
          </td>
          <td>
            <code>{node.owner || "root"}</code>
          </td>
          <td>
            {node.type === "file" ? "1 archivo" : `${node.files_count || 0} archivo(s)`}
          </td>
          <td style={{ textAlign: "right", fontWeight: 700, fontFamily: "monospace" }}>
            {formatSizeHuman(node.size_bytes)}
          </td>
        </tr>
        {hasChildren &&
          isExpanded &&
          (q ? matchingChildren : node.children).map((child) => renderNodeRow(child, depth + 1))}
      </React.Fragment>
    );
  };

  return (
    <div
      style={{
        backgroundColor: "#ffffff",
        border: "1.5px solid #0972d3",
        borderRadius: 6,
        padding: "16px 18px",
        marginTop: 14,
        marginBottom: 14,
      }}
    >
      {/* Cabecera */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          flexWrap: "wrap",
          gap: 12,
          marginBottom: 12,
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span className="cm-badge aws">SELECCIÓN DE ARCHIVOS Y CUOTA AWS</span>
            <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#000716" }}>
              Carpetas y Archivos del Dispositivo Local ({hostname}) a Migrar hacia AWS
            </h4>
          </div>
          <p style={{ margin: "4px 0 0 0", fontSize: 13, color: "#414d5c" }}>
            Explora las carpetas y archivos reales descubiertos por el agente en tu equipo y selecciona cuáles deseas incluir en la migración teniendo en cuenta el límite de almacenamiento de Amazon EBS en AWS.
          </p>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {onRefreshAgentInventory && (
            <button
              type="button"
              className="cm-btn sm"
              onClick={onRefreshAgentInventory}
              disabled={refreshing}
            >
              {refreshing ? "Escaneando carpetas..." : "Re-escanear carpetas del agente"}
            </button>
          )}
          {onProceedToMigration && (
            <button
              type="button"
              className="cm-btn primary sm"
              onClick={() => onProceedToMigration( Array.from(selectedSet), selectionStats )}
              disabled={selectionStats.count === 0 || selectionStats.exceedsQuota}
            >
              Migrar {selectionStats.count} ruta(s) seleccionada(s) en Caso 2 →
            </button>
          )}
        </div>
      </div>

      {/* Medidor de Cuota de Almacenamiento AWS EBS */}
      <div
        style={{
          backgroundColor: "#f8fafc",
          border: `1px solid ${selectionStats.exceedsQuota ? "#d91515" : "#cbd5e1"}`,
          borderRadius: 6,
          padding: "12px 14px",
          marginBottom: 12,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 8,
            marginBottom: 6,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <strong style={{ fontSize: 13.5, color: "#000716" }}>
              Capacidad requerida en AWS EBS: {selectionStats.totalWithOsGib.toFixed(2)} GiB / {maxAwsStorageGib} GiB ({selectionStats.percentUsed}%)
            </strong>
            <AwsStatusIndicator
              type={
                selectionStats.exceedsQuota
                  ? "error"
                  : selectionStats.percentUsed > 80
                  ? "warning"
                  : "success"
              }
            >
              {selectionStats.exceedsQuota
                ? "Excede límite de volumen AWS"
                : `${selectionStats.remainingGib.toFixed(2)} GiB disponibles en volumen AWS`}
            </AwsStatusIndicator>
          </div>
          <div style={{ fontSize: 12.5, color: "#414d5c" }}>
            SO Base: <strong>{baseOsOverheadGib.toFixed(2)} GiB</strong> · Archivos seleccionados:{" "}
            <strong>
              {formatSizeHuman(selectionStats.totalBytes)} ({selectionStats.count} ruta(s))
            </strong>{" "}
            · Cuota máx. cuenta AWS Academy: <strong>{awsAcademyAccountLimitGib} GiB</strong>
          </div>
        </div>

        {/* Barra de progreso segmentada */}
        <div
          style={{
            width: "100%",
            height: 12,
            backgroundColor: "#e2e8f0",
            borderRadius: 6,
            overflow: "hidden",
            display: "flex",
          }}
        >
          <div
            style={{
              width: `${Math.min(100, (baseOsOverheadGib / maxAwsStorageGib) * 100)}%`,
              backgroundColor: "#0972d3",
            }}
            title={`Sistema Operativo Base: ${baseOsOverheadGib} GiB`}
          />
          <div
            style={{
              width: `${Math.min(
                100 - Math.min(100, (baseOsOverheadGib / maxAwsStorageGib) * 100),
                (selectionStats.totalGib / maxAwsStorageGib) * 100
              )}%`,
              backgroundColor: selectionStats.exceedsQuota
                ? "#d91515"
                : selectionStats.percentUsed > 80
                ? "#f59e0b"
                : "#037f0c",
            }}
            title={`Archivos del usuario seleccionados: ${selectionStats.totalGib.toFixed(2)} GiB`}
          />
        </div>
      </div>

      {/* Control de Carga Real a Staging AWS (Agente o Navegador) */}
      <Uc2StageTransferBox
        selectedPaths={Array.from(selectedSet)}
        agentId={agentId}
        onStageReady={onStageReady}
      />

      {quotaError && (
        <AwsAlert
          type="warning"
          title="Control de límite de almacenamiento AWS"
          onDismiss={() => setQuotaError("")}
          style={{ marginBottom: 12 }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <span>{quotaError}</span>
            {onUpgradeStorageProfile && maxAwsStorageGib < 100 && (
              <button
                type="button"
                className="cm-btn primary sm"
                onClick={() => {
                  onUpgradeStorageProfile("aws_academy_max_100gb");
                  setQuotaError("");
                }}
              >
                Ampliar límite de volumen EBS a 100 GiB gp3
              </button>
            )}
          </div>
        </AwsAlert>
      )}

      {/* Barra de Herramientas y Búsqueda de Carpetas/Archivos */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 8,
          marginBottom: 10,
        }}
      >
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button
            type="button"
            className="cm-btn sm"
            onClick={handleSelectAllUserHome}
          >
            Seleccionar carpetas de usuario (/home)
          </button>
          <button
            type="button"
            className="cm-btn sm"
            onClick={() => {
              setQuotaError("");
              updateSelection([]);
            }}
          >
            Limpiar selección
          </button>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input
            type="search"
            className="cm-input"
            placeholder="Filtrar carpetas o archivos por nombre..."
            value={searchFilter}
            onChange={(e) => setSearchFilter(e.target.value)}
            style={{ width: 250, height: 32, fontSize: 13 }}
          />
          <form onSubmit={handleAddCustomPath} style={{ display: "flex", gap: 4 }}>
            <input
              type="text"
              className="cm-input"
              placeholder="/ruta/adicional/a/migrar"
              value={customPathInput}
              onChange={(e) => setCustomPathInput(e.target.value)}
              style={{ width: 210, height: 32, fontSize: 12.5 }}
            />
            <button type="submit" className="cm-btn sm">
              + Incluir ruta
            </button>
          </form>
        </div>
      </div>

      {/* Tabla Jerárquica de Carpetas y Archivos */}
      {combinedTree.length === 0 ? (
        <div
          style={{
            padding: "20px 16px",
            textAlign: "center",
            backgroundColor: "#f8fafc",
            borderRadius: 6,
            border: "1px dashed #cbd5e1",
            color: "#414d5c",
            fontSize: 13.5,
          }}
        >
          El agente conectado está sincronizando el árbol de carpetas y archivos del dispositivo. Haz clic en{" "}
          <strong>Re-escanear carpetas del agente</strong> para actualizar la vista.
        </div>
      ) : (
        <div className="cm-table-wrap" style={{ maxHeight: 380, overflowY: "auto" }}>
          <table className="cm-table" style={{ margin: 0 }}>
            <thead>
              <tr>
                <th>Carpeta / Archivo del Dispositivo Local</th>
                <th>Tipo</th>
                <th>Propietario</th>
                <th>Contenido</th>
                <th style={{ textAlign: "right" }}>Tamaño Real</th>
              </tr>
            </thead>
            <tbody>{combinedTree.map((rootNode) => renderNodeRow(rootNode, 0))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
