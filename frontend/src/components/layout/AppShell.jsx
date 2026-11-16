import React, { useState, useEffect } from "react";
import Sidebar from "./Sidebar";
import Header, { TAB_LABELS } from "./Header";

export default function AppShell({
  activeTab,
  activeUseCase = "app_source",
  setActiveTab,
  onQuickStartUseCase,
  architectureName,
  searchQuery,
  setSearchQuery,
  selectedCount,
  onPrepareMigration,
  targetProvider,
  setTargetProvider,
  workContext = {},
  children,
}) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape" && mobileNavOpen) {
        setMobileNavOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [mobileNavOpen]);

  const { activeMigrationJob, jobsCount } = workContext;
  const currentServiceLabel =
    activeTab === "migration"
      ? activeUseCase === "vm_image"
        ? "Caso 2 · Migración de Imagen de SO / VM"
        : "Caso 1 · Migración de Aplicación (GitHub)"
      : TAB_LABELS[activeTab] || "Console Home";

  return (
    <div
      className={`enterprise-app-shell awsui-app-layout ${
        sidebarCollapsed ? "is-sidebar-collapsed" : ""
      }`}
    >
      <a href="#main-workspace-content" className="skip-link">
        Saltar al contenido principal
      </a>

      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onQuickStartUseCase={onQuickStartUseCase}
        architectureName={architectureName}
        searchQuery={searchQuery}
        setSearchQuery={setSearchQuery}
        selectedCount={selectedCount}
        onPrepareMigration={onPrepareMigration}
        targetProvider={targetProvider}
        setTargetProvider={setTargetProvider}
        onToggleMobileNav={() => setMobileNavOpen((prev) => !prev)}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebarCollapse={() => setSidebarCollapsed((prev) => !prev)}
      />

      <div className="awsui-app-body">
        <Sidebar
          activeTab={activeTab}
          activeUseCase={activeUseCase}
          setActiveTab={setActiveTab}
          onQuickStartUseCase={onQuickStartUseCase}
          mobileOpen={mobileNavOpen}
          onCloseMobile={() => setMobileNavOpen(false)}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((prev) => !prev)}
          systemStats={{ jobsCount }}
        />

        <div className="shell-main-wrapper">
          {/* AWS Cloudscape BreadcrumbGroup */}
          <div
            className="cm-context-bar awsui-breadcrumb-strip"
            role="region"
            aria-label="Ruta de navegación"
          >
            <nav
              className="awsui-global-breadcrumbs"
              aria-label="Ruta de navegación de la consola"
            >
              <button
                type="button"
                className="awsui-crumb-link"
                onClick={() => setActiveTab("overview")}
              >
                AWS CloudMove Console
              </button>
              <span className="awsui-crumb-sep" aria-hidden="true">
                ›
              </span>
              {activeTab === "migration" && (
                <>
                  <button
                    type="button"
                    className="awsui-crumb-link"
                    onClick={() => setActiveTab("migration")}
                  >
                    AWS Migration Hub
                  </button>
                  <span className="awsui-crumb-sep" aria-hidden="true">
                    ›
                  </span>
                </>
              )}
              <span className="awsui-crumb-current">{currentServiceLabel}</span>
            </nav>

            <div className="cm-context-items">
              {activeMigrationJob && activeTab !== "migration" && (
                <button
                  type="button"
                  className="cm-context-chip"
                  onClick={() => setActiveTab("migration")}
                  title="Ir al plan de migración activo"
                >
                  <span>Plan activo:</span>
                  <strong>{activeMigrationJob.name}</strong>
                  <span
                    className={`cm-badge ${
                      activeMigrationJob.target_provider === "gcp" ? "gcp" : "aws"
                    }`}
                  >
                    {activeMigrationJob.target_provider?.toUpperCase()} ·{" "}
                    {activeMigrationJob.state}
                  </span>
                </button>
              )}

              {selectedCount > 0 && (
                <button
                  type="button"
                  className="cm-context-chip"
                  onClick={() => setActiveTab("architecture")}
                >
                  <span>Selección:</span>
                  <strong>{selectedCount} nodo(s)</strong>
                </button>
              )}
            </div>
          </div>

          <main
            id="main-workspace-content"
            tabIndex={-1}
            className="shell-content"
            style={{ padding: activeTab === "architecture" ? "10px 16px" : 0 }}
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
