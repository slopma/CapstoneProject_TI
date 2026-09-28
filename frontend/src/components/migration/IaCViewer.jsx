import React, { useState } from "react";

function IaCViewer({ code, language = "hcl", filename = "main.tf" }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([code], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="iac-viewer-container">
      <div className="iac-toolbar-header">
        <div className="iac-filename-group">
          <span className="file-lang-pill">{language.toUpperCase()}</span>
          <span className="file-name">{filename}</span>
        </div>
        <div className="iac-actions">
          <button type="button" className="iac-btn" onClick={handleCopy}>
            {copied ? "Copied!" : "Copy Code"}
          </button>
          <button type="button" className="iac-btn primary" onClick={handleDownload}>
            Download File
          </button>
        </div>
      </div>
      <pre className="iac-code-content">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export default IaCViewer;
