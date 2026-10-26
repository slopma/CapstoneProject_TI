import React, { useState, useEffect } from "react";
import Sidebar from "./Sidebar";
import Header from "./Header";

export default function AppShell({
  activeTab,
  setActiveTab,
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

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape" && mobileNavOpen) {
        setMobileNavOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [mobileNavOpen]);

  const {
    activeHost,
    activeCampaign,
    activeMigrationJob,
    persistenceEngine,
    jobsCount,
  } = workContext;

  return (
    <div className="enterprise-app-shell">
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        mobileOpen={mobileNavOpen}
        onCloseMobile={() => setMobileNavOpen(false)}
        systemStats={{ jobsCount }}
      />
      <div className="shell-main-wrapper">
        <Header
          activeTab={activeTab}
          architectureName={architectureName}
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          selectedCount={selectedCount}
          onPrepareMigration={onPrepareMigration}
          targetProvider={targetProvider}
          setTargetProvider={setTargetProvider}
          onToggleMobileNav={() => setMobileNavOpen((prev) => !prev)}
        />

        {/* Barra de Contexto Persistente: Permite volver en 1 clic a la sesión de discovery, campaña o migración activa */}
        <div className="cm-context-bar" role="region" aria-label="Contexto de trabajo activo">
          <div className="cm-context-items">
            <span style={{ fontWeight: 700, color: "var(--color-text-primary)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em" }}>
              Contexto Activo:
            </span>

            {activeHost && (
              <button
                type="button"
                className="cm-context-chip"
                onClick={() => setActiveTab("discovery")}
                title="Volver al inventario del host descubierto"
              >
                <span>Host Discovery:</span>
                <strong>{activeHost}</strong>
              </button>
            )}

            {activeCampaign && (
              <button
                type="button"
                className="cm-context-chip"
                onClick={() => setActiveTab("campaigns")}
                title="Volver a la campaña de datacenter activa"
              >
                <span>Campaña DC:</span>
                <strong>{activeCampaign.campaign_id}</strong>
                <span className={`cm-badge ${activeCampaign.status === "completed" ? "validated" : "warning"}`} style={{ padding: "1px 5px", fontSize: 10 }}>
                  {activeCampaign.status}
                </span>
              </button>
            )}

            {activeMigrationJob && (
              <button
                type="button"
                className="cm-context-chip"
                onClick={() => setActiveTab("migration")}
                title="Volver al plan de migración activo en el orquestador"
              >
                <span>Migración Activa:</span>
                <strong>{activeMigrationJob.name}</strong>
                <span className={`cm-badge ${activeMigrationJob.target_provider === "gcp" ? "gcp" : "aws"}`} style={{ padding: "1px 5px", fontSize: 10 }}>
                  {activeMigrationJob.target_provider?.toUpperCase()} · {activeMigrationJob.state}
                </span>
              </button>
            )}

            {selectedCount > 0 && (
              <button
                type="button"
                className="cm-context-chip"
                onClick={() => setActiveTab("architecture")}
                title="Ver recursos seleccionados en el Grafo de Arquitectura"
              >
                <span>Selección en Grafo:</span>
                <strong>{selectedCount} activo(s)</strong>
              </button>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {persistenceEngine && (
              <span className="cm-badge observed" title="Motor de persistencia transaccional ACID">
                BD ACID: {persistenceEngine}
              </span>
            )}
            <span className="cm-badge info" title="Nubes soportadas oficialmente según ADR-001">
              AWS · GCP
            </span>
          </div>
        </div>

        <main className="shell-content" style={{ padding: activeTab === "architecture" ? "10px 14px" : 0 }}>
          {children}
        </main>
      </div>
    </div>
  );
}
