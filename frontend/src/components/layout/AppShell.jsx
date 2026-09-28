import React from "react";
import Sidebar from "./Sidebar";
import Header from "./Header";

function AppShell({
  activeTab,
  onSelectTab,
  architectureName,
  environment,
  searchQuery,
  onSearchChange,
  selectedCount,
  onPrepareMigration,
  children,
}) {
  return (
    <div className="enterprise-app-shell">
      <Sidebar activeTab={activeTab} onSelectTab={onSelectTab} />
      
      <div className="shell-main-wrapper">
        <Header
          architectureName={architectureName}
          environment={environment}
          searchQuery={searchQuery}
          onSearchChange={onSearchChange}
          selectedCount={selectedCount}
          onPrepareMigration={onPrepareMigration}
        />
        
        <main className="shell-content">
          {children}
        </main>
      </div>
    </div>
  );
}

export default AppShell;
