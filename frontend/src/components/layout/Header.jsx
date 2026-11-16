import React, { useState, useRef, useEffect } from "react";
import { getCredentialsSummary } from "../../utils/credentialVault";

export const TAB_LABELS = {
  overview: "Console Home (Inicio)",
  discovery: "Discovery e inventario (osquery)",
  architecture: "Grafo de arquitectura CMIR",
  migration: "Orquestador de migración (Casos 1 y 2)",
  "sources-targets": "Orígenes, agentes y destinos",
  "executions-audit": "Auditoría AWS y Terraform",
};

const QUICK_SERVICES = [
  {
    category: "Casos de Migración Activos",
    items: [
      {
        id: "case-1",
        tab: "migration",
        useCase: "app_source",
        title: "Caso 1 · Migración de Aplicación (GitHub)",
        desc: "Inspección de repositorios y despliegue automatizado en contenedores sobre Amazon EC2 / ECS",
        badge: "Caso 1",
      },
      {
        id: "case-2",
        tab: "migration",
        useCase: "vm_image",
        title: "Caso 2 · Migración de Imagen de SO / VM",
        desc: "Captura en vivo por agente osquery o imagen VMDK/QCOW2 hacia Amazon EC2",
        badge: "Caso 2",
      },
      {
        id: "migration-hub",
        tab: "migration",
        title: "AWS Migration Hub · Planes y Etapas",
        desc: "Gestión del ciclo de vida transaccional, pruebas pre-cutover y generación Terraform HCL",
        badge: "Hub",
      },
    ],
  },
  {
    category: "Descubrimiento, Topología y Gobernanza",
    items: [
      {
        id: "overview-home",
        tab: "overview",
        title: "Console Home (Panel Principal)",
        desc: "Resumen ejecutivo del entorno, widgets de salud, cuotas de AWS Academy y accesos rápidos",
      },
      {
        id: "discovery-osquery",
        tab: "discovery",
        title: "Application Discovery Service (osquery)",
        desc: "Telemetría profunda de hardware, procesos, puertos TCP/UDP y motores de bases de datos",
      },
      {
        id: "arch-graph",
        tab: "architecture",
        title: "Grafo Jerárquico CMIR v2.1",
        desc: "Topología interactiva Nivel 0-5, dependencias transitivas y recursos compartidos",
      },
      {
        id: "sources-agents",
        tab: "sources-targets",
        title: "Conectores, Agentes Remotos y Destinos",
        desc: "Inscripción de agentes multiplataforma (Linux/Windows/macOS) y validación AWS STS",
      },
      {
        id: "cloud-audit",
        tab: "executions-audit",
        title: "Auditoría de Cuenta AWS y Estados Terraform",
        desc: "Consulta en vivo de instancias EC2, volúmenes EBS, VPCs y destrucción controlada",
      },
    ],
  },
];

