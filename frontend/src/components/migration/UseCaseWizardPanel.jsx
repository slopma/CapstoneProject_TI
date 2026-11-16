import React from "react";
import { USE_CASE_CARDS } from "./orchestratorConstants";
import {
  WizardCase1SourceForm,
  WizardCase1PreInspectionPreview,
} from "./WizardCase1AppSection";
import {
  WizardCase2SourceForm,
  WizardCase2PreInspectionPreview,
} from "./WizardCase2VmSection";

export default function UseCaseWizardPanel({
  wizardCollapsed,
  newUseCase,
  setNewUseCase,
  newName,
  setNewName,
  newProvider,
  setNewProvider,
  setGithubToken,
  setShowAdvancedGithub,
  setStatusBanner,
  loading,
  inspecting,
  handleInspectUseCase1,
  handleInspectUseCase2,
  handleCreateMigration,
  case1Props,
  case2Props,
}) {
  const { uc1PreInspection, uc1Decisions, setUc1Decisions } = case1Props;
  const {
    uc2SourceMode,
    agentTokenData,
    enrolledAgents,
    uc2PreInspection,
    hostDevicesData,
    uc2Decisions,
    setUc2Decisions,
    consistencyStrategy,
  } = case2Props;

  return (
    <div className="cm-card" style={{ marginBottom: 20 }}>
      <div className="cm-card-title">
        <span>Selecciona qué quieres migrar</span>
      </div>

      {!wizardCollapsed && (
        <>
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
                      : "Ej. Importación Debian 12 ERP VMDK → AWS"
                  }
                  value={newName}
                  onChange={(e) => {
                    const val = e.target.value;
                    if (/^(ghp_|github_pat_|gho_|ghu_|ghs_|ghr_)/i.test(val.trim())) {
                      setGithubToken(val.trim());
                      setShowAdvancedGithub(true);
                      setStatusBanner("Token de GitHub detectado automáticamente y movido al campo Personal Access Token (PAT).");
                      return;
                    }
                    setNewName(val);
                  }}
                />
              </div>

              <div className="cm-field">
                <label htmlFor="mig-provider-select" className="cm-label">
                  Proveedor Cloud Destino
                </label>
                <select
                  id="mig-provider-select"
                  className="cm-select"
                  value="aws"
                  onChange={() => setNewProvider("aws")}
                >
                  <option value="aws">Amazon Web Services (AWS — EC2 / ECS / RDS / MGN · us-east-1)</option>
                </select>
              </div>
            </div>

            {newUseCase === "app_source" && (
              <WizardCase1SourceForm newProvider={newProvider} {...case1Props} />
            )}

            {newUseCase === "vm_image" && (
              <WizardCase2SourceForm
                setStatusBanner={setStatusBanner}
                {...case2Props}
              />
            )}

            {/* Botones de Acción del Asistente (PASO 3 en Caso 2) */}
            {newUseCase === "vm_image" && uc2SourceMode === "live_capture" && !(agentTokenData?.token || enrolledAgents.length > 0) && (
              <div className="cm-alert warning" style={{ marginTop: 12, marginBottom: 4 }}>
                <strong>Paso 1 Requerido:</strong> Genera primero el token del agente remoto arriba (Paso 1) para desbloquear la captura de SO y la creación del plan de migración.
              </div>
            )}

            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14, alignItems: "center" }}>
              {newUseCase === "app_source" && (
                <button
                  type="button"
                  className="cm-btn"
                  onClick={handleInspectUseCase1}
                  disabled={loading || inspecting}
                >
                  {inspecting
                    ? "Inspeccionando aplicación..."
                    : "Paso Previo: Inspeccionar Evidencias y Dependencias de la App"}
                </button>
              )}

              {newUseCase === "vm_image" && (
                <button
                  type="button"
                  className="cm-btn"
                  onClick={handleInspectUseCase2}
                  disabled={
                    loading ||
                    inspecting ||
                    (uc2SourceMode === "live_capture" && !(agentTokenData?.token || enrolledAgents.length > 0))
                  }
                >
                  {inspecting
                    ? uc2SourceMode === "live_capture"
                      ? "Capturando SO y evaluando..."
                      : "Verificando cabecera binaria..."
                    : uc2SourceMode === "live_capture"
                    ? "Paso 3A: Capturar SO del Agente Remoto y Evaluar Viabilidad AWS"
                    : "Paso Previo: Verificar Cabecera Binaria y SHA-256 (`qemu-img`)"}
                </button>
              )}

              <button
                type="button"
                className="cm-btn primary"
                onClick={handleCreateMigration}
                disabled={
                  loading ||
                  inspecting ||
                  (newUseCase === "vm_image" &&
                    uc2SourceMode === "live_capture" &&
                    !(agentTokenData?.token || enrolledAgents.length > 0))
                }
              >
                {loading
                  ? "Generando evaluación y plan..."
                  : newUseCase === "vm_image" && uc2SourceMode === "live_capture"
                  ? "Paso 3B: Generar Plan de Migración Completo hacia AWS"
                  : "Generar Plan de Migración Completo hacia AWS"}
              </button>
            </div>
          </div>

          {newUseCase === "app_source" && (
            <WizardCase1PreInspectionPreview
              uc1PreInspection={uc1PreInspection}
              uc1Decisions={uc1Decisions}
              setUc1Decisions={setUc1Decisions}
              newProvider={newProvider}
              newName={newName}
            />
          )}

          {newUseCase === "vm_image" && (
            <WizardCase2PreInspectionPreview
              uc2PreInspection={uc2PreInspection}
              hostDevicesData={hostDevicesData}
              uc2Decisions={uc2Decisions}
              setUc2Decisions={setUc2Decisions}
              newProvider={newProvider}
              consistencyStrategy={consistencyStrategy}
            />
          )}
        </>
      )}
    </div>
  );
}
