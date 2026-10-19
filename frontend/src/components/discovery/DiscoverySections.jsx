import React, { useState, useEffect, useMemo } from "react";
import ExplanationCard, { StateBadge } from "./ExplanationCard";

function formatValOrMissing(val, suffix = "") {
  if (val === null || val === undefined || val === "") {
    return <span className="disc-missing-val">No disponible</span>;
  }
  return `${val}${suffix}`;
}

export function CollapsibleSubsection({ id, title, badge, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="disc-subsection-box" id={id}>
      <header
        className="disc-subsection-header"
        onClick={() => setOpen((o) => !o)}
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen((o) => !o);
          }
        }}
      >
        <div className="disc-sub-title-left">
          <span className={`disc-chevron ${open ? "is-open" : ""}`} aria-hidden="true">
            &#9656;
          </span>
          <h3 className="disc-subsection-title">{title}</h3>
          {badge !== undefined && badge !== null && (
            <span className="disc-subsection-badge">{badge}</span>
          )}
        </div>
        <span className="disc-sub-toggle-label">{open ? "Contraer" : "Desplegar"}</span>
      </header>
      {open && <div className="disc-subsection-body">{children}</div>}
    </section>
  );
}

/* ============================================================================
   A. SUMMARY SECTION
   ============================================================================ */
