import React, { memo } from "react";

const ARCHITECTURAL_TIERS = [
  { level: null, label: "Toda la topología" },
  { level: 1, label: "Infraestructura" },
  { level: 3, label: "Red y perímetro" },
  { level: 4, label: "Clústeres" },
  { level: 7, label: "Cómputo y servicios" },
  { level: 8, label: "Datos y colas" },
];

function CanvasToolbar({
  activeLevel = null,
  onSelectLevel,
  onExpandAll,
  onCollapseAll,
  focusNodeId,
  onClearFocus,
  selectedCount = 0,
}) {
  return (
    <div className="canvas-toolbar" role="toolbar" aria-label="Controles de topología">
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

      {typeof onSelectLevel === "function" && (
        <div className="toolbar-group toolbar-tier-filter" role="group" aria-label="Filtrar por capa arquitectónica">
          <span className="toolbar-label">Capa</span>
          {ARCHITECTURAL_TIERS.map((tier) => {
            const isActive = activeLevel === tier.level;
            return (
              <button
                key={tier.label}
                type="button"
                className={`toolbar-btn is-filter-chip ${isActive ? "active" : ""}`}
                aria-pressed={isActive}
                onClick={() => onSelectLevel(tier.level)}
              >
                {tier.label}
              </button>
            );
          })}
        </div>
      )}

      <div className="toolbar-right">
        {focusNodeId && (
          <button
            type="button"
            className="toolbar-btn focus-active"
            onClick={onClearFocus}
          >
            Salir de enfoque
          </button>
        )}
        <span className="selected-indicator" aria-live="polite">
          Seleccionados <strong>{selectedCount}</strong>
        </span>
      </div>
    </div>
  );
}

export default memo(CanvasToolbar);
