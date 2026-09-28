import { useState } from "react";

function DetailPanel({ node, allNodes, edges, onClose, onSelectNode, targetProvider }) {
  const [activeTab, setActiveTab] = useState("overview");

  if (!node) return null;

  // Compute dependencies and dependents
  const directDependencies = edges
    .filter((e) => e.source === node.id && !e.is_hierarchy)
    .map((e) => allNodes.find((n) => n.id === e.target))
    .filter(Boolean);

  const directDependents = edges
    .filter((e) => e.target === node.id && !e.is_hierarchy)
    .map((e) => allNodes.find((n) => n.id === e.source))
    .filter(Boolean);

  const children = allNodes.filter((n) => n.parent_id === node.id);
  const parentNode = allNodes.find((n) => n.id === node.parent_id);

  return (
    <aside className="detail-panel">
      <header className="panel-header">
        <div className="panel-title-group">
          <span className="level-badge">LEVEL {node.level ?? 0}</span>
          <span className="type-badge">{node.type}</span>
          {node.is_shared && <span className="shared-badge">COMPARTIDO</span>}
        </div>
        <h2>{node.name}</h2>
        <p className="node-id">ID: <code>{node.id}</code></p>

        <button type="button" className="close-panel-btn" onClick={onClose} title="Cerrar panel">
          ✕
        </button>
      </header>

      <nav className="panel-tabs">
        <button
          type="button"
          className={activeTab === "overview" ? "active" : ""}
          onClick={() => setActiveTab("overview")}
        >
          Overview
        </button>
        <button
          type="button"
          className={activeTab === "dependencies" ? "active" : ""}
          onClick={() => setActiveTab("dependencies")}
        >
          Dependencies ({directDependencies.length})
        </button>
        <button
          type="button"
          className={activeTab === "dependents" ? "active" : ""}
          onClick={() => setActiveTab("dependents")}
        >
          Dependents ({directDependents.length})
        </button>
        <button
          type="button"
          className={activeTab === "security" ? "active" : ""}
          onClick={() => setActiveTab("security")}
        >
          Security
        </button>
        <button
          type="button"
          className={activeTab === "children" ? "active" : ""}
          onClick={() => setActiveTab("children")}
        >
          Children ({children.length})
        </button>
        <button
          type="button"
          className={activeTab === "migration" ? "active" : ""}
          onClick={() => setActiveTab("migration")}
        >
          Migration
        </button>
        <button
          type="button"
          className={activeTab === "iac" ? "active" : ""}
          onClick={() => setActiveTab("iac")}
        >
          IaC Preview
        </button>
      </nav>

      <div className="panel-content">
        {activeTab === "overview" && (
          <div className="tab-pane">
            <div className="info-grid">
              <div className="info-item">
                <span className="label">Proveedor Origen</span>
                <strong className="value">{node.provider || "AWS"}</strong>
              </div>
              <div className="info-item">
                <span className="label">Ubicación / Región</span>
                <strong className="value">{node.location || "us-east-1"}</strong>
              </div>
              <div className="info-item">
                <span className="label">Entorno</span>
                <strong className="value">{node.environment || "Production"}</strong>
              </div>
              <div className="info-item">
                <span className="label">Estado de Migración</span>
                <span className={`status-pill ${node.status?.toLowerCase()}`}>{node.status || "DISCOVERED"}</span>
              </div>
              <div className="info-item">
                <span className="label">Categoría</span>
                <strong className="value">{node.category || "resource"}</strong>
              </div>
              <div className="info-item">
                <span className="label">Nodo Padre</span>
                {parentNode ? (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onSelectNode(parentNode.id)}
                  >
                    {parentNode.name} (L{parentNode.level})
                  </button>
                ) : (
                  <span className="value muted">Raíz Arquitectura (Nivel 0)</span>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === "dependencies" && (
          <div className="tab-pane">
            <p className="help-text">Recursos de los cuales este componente depende directamente:</p>
            {directDependencies.length === 0 ? (
              <p className="empty-msg">No posee dependencias directas de salida.</p>
            ) : (
              <ul className="resource-list">
                {directDependencies.map((dep) => (
                  <li key={dep.id} className="resource-list-item">
                    <div>
                      <strong>{dep.name}</strong>
                      <small> {dep.type} · L{dep.level}</small>
                    </div>
                    <button
                      type="button"
                      className="secondary-btn-sm"
                      onClick={() => onSelectNode(dep.id)}
                    >
                      Ver Nodo
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {activeTab === "dependents" && (
          <div className="tab-pane">
            <p className="help-text">Servicios aguas arriba que dependen de este componente:</p>
            {directDependents.length === 0 ? (
              <p className="empty-msg">Ningún otro servicio depende actualmente de este componente.</p>
            ) : (
              <ul className="resource-list">
                {directDependents.map((dep) => (
                  <li key={dep.id} className="resource-list-item">
                    <div>
                      <strong>{dep.name}</strong>
                      <small> {dep.type} · L{dep.level}</small>
                    </div>
                    <button
                      type="button"
                      className="secondary-btn-sm"
                      onClick={() => onSelectNode(dep.id)}
                    >
                      Ver Nodo
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {activeTab === "security" && (
          <div className="tab-pane">
            <div className="security-card">
              <h4>Fronteras de Seguridad & Aislamiento Red</h4>
              <ul>
                <li><strong>Aislamiento:</strong> {node.security?.private_only ? "Privado (Sin IP Pública)" : "Aislado por Subred"}</li>
                <li><strong>Cifrado Reposo:</strong> {node.security?.encryption_at_rest ? " Habilitado (AES-256 / KMS)" : "Estándar"}</li>
                <li><strong>Cifrado Tránsito:</strong> TLS 1.3 Forzado</li>
                <li><strong>Reglas de Red:</strong> Ingress/Egress restringidos por Security Group</li>
              </ul>
            </div>
          </div>
        )}

        {activeTab === "children" && (
          <div className="tab-pane">
            <p className="help-text">Sub-componentes jerárquicos contenidos dentro de este nodo:</p>
            {children.length === 0 ? (
              <p className="empty-msg">Este nodo es un componente atómico sin sub-hijos.</p>
            ) : (
              <ul className="resource-list">
                {children.map((child) => (
                  <li key={child.id} className="resource-list-item">
                    <div>
                      <strong>{child.name}</strong>
                      <small> {child.type} · Level {child.level}</small>
                    </div>
                    <button
                      type="button"
                      className="secondary-btn-sm"
                      onClick={() => onSelectNode(child.id)}
                    >
                      Explorar
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {activeTab === "migration" && (
          <div className="tab-pane">
            <div className="migration-card">
              <h4>Soporte de Migración Granular</h4>
              <p><strong>Destino Recomendado:</strong> {(targetProvider || "AWS").toUpperCase()}</p>
              <p><strong>Compatibilidad CMIR:</strong> 100% Soportado (Traductor Neutral)</p>
              {node.is_shared && (
                <div className="alert alert-warning">
                  <strong>Recurso Compartido:</strong> Este componente es utilizado por múltiples cargas de trabajo. Al migrarlo, asegúrese de revisar la conectividad hacia los consumidores no migrados.
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === "iac" && (
          <div className="tab-pane">
            <p className="help-text">Traducción dinámica IaC previa para <code>{(targetProvider || "AWS").toUpperCase()}</code>:</p>
            <pre className="code-block">
              <code>{`# HCL Spec para ${node.name} (${node.id})
resource "${targetProvider === "azure" ? "azurerm_linux_virtual_machine" : "aws_instance"}" "${node.id.replace(/-/g, "_")}" {
  name        = "${node.name}"
  environment = "${node.environment || "production"}"
  cmir_level  = ${node.level || 8}
  tags = {
    ManagedBy = "CloudMove"
    CMIR_ID   = "${node.id}"
  }
}`}</code>
            </pre>
          </div>
        )}
      </div>
    </aside>
  );
}

export default DetailPanel;
