import React from "react";

/**
 * Canonical AWS Cloudscape Page Header
 */
export function AwsPageHeader({
  title,
  description,
  subtitle,
  badges,
  actions,
  resourceCount,
}) {
  const descText = description || subtitle;

  const renderBadges = () => {
    if (!badges) return null;
    if (Array.isArray(badges)) {
      return badges.map((b, idx) => {
        if (React.isValidElement(b)) return b;
        if (b && typeof b === "object" && "label" in b) {
          return (
            <span
              key={b.label || idx}
              className={`cm-badge ${b.className || "info"}`}
            >
              {b.label}
            </span>
          );
        }
        return <span key={idx}>{String(b)}</span>;
      });
    }
    return badges;
  };

  return (
    <div className="awsui-page-header">
      <div className="awsui-page-header-main">
        <div className="awsui-page-title-row">
          <h1 className="awsui-page-title">
            {title}
            {typeof resourceCount === "number" && (
              <span className="awsui-header-counter">({resourceCount})</span>
            )}
          </h1>
          {badges && <div className="awsui-page-badges">{renderBadges()}</div>}
        </div>
        {descText && <p className="awsui-page-description">{descText}</p>}
      </div>
      {actions && <div className="awsui-page-actions">{actions}</div>}
    </div>
  );
}

/**
 * Canonical AWS Cloudscape Container with distinct Header & Body zones
 */
export function AwsContainer({
  title,
  description,
  counter,
  actions,
  footer,
  variant = "default",
  noPadding = false,
  style,
  children,
}) {
  return (
    <section
      className={`awsui-container ${variant === "stacked" ? "is-stacked" : ""}`}
      style={style}
    >
      {(title || actions || description) && (
        <header className="awsui-container-header">
          <div className="awsui-container-header-left">
            {title && (
              <h2 className="awsui-container-title">
                {title}
                {counter !== undefined && counter !== null && (
                  <span className="awsui-container-counter">({counter})</span>
                )}
              </h2>
            )}
            {description && (
              <p className="awsui-container-description">{description}</p>
            )}
          </div>
          {actions && (
            <div className="awsui-container-header-actions">{actions}</div>
          )}
        </header>
      )}
      <div className={`awsui-container-body ${noPadding ? "no-padding" : ""}`}>
        {children}
      </div>
      {footer && <footer className="awsui-container-footer">{footer}</footer>}
    </section>
  );
}

/**
 * Canonical AWS Cloudscape 3-to-4 Column Summary / Key-Value Layout with vertical dividers
 */
export function AwsKeyValuePairs({ title, columns = 4, items = [] }) {
  return (
    <div
      className="awsui-kv-grid-container"
      style={{ marginBottom: 16 }}
      role="region"
      aria-label={title || "Atributos y métricas de resumen"}
    >
      <div className="awsui-kv-grid" style={{ "--kv-cols": columns }}>
        {items.map((item, idx) => (
          <div key={item.label || idx} className="awsui-kv-column">
            <span className="awsui-kv-label">{item.label}</span>
            <div className="awsui-kv-value">{item.value}</div>
            {item.subtext && (
              <div className="awsui-kv-subtext">{item.subtext}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Canonical AWS Cloudscape Rectangular Navigation Tabs
 */
export function AwsTabs({
  tabs = [],
  activeTabId,
  activeId,
  onTabChange,
  onChange,
  ariaLabel = "Secciones de la vista",
  style,
}) {
  const currentTabId = activeTabId !== undefined ? activeTabId : activeId;
  const handleSelect = onTabChange || onChange;
  const activeTabObj = tabs.find((t) => t.id === currentTabId);

  return (
    <div className="awsui-tabs-wrapper" style={style}>
      <div className="awsui-tabs-bar" role="tablist" aria-label={ariaLabel}>
        {tabs.map((tab) => {
          const isActive = currentTabId === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              disabled={tab.disabled}
              className={`awsui-tab-btn ${isActive ? "is-active" : ""}`}
              onClick={() => handleSelect && handleSelect(tab.id)}
            >
              <span>{tab.label}</span>
              {tab.count !== undefined && tab.count !== null && (
                <span className="awsui-tab-count">({tab.count})</span>
              )}
              {tab.badge !== undefined && tab.badge !== null && (
                <span className="awsui-tab-pill">{tab.badge}</span>
              )}
            </button>
          );
        })}
      </div>
      {activeTabObj && activeTabObj.content !== undefined && (
        <div
          className="awsui-container is-stacked"
          role="tabpanel"
          style={{ borderTop: "none", borderTopLeftRadius: 0, borderTopRightRadius: 0 }}
        >
          <div className="awsui-container-body">{activeTabObj.content}</div>
        </div>
      )}
    </div>
  );
}

/**
 * Canonical AWS Cloudscape StatusIndicator
 */
export function AwsStatusIndicator({ type = "info", children }) {
  const icons = {
    success: "✓",
    observed: "✓",
    validated: "✓",
    warning: "⚠",
    inferred: "⚠",
    error: "✕",
    danger: "✕",
    info: "●",
    derived: "●",
    pending: "○",
    stopped: "■",
  };
  const norm =
    type === "observed" || type === "validated"
      ? "success"
      : type === "danger"
      ? "error"
      : type === "inferred"
      ? "warning"
      : type === "derived"
      ? "info"
      : type;

  return (
    <span className={`awsui-status-indicator is-${norm}`}>
      <span className="awsui-status-icon" aria-hidden="true">
        {icons[type] || "●"}
      </span>
      <span className="awsui-status-text">{children}</span>
    </span>
  );
}

/**
 * Canonical AWS Cloudscape Alert / Flashbar item
 */
export function AwsAlert({
  type = "info",
  title,
  children,
  onDismiss,
  action,
  style,
}) {
  const icons = {
    success: "✓",
    warning: "⚠",
    error: "✕",
    info: "ℹ",
  };
  return (
    <div
      className={`awsui-alert is-${type}`}
      role={type === "error" ? "alert" : "status"}
      style={style}
    >
      <div className="awsui-alert-icon" aria-hidden="true">
        {icons[type] || "ℹ"}
      </div>
      <div className="awsui-alert-content">
        {title && <div className="awsui-alert-title">{title}</div>}
        <div className="awsui-alert-body">{children}</div>
      </div>
      {(action || onDismiss) && (
        <div className="awsui-alert-actions">
          {action}
          {onDismiss && (
            <button
              type="button"
              className="awsui-alert-dismiss"
              onClick={onDismiss}
              aria-label="Cerrar alerta"
            >
              ×
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Canonical AWS Cloudscape Structured Empty State
 */
export function AwsEmptyState({ title, description, action }) {
  return (
    <div className="awsui-empty-state">
      <div className="awsui-empty-title">{title}</div>
      {description && <p className="awsui-empty-desc">{description}</p>}
      {action && <div className="awsui-empty-action">{action}</div>}
    </div>
  );
}
