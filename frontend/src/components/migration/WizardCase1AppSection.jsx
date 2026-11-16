import React from "react";
import RepositoryTreeViewer from "./RepositoryTreeViewer";
import GithubToCloudTransformationSelector from "./GithubToCloudTransformationSelector";
import TargetArchitectureView from "./TargetArchitectureView";

export function WizardCase1SourceForm({
  newProvider,
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
}) {
  return (
    <div style={{ marginTop: 16 }}>
      {/* Selector de Modo de Origen */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)" }}>
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
            backgroundColor: "#ffffff",
            border: "1px solid #d5dbdb",
            borderRadius: 6,
            padding: "16px 20px",
            marginBottom: 16,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span className="cm-badge" style={{ backgroundColor: "#232f3e", color: "#ffffff", fontWeight: 700, fontSize: 12 }}>GIT</span>
                <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#16191f" }}>
                  Repositorio GitHub Público
                </h4>
                <span className="cm-badge observed" style={{ fontSize: 12 }}>
                  Sin credenciales · Commit SHA fijado
                </span>
              </div>
              <p style={{ margin: "4px 0 0 0", fontSize: 13, color: "#545b64" }}>
                Análisis estático en sandbox efímero para detectar runtimes, puertos y dependencias hacia {newProvider.toUpperCase()}.
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
                style={{ flex: "1 1 380px", fontSize: 14, backgroundColor: "#ffffff" }}
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
            <div style={{ fontSize: 13.5, color: "#475569", marginTop: 4 }}>
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
                      fontSize: 12.5,
                      fontWeight: 700,
                      textTransform: "uppercase",
                    }}
                  >
                    Repositorio {githubRepoData.visibility}
                  </span>
                  {githubRepoData.language && (
                    <span className="cm-badge" style={{ backgroundColor: "#f1f5f9", color: "#334155", fontSize: 12.5 }}>
                      {githubRepoData.language}
                    </span>
                  )}
                </div>
                <a
                  href={githubRepoData.html_url || githubUrl}
                  target="_blank"
                  rel="noreferrer"
                  style={{ fontSize: 13.5, color: "#2563eb", textDecoration: "none" }}
                >
                  Abrir en GitHub ↗
                </a>
              </div>
              {githubRepoData.description && (
                <p style={{ margin: "2px 0 6px 0", fontSize: 13.5, color: "#475569" }}>
                  {githubRepoData.description}
                </p>
              )}
              <div style={{ fontSize: 13.5, color: "#64748b" }}>
                Rama predeterminada: <strong><code>{githubRepoData.default_branch}</code></strong> · Estrellas: <strong>{githubRepoData.stars_count ?? 0}</strong>
              </div>
              {githubTreeData && (
                <RepositoryTreeViewer
                  treeData={githubTreeData}
                  title={`Inventario de Archivos y Lenguajes: '${githubRepoData.full_name}'`}
                  defaultOpen={false}
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
                  Contenedor Administrado (AWS ECS Fargate)
                </option>
                <option value="vm_rehost">
                  Rehost en VM (AWS EC2)
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
                fontSize: 13.5,
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
                Contenedor Administrado (AWS ECS Fargate)
              </option>
              <option value="vm_rehost">
                Rehost en VM (AWS EC2)
              </option>
            </select>
          </div>
        </div>
      )}
    </div>
  );
}

export function WizardCase1PreInspectionPreview({
  uc1PreInspection,
  uc1Decisions,
  setUc1Decisions,
  newProvider,
  newName,
}) {
  if (!uc1PreInspection?.application) return null;
  const app = uc1PreInspection.application;

  return (
    <div className="cm-step-card" style={{ marginTop: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <strong style={{ fontSize: 14.5, color: "#16191f" }}>
            Pre-Inspección Estática: {app.app_name}
          </strong>
          {app.git_metadata && (
            <span className="cm-badge info">
              Commit {app.git_metadata.short_sha}
            </span>
          )}
        </div>
        <span className="cm-badge observed">
          Sandbox aislado · Sin ejecución de código
        </span>
      </div>

      <div className="cm-kpi-grid" style={{ marginBottom: 10 }}>
        <div className="cm-kpi-card">
          <div className="cm-kpi-label">Runtime / Framework</div>
          <div className="cm-kpi-value" style={{ fontSize: 15 }}>
            {app.language || "N/A"} · {app.framework || "Estándar"}
          </div>
        </div>
        <div className="cm-kpi-card">
          <div className="cm-kpi-label">Puertos Detectados</div>
          <div className="cm-kpi-value" style={{ fontSize: 15 }}>
            {(app.exposed_ports || []).length > 0
              ? (app.exposed_ports || []).join(", ")
              : "Ninguno"}
          </div>
        </div>
        <div className="cm-kpi-card">
          <div className="cm-kpi-label">Dependencias</div>
          <div className="cm-kpi-value" style={{ fontSize: 15 }}>
            {app.dependencies?.length || 0} paquetes
          </div>
        </div>
        <div className="cm-kpi-card">
          <div className="cm-kpi-label">Secretos Redactados</div>
          <div className="cm-kpi-value" style={{ fontSize: 15 }}>
            {app.secrets_redacted_count || 0} hallazgos
          </div>
        </div>
      </div>

      {app.git_metadata && (
        <details className="cm-accordion-shell" style={{ marginBottom: 8 }}>
          <summary className="cm-accordion-trigger" style={{ fontSize: 12.5 }}>
            <span>
              Metadatos Git ({app.git_metadata.owner}/{app.git_metadata.repo} · {app.git_metadata.ref})
            </span>
          </summary>
          <div className="cm-accordion-body" style={{ fontSize: 12.5, color: "#545b64" }}>
            <div>
              <strong>Repositorio:</strong>{" "}
              <a href={app.git_metadata.repository_url} target="_blank" rel="noreferrer">
                {app.git_metadata.repository_url}
              </a>
            </div>
            <div style={{ marginTop: 4 }}>
              <strong>Último commit:</strong> {app.git_metadata.commit_message}
            </div>
            <div style={{ marginTop: 4 }}>
              <strong>Manifiestos inspeccionados:</strong>{" "}
              <code>{(app.files_inspected || []).join(", ") || "N/A"}</code>
            </div>
          </div>
        </details>
      )}
      {app.repository_tree && (
        <RepositoryTreeViewer
          treeData={{
            hierarchical_tree: app.repository_tree,
            summary: app.tree_summary,
            key_manifests: app.key_manifests,
          }}
          title={`Inventario de Archivos y Lenguajes: ${app.app_name}`}
          defaultOpen={false}
        />
      )}

      {/* Selector Interactivo de Transformación GitHub -> Nube (Pre-Plan) */}
      <GithubToCloudTransformationSelector
        catalog={uc1PreInspection.transformation_catalog || app.transformation_catalog}
        decisions={uc1Decisions}
        onSelectDecision={(itemId, optId) =>
          setUc1Decisions((prev) => ({ ...prev, [itemId]: optId }))
        }
        targetProvider={newProvider}
        isJobView={false}
      />

      {/* Gráfica Interactiva en Vivo de Cómo Quedará la Arquitectura en la Nube (Caso 1) */}
      <div style={{ marginTop: 14 }}>
        <TargetArchitectureView
          job={{
            use_case: "app_source",
            target_provider: newProvider,
            name: app.app_name || newName || "Aplicación",
            source_environment: app,
            source_config: { user_decisions: uc1Decisions },
          }}
        />
      </div>
    </div>
  );
}
