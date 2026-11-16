import React, { useState, useEffect, useMemo, useCallback } from "react";
import { apiFetch } from "../../utils/apiClient";
import ArchifyDiagramRenderer from "../architecture/ArchifyDiagramRenderer";
import { AwsTabs, AwsKeyValuePairs, AwsStatusIndicator } from "../cloudscape/AwsPrimitives";
import { HelpTooltipButton, ContextualTechnicalModal } from "./PlannedCloudStructureGraphModal";

function formatBytes(bytes) {
  const n = Number(bytes || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KiB`;
  return `${(n / 1048576).toFixed(2)} MiB`;
}

function classifyRelPath(relPath) {
  const clean = String(relPath || "").replace(/^\/+/, "");
  if (clean.startsWith("etc/")) return "config";
  if (clean.startsWith("home/") || clean.startsWith("opt/") || clean.startsWith("srv/") || clean.startsWith("app/")) {
    return "user";
  }
  return "logs";
}

function CheckIcon({ ok }) {
  if (ok) {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#037f0c" strokeWidth="2.5" aria-hidden="true">
        <polyline points="20 6 9 17 4 12" />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#b45309" strokeWidth="2.5" aria-hidden="true">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
}

function renderHighlightedLine(line, relPath) {
  const trimmed = line.trim();
  if (relPath.endsWith(".json")) {
    const m = line.match(/^(\s*)"([^"]+)"(\s*:\s*)(.*)$/);
    if (m) {
      return (
        <>
          {m[1]}
          <span style={{ color: "#38bdf8", fontWeight: 600 }}>"{m[2]}"</span>
          {m[3]}
          <span style={{ color: "#a7f3d0" }}>{m[4]}</span>
        </>
      );
    }
  }
  if (trimmed.startsWith("#")) {
    return <span style={{ color: "#94a3b8", fontStyle: "italic" }}>{line}</span>;
  }
  const kvMatch = line.match(/^([A-Za-z0-9_.-]+)=(.*)$/);
  if (kvMatch) {
    return (
      <>
        <span style={{ color: "#38bdf8", fontWeight: 600 }}>{kvMatch[1]}</span>=
        <span style={{ color: "#86efac" }}>{kvMatch[2]}</span>
      </>
    );
  }
  if (relPath.includes("passwd") && line.includes(":")) {
    const colonIdx = line.indexOf(":");
    return (
      <>
        <span style={{ color: "#fbbf24", fontWeight: 600 }}>{line.slice(0, colonIdx)}</span>
        {line.slice(colonIdx)}
      </>
    );
  }
  return line;
}

const DEFAULT_CAPTURED_FILES = [
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
];

export default function Case2AwsValidationView({
  job,
  publicIp,
  primaryInstance,
  outputsMap,
  onCopy,
  onProbeLocalHost,
  probingLocalHost,
  localHostProbe,
}) {
  const [activeTab, setActiveTab] = useState("summary");
  const [validation, setValidation] = useState(null);
  const [validating, setValidating] = useState(false);
  const [lastCheckedAt, setLastCheckedAt] = useState(null);
  const [showPathHelp, setShowPathHelp] = useState(false);

  // Explorer state
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [selectedFilePath, setSelectedFilePath] = useState("etc/os-release");
  const [fileContent, setFileContent] = useState("");
  const [loadingFile, setLoadingFile] = useState(false);
  const [fileError, setFileError] = useState("");

  const srcEnv = job?.source_environment || {};
  const telemetry = validation?.telemetry || {};
  const liveFiles = validation?.files_payload?.files || telemetry?.uploaded_files || [];
  const manifestSelectedPaths =
    telemetry?.selected_user_paths ||
    srcEnv?.selected_user_paths ||
    [];

  const runLiveValidation = useCallback(async () => {
    if (!publicIp) return;
    setValidating(true);
    try {
      const res = await apiFetch(`/api/v1/migration/probe-uc2-validation?ip=${encodeURIComponent(publicIp)}`);
      if (res.ok) {
        const data = await res.json();
        setValidation(data);
        setLastCheckedAt(new Date().toLocaleTimeString());
      }
    } catch {
      // Keep previous validation state if transient timeout occurs
    } finally {
      setValidating(false);
    }
  }, [publicIp]);

  useEffect(() => {
    if (publicIp && (!validation || validation.ip !== publicIp)) {
      runLiveValidation();
    }
  }, [publicIp, validation, runLiveValidation]);

  const loadLiveFileContent = useCallback(
    async (relPath) => {
      const cleanRel = String(relPath || "").replace(/^\/+/, "");
      setSelectedFilePath(cleanRel);
      setFileError("");
      if (!publicIp) {
        setFileContent("");
        return;
      }
      setLoadingFile(true);
      try {
        const res = await apiFetch(
          `/api/v1/migration/probe-uc2-file?ip=${encodeURIComponent(publicIp)}&path=${encodeURIComponent(cleanRel)}`
        );
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          setFileError(err.detail || `Error HTTP ${res.status} al leer el archivo en EC2.`);
          setFileContent("");
        } else {
          const payload = await res.json();
          setFileContent(payload.content || "");
        }
      } catch (err) {
        setFileError(`No se pudo consultar ${cleanRel}: ${err.message}`);
        setFileContent("");
      } finally {
        setLoadingFile(false);
      }
    },
    [publicIp]
  );

  // Merge live files (or planned manifest files before apply) + user-selected origin paths
  const mergedFiles = useMemo(() => {
    const map = new Map();
    if (liveFiles.length > 0) {
      for (const f of liveFiles) {
        const cleanRel = String(f.path || "").replace(/^\/+/, "");
        map.set(cleanRel, {
          path: cleanRel,
          originPath: f.origin_path || `/${cleanRel}`,
          rootfsPath: f.rootfs_path || f.disk_path || `/opt/cloudmove/os_capture/rootfs/${cleanRel}`,
          ebsPath: f.ebs_expected_path || f.ebs_path || `/mnt/cloudmove_ebs/rootfs/${cleanRel}`,
          ebsMirrored: Boolean(f.ebs_mirrored),
          category: f.category || classifyRelPath(cleanRel),
          sizeBytes: f.size_bytes ?? null,
          sha256: f.sha256 || "-",
          syncedLive: true,
        });
      }
    } else {
      const baseList =
        (srcEnv.uploaded_os_files && srcEnv.uploaded_os_files.length > 0
          ? srcEnv.uploaded_os_files
          : DEFAULT_CAPTURED_FILES.map((p) => ({ path: p })));
      for (const item of baseList) {
        const cleanRel = String(item.path || item).replace(/^\/+/, "");
        map.set(cleanRel, {
          path: cleanRel,
          originPath: item.origin_path || `/${cleanRel}`,
          rootfsPath: item.rootfs_path || `/opt/cloudmove/os_capture/rootfs/${cleanRel}`,
          ebsPath: item.ebs_path || `/mnt/cloudmove_ebs/rootfs/${cleanRel}`,
          ebsMirrored: false,
          category: classifyRelPath(cleanRel),
          sizeBytes: item.size_bytes ?? null,
          sha256: item.sha256 || "Pendiente apply",
          syncedLive: false,
        });
      }
    }

    for (const rawSel of manifestSelectedPaths) {
      const cleanRel = String(rawSel || "").replace(/^\/+/, "");
      if (!cleanRel || map.has(cleanRel)) continue;
      map.set(cleanRel, {
        path: cleanRel,
        originPath: String(rawSel),
        rootfsPath: `/opt/cloudmove/os_capture/rootfs/${cleanRel}`,
        ebsPath: `/mnt/cloudmove_ebs/rootfs/${cleanRel}`,
        ebsMirrored: Boolean(validation?.checks?.ebs?.mounted),
        category: classifyRelPath(cleanRel),
        sizeBytes: null,
        sha256: "Ruta seleccionada",
        syncedLive: false,
        userSelected: true,
      });
    }
    return Array.from(map.values()).sort((a, b) => a.path.localeCompare(b.path));
  }, [liveFiles, srcEnv.uploaded_os_files, manifestSelectedPaths, validation?.checks?.ebs?.mounted]);

  const filteredFiles = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return mergedFiles.filter((f) => {
      if (categoryFilter !== "all" && f.category !== categoryFilter) return false;
      if (!q) return true;
      return (
        f.originPath.toLowerCase().includes(q) ||
        f.rootfsPath.toLowerCase().includes(q) ||
        f.ebsPath.toLowerCase().includes(q) ||
        String(f.sha256 || "").toLowerCase().includes(q)
      );
    });
  }, [mergedFiles, categoryFilter, searchQuery]);

  const totalSizeBytes = useMemo(
    () => mergedFiles.reduce((acc, f) => acc + (Number(f.sizeBytes) || 0), 0),
    [mergedFiles]
  );

  // Auto-load initial file when entering Explorer tab while EC2 is live
  useEffect(() => {
    if (
      activeTab === "files" &&
      publicIp &&
      validation?.checks?.files?.ok &&
      !fileContent &&
      !loadingFile &&
      mergedFiles.length > 0
    ) {
      const initialTarget = mergedFiles.find((f) => f.syncedLive)?.path || mergedFiles[0].path;
      loadLiveFileContent(initialTarget);
    }
  }, [activeTab, publicIp, validation?.checks?.files?.ok, fileContent, loadingFile, mergedFiles, loadLiveFileContent]);

  const healthCheck = validation?.checks?.health || {};
  const filesCheck = validation?.checks?.files || {};
  const ebsCheck = validation?.checks?.ebs || {};
  const ebsMounted = Boolean(ebsCheck.mounted);
  const mirroredCount = filesCheck.ebs_mirrored_count ?? mergedFiles.filter((f) => f.ebsMirrored).length;
  const syncedCount = filesCheck.synced_count ?? liveFiles.length;
  const expectedCount = filesCheck.expected_count || mergedFiles.length;
  const isAllOk = Boolean(validation?.all_ok);

  // Archify Storage & Volume Mount Topology Model
  const ebsArchifyModel = useMemo(() => {
    const hostLabel = srcEnv.name || "Host Linux Origen";
    const ec2Label = telemetry.cloud_hostname || primaryInstance?.id || "EC2 Nitro AWS";
    return {
      schema_version: "3.1",
      diagram_type: "architecture",
      meta: {
        title: `Trazabilidad de Discos EBS y Rutas de Archivos (${hostLabel} -> AWS)`,
      },
      boundaries: [
        {
          kind: "region",
          label: `VPC AWS (${publicIp || "Pendiente terraform apply"}) · us-east-1`,
          wraps: ["ec2-rootfs", "ebs-secondary", "api-verify"],
          pad: 22,
        },
        {
          kind: "vpc",
          label: `Instancia ${ec2Label}`,
          wraps: ["ec2-rootfs", "ebs-secondary"],
          pad: 14,
        },
      ],
      components: [
        {
          id: "src-os",
          type: "external",
          label: hostLabel,
          sublabel: `/etc, /home, ${manifestSelectedPaths.length || mergedFiles.length} rutas`,
          pos: [24, 150],
          size: [185, 68],
        },
        {
          id: "bundle-stream",
          type: "cloud",
          label: "Bundle tar.gz + Init",
          sublabel: "os_real_files_bundle.tar.gz",
          pos: [248, 150],
          size: [185, 68],
        },
        {
          id: "ec2-rootfs",
          type: "backend",
          label: "RootFS (nvme0n1)",
          sublabel: "/opt/cloudmove/os_capture",
          pos: [490, 95],
          size: [215, 70],
        },
        {
          id: "ebs-secondary",
          type: "database",
          label: "EBS Secundario nvme1n1",
          sublabel: "/mnt/cloudmove_ebs/rootfs",
          pos: [490, 225],
          size: [215, 70],
        },
        {
          id: "api-verify",
          type: "security",
          label: "Validación Live :3000",
          sublabel: "/health · /files · :8000",
          pos: [770, 150],
          size: [215, 70],
        },
      ],
      connections: [
        { from: "src-os", to: "bundle-stream", label: "SSH / Cloud-Init", variant: "default" },
        { from: "bundle-stream", to: "ec2-rootfs", label: "tar -xzf rootfs", variant: "emphasis" },
        { from: "ec2-rootfs", to: "ebs-secondary", label: "cp -r nvme1n1", variant: "default" },
        { from: "ec2-rootfs", to: "api-verify", label: "HTTP :3000/:8000", variant: "security" },
      ],
      cards: [
        {
          title: "1. Volumen Raíz EC2 (nvme0n1)",
          dot: "amber",
          items: [
            "Extrae los archivos reales en /opt/cloudmove/os_capture/rootfs/",
            "Conserva manifiesto completo en /opt/cloudmove/os_capture/image_manifest.json",
            "Restaura parámetros sysctl y cuentas en /etc/passwd",
          ],
        },
        {
          title: "2. Volumen EBS Secundario (nvme1n1)",
          dot: "emerald",
          items: [
            "Formatea y monta automáticamente /dev/nvme1n1 en /mnt/cloudmove_ebs/",
            "Replica íntegramente /rootfs/ en /mnt/cloudmove_ebs/rootfs/",
            `Estado actual: ${ebsMounted ? `Montado (${mirroredCount} archivos replicados)` : publicIp ? "Validando montaje en vivo" : "Provisionado al aplicar Terraform"}`,
          ],
        },
        {
          title: "3. Endpoints de Consulta Directa",
          dot: "cyan",
          items: [
            "Portal Web Stand-Alone: http://<IP>:3000 y puerto 80",
            "Sonda JSON /health: Kernel, uptime, lsblk, df -hT, ps y /etc/passwd",
            "Descarga Directa: GET /bundle.tar.gz con checksums SHA-256",
          ],
        },
      ],
    };
  }, [srcEnv.name, telemetry.cloud_hostname, primaryInstance?.id, publicIp, manifestSelectedPaths.length, mergedFiles.length, ebsMounted, mirroredCount]);

  // Tab 1: Resumen de Salud y Despliegue
  const summaryTabContent = (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <AwsKeyValuePairs
        columns={4}
        items={[
          {
            label: "Instancia EC2 & IP Pública",
            value: publicIp || "Pendiente terraform apply",
            subtext: primaryInstance?.id || outputsMap.instance_id?.value || telemetry.cloud_hostname || "AWS Nitro x86_64",
          },
          {
            label: "SO & Kernel en Vivo",
            value: `${srcEnv.os?.distro || "Ubuntu / Debian Linux"}`,
            subtext: telemetry.cloud_kernel
              ? `Kernel Cloud: ${telemetry.cloud_kernel}`
              : `Kernel Origen: ${srcEnv.os?.kernel || "Linux"}`,
          },
          {
            label: "Uptime & Puertos Portal",
            value: telemetry.cloud_uptime || (publicIp ? "Esperando /health" : "Listo en main.tf"),
            subtext: "HTTP :80, :3000, API :8000",
          },
          {
            label: "Archivos Sincronizados",
            value: publicIp && filesCheck.ok ? `${syncedCount}/${expectedCount} OK` : `${mergedFiles.length} en bundle`,
            subtext: totalSizeBytes > 0 ? `Tamaño total: ${formatBytes(totalSizeBytes)}` : "Paquete os_real_files_bundle.tar.gz",
          },
        ]}
      />

      {/* Rutas exactas en AWS para eliminar cualquier incertidumbre */}
      <div className="cm-card-subtle" style={{ backgroundColor: "#ffffff" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
          <strong style={{ fontSize: 13.5, color: "#16191f" }}>
            ¿Dónde están exactamente mis archivos seleccionados en AWS?
          </strong>
          <HelpTooltipButton
            label="¿Cómo se replican en EBS?"
            onClick={() => setShowPathHelp(true)}
          />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10 }}>
          <div style={{ padding: "10px 12px", borderRadius: 6, border: "1px solid #d5dbdb", backgroundColor: "#fafafa" }}>
            <div style={{ fontSize: 11.5, fontWeight: 700, color: "#545b64", textTransform: "uppercase" }}>
              1. Ruta en SO Origen
            </div>
            <div style={{ marginTop: 4 }}>
              <code>/etc/* , /home/* , /var/log/*</code>
            </div>
            {manifestSelectedPaths.length > 0 && (
              <div style={{ fontSize: 12, color: "#0972d3", marginTop: 4 }}>
                +{manifestSelectedPaths.length} ruta(s) de usuario seleccionadas
              </div>
            )}
          </div>

          <div style={{ padding: "10px 12px", borderRadius: 6, border: "1px solid #d5dbdb", backgroundColor: "#f2f8fd" }}>
            <div style={{ fontSize: 11.5, fontWeight: 700, color: "#0972d3", textTransform: "uppercase" }}>
              2. Volumen Raíz EC2 (nvme0n1)
            </div>
            <div style={{ marginTop: 4 }}>
              <code>/opt/cloudmove/os_capture/rootfs/</code>
            </div>
            <div style={{ fontSize: 12, color: "#545b64", marginTop: 4 }}>
              Extracción primaria vía Cloud-Init al iniciar EC2
            </div>
          </div>

          <div style={{ padding: "10px 12px", borderRadius: 6, border: "1px solid #a7f3d0", backgroundColor: "#f6fef9" }}>
            <div style={{ fontSize: 11.5, fontWeight: 700, color: "#037f0c", textTransform: "uppercase" }}>
              3. Volumen EBS Secundario (nvme1n1)
            </div>
            <div style={{ marginTop: 4 }}>
              <code>/mnt/cloudmove_ebs/rootfs/</code>
            </div>
            <div style={{ fontSize: 12, color: "#037f0c", marginTop: 4 }}>
              {ebsMounted ? `Montado y replicado (${mirroredCount} archivos OK)` : "Montaje automático sobre /dev/nvme1n1"}
            </div>
          </div>
        </div>
      </div>

      {/* Diagrama Interactivo Archify */}
      <ArchifyDiagramRenderer
        model={ebsArchifyModel}
        defaultTheme="light"
        showStandaloneLink={false}
      />

      {/* Enlaces directos al Portal EC2 y SSH */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
        <div className="cm-card-subtle">
          <div style={{ fontSize: 12.5, fontWeight: 700, color: "#16191f", marginBottom: 4 }}>
            Portal Stand-Alone en Instancia EC2
          </div>
          {publicIp ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <a href={`http://${publicIp}:3000`} target="_blank" rel="noreferrer" style={{ fontFamily: "monospace", fontWeight: 700, fontSize: 12.5 }}>
                http://{publicIp}:3000 ↗ (Consola Web EC2)
              </a>
              <a href={`http://${publicIp}:8000/health`} target="_blank" rel="noreferrer" style={{ fontFamily: "monospace", fontSize: 12 }}>
                http://{publicIp}:8000/health ↗ (Telemetría JSON)
              </a>
              <a href={`http://${publicIp}:3000/files`} target="_blank" rel="noreferrer" style={{ fontFamily: "monospace", fontSize: 12 }}>
                http://{publicIp}:3000/files ↗ (Índice JSON)
              </a>
            </div>
          ) : (
            <div style={{ fontSize: 12, color: "#545b64" }}>
              Disponible tras ejecutar <code>terraform apply</code>.
            </div>
          )}
        </div>

        <div className="cm-card-subtle">
          <div style={{ fontSize: 12.5, fontWeight: 700, color: "#16191f", marginBottom: 4 }}>
            Acceso SSH y Consulta Local In-Guest
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
            <code style={{ fontSize: 12 }}>ssh ubuntu@{publicIp || "<IP_PUBLICA_EC2>"}</code>
            <button
              type="button"
              className="cm-btn sm secondary"
              style={{ padding: "2px 8px", fontSize: 11 }}
              onClick={() => onCopy && onCopy(`ssh ubuntu@${publicIp || "<IP_PUBLICA_EC2>"}`, "Comando SSH copiado")}
            >
              Copiar
            </button>
          </div>
          <div style={{ fontSize: 12, color: "#545b64" }}>
            Inspecciona <code>/mnt/cloudmove_ebs/rootfs/</code> o consulta directamente el host origen:
          </div>
          {onProbeLocalHost && (
            <div style={{ marginTop: 6 }}>
              <button
                type="button"
                className="cm-btn sm secondary"
                onClick={onProbeLocalHost}
                disabled={probingLocalHost}
              >
                {probingLocalHost ? "Consultando host origen..." : "Sondear Host Origen Ahora"}
              </button>
              {localHostProbe?.host && (
                <div style={{ marginTop: 6, fontSize: 11.5, color: "#037f0c" }}>
                  Host origen activo: <code>{localHostProbe.host.hostname}</code> ({localHostProbe.host.distro})
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <details className="cm-accordion-shell">
        <summary className="cm-accordion-trigger">
          <span>Nota técnica sobre tiempo de arranque Cloud-Init y HTTPS en navegador</span>
        </summary>
        <div className="cm-accordion-body" style={{ fontSize: 12.5, color: "#545b64" }}>
          Al iniciar una nueva instancia EC2, Cloud-Init tarda entre 1 y 2 minutos en extraer{" "}
          <code>/opt/cloudmove/os_capture/rootfs/</code>, montar <code>/dev/nvme1n1</code> e iniciar el servicio{" "}
          <code>cloudmove-os-telemetry.service</code> en los puertos 80, 3000 y 8000. Usa siempre{" "}
          <code>http://</code> (sin TLS) al abrir la IP pública directamente, o utiliza las pestañas de validación en vivo aquí mismo.
        </div>
      </details>
    </div>
  );

  // Tab 2: Explorador y Visor de Archivos Capturados
  const bundleDownloadUrl = publicIp
    ? `/api/v1/migration/probe-uc2-bundle?ip=${encodeURIComponent(publicIp)}`
    : null;

  const filesTabContent = (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", flex: 1 }}>
          <input
            type="text"
            placeholder="Buscar archivo por ruta origen, RootFS, EBS o SHA-256..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              padding: "6px 10px",
              borderRadius: 4,
              border: "1px solid #879596",
              fontSize: 13,
              minWidth: 220,
              flex: "1 1 240px",
            }}
          />
          {[
            { id: "all", label: "Todos" },
            { id: "config", label: "Configuración (/etc)" },
            { id: "user", label: "Usuario (/home)" },
            { id: "logs", label: "Logs e Inventario (/var)" },
          ].map((cat) => (
            <button
              key={cat.id}
              type="button"
              className={`cm-btn sm ${categoryFilter === cat.id ? "primary" : "secondary"}`}
              onClick={() => setCategoryFilter(cat.id)}
            >
              {cat.label}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span className="cm-badge info">
            {filteredFiles.length} / {mergedFiles.length} archivo(s) · {formatBytes(totalSizeBytes)}
          </span>
          {bundleDownloadUrl && (
            <a
              href={bundleDownloadUrl}
              download="os_real_files_bundle.tar.gz"
              className="cm-btn sm primary"
              style={{ textDecoration: "none" }}
            >
              Descargar Bundle (.tar.gz)
            </a>
          )}
        </div>
      </div>

      <div className="cm-uc2-split-grid">
        <div className="cm-table-wrap" style={{ maxHeight: 440, overflowY: "auto", border: "1px solid #d5dbdb", borderRadius: 6, backgroundColor: "#ffffff" }}>
          <table className="cm-table" style={{ margin: 0, fontSize: 12 }}>
            <thead>
              <tr>
                <th>Ruta en SO Origen</th>
                <th>Ubicación Exacta en AWS (RootFS y EBS)</th>
                <th>Tamaño</th>
                <th>SHA-256</th>
                <th>Acción</th>
              </tr>
            </thead>
            <tbody>
              {filteredFiles.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: "center", color: "#545b64", padding: 18 }}>
                    Ningún archivo coincide con el filtro actual.
                  </td>
                </tr>
              ) : (
                filteredFiles.map((f) => {
                  const isSelected = selectedFilePath === f.path;
                  return (
                    <tr
                      key={f.path}
                      style={{ backgroundColor: isSelected ? "#e7f3ff" : undefined }}
                    >
                      <td>
                        <strong style={{ wordBreak: "break-all" }}>
                          <code>{f.originPath}</code>
                        </strong>
                        {f.userSelected && (
                          <div style={{ fontSize: 10.5, color: "#0972d3", fontWeight: 700, marginTop: 2 }}>
                            Selección del usuario
                          </div>
                        )}
                      </td>
                      <td style={{ wordBreak: "break-all" }}>
                        <div>
                          <span style={{ color: "#545b64", fontWeight: 600 }}>RootFS:</span>{" "}
                          <code>{f.rootfsPath}</code>
                        </div>
                        <div style={{ color: f.ebsMirrored ? "#037f0c" : "#64748b", fontWeight: f.ebsMirrored ? 600 : 400 }}>
                          <span>EBS:</span> <code>{f.ebsPath}</code>
                        </div>
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {f.sizeBytes !== null ? formatBytes(f.sizeBytes) : "—"}
                      </td>
                      <td>
                        <code>{String(f.sha256 || "-").slice(0, 10)}</code>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="cm-btn sm primary"
                          style={{ padding: "3px 8px", fontSize: 11.5 }}
                          onClick={() => loadLiveFileContent(f.path)}
                          disabled={!publicIp && !f.syncedLive}
                        >
                          {loadingFile && isSelected ? "Leyendo..." : "Inspeccionar"}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Rich Syntax-Highlighted Content Viewer */}
        <div
          style={{
            backgroundColor: "#0f172a",
            color: "#e2e8f0",
            borderRadius: 6,
            border: "1px solid #1e293b",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div
            style={{
              padding: "10px 12px",
              backgroundColor: "#1e293b",
              borderBottom: "1px solid #334155",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 8,
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: 700, color: "#ffffff", wordBreak: "break-all" }}>
                <code>/{selectedFilePath}</code>
              </div>
              <div style={{ fontSize: 11, color: "#94a3b8", wordBreak: "break-all", marginTop: 2 }}>
                EC2: <code>/opt/cloudmove/os_capture/rootfs/{selectedFilePath}</code> · EBS:{" "}
                <code>/mnt/cloudmove_ebs/rootfs/{selectedFilePath}</code>
              </div>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <button
                type="button"
                className="cm-btn sm secondary"
                style={{ padding: "3px 8px", fontSize: 11.5 }}
                onClick={() => onCopy && fileContent && onCopy(fileContent, "Contenido copiado")}
                disabled={!fileContent}
              >
                Copiar
              </button>
              {publicIp && (
                <a
                  href={`http://${publicIp}:3000/files/view?path=${encodeURIComponent(selectedFilePath)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="cm-btn sm primary"
                  style={{ padding: "3px 8px", fontSize: 11.5, textDecoration: "none" }}
                >
                  Raw EC2 ↗
                </a>
              )}
            </div>
          </div>

          <pre
            style={{
              margin: 0,
              padding: 12,
              maxHeight: 380,
              minHeight: 240,
              overflow: "auto",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              fontSize: 12,
              lineHeight: 1.5,
              flex: 1,
            }}
          >
            {!publicIp ? (
              <span style={{ color: "#94a3b8" }}>
                Ejecuta primero <code>terraform apply</code> en la sección superior para consultar en vivo el contenido real de cada archivo desde la instancia EC2 en AWS.
              </span>
            ) : loadingFile ? (
              <span style={{ color: "#38bdf8" }}>Consultando /files/view en la instancia EC2 ({publicIp})...</span>
            ) : fileError ? (
              <span style={{ color: "#fca5a5" }}>{fileError}</span>
            ) : fileContent ? (
              fileContent.split("\n").map((ln, idx) => (
                <div key={idx} style={{ display: "flex" }}>
                  <span
                    style={{
                      display: "inline-block",
                      width: 34,
                      flexShrink: 0,
                      textAlign: "right",
                      paddingRight: 10,
                      color: "#64748b",
                      userSelect: "none",
                    }}
                  >
                    {idx + 1}
                  </span>
                  <span style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                    {renderHighlightedLine(ln, selectedFilePath)}
                  </span>
                </div>
              ))
            ) : (
              <span style={{ color: "#94a3b8" }}>
                Haz clic en "Inspeccionar" sobre cualquier fila para cargar el contenido real del disco en AWS.
              </span>
            )}
          </pre>
        </div>
      </div>
    </div>
  );

  // Tab 3: Almacenamiento y Discos EBS en AWS
  const liveLsblkRows = telemetry.lsblk_rows || [];
  const liveDfRows = telemetry.df_rows || [];
  const sourcePartitions = (srcEnv.disks || []).flatMap((d) =>
    (d.partitions || []).map((p, idx) => ({
      device: p.device || p.name || `${d.device}p${idx + 1}`,
      mountPoint: p.mount_point || "[SWAP / RAW]",
      filesystem: p.filesystem || "ext4",
      uuid: p.uuid || "Preservado en /etc/fstab",
      sizeGib: p.size_gib ?? d.size_gib,
      usedGib: p.used_gib,
    }))
  );

  const storageTabContent = (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {liveLsblkRows.length > 0 && (
        <div className="cm-card-subtle" style={{ backgroundColor: "#ffffff" }}>
          <strong style={{ fontSize: 13.5, color: "#16191f", display: "block", marginBottom: 8 }}>
            Discos de Bloque Activos en Vivo en AWS EC2 (<code>lsblk</code>: <code>nvme0n1</code> y <code>nvme1n1</code>)
          </strong>
          <div className="cm-table-wrap">
            <table className="cm-table" style={{ margin: 0, fontSize: 12 }}>
              <thead>
                <tr>
                  <th>Dispositivo</th>
                  <th>Tamaño</th>
                  <th>Tipo</th>
                  <th>Filesystem</th>
                  <th>Punto de Montaje AWS</th>
                  <th>UUID</th>
                </tr>
              </thead>
              <tbody>
                {liveLsblkRows.map((r, i) => (
                  <tr key={`${r.name}-${i}`}>
                    <td>
                      <code>{"  ".repeat(r.depth || 0)}{r.name}</code>
                    </td>
                    <td><strong>{r.size}</strong></td>
                    <td>{r.type}</td>
                    <td><code>{r.fstype}</code></td>
                    <td>
                      <code style={{ color: r.mountpoint?.includes("cloudmove_ebs") ? "#037f0c" : undefined, fontWeight: r.mountpoint?.includes("cloudmove_ebs") ? 700 : 400 }}>
                        {r.mountpoint}
                      </code>
                    </td>
                    <td><code>{r.uuid}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {liveDfRows.length > 0 && (
        <div className="cm-card-subtle" style={{ backgroundColor: "#ffffff" }}>
          <strong style={{ fontSize: 13.5, color: "#16191f", display: "block", marginBottom: 8 }}>
            Uso Real de Sistemas de Archivos en AWS (<code>df -hT</code>)
          </strong>
          <div className="cm-table-wrap">
            <table className="cm-table" style={{ margin: 0, fontSize: 12 }}>
              <thead>
                <tr>
                  <th>Filesystem</th>
                  <th>Tipo</th>
                  <th>Tamaño</th>
                  <th>Usado</th>
                  <th>Disponible</th>
                  <th>Uso %</th>
                  <th>Montaje</th>
                </tr>
              </thead>
              <tbody>
                {liveDfRows.map((r, i) => (
                  <tr key={`${r.filesystem}-${i}`}>
                    <td><code>{r.filesystem}</code></td>
                    <td>{r.fstype}</td>
                    <td>{r.size}</td>
                    <td>{r.used}</td>
                    <td>{r.avail}</td>
                    <td style={{ minWidth: 90 }}>
                      <strong>{r.use_pct}</strong>
                      <div style={{ height: 6, backgroundColor: "#e5e7eb", borderRadius: 999, overflow: "hidden", marginTop: 3 }}>
                        <div style={{ height: "100%", width: r.use_pct, backgroundColor: "#0972d3" }} />
                      </div>
                    </td>
                    <td><code>{r.mountpoint}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="cm-card-subtle" style={{ backgroundColor: "#ffffff" }}>
        <strong style={{ fontSize: 13.5, color: "#16191f", display: "block", marginBottom: 8 }}>
          Particiones del SO Origen Mapeadas a <code>root_block_device</code> / <code>aws_ebs_volume</code>
        </strong>
        <div className="cm-table-wrap">
          <table className="cm-table" style={{ margin: 0, fontSize: 12.5 }}>
            <thead>
              <tr>
                <th>Dispositivo / Partición Origen</th>
                <th>Punto de Montaje</th>
                <th>Filesystem</th>
                <th>UUID Preservado</th>
                <th>Capacidad</th>
              </tr>
            </thead>
            <tbody>
              {sourcePartitions.map((p, idx) => (
                <tr key={`${p.device}-${idx}`}>
                  <td><strong><code>{p.device}</code></strong></td>
                  <td><code>{p.mountPoint}</code></td>
                  <td><code>{p.filesystem}</code></td>
                  <td><code>{p.uuid}</code></td>
                  <td>
                    <strong>{p.sizeGib} GiB</strong>
                    {p.usedGib ? ` (${p.usedGib} GiB usados)` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {(telemetry.lsblk_live || telemetry.df_live) && (
        <details className="cm-accordion-shell">
          <summary className="cm-accordion-trigger">
            <span>Ver salida cruda CLI (<code>lsblk</code> y <code>df -hT</code>)</span>
          </summary>
          <div className="cm-accordion-body">
            <pre style={{ margin: 0, padding: 10, backgroundColor: "#0f172a", color: "#a7f3d0", borderRadius: 6, fontSize: 12, overflowX: "auto" }}>
              {`${telemetry.lsblk_live || ""}\n${telemetry.df_live || ""}`}
            </pre>
          </div>
        </details>
      )}
    </div>
  );

  // Tab 4: Procesos y Usuarios Restaurados
  const livePasswdUsers = telemetry.passwd_users || [];
  const sourceLocalUsers = srcEnv.local_users || ["root"];
  const activeProcesses =
    telemetry.ps_rows && telemetry.ps_rows.length > 0
      ? telemetry.ps_rows
      : srcEnv.running_processes || [];
  const isLivePs = Boolean(telemetry.ps_rows && telemetry.ps_rows.length > 0);

  const processesUsersTabContent = (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="cm-card-subtle" style={{ backgroundColor: "#ffffff" }}>
        <strong style={{ fontSize: 13.5, color: "#16191f", display: "block", marginBottom: 8 }}>
          Verificación de Cuentas Locales Restauradas en <code>/etc/passwd</code>
        </strong>
        {livePasswdUsers.length > 0 ? (
          <div className="cm-table-wrap">
            <table className="cm-table" style={{ margin: 0, fontSize: 12 }}>
              <thead>
                <tr>
                  <th>Usuario</th>
                  <th>UID / GID</th>
                  <th>Directorio Home</th>
                  <th>Shell</th>
                  <th>Verificación</th>
                </tr>
              </thead>
              <tbody>
                {livePasswdUsers.map((u) => (
                  <tr key={u.username}>
                    <td><strong><code>{u.username}</code></strong></td>
                    <td><code>{u.uid} / {u.gid}</code></td>
                    <td><code>{u.home}</code></td>
                    <td><code>{u.shell}</code></td>
                    <td>
                      <span className={`cm-badge ${u.is_source_user ? "observed" : "neutral"}`}>
                        {u.is_source_user ? "Usuario Origen Restaurado" : "Sistema EC2"}
                      </span>{" "}
                      {u.home_exists && <span style={{ fontSize: 11.5, color: "#037f0c", fontWeight: 600 }}>(Home OK)</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {sourceLocalUsers.map((u) => (
              <span key={u} className="cm-badge info" style={{ fontSize: 12 }}>
                <code>{u}</code> (planificado en user_data.sh)
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="cm-card-subtle" style={{ backgroundColor: "#ffffff" }}>
        <strong style={{ fontSize: 13.5, color: "#16191f", display: "block", marginBottom: 6 }}>
          Puertos Habilitados en <code>aws_security_group.app_sg</code> ({(srcEnv.listening_ports || []).length || 5})
        </strong>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {(srcEnv.listening_ports || [22, 80, 443, 3000, 8000]).map((port) => (
            <span key={port} className="cm-badge observed" style={{ fontSize: 12 }}>
              TCP <code>:{port}</code>
            </span>
          ))}
        </div>
      </div>

      <div className="cm-card-subtle" style={{ backgroundColor: "#ffffff" }}>
        <strong style={{ fontSize: 13.5, color: "#16191f", display: "block", marginBottom: 8 }}>
          {isLivePs ? `Procesos Activos en Vivo en EC2 (${activeProcesses.length})` : `Procesos Capturados en el SO Origen (${activeProcesses.length})`}
        </strong>
        <div className="cm-table-wrap" style={{ maxHeight: 280, overflowY: "auto" }}>
          <table className="cm-table" style={{ margin: 0, fontSize: 12 }}>
            <thead>
              <tr>
                <th>PID</th>
                <th>Usuario</th>
                <th>CPU %</th>
                <th>MEM %</th>
                <th>Proceso</th>
              </tr>
            </thead>
            <tbody>
              {activeProcesses.slice(0, 35).map((proc, idx) => (
                <tr key={`${proc.pid}-${idx}`}>
                  <td><code>{proc.pid}</code></td>
                  <td><code>{proc.user}</code></td>
                  <td>{proc.cpu ?? proc.cpu_percent}%</td>
                  <td>{proc.mem ?? proc.mem_percent}%</td>
                  <td><strong>{proc.command || proc.name}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );

  const diagnosticItems = [
    {
      title: "1. Instancia EC2 & SSH",
      ok: Boolean(validation?.ssh_open || healthCheck.ok),
      detail: publicIp
        ? validation?.ssh_open
          ? `${publicIp}:22 abierto`
          : "Esperando apertura TCP"
        : "Pendiente terraform apply",
    },
    {
      title: "2. Sonda GET /health",
      ok: Boolean(healthCheck.ok),
      detail: healthCheck.ok
        ? `HTTP ${healthCheck.http_status} · ${healthCheck.latency_ms} ms`
        : publicIp
        ? healthCheck.error || "Esperando servicio :3000/:8000"
        : "Sin IP pública asignada",
    },
    {
      title: "3. Sonda GET /files",
      ok: Boolean(filesCheck.ok),
      detail: filesCheck.ok
        ? `HTTP ${filesCheck.http_status} · ${syncedCount}/${expectedCount} archivos OK`
        : publicIp
        ? filesCheck.error || "Verificando endpoint /files"
        : `${mergedFiles.length} archivos preparados`,
    },
    {
      title: "4. RootFS y EBS Montados",
      ok: Boolean(filesCheck.ok && (ebsMounted || syncedCount > 0)),
      detail: ebsMounted
        ? `${ebsCheck.mount_dir} (${mirroredCount} replicados)`
        : ebsCheck.rootfs_dir || "/opt/cloudmove/os_capture/rootfs",
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* AWS Health Status Banner + Asistente "¿Funcionó mi despliegue?" */}
      <div
        style={{
          backgroundColor: "#ffffff",
          border: `1px solid ${isAllOk ? "#a7f3d0" : "#d5dbdb"}`,
          borderRadius: 8,
          padding: "14px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <AwsStatusIndicator type={isAllOk ? "success" : publicIp ? "warning" : "pending"}>
              {isAllOk
                ? "Despliegue Exitoso"
                : publicIp
                ? "Validando Servicios en EC2"
                : "Vista Previa (Pre-Apply)"}
            </AwsStatusIndicator>
            <span className={`cm-badge ${filesCheck.ok ? "observed" : "neutral"}`}>
              Sincronización de Archivos: {publicIp && filesCheck.ok ? `${syncedCount}/${expectedCount} OK` : `${mergedFiles.length} en bundle`}
            </span>
            <span className={`cm-badge ${ebsMounted ? "observed" : "info"}`}>
              {ebsMounted ? "Volúmenes EBS Montados (/mnt/cloudmove_ebs)" : "EBS: /opt/cloudmove/os_capture + /mnt/cloudmove_ebs"}
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            {lastCheckedAt && (
              <span style={{ fontSize: 12, color: "#545b64" }}>
                Última verificación: {lastCheckedAt}
              </span>
            )}
            <button
              type="button"
              className="cm-btn sm primary"
              onClick={runLiveValidation}
              disabled={!publicIp || validating}
            >
              {validating ? "Validando /health y /files..." : "¿Funcionó mi despliegue? Verificar Ahora"}
            </button>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 8 }}>
          {diagnosticItems.map((item) => (
            <div
              key={item.title}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 8,
                padding: "9px 10px",
                borderRadius: 6,
                border: `1px solid ${item.ok ? "#a7f3d0" : "#e5e7eb"}`,
                backgroundColor: item.ok ? "#f6fef9" : "#fafafa",
              }}
            >
              <div style={{ marginTop: 1 }}>
                <CheckIcon ok={item.ok} />
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: "#16191f" }}>{item.title}</div>
                <div style={{ fontSize: 11.5, color: "#545b64", fontFamily: "monospace", wordBreak: "break-all" }}>
                  {item.detail}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Navegación Modular en 4 Pestañas Ejecutivas */}
      <AwsTabs
        activeTabId={activeTab}
        onTabChange={setActiveTab}
        ariaLabel="Validación de Sistema Operativo y Archivos en AWS"
        tabs={[
          {
            id: "summary",
            label: "1. Resumen de Salud y Despliegue",
            content: summaryTabContent,
          },
          {
            id: "files",
            label: "2. Explorador y Visor de Archivos Capturados",
            count: mergedFiles.length,
            content: filesTabContent,
          },
          {
            id: "storage",
            label: "3. Almacenamiento y Discos EBS en AWS",
            content: storageTabContent,
          },
          {
            id: "processes_users",
            label: "4. Procesos y Usuarios Restaurados",
            content: processesUsersTabContent,
          },
        ]}
      />

      <ContextualTechnicalModal
        isOpen={showPathHelp}
        onClose={() => setShowPathHelp(false)}
        title="Ubicación y Replicación de Archivos del SO en AWS"
        badge="Caso 2 · EC2 & EBS"
        whyTransformed="Para evitar pérdida de datos entre reinicios y asegurar trazabilidad entre el disco raíz y el volumen de almacenamiento secundario, Cloud-Init extrae el paquete capturado en dos rutas verificables y las expone vía HTTP."
        customSections={[
          {
            title: "Ruta 1: /opt/cloudmove/os_capture/rootfs/ (Volumen Raíz nvme0n1)",
            description:
              "Contiene la extracción directa de os_real_files_bundle.tar.gz generada durante el arranque de la instancia EC2, además de image_manifest.json.",
          },
          {
            title: "Ruta 2: /mnt/cloudmove_ebs/rootfs/ (Volumen EBS Secundario nvme1n1)",
            description:
              "Cuando hay un volumen EBS secundario adjunto (/dev/nvme1n1, /dev/xvdf o /dev/sdf), user_data.sh lo formatea como ext4 (etiqueta CLOUDMOVE_OS), lo monta en /mnt/cloudmove_ebs y replica íntegro el árbol rootfs.",
          },
        ]}
      />
    </div>
  );
}
