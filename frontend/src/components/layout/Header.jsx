import React from "react";

function Header({
  architectureName,
  environment = "On-Premise Enterprise",
  searchQuery,
  onSearchChange,
  selectedCount,
  onPrepareMigration,
}) {
  return (
    <header className="enterprise-header">
      <div className="header-left">
        <div className="header-meta-group">
          <span className="env-badge">{environment}</span>
          <span className="meta-separator">/</span>
          <h1 className="active-arch-title" title={architectureName}>
            {architectureName || "On-Premise Architecture"}
          </h1>
        </div>
      </div>

      <div className="header-right">
        <div className="header-search-box">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="search-icon">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="text"
            placeholder="Search architecture..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
          />
        </div>

        <button
          type="button"
          className="header-action-btn primary"
          onClick={onPrepareMigration}
          disabled={selectedCount === 0}
        >
          Prepare Migration ({selectedCount})
        </button>

        <div className="user-profile-badge" title="Administrator">
          AD
        </div>
      </div>
    </header>
  );
}

export default Header;
