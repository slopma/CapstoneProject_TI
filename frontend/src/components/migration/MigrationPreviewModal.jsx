import React, { useState, useEffect, useMemo } from "react";
import IaCViewer from "./IaCViewer";

export default function MigrationPreviewModal({
  selectedNodes = [],
  allNodes = [],
  dependencies,
  targetProvider,
  setTargetProvider,
  onConfirmGenerate,
  onClose,
  generating,
  generationResult,
}) {
  const [validatedSharedIds, setValidatedSharedIds] = useState([]);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const nodeMap = useMemo(() => {
    const m = new Map();
    allNodes.forEach((n) => m.set(n.id, n));
    return m;
  }, [allNodes]);

  const resolveItem = (item) => {
    if (!item) return { id: "unknown", name: "Desconocido", type: "resource" };
    if (typeof item === "object" && item.id) {
      const ref = nodeMap.get(item.id);
      return {
        id: item.id,
        name: item.name || ref?.name || item.id,
        type: item.type || ref?.type || "resource",
        is_shared: Boolean(item.is_shared ?? ref?.is_shared),
      };
    }
    const idStr = String(item);
    const ref = nodeMap.get(idStr);
    return {
      id: idStr,
      name: ref?.name || idStr,
      type: ref?.type || "resource",
      is_shared: Boolean(ref?.is_shared),
    };
  };

  if (!dependencies) return null;

  const rawDirect = dependencies.required_direct || dependencies.direct_dependencies || [];
  const rawTransitive = dependencies.required_transitive || dependencies.transitive_dependencies || [];
  const rawShared = dependencies.shared_dependencies || dependencies.shared_resources || [];
  const rawInferred = dependencies.inferred_dependencies || [];
  const rawUnknown = dependencies.unknown_dependencies || [];
  const sharedPolicies = dependencies.shared_dependency_policies || {};

  const direct = rawDirect.map(resolveItem);
  const transitive = rawTransitive.map(resolveItem);
  const shared = rawShared.map(resolveItem);
  const selectedResolved = selectedNodes.map(resolveItem);

  const toggleSharedAuth = (id) => {
    setValidatedSharedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  return (
    <div
      className="modal-backdrop"
      onClick={onClose}
      style={{ overscrollBehavior: "contain" }}
    >
      <div
        className="migration-modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="mig-preview-modal-title"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 840, width: "94vw", maxHeight: "88vh", overflowY: "auto", overscrollBehavior: "contain" }}
      >
        <div className="modal-header">
          <div>
            <h3 id="mig-preview-modal-title">
              Análisis de Alcance, Dependencias y Generación de IaC (AWS · GCP)
            </h3>
            <p className="modal-subtitle">
              Revisa dependencias directas, transitivas e inferidas, protege recursos compartidos y genera los módulos Terraform HCL.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="modal-close-btn"
            aria-label="Cerrar ventana de preparación de migración"
          >
            ×
          </button>
        </div>

        <div className="modal-body">
          {/* Selector de Proveedor Cloud Destino (Solo AWS y GCP por ADR-001) */}
          <div className="provider-selector-bar" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
            <span className="selector-label" style={{ fontWeight: 700 }}>
              Proveedor Cloud Destino (ADR-001):
            </span>
            <div className="provider-pills" style={{ display: "flex", gap: 8 }}>
              {[
                { id: "aws", label: "Amazon Web Services (AWS)" },
                { id: "gcp", label: "Google Cloud Platform (GCP)" },
              ].map((prov) => (
                <button
                  key={prov.id}
                  type="button"
                  onClick={() => setTargetProvider(prov.id)}
                  className={`cm-btn sm ${targetProvider === prov.id ? "primary" : ""}`}
                  aria-pressed={targetProvider === prov.id}
                >
                  {prov.label}
                </button>
              ))}
            </div>
          </div>

          {/* Alerta y Autorización de Recursos Compartidos */}
          {shared.length > 0 && (
            <div className="cm-alert warning" style={{ marginBottom: 14 }}>
              <div style={{ fontWeight: 700, marginBottom: 4 }}>
                Protección de Infraestructura Compartida Detectada ({shared.length} recurso(s))
              </div>
              <div style={{ fontSize: 12, marginBottom: 8 }}>
                Los siguientes recursos son consumidos también por cargas fuera de tu selección. Por seguridad, CloudMove los mantiene en On-Premise a menos que autorices explícitamente su migración:
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {shared.map((sh) => {
                  const pol = sharedPolicies[sh.id];
                  const consumers = pol?.consumers_outside_selection || [];
                  return (
                    <label
                      key={sh.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 8,
                        background: "#ffffff",
                        padding: "6px 10px",
                        borderRadius: 6,
                        border: "1px solid #fcd34d",
                        cursor: "pointer",
                      }}
                    >
                      <div>
                        <strong>{sh.name}</strong> (<code>{sh.type}</code>)
                        {consumers.length > 0 && (
                          <span className="cm-hint" style={{ marginLeft: 6 }}>
                            · Consumidores externos: <code>{consumers.join(", ")}</code>
                          </span>
                        )}
                      </div>
                      <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600 }}>
                        <input
                          type="checkbox"
                          checked={validatedSharedIds.includes(sh.id)}
                          onChange={() => toggleSharedAuth(sh.id)}
                        />
                        Autorizar migración compartida
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          {/* Cuadrícula de Alcance: Seleccionados, Directos y Transitivos */}
          <div className="dependencies-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
            <div className="cm-card-subtle">
              <h4 style={{ margin: "0 0 8px 0", fontSize: 12.5 }}>
                Recursos Seleccionados ({selectedResolved.length})
              </h4>
              <ul className="dep-list" style={{ margin: 0, paddingLeft: 16, fontSize: 12 }}>
                {selectedResolved.map((item) => (
                  <li key={item.id} style={{ marginBottom: 4 }}>
                    <strong>{item.name}</strong> <span className="cm-hint">({item.type})</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="cm-card-subtle">
              <h4 style={{ margin: "0 0 8px 0", fontSize: 12.5 }}>
                Dependencias Directas ({direct.length})
              </h4>
              {direct.length === 0 ? (
                <p className="cm-hint" style={{ margin: 0 }}>Sin dependencias directas adicionales.</p>
              ) : (
                <ul className="dep-list" style={{ margin: 0, paddingLeft: 16, fontSize: 12 }}>
                  {direct.map((dep) => (
                    <li key={dep.id} style={{ marginBottom: 4 }}>
                      <strong>{dep.name}</strong>{" "}
                      <span className="cm-hint">({dep.type})</span>
                      {dep.is_shared && (
                        <span className="cm-badge shared" style={{ marginLeft: 4, fontSize: 9.5, padding: "1px 4px" }}>
                          Compartido
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="cm-card-subtle">
              <h4 style={{ margin: "0 0 8px 0", fontSize: 12.5 }}>
                Dependencias Transitivas e Inferidas ({transitive.length + rawInferred.length + rawUnknown.length})
              </h4>
              {transitive.length === 0 && rawInferred.length === 0 && rawUnknown.length === 0 ? (
                <p className="cm-hint" style={{ margin: 0 }}>Sin dependencias transitivas ni inferidas pendientes.</p>
              ) : (
                <ul className="dep-list" style={{ margin: 0, paddingLeft: 16, fontSize: 12 }}>
                  {transitive.map((dep) => (
                    <li key={dep.id} style={{ marginBottom: 4 }}>
                      <strong>{dep.name}</strong> <span className="cm-badge derived">Transitiva</span>
                    </li>
                  ))}
                  {rawInferred.map((infId) => (
                    <li key={infId} style={{ marginBottom: 4 }}>
                      <strong>{resolveItem(infId).name}</strong> <span className="cm-badge inferred">Inferida</span>
                    </li>
                  ))}
                  {rawUnknown.map((unkId) => (
                    <li key={unkId} style={{ marginBottom: 4 }}>
                      <strong>{resolveItem(unkId).name}</strong> <span className="cm-badge unknown">Desconocida</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {generationResult && (
            <div className="generated-iac-section" style={{ marginTop: 16 }}>
              <IaCViewer
                code={generationResult.iac_code || generationResult.terraform}
                files={generationResult.files}
                language="hcl"
                filename="main.tf"
              />
            </div>
          )}
        </div>

        <div className="modal-footer" style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button type="button" onClick={onClose} className="cm-btn">
            Cerrar
          </button>
          <button
            type="button"
            onClick={() => onConfirmGenerate(validatedSharedIds)}
            disabled={generating}
            className="cm-btn primary"
          >
            {generating
              ? "Generando módulos Terraform HCL..."
              : `Generar Terraform (${targetProvider.toUpperCase()})`}
          </button>
        </div>
      </div>
    </div>
  );
}
