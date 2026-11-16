/**
 * CloudMove — Unified API Client & Endpoint Resolver
 * Guarantees consistent connectivity across Architecture, Discovery,
 * Centralized API Client for Discovery, Migration Orchestrator (Case 1 & Case 2), Connectors, and Audit modules.
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
  const { timeoutMs = 45000, signal: externalSignal, ...fetchOptions } = options || {};
  const basesToTry = [
    cachedApiBase,
    ...CANDIDATE_API_BASES.filter((b) => b !== cachedApiBase),
  ];

  // Deduplicate candidate URLs that resolve to the exact same endpoint in the browser
  const attemptedTargets = [];
  const seenResolvedUrls = new Set();
  for (const base of basesToTry) {
    const targetUrl = buildUrl(base, path);
    let resolvedHref = targetUrl;
    if (typeof window !== "undefined" && window.location?.origin) {
      try {
        resolvedHref = new URL(targetUrl, window.location.origin).href;
      } catch {
        resolvedHref = targetUrl;
      }
    }
    if (seenResolvedUrls.has(resolvedHref)) continue;
    seenResolvedUrls.add(resolvedHref);
    attemptedTargets.push({ base, targetUrl });
  }

  let lastError = null;
  let lastBadGatewayRes = null;
  for (const { base, targetUrl } of attemptedTargets) {
    const controller = new AbortController();
    let timedOut = false;
    const onExternalAbort = () => controller.abort();
    if (externalSignal) {
      if (externalSignal.aborted) {
        controller.abort();
      } else {
        externalSignal.addEventListener("abort", onExternalAbort, { once: true });
      }
    }
    const timer =
      timeoutMs > 0
        ? setTimeout(() => {
            timedOut = true;
            controller.abort();
          }, timeoutMs)
        : null;

    try {
      const res = await fetch(targetUrl, {
        ...fetchOptions,
        signal: controller.signal,
      });
      if (res.status === 502 || res.status === 504) {
        lastBadGatewayRes = res;
        continue;
      }
      cachedApiBase = base;
      return res;
    } catch (err) {
      if (timedOut) {
        lastError = new Error(
          `Tiempo de espera agotado (${Math.round(timeoutMs / 1000)}s) esperando respuesta del servidor.`
        );
      } else {
        lastError = err;
      }
    } finally {
      if (timer) clearTimeout(timer);
      if (externalSignal) {
        externalSignal.removeEventListener("abort", onExternalAbort);
      }
    }
  }
  if (lastBadGatewayRes) return lastBadGatewayRes;
  if (lastError) throw lastError;
  throw new Error("No fue posible conectar con el backend de CloudMove.");
}

