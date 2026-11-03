import React, { useState, useEffect, useMemo } from "react";
import IaCViewer from "./IaCViewer";
import { AwsKeyValuePairs, AwsTabs, AwsAlert } from "../cloudscape/AwsPrimitives";

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
  const [activeModalTab, setActiveModalTab] = useState("scope");

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    if (generationResult) {
      setActiveModalTab("iac");
    }
  }, [generationResult]);

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
        style={{
          maxWidth: 880,
          width: "94vw",
          maxHeight: "90vh",
          overflowY: "auto",
          overscrollBehavior: "contain",
          backgroundColor: "#FFFFFF",
          border: "1px solid #D5DBDB",
          borderRadius: 4,
          boxShadow: "0 4px 20px rgba(0, 28, 36, 0.25)",
        }}
      >
        <div
          className="modal-header"
          style={{
            backgroundColor: "#FAFAFA",
            borderBottom: "1px solid #E9EBED",
            padding: "16px 20px",
          }}
        >
          <div>
            <h3 id="mig-preview-modal-title" style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#16191F" }}>
              Análisis de Alcance, Dependencias y Generación de IaC (AWS · GCP)
            </h3>
            <p className="modal-subtitle" style={{ margin: "4px 0 0 0", fontSize: 14, color: "#5F6B7A" }}>
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

        <div className="modal-body" style={{ padding: "16px 20px", backgroundColor: "#F2F3F3" }}>
          {/* Selector de Proveedor Cloud Destino (Solo AWS y GCP por ADR-001) */}
          <div
            className="provider-selector-bar"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: 12,
              backgroundColor: "#FFFFFF",
              border: "1px solid #D5DBDB",
              borderRadius: 4,
              padding: "12px 16px",
              marginBottom: 16,
            }}
          >
            <span className="selector-label" style={{ fontWeight: 700, fontSize: 14, color: "#16191F" }}>
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
                  className={`cm-btn sm ${targetProvider === prov.id ? "primary" : "secondary"}`}
                  aria-pressed={targetProvider === prov.id}
                >
                  {prov.label}
                </button>
              ))}
            </div>
          </div>

          {/* Resumen de Alcance con KeyValuePairs */}
          <AwsKeyValuePairs
            title="Resumen de alcance del subgrafo seleccionado"
            columns={4}
            items={[
              {
                label: "Recursos seleccionados",
                value: `${selectedResolved.length} nodo(s)`,
                subtext: "Selección primaria del usuario",
              },
              {
                label: "Dependencias directas",
                value: `${direct.length} recurso(s)`,
                subtext: "Requeridas para conectividad",
              },
              {
                label: "Transitivas e inferidas",
                value: `${transitive.length + rawInferred.length + rawUnknown.length}`,
                subtext: "Clausura del grafo dirigida",
              },
              {
                label: "Recursos compartidos",
                value: `${shared.length} (${validatedSharedIds.length} autorizados)`,
                subtext: "Protección multi-consumidor",
              },
            ]}
          />

          {/* Alerta y Autorización de Recursos Compartidos */}
          {shared.length > 0 && (
            <AwsAlert
              type="warning"
              title={`Protección de Infraestructura Compartida Detectada (${shared.length} recurso(s))`}
            >
              <div style={{ fontSize: 13.5, marginBottom: 8 }}>
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
                        borderRadius: 4,
                        border: "1px solid #F8C26B",
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
                      <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13.5, fontWeight: 700 }}>
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
            </AwsAlert>
          )}

          {/* Pestañas Cloudscape para Alcance vs Código Terraform */}
          <AwsTabs
            activeId={activeModalTab}
            onChange={setActiveModalTab}
            ariaLabel="Secciones de preparación de migración"
            tabs={[
              {
                id: "scope",
                label: "Desglose de dependencias",
                badge: selectedResolved.length + direct.length + transitive.length,
                content: (
                  <div
                    className="dependencies-grid"
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 12,
                    }}
                  >
                    <div className="cm-card-subtle">
                      <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>
                        Recursos Seleccionados ({selectedResolved.length})
                      </h4>
                      <ul className="dep-list" style={{ margin: 0, paddingLeft: 16, fontSize: 13.5 }}>
                        {selectedResolved.map((item) => (
                          <li key={item.id} style={{ marginBottom: 4 }}>
                            <strong>{item.name}</strong> <span className="cm-hint">({item.type})</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div className="cm-card-subtle">
                      <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>
                        Dependencias Directas ({direct.length})
                      </h4>
                      {direct.length === 0 ? (
                        <p className="cm-hint" style={{ margin: 0 }}>Sin dependencias directas adicionales.</p>
                      ) : (
                        <ul className="dep-list" style={{ margin: 0, paddingLeft: 16, fontSize: 13.5 }}>
                          {direct.map((dep) => (
                            <li key={dep.id} style={{ marginBottom: 4 }}>
                              <strong>{dep.name}</strong>{" "}
                              <span className="cm-hint">({dep.type})</span>
                              {dep.is_shared && (
                                <span className="cm-badge shared" style={{ marginLeft: 4, fontSize: 12.5, padding: "1px 4px" }}>
                                  Compartido
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="cm-card-subtle">
                      <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>
                        Dependencias Transitivas e Inferidas ({transitive.length + rawInferred.length + rawUnknown.length})
                      </h4>
                      {transitive.length === 0 && rawInferred.length === 0 && rawUnknown.length === 0 ? (
                        <p className="cm-hint" style={{ margin: 0 }}>Sin dependencias transitivas ni inferidas pendientes.</p>
                      ) : (
                        <ul className="dep-list" style={{ margin: 0, paddingLeft: 16, fontSize: 13.5 }}>
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
                ),
              },
              {
                id: "iac",
                label: "Módulos Terraform HCL generados",
                badge: generationResult?.files ? Object.keys(generationResult.files).length : 0,
                content: generationResult ? (
                  <IaCViewer
                    code={generationResult.iac_code || generationResult.terraform}
                    files={generationResult.files}
                    language="hcl"
                    filename="main.tf"
                  />
                ) : (
                  <div style={{ padding: "24px 16px", textAlign: "center", color: "#5F6B7A", fontSize: 14 }}>
                    Haz clic en <strong>"Generar Terraform ({targetProvider.toUpperCase()})"</strong> abajo para sintetizar los archivos HCL del subgrafo seleccionado.
                  </div>
                ),
              },
            ]}
          />
        </div>

        <div
          className="modal-footer"
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 10,
            backgroundColor: "#FAFAFA",
            borderTop: "1px solid #E9EBED",
            padding: "12px 20px",
          }}
        >
          <button type="button" onClick={onClose} className="cm-btn secondary">
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