export default function Header({
  activeTab,
  setActiveTab,
  onQuickStartUseCase,
  searchQuery,
  setSearchQuery,
  selectedCount,
  onPrepareMigration,
  targetProvider: _targetProvider = "aws",
  setTargetProvider,
  onToggleMobileNav,
  sidebarCollapsed,
  onToggleSidebarCollapse,
}) {
  const [servicesOpen, setServicesOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [searchFocused, setSearchFocused] = useState(false);
  const [credSummary, setCredSummary] = useState(() => getCredentialsSummary());
  const servicesRef = useRef(null);
  const accountRef = useRef(null);
  const searchRef = useRef(null);

  useEffect(() => {
    const handleCredsSync = () => setCredSummary(getCredentialsSummary());
    window.addEventListener("cloudmove:credentials-updated", handleCredsSync);
    return () => window.removeEventListener("cloudmove:credentials-updated", handleCredsSync);
  }, []);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (servicesRef.current && !servicesRef.current.contains(e.target)) {
        setServicesOpen(false);
      }
      if (accountRef.current && !accountRef.current.contains(e.target)) {
        setAccountOpen(false);
      }
      if (searchRef.current && !searchRef.current.contains(e.target)) {
        setSearchFocused(false);
      }
    };
    const handleKeyDown = (e) => {
      if ((e.altKey && e.key.toLowerCase() === "s") || (e.metaKey && e.key.toLowerCase() === "k")) {
        e.preventDefault();
        const input = searchRef.current?.querySelector("input");
        if (input) input.focus();
      }
      if (e.key === "Escape") {
        setServicesOpen(false);
        setAccountOpen(false);
        setSearchFocused(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  const handleServiceSelect = (item) => {
    setServicesOpen(false);
    setSearchFocused(false);
    if (item.useCase && onQuickStartUseCase) {
      onQuickStartUseCase(item.useCase);
    } else if (setActiveTab) {
      setActiveTab(item.tab);
    }
  };

  const flatServices = QUICK_SERVICES.flatMap((g) => g.items);
  const filteredServices = searchQuery?.trim()
    ? flatServices.filter(
        (s) =>
          s.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
          s.desc.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : flatServices;

  return (
    <header className="enterprise-header awsui-top-navigation" role="banner">
      <div className="header-left">
        <button
          type="button"
          className="mobile-nav-toggle"
          onClick={onToggleMobileNav}
          aria-label="Abrir menú de navegación"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>

        {onToggleSidebarCollapse && (
          <button
            type="button"
            className="awsui-top-icon-btn"
            onClick={onToggleSidebarCollapse}
            title={sidebarCollapsed ? "Expandir panel de navegación" : "Contraer panel de navegación"}
            aria-label="Alternar panel lateral"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
            </svg>
          </button>
        )}

        {/* AWS Console Brand Identity */}
        <button
          type="button"
          className="awsui-brand-identity"
          onClick={() => setActiveTab && setActiveTab("overview")}
          title="Ir a Console Home (Página Principal)"
        >
          <span className="awsui-brand-cube" aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FF9900" strokeWidth="2.2">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </span>
          <span className="awsui-brand-title">CloudMove</span>
          <span className="awsui-brand-tag">Management Console</span>
        </button>

        {/* AWS Services 3x3 Waffle Menu */}
        <div className="awsui-services-dropdown-wrap" ref={servicesRef}>
          <button
            type="button"
            className={`awsui-services-trigger ${servicesOpen ? "is-open" : ""}`}
            onClick={() => setServicesOpen((prev) => !prev)}
            aria-expanded={servicesOpen}
            aria-haspopup="true"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <rect x="3" y="3" width="4" height="4" rx="1" />
              <rect x="10" y="3" width="4" height="4" rx="1" />
              <rect x="17" y="3" width="4" height="4" rx="1" />
              <rect x="3" y="10" width="4" height="4" rx="1" />
              <rect x="10" y="10" width="4" height="4" rx="1" />
              <rect x="17" y="10" width="4" height="4" rx="1" />
              <rect x="3" y="17" width="4" height="4" rx="1" />
              <rect x="10" y="17" width="4" height="4" rx="1" />
              <rect x="17" y="17" width="4" height="4" rx="1" />
            </svg>
            <span>Servicios</span>
            <span style={{ fontSize: 10, opacity: 0.8 }}>▾</span>
          </button>

          {servicesOpen && (
            <div className="awsui-services-popover" role="menu" aria-label="Catálogo de servicios de CloudMove">
              <div className="awsui-services-popover-header">
                <span>Servicios de CloudMove Console</span>
                <span className="awsui-services-popover-sub">Casos 1 y 2 · Modelo CMIR v2.1</span>
              </div>
              <div className="awsui-services-popover-grid">
                {QUICK_SERVICES.map((group) => (
                  <div key={group.category} className="awsui-services-group">
                    <div className="awsui-services-group-title">{group.category}</div>
                    <div className="awsui-services-list">
                      {group.items.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          className="awsui-service-item"
                          onClick={() => handleServiceSelect(item)}
                        >
                          <div className="awsui-service-item-top">
                            <span className="awsui-service-item-title">{item.title}</span>
                            {item.badge && (
                              <span className="awsui-service-item-badge">{item.badge}</span>
                            )}
                          </div>
                          <span className="awsui-service-item-desc">{item.desc}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Global Search Bar */}
      <div className="awsui-top-center" ref={searchRef}>
        <div className="header-search-box" style={{ position: "relative" }}>
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="search-icon"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="search"
            name="architecture-search"
            className="header-search-input"
            aria-label="Buscar servicios, recursos, IPs o planes"
            placeholder="Buscar servicios, casos de uso, recursos o IPs... [Alt+S]"
            value={searchQuery}
            onFocus={() => setSearchFocused(true)}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setSearchFocused(true);
            }}
          />
          {searchFocused && (
            <div className="awsui-search-suggestions" role="listbox">
              <div className="awsui-search-suggestions-header">
                Navegación rápida de servicios ({filteredServices.length})
              </div>
              {filteredServices.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className="awsui-search-suggestion-item"
                  onClick={() => handleServiceSelect(s)}
                >
                  <div>
                    <strong>{s.title}</strong>
                    <div style={{ fontSize: 12, color: "#545b64" }}>{s.desc}</div>
                  </div>
                  <span style={{ fontSize: 11, color: "#0972d3", fontWeight: 700 }}>Abrir →</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right Utilities: Cloud Audit, Region Selector, Account Menu & Primary CTA */}
      <div className="header-right">
        <button
          type="button"
          className={`awsui-top-util-btn ${activeTab === "executions-audit" ? "is-active" : ""}`}
          onClick={() => setActiveTab && setActiveTab("executions-audit")}
          title="Auditoría de Cuenta AWS y Ejecuciones Terraform"
        >
          <span style={{ fontFamily: "monospace", fontWeight: 700, color: "#FF9900" }}>&gt;_</span>
          <span className="awsui-util-label">Auditoría AWS</span>
        </button>

        {setTargetProvider && (
          <div className="awsui-top-util-select">
            <select
              aria-label="Región AWS destino activa"
              defaultValue="us-east-1"
              onChange={() => setTargetProvider("aws")}
              className="awsui-squid-select"
            >
              <option value="us-east-1">EE. UU. Este (N. Virginia) · us-east-1</option>
              <option value="us-west-2">EE. UU. Oeste (Oregón) · us-west-2</option>
            </select>
          </div>
        )}

        {/* Account Menu */}
        <div className="awsui-account-dropdown-wrap" ref={accountRef}>
          <button
            type="button"
            className="awsui-account-trigger"
            onClick={() => setAccountOpen((prev) => !prev)}
            title="Detalles de cuenta y sesión AWS Academy"
          >
            <span className="awsui-account-dot" aria-hidden="true" />
            <span className="awsui-account-name">
              {credSummary.hasCredentials ? `aws/${credSummary.maskedAccessKey}` : "Sesión Web AWS"}
            </span>
            <span style={{ fontSize: 10, opacity: 0.75 }}>▾</span>
          </button>

          {accountOpen && (
            <div className="awsui-account-popover" role="menu">
              <div className="awsui-account-popover-header">
                <div style={{ fontSize: 12, color: "#545b64" }}>Sesión aislada por navegador (sessionStorage)</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#000716", fontFamily: "monospace" }}>
                  {credSummary.hasCredentials ? credSummary.maskedAccessKey : "Sin credenciales cargadas"}
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: credSummary.hasCredentials ? "#037f0c" : "#b45309",
                    fontWeight: 600,
                    marginTop: 2,
                  }}
                >
                  {credSummary.hasCredentials
                    ? `● Credenciales activas en pestaña · ${credSummary.region || "us-east-1"}`
                    : "○ Ingresa credenciales AWS en Despliegue o Auditoría"}
                </div>
              </div>
              <div className="awsui-account-popover-body">
                <button
                  type="button"
                  className="awsui-account-menu-item"
                  onClick={() => {
                    setAccountOpen(false);
                    if (setActiveTab) setActiveTab("overview");
                  }}
                >
                  Ir a Console Home
                </button>
                <button
                  type="button"
                  className="awsui-account-menu-item"
                  onClick={() => {
                    setAccountOpen(false);
                    if (setActiveTab) setActiveTab("executions-audit");
                  }}
                >
                  Gestionar credenciales AWS y recursos activos
                </button>
                <button
                  type="button"
                  className="awsui-account-menu-item"
                  onClick={() => {
                    setAccountOpen(false);
                    if (setActiveTab) setActiveTab("sources-targets");
                  }}
                >
                  Configurar agentes y conectores
                </button>
              </div>
            </div>
          )}
        </div>

        {selectedCount > 0 ? (
          <button
            type="button"
            className="header-action-btn primary"
            onClick={onPrepareMigration}
          >
            Generar IaC ({selectedCount})
          </button>
        ) : (
          <button
            type="button"
            className="header-action-btn primary"
            onClick={() => setActiveTab && setActiveTab("migration")}
          >
            Nueva migración
          </button>
        )}
      </div>
    </header>
  );
}
