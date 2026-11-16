export const STATE_FLOW = [
  "DRAFT",
  "DISCOVERING",
  "ASSESSED",
  "PLAN_READY",
  "APPROVED",
  "PREPARING",
  "TESTING",
  "READY_FOR_CUTOVER",
  "COMPLETED",
];

export const OPERATIONAL_BADGE_MAP = {
  SIMULATED: { badgeClass: "simulated", label: "SIMULADO (Dry-Run)" },
  PLANNED: { badgeClass: "info", label: "PLANIFICADO" },
  READY_TO_EXECUTE: { badgeClass: "observed", label: "APROBADO · LISTO PARA EJECUTAR" },
  RUNNING: { badgeClass: "running", label: "EN EJECUCIÓN" },
  VALIDATED: { badgeClass: "validated", label: "VALIDADO PRE-CUTOVER" },
  BLOCKED: { badgeClass: "danger", label: "BLOQUEADO POR INCOMPATIBILIDAD" },
  FAILED: { badgeClass: "danger", label: "FALLO EN ETAPA (Recuperable)" },
  COMPLETED_IN_REAL_CLOUD: { badgeClass: "validated", label: "COMPLETADO EN NUBE REAL" },
};

export function deriveOperationalStatusBadge(job) {
  if (!job) return "PLANNED";
  if (job.blockers?.length > 0 && job.state === "FAILED") return "BLOCKED";
  if (job.state === "FAILED") return "FAILED";
  if (job.state === "COMPLETED" && job.completed_in_real_cloud) return "COMPLETED_IN_REAL_CLOUD";
  if (job.state === "COMPLETED" && !job.completed_in_real_cloud) return "SIMULATED";
  if (job.state === "READY_FOR_CUTOVER") return "VALIDATED";
  if (job.state === "APPROVED") return "READY_TO_EXECUTE";
  if (["PREPARING", "TESTING", "DISCOVERING"].includes(job.state)) return "RUNNING";
  return "PLANNED";
}

export const USE_CASE_CARDS = [
  {
    id: "app_source",
    title: "Caso 1 · Aplicación (GitHub / Código Fuente)",
    subtitle: "Inspecciona repositorios GitHub o carpetas locales hacia contenedores gestionados y bases de datos en Amazon Web Services (AWS).",
    badge: "Caso 1 · App",
  },
  {
    id: "vm_image",
    title: "Caso 2 · Imagen de SO / Máquina Virtual",
    subtitle: "Inscribe el agente remoto osquery o analiza un disco virtual (VMDK/QCOW2/RAW) hacia instancias Amazon EC2.",
    badge: "Caso 2 · VM / SO",
  },
];

export const FIDELITY_STATUS_META = {
  preserved: { label: "PRESERVADO ÍNTEGRAMENTE", badgeClass: "observed" },
  modified_or_adapted: { label: "MODIFICADO / ADAPTADO EN DESTINO", badgeClass: "derived" },
  requires_manual_reconfiguration: { label: "REQUIERE RECONFIGURACIÓN", badgeClass: "warning" },
  not_preserved: { label: "NO TRANSFERIBLE (Limitación Física)", badgeClass: "danger" },
};

export const PRIMARY_TRANSFORMATION_IDS = new Set([
  "compute_architecture",
  "ebs_storage_sizing",
  "instance_sizing_profile",
  "compute_provisioning_mode",
  "storage_and_build_capacity",
]);

export function summarizeOptionTagline(text) {
  const clean = String(text || "").trim();
  if (!clean) return "";
  const firstSentence = clean.split(/(?<=[.!])\s+/)[0] || clean;
  return firstSentence.length > 108 ? `${firstSentence.slice(0, 105)}...` : firstSentence;
}
