import React from "react";

function CanvasToolbar({
  activeLevel,
  onSelectLevel,
  onExpandAll,
  onCollapseAll,
  focusNodeId,
  onClearFocus,
  selectedCount,
}) {
  return (
    <div className="canvas-toolbar">
      <div className="toolbar-group">
        <span className="toolbar-label">Expansion:</span>
        <button type="button" className="toolbar-btn" onClick={onExpandAll}>
          Expand All
        </button>
        <button type="button" className="toolbar-btn" onClick={onCollapseAll}>
          Collapse to Root
        </button>
      </div>

      <div className="toolbar-divider"></div>

      <div className="toolbar-group">
        <span className="toolbar-label">Level Filter:</span>
        <button
          type="button"
          className={`toolbar-btn ${activeLevel === null ? "active" : ""}`}
          onClick={() => onSelectLevel(null)}
        >
          All (L1-L8)
        </button>
        {[1, 2, 3, 4, 5, 6, 7, 8].map((lvl) => (
          <button
            key={lvl}
            type="button"
            className={`toolbar-btn ${activeLevel === lvl ? "active" : ""}`}
            onClick={() => onSelectLevel(lvl)}
          >
            L{lvl}
          </button>
        ))}
      </div>

      {focusNodeId && (
        <>
          <div className="toolbar-divider"></div>
          <button type="button" className="toolbar-btn focus-active" onClick={onClearFocus}>
            Exit Focus Mode
          </button>
        </>
      )}

      <div className="toolbar-right">
        <span className="selected-indicator">
          Selected: <strong>{selectedCount}</strong>
        </span>
      </div>
    </div>
  );
}

export default CanvasToolbar;
