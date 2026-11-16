import React, { useState } from "react";

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function getFileBadge(name, ext, isManifest) {
  const lower = (name || "").toLowerCase();
  if (lower.includes("dockerfile")) return { label: "DOCKER", bg: "#e0f2fe", color: "#0369a1" };
  if (lower.includes("docker-compose") || lower.includes("compose.")) return { label: "COMPOSE", bg: "#e0e7ff", color: "#4338ca" };
  if (lower.startsWith(".env") || lower.endsWith(".env")) return { label: "ENV", bg: "#fef3c7", color: "#b45309" };
  if (ext === ".py") return { label: "PY", bg: "#ecfdf5", color: "#047857" };
  if ([".js", ".jsx", ".mjs"].includes(ext)) return { label: "JS", bg: "#fef9c3", color: "#a16207" };
  if ([".ts", ".tsx"].includes(ext)) return { label: "TS", bg: "#eff6ff", color: "#1d4ed8" };
  if (ext === ".java") return { label: "JAVA", bg: "#ffedd5", color: "#c2410c" };
  if (ext === ".go") return { label: "GO", bg: "#cffafe", color: "#0e7490" };
  if (ext === ".rs") return { label: "RUST", bg: "#fee2e2", color: "#b91c1c" };
  if ([".json", ".yaml", ".yml", ".toml"].includes(ext)) return { label: "CONF", bg: "#f1f5f9", color: "#475569" };
  if (ext === ".sql") return { label: "SQL", bg: "#fae8ff", color: "#86198f" };
  if ([".sh", ".bash"].includes(ext)) return { label: "SH", bg: "#f3f4f6", color: "#374151" };
  if ([".md", ".txt"].includes(ext)) return { label: "DOC", bg: "#f8fafc", color: "#64748b" };
  if (isManifest) return { label: "MANIFEST", bg: "#f0fdf4", color: "#15803d" };
  return { label: "FILE", bg: "#f8fafc", color: "#64748b" };
}

function TreeNode({ node, depth = 0, filter = "" }) {
  const [expanded, setExpanded] = useState(depth < 2);

  if (!node) return null;

  if (node.type === "directory") {
    const hasChildren = node.children && node.children.length > 0;
    const matchesFilter = !filter || node.name.toLowerCase().includes(filter.toLowerCase()) ||
      (node.children || []).some(c => c.name.toLowerCase().includes(filter.toLowerCase()));

    if (filter && !matchesFilter) return null;

    return (
      <div style={{ marginLeft: depth > 0 ? 14 : 0, userSelect: "none" }}>
        <button
          type="button"
          className="cm-tree-folder-btn"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
          style={{
            backgroundColor: expanded ? "rgba(241, 245, 249, 0.7)" : "transparent",
          }}
          title={node.path || "Directorio raíz"}
        >
          <span style={{ fontSize: 12.5, color: "#475569", width: 12 }} aria-hidden="true">
            {hasChildren ? (expanded ? "▼" : "") : "•"}
          </span>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#475569", fontFamily: "monospace" }} aria-hidden="true">
            {expanded ? "[-]" : "[+]"}
          </span>
          <span style={{ fontFamily: "monospace" }}>{node.name || "root"}</span>
          <span style={{ fontSize: 12.5, color: "var(--color-text-muted)", fontWeight: 500 }}>
            ({(node.children || []).length} elementos)
          </span>
        </button>

        {expanded && hasChildren && (
          <div style={{ borderLeft: "1px dashed #cbd5e1", marginLeft: 8, paddingLeft: 4 }}>
            {node.children.map((child, idx) => (
              <TreeNode key={`${child.path || child.name}-${idx}`} node={child} depth={depth + 1} filter={filter} />
            ))}
          </div>
        )}
      </div>
    );
  }

  // File Node
  const matchesFilter = !filter || node.name.toLowerCase().includes(filter.toLowerCase()) ||
    (node.path || "").toLowerCase().includes(filter.toLowerCase());

  if (filter && !matchesFilter) return null;

  const badge = getFileBadge(node.name, node.extension, node.is_manifest);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
        padding: "2px 6px",
        marginLeft: depth > 0 ? 14 : 0,
        fontSize: 13.5,
        borderRadius: 4,
      }}
      title={node.path}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, overflow: "hidden" }}>
        <span
          style={{
            fontSize: 12.5,
            fontWeight: 700,
            padding: "1px 4px",
            borderRadius: 3,
            backgroundColor: badge.bg,
            color: badge.color,
            fontFamily: "monospace",
            lineHeight: 1.2,
          }}
        >
          {badge.label}
        </span>
        <span
          style={{
            fontFamily: "monospace",
            color: node.is_manifest ? "#1e40af" : "#334155",
            fontWeight: node.is_manifest ? 600 : 400,
            textOverflow: "ellipsis",
            overflow: "hidden",
            whiteSpace: "nowrap",
          }}
        >
          {node.name}
        </span>
        {node.is_manifest && (
          <span
            style={{
              fontSize: 12.5,
              fontWeight: 700,
              padding: "1px 5px",
              borderRadius: 3,
              backgroundColor: "#dbeafe",
              color: "#1d4ed8",
              textTransform: "uppercase",
            }}
          >
            {node.manifest_type || "Manifiesto"}
          </span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0, fontSize: 13, color: "#64748b" }}>
        {node.language && node.language !== "Other" && node.language !== "Plain Text" && (
          <span style={{ fontSize: 12.5, color: "#475569", backgroundColor: "#f8fafc", padding: "1px 4px", borderRadius: 3 }}>
            {node.language}
          </span>
        )}
        <span style={{ fontFamily: "monospace" }}>{formatBytes(node.size)}</span>
      </div>
    </div>
  );
}

