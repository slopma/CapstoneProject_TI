import React, { memo } from "react";

const LAYER_PRESETS = [
  { id: "ALL", label: "Toda la topología" },
  { id: "L0_L1", label: "Infraestructura" },
  { id: "L2", label: "Red y perímetro" },
  { id: "L3_L4", label: "Clústeres y grupos" },
  { id: "L5", label: "Cargas y servicios" },
];

const DOMAIN_FILTERS = [
  { id: "ALL", label: "Todos los tipos" },
  { id: "compute", label: "Cómputo & Apps" },
  { id: "data", label: "Bases de Datos" },
  { id: "network", label: "Red & Seguridad" },
  { id: "shared", label: "Solo Compartidos" },
];

function CanvasToolbar({
  activeLayer,
  setActiveLayer,
  domainFilter = "ALL",
  setDomainFilter,
  highlightDeps = true,
  setHighlightDeps,
  showLegend = true,
  setShowLegend,
  onExpandAll,
  onCollapseAll,
  selectedCount = 0,
  onClearSelection,
  onAnalyzeDependencies,
}) {
  return (
    <div className="canvas-toolbar" role="toolbar" aria-label="Controles de visualización del grafo de arquitectura">
      <div className="toolbar-group">
        <span className="toolbar-label">Jerarquía</span>
        <button
          type="button"
          className="toolbar-btn"
          onClick={onExpandAll}
          title="Desplegar todos los contenedores de la arquitectura"
        >
          Desplegar todo
        </button>
        <button
          type="button"
          className="toolbar-btn"
          onClick={onCollapseAll}
          title="Contraer hacia los contenedores raíz"
        >
          Colapsar a raíz
        </button>
      </div>

      <div className="toolbar-group toolbar-tier-filter" role="group" aria-label="Filtrar por capa arquitectónica">
        <span className="toolbar-label">Capa</span>
        {LAYER_PRESETS.map((layer) => {
          const isActive = activeLayer === layer.id;
          return (
            <button
              key={layer.id}
              type="button"
              className={`toolbar-btn is-filter-chip ${isActive ? "active" : ""}`}
              aria-pressed={isActive}
              onClick={() => setActiveLayer(layer.id)}
            >
              {layer.label}
            </button>
          );
        })}
      </div>

      {setDomainFilter && (
        <div className="toolbar-group toolbar-tier-filter" role="group" aria-label="Filtrar por tipo de activo">
          <span className="toolbar-label">Activos</span>
          {DOMAIN_FILTERS.map((df) => {
            const isActive = domainFilter === df.id;
            return (
              <button
                key={df.id}
                type="button"
                className={`toolbar-btn is-filter-chip ${isActive ? "active" : ""}`}
                aria-pressed={isActive}
                onClick={() => setDomainFilter(df.id)}
              >
                {df.label}
              </button>
            );
          })}
        </div>
      )}

      <div className="toolbar-right" style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        {setHighlightDeps && (
          <button
            type="button"
            className={`toolbar-btn is-filter-chip ${highlightDeps ? "active" : ""}`}
            aria-pressed={highlightDeps}
            onClick={() => setHighlightDeps((prev) => !prev)}
          >
            {highlightDeps ? "Alcance ON" : "Alcance OFF"}
          </button>
        )}

        {setShowLegend && (
          <button
            type="button"
            className={`toolbar-btn is-filter-chip ${showLegend ? "active" : ""}`}
            aria-pressed={showLegend}
            onClick={() => setShowLegend((prev) => !prev)}
          >
            {showLegend ? "Leyenda ON" : "Leyenda OFF"}
          </button>
        )}

        <span className="selected-indicator" aria-live="polite">
          Seleccionados <strong>{selectedCount}</strong>
        </span>

        {selectedCount > 0 && (
          <>
            {onAnalyzeDependencies && (
              <button
                type="button"
                className="toolbar-btn active"
                onClick={onAnalyzeDependencies}
              >
                Analizar alcance
              </button>
            )}
            <button type="button" className="toolbar-btn" onClick={onClearSelection}>
              Limpiar
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default memo(CanvasToolbar);
