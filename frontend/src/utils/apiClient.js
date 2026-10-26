/**
 * CloudMove — Unified API Client & Endpoint Resolver
 * Guarantees consistent connectivity across Architecture, Discovery,
 * Data Center Campaigns, Migration Orchestrator, Connectors, and Audit modules.
 */

const ENV_API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

export const CANDIDATE_API_BASES = Array.from(
  new Set([
    ENV_API,
    "",
    typeof window !== "undefined" ? window.location.origin : "",
  ].filter((b) => b !== undefined && b !== null))
);

let cachedApiBase = ENV_API || "";

export function getApiBase() {
  return cachedApiBase;
}

export function buildUrl(base, path) {
  const cleanPath = path ? (path.startsWith("/") ? path : `/${path}`) : "";
  if (!base) return cleanPath;
  const cleanBase = base.replace(/\/+$/, "");
  if (cleanBase.endsWith("/api")) {
    if (cleanPath === "/api" || cleanPath === "/api/") {
      return cleanBase;
    }
    if (cleanPath.startsWith("/api/")) {
      return `${cleanBase}${cleanPath.substring(4)}`;
    }
  }
  return `${cleanBase}${cleanPath}`;
}

export async function resolveHealthyApiBase() {
  for (const base of CANDIDATE_API_BASES) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2000);
      const testUrl = buildUrl(base, "/health");
      const res = await fetch(testUrl, { signal: controller.signal });
      clearTimeout(timer);
      if (res.ok) {
        cachedApiBase = base;
        return base;
      }
    } catch {
      // Try next candidate
    }
  }
  return cachedApiBase;
}

export async function apiFetch(path, options = {}) {
  const basesToTry = [
    cachedApiBase,
    ...CANDIDATE_API_BASES.filter((b) => b !== cachedApiBase),
  ];

  let lastError = null;
  for (const base of basesToTry) {
    try {
      const targetUrl = buildUrl(base, path);
      const res = await fetch(targetUrl, options);
      if (res.status === 502 || res.status === 504) {
        continue;
      }
      cachedApiBase = base;
      return res;
    } catch (err) {
      lastError = err;
    }
  }
  if (lastError) throw lastError;
  return fetch(buildUrl(cachedApiBase, path), options);
}