export default function RepositoryTreeViewer({ treeData, title = "Inventario de Archivos", defaultOpen = false }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [filter, setFilter] = useState("");

  if (!treeData) return null;

  const summary = treeData.summary || {};
  const rootNode = treeData.hierarchical_tree || treeData;
  const languages = summary.languages || [];
  const keyManifests = treeData.key_manifests || [];
  const topLangs = languages.slice(0, 3).map((l) => `${l.language} (${l.percentage_files}%)`).join(" · ");

  return (
    <div
      style={{
        marginTop: 10,
        marginBottom: 10,
        border: "1px solid #d5dbdb",
        borderRadius: 6,
        backgroundColor: "#ffffff",
        overflow: "hidden",
      }}
    >
      {/* Compact Executive Bar */}
      <button
        type="button"
        className="cm-tree-header-btn"
        aria-expanded={isOpen}
        onClick={() => setIsOpen(!isOpen)}
        style={{
          borderBottom: isOpen ? "1px solid #eaeded" : "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", minWidth: 0 }}>
          <span style={{ fontSize: 13.5, fontWeight: 700, color: "#000716" }}>
            {title}
          </span>
          <span className="cm-badge info">
            {summary.total_files ?? 0} archivos · {summary.total_directories ?? 0} carpetas
          </span>
          {topLangs && (
            <span className="cm-hint" style={{ fontSize: 12 }}>
              {topLangs}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, flexShrink: 0 }}>
          {keyManifests.length > 0 && (
            <span className="cm-badge observed">
              {keyManifests.length} manifiesto(s)
            </span>
          )}
          <span style={{ color: "#0972d3", fontWeight: 700 }}>
            {isOpen ? "Ocultar inventario ▲" : "Explorar archivos ▾"}
          </span>
        </div>
      </button>

      {/* Expanded Content (Progressive Disclosure) */}
      {isOpen && (
        <div style={{ padding: "12px 14px" }}>
          {languages.length > 0 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
              {languages.slice(0, 5).map((lang) => (
                <span
                  key={lang.language}
                  className="cm-badge neutral"
                  style={{ fontSize: 12 }}
                >
                  <strong>{lang.language}</strong>: {lang.file_count} ({lang.percentage_files}%)
                </span>
              ))}
            </div>
          )}

          {/* Search Filter */}
          <div style={{ marginBottom: 10 }}>
            <input
              type="search"
              className="cm-input"
              aria-label="Filtrar carpetas, subcarpetas o archivos en el árbol del repositorio"
              placeholder="Filtrar archivos o carpetas..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>

          {/* Tree View Container */}
          <div
            style={{
              maxHeight: 300,
              overflowY: "auto",
              padding: "6px 8px",
              backgroundColor: "#fbfcfd",
              border: "1px solid #eaeded",
              borderRadius: 4,
            }}
          >
            {rootNode ? (
              <TreeNode node={rootNode} depth={0} filter={filter} />
            ) : (
              <div style={{ fontSize: 13, color: "var(--color-text-muted)", textAlign: "center", padding: 12 }}>
                No se pudo construir la jerarquía del árbol.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