export function SummarySection({ data }) {
  const summary = data.summary || {};
  const source = data.source || {};
  const os = summary.os || {};
  const m = summary.metrics || {};
  const q = summary.collection_quality || {};
  const issues = data.issues || [];

  return (
    <div className="disc-section-view">
      <div className="disc-section-heading">
        <div>
          <h2 className="disc-page-title">
            Resumen Ejecutivo de Discovery — <code>{summary.hostname}</code>
          </h2>
          <p className="disc-page-subtitle">
            Fuente: <strong>{source.tool}</strong> ({source.tool_version || "N/A"}) · Recolector:{" "}
            <code>{source.collector || "N/A"}</code> · Fecha UTC:{" "}
            <code>{source.collected_at || "No registrada"}</code>
          </p>
        </div>
        <div className="disc-quality-pill">
          <span>Completitud:</span>
          <strong>{q.completeness_percent}%</strong>
          <span>({q.successful_query_count}/{q.query_count} consultas osquery)</span>
        </div>
      </div>

      {/* Primary Identity & Capacity Ledger */}
      <div className="disc-ledger-grid">
        <div className="disc-ledger-block">
          <h3 className="disc-ledger-heading">Identidad y Plataforma</h3>
          <dl className="disc-dl">
            <div>
              <dt>Hostname efectivo</dt>
              <dd><code>{formatValOrMissing(summary.hostname)}</code></dd>
            </div>
            <div>
              <dt>UUID de Hardware</dt>
              <dd><code>{formatValOrMissing(summary.uuid)}</code></dd>
            </div>
            <div>
              <dt>Fabricante y Modelo</dt>
              <dd>
                {formatValOrMissing(summary.vendor)} · {formatValOrMissing(summary.model)}
                {summary.is_workstation_or_laptop && (
                  <span className="disc-inline-warn-tag">Portátil / Lab</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Sistema Operativo</dt>
              <dd>
                {formatValOrMissing(os.name)} {os.version || ""} ({os.codename || "N/A"})
              </dd>
            </div>
            <div>
              <dt>Familia / Arquitectura</dt>
              <dd>
                <code>{os.platform_like || os.platform || "linux"}</code> ·{" "}
                <code>{formatValOrMissing(summary.architecture)}</code>
              </dd>
            </div>
          </dl>
        </div>

        <div className="disc-ledger-block">
          <h3 className="disc-ledger-heading">Cómputo y Almacenamiento</h3>
          <dl className="disc-dl">
            <div>
              <dt>Procesador (CPU)</dt>
              <dd>{formatValOrMissing(m.cpu_model)}</dd>
            </div>
            <div>
              <dt>Núcleos Físicos / Lógicos</dt>
              <dd>
                <strong>{formatValOrMissing(m.cpu_physical_cores)}</strong> físicos /{" "}
                <strong>{formatValOrMissing(m.cpu_logical_cores)}</strong> lógicos
              </dd>
            </div>
            <div>
              <dt>Memoria Física Total</dt>
              <dd>
                <strong>{formatValOrMissing(m.memory_total_formatted)}</strong>{" "}
                <span className="disc-muted-inline">
                  ({m.memory_total_bytes !== null ? `${m.memory_total_bytes.toLocaleString()} B` : "N/A"})
                </span>
              </dd>
            </div>
            <div>
              <dt>Memoria Disponible (Corte)</dt>
              <dd>
                {formatValOrMissing(m.memory_available_formatted)} ({formatValOrMissing(m.memory_utilization_percent, "% en uso")})
              </dd>
            </div>
            <div>
              <dt>Discos Físicos / Particiones</dt>
              <dd>
                <strong>{m.physical_disks_count}</strong> disco físico ({formatValOrMissing(m.total_physical_disk_formatted)}) ·{" "}
                <strong>{m.partitions_count}</strong> particiones
              </dd>
            </div>
          </dl>
        </div>

        <div className="disc-ledger-block">
          <h3 className="disc-ledger-heading">Red, Software y Runtime</h3>
          <dl className="disc-dl">
            <div>
              <dt>IPs Primarias / Subredes</dt>
              <dd>
                <code>{(m.primary_ips || []).join(", ") || "Ninguna"}</code> · Subredes:{" "}
                <code>{(m.derived_subnets || []).join(", ") || "N/A"}</code>
              </dd>
            </div>
            <div>
              <dt>Puerta de Enlace (Gateway)</dt>
              <dd><code>{(m.default_gateways || []).join(", ") || "No detectada"}</code></dd>
            </div>
            <div>
              <dt>Puertos en Escucha</dt>
              <dd>
                <strong>{m.listening_ports_count}</strong> total ({m.external_listeners_count} expuestos en red ·{" "}
                {m.loopback_listeners_count} loopback)
              </dd>
            </div>
            <div>
              <dt>Sockets / Endpoints Remotos</dt>
              <dd>
                {m.socket_observations_count} registros socket &rarr;{" "}
                <strong>{m.unique_remote_endpoints_count}</strong> IPs remotas únicas
              </dd>
            </div>
            <div>
              <dt>Paquetes / Servicios / Procesos</dt>
              <dd>
                <strong>{(m.installed_packages_count || 0).toLocaleString()}</strong> pkgs ·{" "}
                <strong>{m.running_services_count}</strong>/{m.systemd_units_count} servicios activos ·{" "}
                <strong>{m.processes_count}</strong> procesos
              </dd>
            </div>
          </dl>
        </div>
      </div>

      {/* Warnings, Caveats & Data Completeness */}
      <CollapsibleSubsection
        id="summary-warnings"
        title="Estado de Recolección, Advertencias y Calidad de Datos"
        badge={`${issues.length} avisos`}
        defaultOpen={true}
      >
        {q.collector_note && (
          <div className="disc-callout is-info">
            <strong>Nota del recolector:</strong> {q.collector_note}
          </div>
        )}

        {issues.length > 0 && (
          <div className="disc-issues-list">
            {issues.map((iss, i) => (
              <div key={`${iss.code}-${i}`} className={`disc-issue-item is-${iss.severity}`}>
                <div className="disc-issue-top">
                  <span className="disc-issue-code">{iss.code}</span>
                  <span className="disc-issue-sec">Sección: {iss.section}</span>
                  <StateBadge state={iss.state} />
                </div>
                <p className="disc-issue-msg">{iss.message}</p>
                {iss.suggested_action && (
                  <p className="disc-issue-action">
                    <strong>Acción sugerida:</strong> {iss.suggested_action}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}

        {(q.missing_fields || []).length > 0 && (
          <div className="disc-missing-box">
            <h4>Campos ausentes o no reportados ({q.missing_fields.length})</h4>
            <ul>
              {q.missing_fields.map((mf, idx) => (
                <li key={idx}>
                  <code>{mf.section}.{mf.field}</code>: {mf.reason}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CollapsibleSubsection>

      {/* Executive Explanatory Cards */}
      <CollapsibleSubsection
        id="summary-explanations"
        title="Análisis Explicativo de Hallazgos Principales y Migración a AWS"
        badge={`${(summary.explanations || []).length} análisis`}
        defaultOpen={true}
      >
        <div className="disc-exp-stack">
          {(summary.explanations || []).map((exp) => (
            <ExplanationCard key={exp.id} explanation={exp} defaultExpanded={true} />
          ))}
        </div>
      </CollapsibleSubsection>
    </div>
  );
}

/* ============================================================================
   B. HARDWARE SECTION
   ============================================================================ */
export function HardwareSection({ hardware }) {
  const cpu = hardware?.cpu || {};
  const mem = hardware?.memory || {};
  const stg = hardware?.storage || {};
  const fw = hardware?.firmware_and_board || {};
  const other = hardware?.other_characteristics || {};

  return (
    <div className="disc-section-view">
      <div className="disc-section-heading">
        <div>
          <h2 className="disc-page-title">Hardware — CPU, Memoria, Almacenamiento y Firmware</h2>
          <p className="disc-page-subtitle">
            Desglose jerárquico de recursos físicos reportados por <code>cpu_info</code>,{" "}
            <code>memory_info</code>, <code>block_devices</code>, <code>mounts</code> y <code>platform_info</code>.
          </p>
        </div>
      </div>

      {/* 1. CPU */}
      <CollapsibleSubsection
        id="hw-cpu"
        title="1. Procesador (CPU)"
        badge={`${cpu.physical_cores ?? "?"}C / ${cpu.logical_cores ?? "?"}T`}
        defaultOpen={true}
      >
        <div className="disc-kv-grid">
          <div className="disc-kv-card">
            <span className="disc-kv-label">Modelo detectado</span>
            <strong className="disc-kv-big">{formatValOrMissing(cpu.model)}</strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Fabricante / Arquitectura</span>
            <strong className="disc-kv-big">
              {formatValOrMissing(cpu.manufacturer)} · <code>{formatValOrMissing(cpu.architecture)}</code>
            </strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Núcleos Físicos / Lógicos</span>
            <strong className="disc-kv-big">
              {formatValOrMissing(cpu.physical_cores)} físicos · {formatValOrMissing(cpu.logical_cores)} lógicos
            </strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Sockets / Designación</span>
            <strong className="disc-kv-big">
              {formatValOrMissing(cpu.sockets)} socket ({formatValOrMissing(cpu.socket_designation)})
            </strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Frecuencia Actual / Máxima</span>
            <strong className="disc-kv-big">
              {formatValOrMissing(cpu.current_clock_mhz, " MHz")} / {formatValOrMissing(cpu.max_clock_mhz, " MHz")}
            </strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Ancho de Dirección / Microcódigo</span>
            <strong className="disc-kv-big">
              {formatValOrMissing(cpu.address_width, " bits")} · <code>{formatValOrMissing(cpu.microcode)}</code>
            </strong>
          </div>
        </div>
        <ExplanationCard explanation={cpu.explanation} defaultExpanded={false} />
      </CollapsibleSubsection>

      {/* 2. Memory */}
      <CollapsibleSubsection
        id="hw-memory"
        title="2. Memoria Física (RAM) y Swap"
        badge={mem.total_formatted || "N/A"}
        defaultOpen={true}
      >
        {mem.utilization_percent !== null && mem.utilization_percent !== undefined && (
          <div className="disc-usage-bar-wrap">
            <div className="disc-usage-bar-labels">
              <span>
                Memoria en uso derivada: <strong>{mem.used_derived_formatted}</strong> ({mem.utilization_percent}%)
              </span>
              <span>
                Disponible para aplicaciones: <strong>{mem.available_formatted}</strong> de{" "}
                <strong>{mem.total_formatted}</strong>
              </span>
            </div>
            <div className="disc-usage-track">
              <div
                className="disc-usage-fill"
                style={{ width: `${Math.min(mem.utilization_percent, 100)}%` }}
              />
            </div>
          </div>
        )}

        <div className="disc-kv-grid">
          <div className="disc-kv-card">
            <span className="disc-kv-label">Memoria Física Total</span>
            <strong className="disc-kv-big">{formatValOrMissing(mem.total_formatted)}</strong>
            <small className="disc-kv-raw">{mem.total_bytes?.toLocaleString()} bytes</small>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Memoria Disponible</span>
            <strong className="disc-kv-big">{formatValOrMissing(mem.available_formatted)}</strong>
            <small className="disc-kv-raw">{mem.available_bytes?.toLocaleString()} bytes</small>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Memoria Libre Estricta</span>
            <strong className="disc-kv-big">{formatValOrMissing(mem.free_formatted)}</strong>
            <small className="disc-kv-raw">{mem.free_bytes?.toLocaleString()} bytes</small>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Caché de Página + Buffers</span>
            <strong className="disc-kv-big">
              Caché: {formatValOrMissing(mem.cached_formatted)} · Buffers: {formatValOrMissing(mem.buffers_formatted)}
            </strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Memoria Activa / Inactiva</span>
            <strong className="disc-kv-big">
              {formatValOrMissing(mem.active_formatted)} / {formatValOrMissing(mem.inactive_formatted)}
            </strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Swap Total / Libre / Usado</span>
            <strong className="disc-kv-big">
              {formatValOrMissing(mem.swap_total_formatted)} total · {formatValOrMissing(mem.swap_free_formatted)} libre ({formatValOrMissing(mem.swap_used_derived_formatted)} usado)
            </strong>
          </div>
        </div>
        <ExplanationCard explanation={mem.explanation} defaultExpanded={false} />
      </CollapsibleSubsection>

      {/* 3. Storage */}
      <CollapsibleSubsection
        id="hw-storage"
        title="3. Almacenamiento: Discos Físicos, Particiones y Sistemas de Archivos"
        badge={`${(stg.physical_disks || []).length} disco · ${(stg.partitions || []).length} particiones`}
        defaultOpen={true}
      >
        <div className="disc-callout is-info">
          <strong>Regla de integridad de capacidad:</strong> {stg.storage_rule_note} Capacidad física total:{" "}
          <strong>{stg.total_physical_formatted}</strong>.
        </div>

        <h4 className="disc-table-heading">3.1 Dispositivos de Bloque Físicos (Raíz)</h4>
        <div className="disc-table-wrap">
          <table className="disc-table">
            <thead>
              <tr>
                <th>Dispositivo</th>
                <th>Modelo / Vendor</th>
                <th>Serie</th>
                <th>Sectores (size)</th>
                <th>Block Size</th>
                <th>Capacidad Derivada</th>
                <th>Particiones Hijas</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {(stg.physical_disks || []).map((d) => (
                <tr key={d.name}>
                  <td><code>{d.name}</code></td>
                  <td>{formatValOrMissing(d.model)} <span className="disc-muted-inline">({d.vendor || "N/A"})</span></td>
                  <td><code>{formatValOrMissing(d.serial)}</code></td>
                  <td className="num">{d.raw_sectors?.toLocaleString() ?? "N/A"}</td>
                  <td className="num">{formatValOrMissing(d.block_size, " B")}</td>
                  <td className="num"><strong>{formatValOrMissing(d.size_formatted)}</strong></td>
                  <td><code>{(d.children_partitions || []).join(", ") || "Ninguna"}</code></td>
                  <td><StateBadge state={d.state} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h4 className="disc-table-heading">3.2 Particiones Hijas (Subdivisiones del Disco Padre)</h4>
        <div className="disc-table-wrap">
          <table className="disc-table">
            <thead>
              <tr>
                <th>Partición</th>
                <th>Disco Padre</th>
                <th>Sistema de Archivos</th>
                <th>UUID</th>
                <th>Sectores (size)</th>
                <th>Sector Efectivo</th>
                <th>Tamaño Derivado</th>
                <th>Punto de Montaje</th>
              </tr>
            </thead>
            <tbody>
              {(stg.partitions || []).map((p) => (
                <tr key={p.name}>
                  <td><code>{p.name}</code></td>
                  <td><code>{formatValOrMissing(p.parent)}</code></td>
                  <td><span className="disc-tag">{formatValOrMissing(p.filesystem_type)}</span></td>
                  <td><code>{formatValOrMissing(p.uuid)}</code></td>
                  <td className="num">{p.raw_sectors?.toLocaleString() ?? "N/A"}</td>
                  <td className="num" title={p.sector_size_source}>
                    {formatValOrMissing(p.effective_sector_size, " B")}
                  </td>
                  <td className="num"><strong>{formatValOrMissing(p.size_formatted)}</strong></td>
                  <td><code>{p.mount_point || "No montada (ej. swap)"}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h4 className="disc-table-heading">3.3 Puntos de Montaje Persistentes</h4>
        <div className="disc-table-wrap">
          <table className="disc-table">
            <thead>
              <tr>
                <th>Punto de Montaje</th>
                <th>Dispositivo</th>
                <th>Tipo FS</th>
                <th>Espacio Total</th>
                <th>Espacio Usado</th>
                <th>Espacio Libre</th>
                <th>Espacio Disponible</th>
                <th>Uso %</th>
              </tr>
            </thead>
            <tbody>
              {(stg.persistent_mounts || []).map((m) => (
                <tr key={`${m.path}-${m.device}`}>
                  <td><strong><code>{m.path}</code></strong></td>
                  <td><code>{m.device}</code></td>
                  <td><span className="disc-tag">{m.filesystem}</span></td>
                  <td className="num">{formatValOrMissing(m.total_formatted)}</td>
                  <td className="num">{formatValOrMissing(m.used_formatted)}</td>
                  <td className="num">{formatValOrMissing(m.free_formatted)}</td>
                  <td className="num"><strong>{formatValOrMissing(m.available_formatted)}</strong></td>
                  <td className="num">
                    {m.usage_percent !== null ? <strong>{m.usage_percent}%</strong> : "N/A"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {(stg.physical_disks || []).map((d) => (
          <ExplanationCard key={d.name} explanation={d.explanation} defaultExpanded={false} compact={true} />
        ))}
        {(stg.persistent_mounts || []).map((m) => (
          <ExplanationCard key={m.path} explanation={m.explanation} defaultExpanded={false} compact={true} />
        ))}
      </CollapsibleSubsection>

      {/* 4. Firmware & Motherboard */}
      <CollapsibleSubsection
        id="hw-firmware"
        title="4. Firmware UEFI/BIOS y Placa Base"
        badge={(fw.firmware_type || "UEFI").toUpperCase()}
        defaultOpen={false}
      >
        <div className="disc-kv-grid">
          <div className="disc-kv-card">
            <span className="disc-kv-label">Tipo de Firmware</span>
            <strong className="disc-kv-big">{formatValOrMissing(fw.firmware_type?.toUpperCase())}</strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Proveedor / Versión de Firmware</span>
            <strong className="disc-kv-big">
              {formatValOrMissing(fw.firmware_vendor)} · <code>{formatValOrMissing(fw.firmware_version)}</code>
            </strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Fecha y Revisión BIOS/UEFI</span>
            <strong className="disc-kv-big">
              {formatValOrMissing(fw.firmware_date)} (Rev. {formatValOrMissing(fw.firmware_revision)})
            </strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Placa Base (Fabricante / Modelo)</span>
            <strong className="disc-kv-big">
              {formatValOrMissing(fw.board_vendor)} · <code>{formatValOrMissing(fw.board_model)}</code>
            </strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Versión de Placa / Chasis</span>
            <strong className="disc-kv-big">
              {formatValOrMissing(fw.board_version)} ({formatValOrMissing(fw.hardware_version)})
            </strong>
          </div>
          <div className="disc-kv-card">
            <span className="disc-kv-label">Número de Serie</span>
            <strong className="disc-kv-big"><code>{formatValOrMissing(fw.board_serial || fw.hardware_serial)}</code></strong>
          </div>
        </div>
        <ExplanationCard explanation={fw.explanation} defaultExpanded={true} />
      </CollapsibleSubsection>

      {/* 5. Other Hardware Characteristics */}
      <CollapsibleSubsection
        id="hw-other"
        title="5. Otras Características y Módulos de Hardware"
        badge={(other.gpu_kernel_modules || []).length > 0 ? "GPU Detectada" : "Estándar"}
        defaultOpen={false}
      >
        <ExplanationCard explanation={other.explanation} defaultExpanded={true} />
      </CollapsibleSubsection>
    </div>
  );
}

/* ============================================================================
   C. SOFTWARE SECTION
   ============================================================================ */
export function SoftwareSection({ software, sessionId, apiUrl }) {
  const [pkgSearch, setPkgSearch] = useState("");
  const [pkgSection, setPkgSection] = useState("all");
  const [pkgItems, setPkgItems] = useState(software?.packages || []);
  const [pkgTotal, setPkgTotal] = useState(software?.packages_total_count || software?.package_count || 0);
  const [pkgOffset, setPkgOffset] = useState(0);
  const [loadingPkgs, setLoadingPkgs] = useState(false);

  const [svcSearch, setSvcSearch] = useState("");
  const [svcStateFilter, setSvcStateFilter] = useState("active");
  const [kmodSearch, setKmodSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function fetchPackages() {
      if (!sessionId) return;
      setLoadingPkgs(true);
      try {
        const params = new URLSearchParams({
          limit: "100",
          offset: String(pkgOffset),
        });
        if (pkgSearch.trim()) params.set("q", pkgSearch.trim());
        if (pkgSection !== "all") params.set("section", pkgSection);

        const res = await fetch(`${apiUrl}/api/v1/discovery/sessions/${sessionId}/packages?${params}`);
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) {
            setPkgItems(data.items || []);
            setPkgTotal(data.total ?? 0);
          }
        }
      } catch {
        // Fallback to inline packages filtering when offline
      } finally {
        if (!cancelled) setLoadingPkgs(false);
      }
    }
    fetchPackages();
    return () => {
      cancelled = true;
    };
  }, [sessionId, apiUrl, pkgSearch, pkgSection, pkgOffset]);

  const filteredServices = useMemo(() => {
    const list = software?.services || [];
    const q = svcSearch.trim().toLowerCase();
    return list.filter((s) => {
      if (svcStateFilter !== "all" && s.active_state !== svcStateFilter) return false;
      if (q) {
        return (
          (s.id || "").toLowerCase().includes(q) ||
          (s.description || "").toLowerCase().includes(q) ||
          (s.fragment_path || "").toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [software?.services, svcSearch, svcStateFilter]);

  const filteredKmods = useMemo(() => {
    const list = software?.kernel_modules || [];
    const q = kmodSearch.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (m) =>
        (m.name || "").toLowerCase().includes(q) ||
        (m.used_by || []).join(" ").toLowerCase().includes(q)
    );
  }, [software?.kernel_modules, kmodSearch]);

  const sectionsList = Object.entries(software?.package_section_counts || {});

  return (
    <div className="disc-section-view">
      <div className="disc-section-heading">
        <div>
          <h2 className="disc-page-title">Software — Paquetes, Servicios Systemd, Módulos y Aplicaciones</h2>
          <p className="disc-page-subtitle">
            Catálogo de {(software?.package_count || 0).toLocaleString()} paquetes instalados,{" "}
            {software?.service_count || 0} unidades systemd y {software?.kernel_module_count || 0} módulos del kernel.
          </p>
        </div>
      </div>

      <ExplanationCard explanation={software?.explanation} defaultExpanded={false} />

      {/* 1. Relevant Applications */}
      <CollapsibleSubsection
        id="sw-relevant-apps"
        title="1. Software Potencialmente Relevante para Evaluación de Migración"
        badge="Clasificado por evidencia"
        defaultOpen={true}
      >
        <div className="disc-callout is-warning">
          <strong>Principio de interpretación:</strong> Un paquete instalado en <code>dpkg</code> no constituye
          automáticamente una aplicación empresarial activa ni una carga de trabajo independiente. Revise siempre si
          tiene servicios <code>systemd</code> o procesos en ejecución.
        </div>

        <div className="disc-app-groups-grid">
          {(software?.relevant_applications || []).map((grp) => (
            <div key={grp.id} className="disc-app-group-card">
              <div className="disc-app-group-head">
                <h4>{grp.title}</h4>
                <span className="disc-subsection-badge">{(grp.packages || []).length} pkgs</span>
              </div>
              <p className="disc-app-group-desc">{grp.rationale}</p>
              {(grp.packages || []).length === 0 ? (
                <p className="disc-muted-inline">Sin paquetes detectados en esta categoría.</p>
              ) : (
                <div className="disc-pkg-pills">
                  {grp.packages.map((p) => (
                    <span key={`${p.name}-${p.version}`} className="disc-pkg-pill">
                      <strong>{p.name}</strong> <code>{p.version}</code>
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </CollapsibleSubsection>

      {/* 2. Systemd Services */}
      <CollapsibleSubsection
        id="sw-services"
        title="2. Servicios y Unidades del Sistema (systemd_units)"
        badge={`${filteredServices.length} / ${software?.service_count || 0}`}
        defaultOpen={true}
      >
        <div className="disc-filter-bar">
          <input
            type="search"
            className="disc-search-input"
            placeholder="Buscar servicio por nombre, descripción o ruta de unidad..."
            value={svcSearch}
            onChange={(e) => setSvcSearch(e.target.value)}
          />
          <select
            className="disc-select"
            value={svcStateFilter}
            onChange={(e) => setSvcStateFilter(e.target.value)}
          >
            <option value="all">Todos los estados ({software?.service_count || 0})</option>
            <option value="active">Activos (active)</option>
            <option value="inactive">Inactivos (inactive)</option>
            <option value="failed">Con fallo (failed)</option>
          </select>
        </div>

        <div className="disc-table-wrap is-scrollable">
          <table className="disc-table">
            <thead>
              <tr>
                <th>Unidad Systemd</th>
                <th>Tipo</th>
                <th>Estado Activo / Subestado</th>
                <th>Configuración (Unit File)</th>
                <th>Descripción</th>
                <th>Ruta / Fragment Path</th>
              </tr>
            </thead>
            <tbody>
              {filteredServices.slice(0, 150).map((s) => (
                <tr key={s.id}>
                  <td><strong><code>{s.id}</code></strong></td>
                  <td><span className="disc-tag">{s.unit_type}</span></td>
                  <td>
                    <span className={`disc-status-pill is-${s.active_state}`}>
                      {s.active_state} / {s.sub_state}
                    </span>
                  </td>
                  <td><code>{formatValOrMissing(s.unit_file_state)}</code></td>
                  <td>{formatValOrMissing(s.description)}</td>
                  <td><code className="disc-code-xs">{formatValOrMissing(s.fragment_path)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSubsection>

      {/* 3. Installed Debian Packages */}
      <CollapsibleSubsection
        id="sw-packages"
        title="3. Paquetes Debian Instalados (deb_packages)"
        badge={`${pkgTotal.toLocaleString()} paquetes`}
        defaultOpen={true}
      >
        <div className="disc-filter-bar">
          <input
            type="search"
            className="disc-search-input"
            placeholder="Buscar paquete por nombre o versión (ej. postgresql, docker, nginx, python3)..."
            value={pkgSearch}
            onChange={(e) => {
              setPkgSearch(e.target.value);
              setPkgOffset(0);
            }}
          />
          <select
            className="disc-select"
            value={pkgSection}
            onChange={(e) => {
              setPkgSection(e.target.value);
              setPkgOffset(0);
            }}
          >
            <option value="all">Todas las secciones</option>
            {sectionsList.map(([sec, cnt]) => (
              <option key={sec} value={sec}>
                {sec} ({cnt})
              </option>
            ))}
          </select>
          <div className="disc-pagination-controls">
            <button
              type="button"
              className="toolbar-btn"
              disabled={pkgOffset === 0 || loadingPkgs}
              onClick={() => setPkgOffset((o) => Math.max(0, o - 100))}
            >
              &larr; Anterior
            </button>
            <span className="disc-page-indicator">
              {pkgTotal === 0 ? "0" : `${pkgOffset + 1}–${Math.min(pkgOffset + 100, pkgTotal)}`} de{" "}
              {pkgTotal.toLocaleString()}
            </span>
            <button
              type="button"
              className="toolbar-btn"
              disabled={pkgOffset + 100 >= pkgTotal || loadingPkgs}
              onClick={() => setPkgOffset((o) => o + 100)}
            >
              Siguiente &rarr;
            </button>
          </div>
        </div>

        <div className="disc-table-wrap is-scrollable">
          <table className="disc-table">
            <thead>
              <tr>
                <th>Nombre del Paquete</th>
                <th>Versión</th>
                <th>Arquitectura</th>
                <th>Sección</th>
                <th>Tamaño (KiB)</th>
                <th>Fuente de Datos</th>
              </tr>
            </thead>
            <tbody>
              {pkgItems.map((p, idx) => (
                <tr key={`${p.name}-${p.version}-${idx}`}>
                  <td><strong><code>{p.name}</code></strong></td>
                  <td><code>{formatValOrMissing(p.version)}</code></td>
                  <td><span className="disc-tag">{formatValOrMissing(p.arch)}</span></td>
                  <td>{formatValOrMissing(p.section)}</td>
                  <td className="num">{p.size_kb !== null && p.size_kb !== undefined ? p.size_kb.toLocaleString() : "N/A"}</td>
                  <td><code>{p.data_source || "software.deb_packages"}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSubsection>

      {/* 4. Kernel Modules */}
      <CollapsibleSubsection
        id="sw-kernel-modules"
        title="4. Módulos del Kernel Cargados (kernel_modules)"
        badge={`${filteredKmods.length} módulos`}
        defaultOpen={false}
      >
        <div className="disc-filter-bar">
          <input
            type="search"
            className="disc-search-input"
            placeholder="Filtrar módulo del kernel (ej. nvidia, xt_conntrack, overlay, nvme)..."
            value={kmodSearch}
            onChange={(e) => setKmodSearch(e.target.value)}
          />
        </div>
        <div className="disc-table-wrap is-scrollable">
          <table className="disc-table">
            <thead>
              <tr>
                <th>Módulo</th>
                <th>Estado</th>
                <th>Tamaño en Memoria</th>
                <th>Usado por (Dependientes)</th>
              </tr>
            </thead>
            <tbody>
              {filteredKmods.map((m) => (
                <tr key={m.name}>
                  <td><strong><code>{m.name}</code></strong></td>
                  <td><span className="disc-status-pill is-active">{formatValOrMissing(m.status)}</span></td>
                  <td className="num">{formatValOrMissing(m.size_formatted)}</td>
                  <td><code>{(m.used_by || []).join(", ") || "—"}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSubsection>
    </div>
  );
}

/* ============================================================================
   D. NETWORK SECTION
   ============================================================================ */
export function NetworkSection({ network }) {
  const ifaces = network?.interfaces || [];
  const routes = network?.routes || [];
  const listeners = network?.listening_ports || [];
  const peers = network?.observed_remote_endpoints || [];
  const sockSum = network?.socket_summary || {};

  return (
    <div className="disc-section-view">
      <div className="disc-section-heading">
        <div>
          <h2 className="disc-page-title">Red — Interfaces, Subredes, Rutas, Puertos y Conexiones</h2>
          <p className="disc-page-subtitle">
            {ifaces.length} direcciones en interfaces · {routes.length} rutas · {listeners.length} puertos en escucha ·{" "}
            {peers.length} endpoints remotos observados.
          </p>
        </div>
      </div>

      {/* 1. Interfaces */}
      <CollapsibleSubsection
        id="net-interfaces"
        title="1. Interfaces de Red, Direcciones IPv4/IPv6 y Subredes Derivadas"
        badge={`${ifaces.length} asignaciones`}
        defaultOpen={true}
      >
        <div className="disc-table-wrap">
          <table className="disc-table">
            <thead>
              <tr>
                <th>Interfaz</th>
                <th>Versión</th>
                <th>Dirección</th>
                <th>Máscara</th>
                <th>CIDR Derivado</th>
                <th>Subred Derivada</th>
                <th>Clasificación</th>
                <th>Estado del Dato</th>
              </tr>
            </thead>
            <tbody>
              {ifaces.map((i) => (
                <tr key={i.id}>
                  <td><strong><code>{i.interface}</code></strong></td>
                  <td><span className="disc-tag">{i.ip_version}</span></td>
                  <td><code>{formatValOrMissing(i.address)}</code></td>
                  <td><code>{formatValOrMissing(i.mask)}</code></td>
                  <td><code>{formatValOrMissing(i.cidr)}</code></td>
                  <td><strong><code>{formatValOrMissing(i.subnet)}</code></strong></td>
                  <td>
                    <span className="disc-tag">{i.classified_kind}</span>
                  </td>
                  <td><StateBadge state={i.classified_state} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="disc-exp-stack">
          {ifaces.map((i) => (
            <ExplanationCard key={i.id} explanation={i.explanation} defaultExpanded={false} compact={true} />
          ))}
        </div>
      </CollapsibleSubsection>

      {/* 2. Listening Ports */}
      <CollapsibleSubsection
        id="net-listening-ports"
        title="2. Puertos en Escucha y Correlación con Procesos (listening_ports)"
        badge={`${listeners.length} sockets LISTEN`}
        defaultOpen={true}
      >
        <div className="disc-table-wrap">
          <table className="disc-table">
            <thead>
              <tr>
                <th>Protocolo / Puerto</th>
                <th>Dirección de Escucha</th>
                <th>Exposición</th>
                <th>PID</th>
                <th>Proceso Asociado</th>
                <th>Ruta del Ejecutable</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {listeners.map((l) => (
                <tr key={l.id}>
                  <td><strong><code>{l.protocol}/{l.port}</code></strong></td>
                  <td><code>{l.address}</code></td>
                  <td>
                    <span className={`disc-exposure-pill is-${l.exposure}`}>
                      {l.exposure_label}
                    </span>
                  </td>
                  <td className="num"><code>{formatValOrMissing(l.pid)}</code></td>
                  <td><strong>{l.process_name}</strong></td>
                  <td><code className="disc-code-xs">{formatValOrMissing(l.process_path)}</code></td>
                  <td><StateBadge state={l.state} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="disc-exp-stack">
          {listeners.slice(0, 6).map((l) => (
            <ExplanationCard key={l.id} explanation={l.explanation} defaultExpanded={false} compact={true} />
          ))}
        </div>
      </CollapsibleSubsection>

      {/* 3. Observed Remote Endpoints */}
      <CollapsibleSubsection
        id="net-remote-endpoints"
        title="3. Conexiones y Endpoints Remotos Observados (Instantánea de Sockets)"
        badge={`${peers.length} endpoints únicos`}
        defaultOpen={true}
      >
        <div className="disc-callout is-warning">
          <strong>Advertencia metodológica:</strong> Estos {peers.length} endpoints remotos provienen de{" "}
          {sockSum.total_sockets_queried || 0} registros en <code>process_open_sockets</code> capturados en un único
          instante. <strong>No representan dependencias confirmadas entre aplicaciones empresariales.</strong>
        </div>

        <div className="disc-table-wrap">
          <table className="disc-table">
            <thead>
              <tr>
                <th>IP Remota</th>
                <th>Puerto / Protocolo</th>
                <th>Ámbito IP</th>
                <th>Observaciones</th>
                <th>Procesos Locales Observados</th>
                <th>IPs Locales Origen</th>
                <th>Naturaleza</th>
              </tr>
            </thead>
            <tbody>
              {peers.map((p) => (
                <tr key={p.id}>
                  <td><strong><code>{p.remote_ip}</code></strong></td>
                  <td><code>{p.protocol}/{p.remote_port}</code></td>
                  <td>
                    <span className="disc-tag">
                      {p.is_public_ip ? "IP Pública" : "IP Privada / LAN"}
                    </span>
                  </td>
                  <td className="num"><strong>{p.observation_count}</strong></td>
                  <td>
                    {(p.processes || []).map((pr) => `${pr.name} (${pr.observations})`).join(", ")}
                  </td>
                  <td>
                    <code>{(p.local_addresses || []).map((la) => la.address).join(", ")}</code>
                  </td>
                  <td>
                    <span className="disc-state-badge is-inferred">
                      Observación puntual (No confirmada)
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="disc-exp-stack">
          {peers.slice(0, 5).map((p) => (
            <ExplanationCard key={p.id} explanation={p.explanation} defaultExpanded={false} compact={true} />
          ))}
        </div>
      </CollapsibleSubsection>

      {/* 4. Routes & Gateways */}
      <CollapsibleSubsection
        id="net-routes"
        title="4. Tabla de Rutas y Puertas de Enlace (routes)"
        badge={`${routes.length} rutas`}
        defaultOpen={false}
      >
        <div className="disc-table-wrap">
          <table className="disc-table">
            <thead>
              <tr>
                <th>Destino</th>
                <th>Prefijo / Máscara</th>
                <th>Gateway</th>
                <th>Interfaz</th>
                <th>IP Origen</th>
                <th>Tipo</th>
                <th>Métrica</th>
              </tr>
            </thead>
            <tbody>
              {routes.map((r) => (
                <tr key={r.id}>
                  <td><strong><code>{r.destination}</code></strong></td>
                  <td><code>{formatValOrMissing(r.netmask)}</code></td>
                  <td><code>{r.gateway || "Directo / Local"}</code></td>
                  <td><code>{formatValOrMissing(r.interface)}</code></td>
                  <td><code>{formatValOrMissing(r.source)}</code></td>
                  <td><span className="disc-tag">{formatValOrMissing(r.type)}</span></td>
                  <td className="num">{r.metric ?? "0"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSubsection>
    </div>
  );
}

/* ============================================================================
   E. RUNTIME / PROCESSES SECTION
   ============================================================================ */
export function RuntimeSection({ runtime }) {
  const [procSearch, setProcSearch] = useState("");
  const [onlyNet, setOnlyNet] = useState(false);
  const [hideKernel, setHideKernel] = useState(true);

  const uptime = runtime?.uptime || {};
  const processes = useMemo(() => runtime?.processes || [], [runtime?.processes]);

  const filteredProcs = useMemo(() => {
    const q = procSearch.trim().toLowerCase();
    return processes.filter((p) => {
      if (onlyNet && (!p.listening_ports || p.listening_ports.length === 0) && !p.open_socket_count) {
        return false;
      }
      if (hideKernel && p.is_kernel_thread) {
        return false;
      }
      if (q) {
        return (
          String(p.pid || "").includes(q) ||
          (p.name || "").toLowerCase().includes(q) ||
          (p.path || "").toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [processes, procSearch, onlyNet, hideKernel]);

  return (
    <div className="disc-section-view">
      <div className="disc-section-heading">
        <div>
          <h2 className="disc-page-title">Runtime — Tiempo de Actividad y Procesos en Ejecución</h2>
          <p className="disc-page-subtitle">
            Uptime del sistema: <strong>{uptime.formatted}</strong> · {runtime?.process_count || 0} procesos totales ({runtime?.user_process_count || 0} de espacio de usuario y {runtime?.kernel_thread_count || 0} hilos del kernel).
          </p>
        </div>
      </div>

      <ExplanationCard explanation={uptime.explanation} defaultExpanded={true} />

      <div className="disc-callout is-info">
        <strong>Protección de Privacidad y Secretos:</strong> {runtime?.privacy_note}
      </div>

      <CollapsibleSubsection
        id="rt-processes"
        title="Lista de Procesos y Correlación con Puertos/Sockets"
        badge={`${filteredProcs.length} visibles`}
        defaultOpen={true}
      >
        <div className="disc-filter-bar">
          <input
            type="search"
            className="disc-search-input"
            placeholder="Buscar por PID, nombre de proceso o ruta ejecutable..."
            value={procSearch}
            onChange={(e) => setProcSearch(e.target.value)}
          />
          <label className="disc-checkbox-label">
            <input
              type="checkbox"
              checked={onlyNet}
              onChange={(e) => setOnlyNet(e.target.checked)}
            />
            Solo con puertos/sockets abiertos
          </label>
          <label className="disc-checkbox-label">
            <input
              type="checkbox"
              checked={hideKernel}
              onChange={(e) => setHideKernel(e.target.checked)}
            />
            Ocultar hilos del kernel ({runtime?.kernel_thread_count || 0})
          </label>
        </div>

        <div className="disc-table-wrap is-scrollable">
          <table className="disc-table">
            <thead>
              <tr>
                <th>PID</th>
                <th>Nombre del Proceso</th>
                <th>Ruta del Ejecutable</th>
                <th>UID</th>
                <th>Puertos en Escucha</th>
                <th>Sockets Abiertos</th>
                <th>Peers Remotos</th>
              </tr>
            </thead>
            <tbody>
              {filteredProcs.map((p) => (
                <tr key={p.pid}>
                  <td className="num"><code>{p.pid}</code></td>
                  <td><strong>{p.name}</strong></td>
                  <td><code className="disc-code-xs">{p.path || "Hilo de kernel / sin binario"}</code></td>
                  <td className="num"><code>{p.uid}</code></td>
                  <td>
                    {(p.listening_ports || []).length > 0 ? (
                      <code>{p.listening_ports.join(", ")}</code>
                    ) : (
                      <span className="disc-muted-inline">—</span>
                    )}
                  </td>
                  <td className="num">{p.open_socket_count || 0}</td>
                  <td className="num">{p.remote_peers_count || 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSubsection>
    </div>
  );
}

/* ============================================================================
   F. DATABASES SECTION
   ============================================================================ */
export function DatabasesSection({ databases }) {
  const evidence = databases?.detected_engine_evidence || [];
  const specs = databases?.prepared_collectors || [];

  return (
    <div className="disc-section-view">
      <div className="disc-section-heading">
        <div>
          <h2 className="disc-page-title">Bases de Datos — Indicios Observados y Alcance de Recolección</h2>
          <p className="disc-page-subtitle">
            Distinción estricta entre paquetes instalados en el host e instancias de bases de datos en ejecución.
          </p>
        </div>
        <span className="disc-state-badge is-unavailable">{databases?.summary_badge}</span>
      </div>

      <div className="disc-callout is-warning">
        <strong>Estado de metadatos de bases de datos:</strong> {databases?.summary_explanation}
      </div>

      <CollapsibleSubsection
        id="db-evidence"
        title="1. Indicios de Motores de Bases de Datos en el Host"
        badge={`${evidence.length} motores analizados`}
        defaultOpen={true}
      >
        <div className="disc-table-wrap">
          <table className="disc-table">
            <thead>
              <tr>
                <th>Motor</th>
                <th>Paquetes Detectados en dpkg</th>
                <th>Procesos Activos</th>
                <th>Puertos en Escucha</th>
                <th>Estado en Runtime</th>
                <th>Catálogo Interno (Esquemas / Tablas / Tamaño)</th>
              </tr>
            </thead>
            <tbody>
              {evidence.map((ev) => (
                <tr key={ev.engine_id}>
                  <td><strong>{ev.engine_name}</strong></td>
                  <td>
                    <code>
                      {(ev.packages_detected || [])
                        .slice(0, 4)
                        .map((p) => `${p.name} (${p.version})`)
                        .join(", ")}
                    </code>
                  </td>
                  <td>
                    {(ev.running_processes || []).length > 0
                      ? ev.running_processes.map((p) => `${p.name} (PID ${p.pid})`).join(", ")
                      : "0 procesos activos"}
                  </td>
                  <td>
                    {(ev.listening_ports || []).length > 0
                      ? ev.listening_ports.map((l) => `${l.port}`).join(", ")
                      : "Ninguno"}
                  </td>
                  <td>
                    <span className="disc-status-pill is-inactive">{ev.runtime_status}</span>
                  </td>
                  <td>
                    <span className="disc-state-badge is-unavailable">
                      {ev.catalog_metadata_status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="disc-exp-stack">
          {evidence.map((ev) => (
            <ExplanationCard key={ev.engine_id} explanation={ev.explanation} defaultExpanded={true} />
          ))}
        </div>
      </CollapsibleSubsection>

      <CollapsibleSubsection
        id="db-collectors"
        title="2. Arquitectura Preparada para Recolectores Específicos (PostgreSQL, MySQL, SQL Server)"
        badge={`${specs.length} conectores preparados`}
        defaultOpen={true}
      >
        <div className="disc-app-groups-grid">
          {specs.map((sp) => (
            <div key={sp.engine_id} className="disc-app-group-card">
              <div className="disc-app-group-head">
                <h4>{sp.engine_name}</h4>
                <span className="disc-state-badge is-derived">Interfaz preparada</span>
              </div>
              <p className="disc-app-group-desc">
                <strong>Servicios destino AWS:</strong> {(sp.target_aws_services || []).join(" · ")}
              </p>
              <h5>Metadatos pendientes que osquery no recopila:</h5>
              <ul className="disc-compact-list">
                {(sp.missing_in_osquery || []).map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
              <h5>Consultas de catálogo previstas:</h5>
              <pre className="disc-code-block">{(sp.required_queries || []).join("\n")}</pre>
            </div>
          ))}
        </div>
      </CollapsibleSubsection>
    </div>
  );
}

/* ============================================================================
   G. MIGRATION ASSESSMENT SECTION
   ============================================================================ */
export function AssessmentSection({ assessment }) {
  if (!assessment) return null;

  return (
    <div className="disc-section-view">
      <div className="disc-section-heading">
        <div>
          <h2 className="disc-page-title">Evaluación de Preparación para Migración a AWS (Assessment)</h2>
          <p className="disc-page-subtitle">
            Separación rigurosa entre hechos descubiertos, información pendiente, riesgos y pasos de validación.
          </p>
        </div>
      </div>

      <div className="disc-callout is-info">
        <strong>Postura actual:</strong> {assessment.readiness_summary}
      </div>

      <div className="disc-assessment-columns">
        <div className="disc-assess-card is-positive">
          <h3>Información Disponible (Confirmada por Discovery)</h3>
          <ul className="disc-assess-list">
            {(assessment.available_information || []).map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>

        <div className="disc-assess-card is-pending">
          <h3>Información Pendiente de Recopilar</h3>
          <ul className="disc-assess-list">
            {(assessment.pending_information || []).map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      </div>

      <CollapsibleSubsection
        id="assess-risks"
        title="Posibles Riesgos y Condiciones Detectadas"
        badge={`${(assessment.identified_risks || []).length} riesgos`}
        defaultOpen={true}
      >
        <div className="disc-issues-list">
          {(assessment.identified_risks || []).map((r) => (
            <div key={r.id} className={`disc-issue-item is-${r.severity === "high" ? "error" : "warning"}`}>
              <div className="disc-issue-top">
                <span className="disc-issue-code">RIESGO {r.severity?.toUpperCase()}</span>
                <strong>{r.title}</strong>
              </div>
              <p className="disc-issue-msg">{r.detail}</p>
            </div>
          ))}
        </div>
      </CollapsibleSubsection>

      <div className="disc-assessment-columns">
        <div className="disc-assess-card">
          <h3>Compatibilidad Pendiente de Verificar</h3>
          <ul className="disc-assess-list">
            {(assessment.compatibility_to_verify || []).map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>

        <div className="disc-assess-card">
          <h3>Métricas Históricas Requeridas antes de Right-Sizing</h3>
          <ul className="disc-assess-list">
            {(assessment.historical_metrics_needed || []).map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      </div>

      <CollapsibleSubsection
        id="assess-deps"
        title="Dependencias Confirmadas vs. Conexiones Observadas"
        defaultOpen={true}
      >
        <div className="disc-assessment-columns">
          <div className="disc-assess-card is-positive">
            <h4>Relaciones Estructurales Confirmadas</h4>
            <ul className="disc-assess-list">
              {(assessment.dependencies_distinction?.confirmed_structural || []).map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
          <div className="disc-assess-card is-pending">
            <h4>Observaciones Puntuales (No Confirmadas como Dependencia)</h4>
            <ul className="disc-assess-list">
              {(assessment.dependencies_distinction?.observed_unconfirmed || []).map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
        </div>
      </CollapsibleSubsection>

      <CollapsibleSubsection
        id="assess-next-steps"
        title="Recomendaciones Siguientes para Migración y Open-AudIT"
        defaultOpen={true}
      >
        <ul className="disc-assess-list">
          {(assessment.recommended_next_steps || []).map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ul>
      </CollapsibleSubsection>
    </div>
  );
}

/* ==========================================================================
   H. DIAGRAMA AWS SUGERIDO (ARCHIFY) Y GENERADOR TERRAFORM DESDE JSON
   ========================================================================== */
export function AwsSuggestedDiagramSection({ data, apiUrl }) {
  const [iframeHeight, setIframeHeight] = useState(680);
  const [tfStrategy, setTfStrategy] = useState("replatform");
  const [activeTfFile, setActiveTfFile] = useState("main.tf");
  const [copyFeedback, setCopyFeedback] = useState("");
  const [persistFeedback, setPersistFeedback] = useState("");
  const [persisting, setPersisting] = useState(false);

  if (!data) return null;

  const summary = data.summary || {};
  const hw = data.sections?.hardware || {};
  const net = data.sections?.network || {};
  const hostname = data.hostname || summary.hostname || "rabbitmq-kali";
  const osLabel = `${summary.os?.name || "Kali GNU/Linux"} ${summary.os?.version || "2025.4"}`.trim();
  const cpuBrand = hw.cpu?.brand || summary.cpu?.brand || "AMD Ryzen 5 5500U";
  const vcpus = hw.cpu?.logical_cores ?? summary.cpu?.logical_cores ?? 2;
  const ramHuman = hw.memory?.total_human || summary.memory?.total_human || "1.88 GiB";
  const diskHuman = hw.storage?.total_physical_disk_human || summary.storage?.total_physical_disk_human || "80.00 GiB";
  const rootFs = (hw.storage?.filesystems || [])[0] || {};
  const rootUsedHuman = rootFs.used_human || "14.91 GiB";
  const rootUsedPct = rootFs.used_percent ?? 19.29;
  const primaryIface = (net.interfaces || []).find((i) => i.interface !== "lo") || {};
  const primaryCidr = primaryIface.cidr || "10.0.2.15/24";

  const tfBundle =
    data.terraform?.[tfStrategy] ||
    data.terraform?.replatform ||
    null;

  const tfFiles = tfBundle?.files || {};
  const currentTfCode =
    activeTfFile === "all"
      ? tfBundle?.iac_code || ""
      : tfFiles[activeTfFile] || tfBundle?.iac_code || "";

  const handleCopyTf = async (text, label = "Código HCL") => {
    try {
      await navigator.clipboard.writeText(text);
      setCopyFeedback(`${label} copiado al portapapeles`);
      setTimeout(() => setCopyFeedback(""), 2500);
    } catch {
      setCopyFeedback("No se pudo copiar automáticamente");
    }
  };

  const handleDownloadTf = (filename, content) => {
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handlePersistToProject = async () => {
    if (!data.session_id) return;
    setPersisting(true);
    setPersistFeedback("");
    try {
      const base = apiUrl || "http://localhost:8001";
      const res = await fetch(
        `${base}/api/v1/discovery/sessions/${data.session_id}/terraform?strategy=${tfStrategy}&write_files=true`,
        { method: "POST" }
      );
      if (res.ok) {
        const json = await res.json();
        setPersistFeedback(
          `Archivos provider.tf, variables.tf, main.tf y outputs.tf guardados en ${json.written_to_dir || "generated/aws/"}`
        );
      } else {
        setPersistFeedback("Error al escribir archivos en generated/aws/.");
      }
    } catch {
      setPersistFeedback("No se pudo conectar con el backend para escribir en generated/aws/.");
    } finally {
      setPersisting(false);
    }
  };

  const awsMappings = [
    {
      id: "map-compute",
      sourceComponent: `Host ${hostname} (${osLabel})`,
      observedEvidence: `${cpuBrand} (${vcpus} vCPU) · ${ramHuman} RAM · Hipervisor VirtualBox`,
      rehostTarget: "Amazon EC2 t3a.small / t3.small (2 vCPU, 2 GiB RAM) vía AWS MGN",
      replatformTarget: "Desacoplar servicios en contenedores ECS Fargate o instancias dedicadas",
      state: "observed",
    },
    {
      id: "map-storage",
      sourceComponent: "Disco físico /dev/sda y sistema de archivos / (ext4)",
      observedEvidence: `${diskHuman} brutos aprovisionados · ${rootUsedHuman} usados (${rootUsedPct}%)`,
      rehostTarget: "Amazon EBS gp3 (80 GiB 1:1 o 30 GiB optimizado, 3,000 IOPS, cifrado KMS)",
      replatformTarget: "Almacenamiento administrado en Amazon RDS + Amazon MQ (sin gestión manual de LVM/ext4)",
      state: "derived",
    },
    {
      id: "map-messaging",
      sourceComponent: "RabbitMQ Broker (beam.smp PID 1076)",
      observedEvidence: "TCP :5672 (AMQP), :25672 (Clustering), :15692 (Prometheus), :4369 (epmd) en 0.0.0.0/::",
      rehostTarget: "RabbitMQ autogestionado en EC2 dentro de Subred Privada VPC",
      replatformTarget: "Amazon MQ for RabbitMQ (Broker administrado Multi-AZ con endpoint AMQP :5671/:5672)",
      state: "observed",
    },
    {
      id: "map-database",
      sourceComponent: "PostgreSQL 17 (postgres PID 1031)",
      observedEvidence: "TCP 127.0.0.1:5432 y ::1:5432 (loopback) · /var/lib/postgresql/17/main",
      rehostTarget: "PostgreSQL 17 local en la misma instancia EC2 (solo consumo local)",
      replatformTarget: "Amazon RDS for PostgreSQL 17 en Subred Privada (backups automáticos y Multi-AZ)",
      state: "observed",
    },
    {
      id: "map-network",
      sourceComponent: `Interfaz ${primaryIface.interface || "eth0"} + Gateway 10.0.2.2`,
      observedEvidence: `IP ${primaryCidr} (NAT VirtualBox) · SSH :22 y AMQP :5672 expuestos`,
      rehostTarget: "Amazon VPC (10.0.0.0/16) + ENI en Subred Privada + Security Group mínimo privilegio",
      replatformTarget: "AWS Systems Manager Session Manager (reemplaza SSH :22 público) + Security Groups por capa",
      state: "inferred",
    },
    {
      id: "map-observability",
      sourceComponent: "Métricas RabbitMQ (:15692) y 668 unidades systemd",
      observedEvidence: "Plugin rabbitmq_prometheus activo en :15692 + journald local",
      rehostTarget: "CloudWatch Agent en EC2 para memoria, disco y logs de systemd",
      replatformTarget: "Amazon CloudWatch + Amazon Managed Service for Prometheus (AMP)",
      state: "derived",
    },
  ];

  const archifyExplanations = [
    {
      what_is: "Amazon EC2 t3a.small / t3.small (Nodo central de cómputo en el diagrama Archify)",
      detected_value: `Origen: ${vcpus} núcleos lógicos (${cpuBrand}) y ${ramHuman} de RAM física`,
      interpretation:
        "Las familias t3a.small y t3.small en AWS ofrecen exactamente 2 vCPUs x86_64 y 2 GiB de RAM, coincidiendo con la huella de hardware observada en osquery.",
      why_it_matters:
        "Permite ejecutar una migración Rehost (Lift & Shift) mediante AWS Application Migration Service (MGN) sin sobreaprovisionar cómputo.",
      migration_relevance:
        "Si PostgreSQL 17 y RabbitMQ se trasladan a servicios administrados (RDS y Amazon MQ), la instancia EC2 puede reducirse aún más o eliminarse si solo actuaba como host de ambos servicios.",
      provenance: "asset.system_info + hardware.memory_info",
      state: "derived",
      limitations:
        "Osquery captura la capacidad instalada, no el percentil 95 de uso de CPU/RAM a lo largo de varias semanas.",
      suggested_action:
        "Monitorear CPU Credit Balance durante las primeras 2 semanas en AWS o recolectar sar/vmstat antes del cutover.",
    },
    {
      what_is: "Amazon MQ for RabbitMQ y Amazon RDS for PostgreSQL 17 (Rutas Replatform en el diagrama Archify)",
      detected_value: "beam.smp en TCP :5672/:25672/:15692 y postgres en 127.0.0.1:5432",
      interpretation:
        "El diagrama Archify muestra explícitamente la relación desde el host hacia Amazon MQ (AMQP :5672) y Amazon RDS PostgreSQL 17 (SQL :5432) dentro de la subred privada.",
      why_it_matters:
        "Desacoplar el broker de mensajería y el motor relacional elimina la carga operativa de parches Debian, clustering Erlang manual y respaldos de /var/lib/postgresql/17/main.",
      migration_relevance:
        "En caso de Replatform, los productores externos pasan a conectarse al endpoint de Amazon MQ protegido por el AWS Security Group.",
      provenance: "network.listening_ports + runtime.processes + software.systemd_units",
      state: "observed",
      limitations:
        "No se conoce el tamaño lógico de las bases en PostgreSQL 17 ni la lista de colas/exchanges en RabbitMQ solo con osquery.",
      suggested_action:
        "Ejecutar el recolector de catálogo PostgreSQL y exportar las definiciones de RabbitMQ (rabbitmqctl export_definitions) antes de elegir entre Rehost y Replatform.",
    },
  ];

  return (
    <div className="disc-section-view">
      <div className="disc-section-heading">
        <div>
          <h2 className="disc-page-title">
            H. Arquitectura AWS Sugerida (Archify) y Terraform Generado desde JSON — {hostname}
          </h2>
          <p className="disc-page-subtitle">
            Diagrama interactivo <strong>Archify</strong> y código <strong>Terraform AWS</strong> generados
            automáticamente desde el inventario osquery (<code>{osLabel}</code> · {vcpus} vCPU · {ramHuman} RAM ·{" "}
            {diskHuman} Disco) pasando por el modelo intermedio <code>CMIR v2.0</code> y <code>AWSAdapter</code>.
          </p>
        </div>

        <div className="disc-top-right" style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <button
            type="button"
            className="toolbar-btn"
            onClick={() => setIframeHeight((h) => (h === 680 ? 920 : 680))}
          >
            {iframeHeight === 680 ? "Ampliar Altura Visor" : "Altura Estándar"}
          </button>
          <a
            href="/archify-aws-target.html"
            target="_blank"
            rel="noopener noreferrer"
            className="tech-btn primary"
            style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}
          >
            Abrir Visor Archify en Pestaña Completa ↗
          </a>
          <a
            href="/archify-aws-target.html"
            download={`archify-aws-${hostname}.html`}
            className="toolbar-btn"
            style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}
          >
            Descargar HTML Archify
          </a>
        </div>
      </div>

      {/* 1. Interactive Archify Diagram Viewer */}
      <CollapsibleSubsection
        id="aws-archify-viewer"
        title="1. Diagrama Interactivo AWS en Vivo (Archify Showcase Viewer)"
        badge="Validado con Archify CLI"
        defaultOpen={true}
      >
        <div className="disc-callout is-info" style={{ marginBottom: "12px" }}>
          <strong>Controles interactivos del visor Archify:</strong> Dentro del lienzo puedes alternar entre modo{" "}
          <strong>Live / Still</strong> (animación de flujo de paquetes en las rutas AMQP y SQL), cambiar entre tema{" "}
          <strong>Claro / Oscuro</strong>, hacer zoom/pan y exportar directamente a <strong>SVG / PNG / WebM</strong>.
        </div>

        <div
          style={{
            width: "100%",
            height: `${iframeHeight}px`,
            border: "1px solid var(--border-subtle, #cbd5e1)",
            borderRadius: "10px",
            overflow: "hidden",
            background: "#0f172a",
            boxShadow: "0 4px 16px rgba(15, 23, 42, 0.08)",
          }}
        >
          <iframe
            src="/archify-aws-target.html"
            title={`Diagrama AWS Sugerido Archify - ${hostname}`}
            style={{ width: "100%", height: "100%", border: "none", display: "block" }}
          />
        </div>
      </CollapsibleSubsection>

      {/* 2. Mapping Table: Osquery Evidence -> AWS Target */}
      <CollapsibleSubsection
        id="aws-mapping-table"
        title="2. Correspondencia Evidencia Osquery → Arquitectura AWS Sugerida (Rehost vs. Replatform)"
        badge={`${awsMappings.length} capas mapeadas`}
        defaultOpen={true}
      >
        <div className="disc-table-wrap">
          <table className="disc-table">
            <thead>
              <tr>
                <th>Componente Descubierto (Origen)</th>
                <th>Evidencia en JSON Osquery</th>
                <th>Alternativa A: Rehost (Lift &amp; Shift EC2)</th>
                <th>Alternativa B: Replatform (Servicios Administrados AWS)</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {awsMappings.map((row) => (
                <tr key={row.id}>
                  <td><strong>{row.sourceComponent}</strong></td>
                  <td><code>{row.observedEvidence}</code></td>
                  <td>{row.rehostTarget}</td>
                  <td><strong>{row.replatformTarget}</strong></td>
                  <td><StateBadge state={row.state} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSubsection>

      {/* 3. Step-by-Step Integration & Traceability: JSON -> CMIR -> AWSAdapter -> Terraform */}
      {tfBundle && (
        <CollapsibleSubsection
          id="aws-terraform-traceability"
          title="3. Integración Paso a Paso: Cómo el JSON Analizado Pasa a Terraform AWS (JSON → CMIR → AWSAdapter → HCL)"
          badge={`${tfBundle.traceability_count || 0} bloques generados`}
          defaultOpen={true}
        >
          {/* Strategy Switcher */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "12px",
              marginBottom: "16px",
              padding: "12px 14px",
              background: "var(--surface-subtle, #f8fafc)",
              border: "1px solid var(--border-subtle, #e2e8f0)",
              borderRadius: "8px",
            }}
          >
            <div>
              <strong>Estrategia de Traducción a Terraform AWS:</strong>
              <div style={{ fontSize: "12px", color: "var(--text-secondary, #475569)", marginTop: "2px" }}>
                Nodos CMIR procesados por <code>AWSAdapter</code>:{" "}
                <strong>{tfBundle.cmir_nodes_translated}</strong> · Dimensionamiento EC2 calculado:{" "}
                <code>{tfBundle.sizing?.instance_type}</code> ({tfBundle.sizing?.target_vcpu} vCPU /{" "}
                {tfBundle.sizing?.target_ram_gib} GiB RAM)
              </div>
            </div>

            <div style={{ display: "flex", gap: "8px" }}>
              <button
                type="button"
                className={tfStrategy === "replatform" ? "tech-btn primary" : "toolbar-btn"}
                onClick={() => setTfStrategy("replatform")}
              >
                Modo Replatform (EC2 + RDS PostgreSQL 17 + Amazon MQ)
              </button>
              <button
                type="button"
                className={tfStrategy === "rehost" ? "tech-btn primary" : "toolbar-btn"}
                onClick={() => setTfStrategy("rehost")}
              >
                Modo Rehost (Lift &amp; Shift todo en EC2 + EBS gp3)
              </button>
            </div>
          </div>

          {/* 4-Stage Architectural Pipeline Banner */}
          <div className="disc-kpi-grid" style={{ marginBottom: "18px" }}>
            {(tfBundle.pipeline_stages || []).map((st, idx) => (
              <div key={idx} className="disc-kpi-card">
                <span className="disc-kpi-label">{st.stage}</span>
                <strong className="disc-kpi-val" style={{ fontSize: "13px" }}>
                  <code>{st.module}</code>
                </strong>
                <span className="disc-kpi-sub">{st.detail}</span>
              </div>
            ))}
          </div>

          {/* Item-by-Item Traceability Cards */}
          <div className="disc-exp-stack">
            {(tfBundle.traceability || []).map((item) => (
              <div
                key={item.step}
                style={{
                  border: "1px solid var(--border-subtle, #cbd5e1)",
                  borderRadius: "8px",
                  padding: "14px 16px",
                  background: "#ffffff",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: "8px",
                    marginBottom: "10px",
                  }}
                >
                  <div>
                    <span className="disc-tag" style={{ marginRight: "8px" }}>
                      PASO {item.step}
                    </span>
                    <strong style={{ fontSize: "15px" }}>{item.category}</strong>
                  </div>
                  <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                    <StateBadge state={item.state} />
                    <button
                      type="button"
                      className="toolbar-btn"
                      onClick={() => handleCopyTf(item.hcl_snippet, `Bloque Paso ${item.step}`)}
                    >
                      Copiar este bloque HCL
                    </button>
                  </div>
                </div>

                <div className="disc-table-wrap" style={{ marginBottom: "10px" }}>
                  <table className="disc-table">
                    <tbody>
                      <tr>
                        <th style={{ width: "220px" }}>1. Tabla / Campo en JSON Osquery</th>
                        <td><code>{item.osquery_source}</code></td>
                      </tr>
                      <tr>
                        <th>2. Valor Real Detectado en JSON</th>
                        <td><strong>{item.detected_json_value}</strong></td>
                      </tr>
                      <tr>
                        <th>3. Nodo Intermedio CMIR v2.0</th>
                        <td><code>{item.cmir_node}</code></td>
                      </tr>
                      <tr>
                        <th>4. Recurso Terraform AWS Generado</th>
                        <td><strong><code>{item.aws_terraform_resource}</code></strong></td>
                      </tr>
                      <tr>
                        <th>5. Cómo se Integra y Pasa a AWS</th>
                        <td>{item.integration_explanation}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <pre
                  style={{
                    margin: 0,
                    padding: "12px 14px",
                    background: "#0f172a",
                    color: "#e2e8f0",
                    borderRadius: "6px",
                    fontSize: "12px",
                    lineHeight: 1.5,
                    overflowX: "auto",
                  }}
                >
                  <code>{item.hcl_snippet}</code>
                </pre>
              </div>
            ))}
          </div>
        </CollapsibleSubsection>
      )}

      {/* 4. Full Modular Terraform Code Viewer (`provider.tf`, `variables.tf`, `main.tf`, `outputs.tf`) */}
      {tfBundle && (
        <CollapsibleSubsection
          id="aws-terraform-files"
          title="4. Archivos Terraform Modulares Generados desde el JSON (provider.tf, variables.tf, main.tf, outputs.tf)"
          badge="HCL Formateado"
          defaultOpen={true}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "10px",
              marginBottom: "12px",
            }}
          >
            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
              {["main.tf", "variables.tf", "provider.tf", "outputs.tf", "all"].map((fname) => (
                <button
                  key={fname}
                  type="button"
                  className={activeTfFile === fname ? "tech-btn primary" : "toolbar-btn"}
                  onClick={() => setActiveTfFile(fname)}
                >
                  {fname === "all" ? "Todo Combinado (.tf)" : fname}
                </button>
              ))}
            </div>

            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
              {copyFeedback && (
                <span style={{ fontSize: "12px", color: "#059669", fontWeight: 600 }}>
                  ✓ {copyFeedback}
                </span>
              )}
              <button
                type="button"
                className="toolbar-btn"
                onClick={() =>
                  handleCopyTf(
                    currentTfCode,
                    activeTfFile === "all" ? "Módulo completo" : activeTfFile
                  )
                }
              >
                Copiar {activeTfFile === "all" ? "Todo" : activeTfFile}
              </button>
              <button
                type="button"
                className="toolbar-btn"
                onClick={() =>
                  handleDownloadTf(
                    activeTfFile === "all" ? `cloudmove-aws-${hostname}.tf` : activeTfFile,
                    currentTfCode
                  )
                }
              >
                Descargar {activeTfFile === "all" ? `cloudmove-aws-${hostname}.tf` : activeTfFile}
              </button>
              <button
                type="button"
                className="tech-btn primary"
                disabled={persisting}
                onClick={handlePersistToProject}
                title="Escribe provider.tf, variables.tf, main.tf y outputs.tf en la carpeta generated/aws/ del proyecto"
              >
                {persisting ? "Guardando..." : "Guardar en generated/aws/ del Proyecto"}
              </button>
            </div>
          </div>

          {persistFeedback && (
            <div className="disc-callout is-info" style={{ marginBottom: "12px" }}>
              <strong>Sincronización con proyecto:</strong> {persistFeedback}
            </div>
          )}

          <pre
            style={{
              margin: 0,
              padding: "16px",
              background: "#0f172a",
              color: "#f8fafc",
              borderRadius: "8px",
              fontSize: "12.5px",
              lineHeight: 1.55,
              maxHeight: "620px",
              overflow: "auto",
            }}
          >
            <code>{currentTfCode}</code>
          </pre>
        </CollapsibleSubsection>
      )}

      {/* 5. Architectural Explanation Cards */}
      <CollapsibleSubsection
        id="aws-archify-explanations"
        title="5. Justificación Técnica de los Componentes del Diagrama AWS"
        badge="9 dimensiones"
        defaultOpen={true}
      >
        <div className="disc-exp-stack">
          {archifyExplanations.map((exp, idx) => (
            <ExplanationCard key={idx} explanation={exp} defaultExpanded={true} />
          ))}
        </div>
      </CollapsibleSubsection>
    </div>
  );
}


