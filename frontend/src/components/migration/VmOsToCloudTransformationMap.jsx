import React, { useState } from "react";
import {
  ContextualTechnicalModal,
  HelpTooltipButton,
} from "./PlannedCloudStructureGraphModal";

export default function VmOsToCloudTransformationMap({
  manifest,
  consistencyStrategy = "quiesced_snapshot",
}) {
  const [showTable, setShowTable] = useState(false);
  const [showHelpModal, setShowHelpModal] = useState(false);

  if (!manifest) return null;

  const slug = String(manifest.name || "live-os")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const osInfo = manifest.os || {};
  const disks = manifest.disks || [];
  const primaryDisk = disks[0] || {};
  const ports = manifest.listening_ports || [22, 80, 443, 3000, 8000];
  const procsCount = (manifest.running_processes || []).length;
  const svcsCount = (manifest.systemd_services || []).length;
  const usersList = manifest.local_users || ["root"];

  const summaryCards = [
    {
      layer: "Red y Puertos",
      targetTitle: `VPC Multi-AZ + ${ports.slice(0, 12).length} Reglas SG`,
      summary: `Puertos: ${ports.slice(0, 6).join(", ")}${ports.length > 6 ? "..." : ""}`,
      cost: "$0 USD/mes",
    },
    {
      layer: "Cómputo EC2",
      targetTitle: `${osInfo.distro || "Linux"} · ${manifest.boot_mode || "UEFI"}`,
      summary:
        consistencyStrategy === "continuous_replication"
          ? "Replicación AWS MGN"
          : "Instancia EC2 Nitro + Snapshot Quiesced",
      cost: "Free Tier / ~$8",
    },
    {
      layer: "Almacenamiento EBS",
      targetTitle: `${primaryDisk.size_gib || manifest.total_provisioned_gib || 30} GiB gp3 Cifrado`,
      summary: `Origen ${primaryDisk.device || "/dev/nvme0n1"} (${manifest.partition_scheme || "GPT"})`,
      cost: "~$0.08/GiB-mes",
    },
    {
      layer: "Archivos y Servicios",
      targetTitle:
        Array.isArray(manifest.selected_user_paths) && manifest.selected_user_paths.length > 0
          ? `${manifest.selected_user_paths.length} ruta(s) seleccionadas`
          : `${usersList.length} usuarios · ${svcsCount} servicios`,
      summary: `Rehidratación Cloud-Init + ${procsCount} procesos`,
      cost: "$0 USD/mes",
    },
  ];

  return (
    <div
      className="cm-card"
      style={{
        marginTop: 14,
        border: "1px solid #d5dbdb",
        backgroundColor: "#fafafa",
        padding: "14px 16px",
        borderRadius: 6,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span className="cm-badge observed">MAPA SO / VM → AWS</span>
          <strong style={{ fontSize: 14.5, color: "#000716" }}>
            Equivalencia de Sistema Operativo en AWS
          </strong>
          <HelpTooltipButton
            label="¿Qué se preserva y adapta?"
            onClick={() => setShowHelpModal(true)}
          />
        </div>
        <button
          type="button"
          className="cm-btn sm secondary"
          onClick={() => setShowTable((v) => !v)}
        >
          {showTable ? "Ocultar detalle HCL ▲" : "Ver detalle HCL por capa ▾"}
        </button>
      </div>

      <ContextualTechnicalModal
        isOpen={showHelpModal}
        onClose={() => setShowHelpModal(false)}
        title="Transformación de Sistema Operativo / VM hacia Amazon EC2"
        badge="Caso 2 · AWS Nitro"
        whyTransformed="El sistema operativo en vivo se adapta al hipervisor AWS Nitro preservando las carpetas seleccionadas del usuario, montajes por UUID en /etc/fstab, servicios systemd y usuarios locales mediante Cloud-Init, mientras descarta la memoria RAM volátil para garantizar un arranque limpio."
        customSections={[
          {
            heading: "Recursos Terraform sintetizados",
            body: `aws_vpc.target_vpc, aws_security_group.app_sg, aws_instance.vm_${slug}, aws_ebs_volume.disk_${slug}_1 y bootstrap user_data.sh.`,
          },
        ]}
      />

      <div className="cm-choice-cards-grid" style={{ marginBottom: showTable ? 12 : 0 }}>
        {summaryCards.map((c, idx) => (
          <div key={idx} className="cm-card-subtle" style={{ backgroundColor: "#ffffff", padding: "10px 12px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6, marginBottom: 4 }}>
              <span className="cm-badge info" style={{ fontSize: 11 }}>{c.layer}</span>
              <span className="cm-hint" style={{ fontSize: 11.5 }}>{c.cost}</span>
            </div>
            <strong style={{ fontSize: 13.5, color: "#000716", display: "block", marginBottom: 2 }}>
              {c.targetTitle}
            </strong>
            <div className="cm-hint" style={{ fontSize: 12 }}>{c.summary}</div>
          </div>
        ))}
      </div>

      {showTable && (
        <div className="cm-table-wrap" style={{ backgroundColor: "#ffffff", borderRadius: 4 }}>
          <table className="cm-table" style={{ margin: 0 }}>
            <thead>
              <tr>
                <th>Capa Origen</th>
                <th>Mapeo en AWS</th>
                <th>Recurso HCL (main.tf)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Red y Puertos ({ports.length})</strong></td>
                <td>VPC Multi-AZ + Security Group</td>
                <td><code>aws_vpc.target_vpc + aws_security_group.app_sg</code></td>
              </tr>
              <tr>
                <td><strong>SO {osInfo.distro || "Linux"} ({manifest.boot_mode || "UEFI"})</strong></td>
                <td>Instancia EC2 Nitro + Snapshot Quiesced</td>
                <td><code>aws_instance.vm_{slug}</code></td>
              </tr>
              <tr>
                <td><strong>Disco {primaryDisk.device || "/dev/nvme0n1"}</strong></td>
                <td>Volumen EBS gp3 cifrado (UUID fstab)</td>
                <td><code>aws_ebs_volume.disk_{slug}_1</code></td>
              </tr>
              <tr>
                <td><strong>Carpetas y Servicios systemd</strong></td>
                <td>Bootstrap Cloud-Init + Restore Tarball</td>
                <td><code>user_data.sh + restore_system_image.sh</code></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

