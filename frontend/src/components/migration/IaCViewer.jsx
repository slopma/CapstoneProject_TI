import React, { useState } from "react";

function IaCViewer({ code, files, language = "hcl", filename = "main.tf" }) {
  const fileEntries = files ? Object.entries(files) : [[filename, code || ""]];
  const [activeFile, setActiveFile] = useState(fileEntries[0][0]);
  const [copied, setCopied] = useState(false);

  const activeContent = files ? files[activeFile] || "" : code || "";

  const handleCopy = () => {
    navigator.clipboard.writeText(activeContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([activeContent], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = activeFile;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="iac-viewer-container">
      <div className="iac-toolbar-header">
        <div className="iac-filename-group">
          <span className="file-lang-pill">{language.toUpperCase()}</span>
          {fileEntries.length > 1 ? (
            <div className="iac-file-tabs">
              {fileEntries.map(([fname]) => (
                <button
                  key={fname}
                  type="button"
                  className={`iac-tab-btn ${activeFile === fname ? "active" : ""}`}
                  onClick={() => setActiveFile(fname)}
                >
                  {fname}
                </button>
              ))}
            </div>
          ) : (
            <span className="file-name">{activeFile}</span>
          )}
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
        <code>{activeContent}</code>
      </pre>
    </div>
  );
}

export default IaCViewer;

