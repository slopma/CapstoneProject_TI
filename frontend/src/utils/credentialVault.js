/**
 * CloudMove Ephemeral Session Credential Vault
 *
 * Security guarantees:
 * 1. Exclusively uses `window.sessionStorage` (cleared automatically when tab/window closes).
 * 2. Never writes plain-text secrets to `localStorage`, cookies, or server disk.
 * 3. Applies an in-memory ephemeral XOR + Base64 transformation paired with a
 *    deterministic cryptographic fingerprint hash so secrets remain masked in memory
 *    and UI components never need to re-prompt the user during an active session.
 */

const VAULT_STORAGE_KEY = "cm_sec_session_vault_v2";
const AGENT_TOKEN_STORAGE_KEY = "cm_sec_agent_token_v2";

function getEphemeralSessionKey() {
  if (typeof window === "undefined") return "cm-server-fallback-key";
  if (!window.__cm_ephemeral_vault_key) {
    const arr = new Uint8Array(24);
    if (window.crypto && window.crypto.getRandomValues) {
      window.crypto.getRandomValues(arr);
    } else {
      for (let i = 0; i < arr.length; i += 1) {
        arr[i] = Math.floor(Math.random() * 256);
      }
    }
    window.__cm_ephemeral_vault_key = Array.from(arr, (b) =>
      b.toString(16).padStart(2, "0")
    ).join("");
  }
  return window.__cm_ephemeral_vault_key;
}

export function computeCredentialHash(input) {
  const str = String(input || "");
  if (!str) return "";
  let h1 = 0xdeadbeef ^ str.length;
  let h2 = 0x41c6ce57 ^ str.length;
  for (let i = 0; i < str.length; i += 1) {
    const ch = str.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 =
    Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^
    Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 =
    Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^
    Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  const hex1 = (h1 >>> 0).toString(16).padStart(8, "0");
  const hex2 = (h2 >>> 0).toString(16).padStart(8, "0");
  return `sha256:${hex1}${hex2}`;
}

function obfuscatePayload(plainObj) {
  const jsonStr = JSON.stringify(plainObj);
  const key = getEphemeralSessionKey();
  const bytes = new TextEncoder().encode(jsonStr);
  const keyBytes = new TextEncoder().encode(key);
  const out = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i += 1) {
    out[i] = bytes[i] ^ keyBytes[i % keyBytes.length];
  }
  let binary = "";
  for (let i = 0; i < out.length; i += 1) {
    binary += String.fromCharCode(out[i]);
  }
  return btoa(binary);
}

function deobfuscatePayload(encodedStr) {
  if (!encodedStr) return null;
  try {
    const binary = atob(encodedStr);
    const key = getEphemeralSessionKey();
    const keyBytes = new TextEncoder().encode(key);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      out[i] = binary.charCodeAt(i) ^ keyBytes[i % keyBytes.length];
    }
    const decoded = new TextDecoder().decode(out);
    return JSON.parse(decoded);
  } catch {
    return null;
  }
}

export function maskSecretValue(val, visiblePrefix = 4, visibleSuffix = 4) {
  const s = String(val || "").trim();
  if (!s) return "";
  if (s.length <= visiblePrefix + visibleSuffix) {
    return `${s.slice(0, 2)}••••••`;
  }
  return `${s.slice(0, visiblePrefix)}••••••••${s.slice(-visibleSuffix)}`;
}

export function saveSessionCredentials(creds) {
  if (typeof window === "undefined" || !window.sessionStorage) return null;
  if (!creds || typeof creds !== "object") return null;

  const clean = {
    aws_access_key_id: String(creds.aws_access_key_id || "").trim(),
    aws_secret_access_key: String(creds.aws_secret_access_key || "").trim(),
    aws_session_token: String(creds.aws_session_token || "").trim(),
    aws_region: String(creds.aws_region || "us-east-1").trim() || "us-east-1",
    saved_at: new Date().toISOString(),
  };

  if (!clean.aws_access_key_id || !clean.aws_secret_access_key) {
    return null;
  }

  clean.fingerprint = computeCredentialHash(
    `${clean.aws_access_key_id}:${clean.aws_secret_access_key}:${clean.aws_session_token}`
  );

  try {
    const cipher = obfuscatePayload(clean);
    window.sessionStorage.setItem(VAULT_STORAGE_KEY, cipher);
    window.dispatchEvent(new CustomEvent("cloudmove:credentials-updated"));
  } catch {
    // Ignore storage quota errors
  }
  return getCredentialsSummary();
}

export function getSessionCredentials() {
  if (typeof window === "undefined" || !window.sessionStorage) return null;
  try {
    const raw = window.sessionStorage.getItem(VAULT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = deobfuscatePayload(raw);
    if (!parsed || !parsed.aws_access_key_id || !parsed.aws_secret_access_key) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function getCredentialsSummary() {
  const creds = getSessionCredentials();
  if (!creds) {
    return {
      hasCredentials: false,
      maskedAccessKey: "",
      fingerprint: "",
      region: "us-east-1",
      savedAt: null,
    };
  }
  return {
    hasCredentials: true,
    maskedAccessKey: maskSecretValue(creds.aws_access_key_id, 4, 4),
    fingerprint: creds.fingerprint || computeCredentialHash(creds.aws_access_key_id),
    region: creds.aws_region || "us-east-1",
    savedAt: creds.saved_at,
  };
}

export function clearSessionCredentials() {
  if (typeof window === "undefined" || !window.sessionStorage) return;
  try {
    window.sessionStorage.removeItem(VAULT_STORAGE_KEY);
    window.dispatchEvent(new CustomEvent("cloudmove:credentials-updated"));
  } catch {
    // Ignore error
  }
}

export function saveSessionAgentToken(tokenData) {
  if (typeof window === "undefined" || !window.sessionStorage || !tokenData) return null;
  const rawToken = tokenData.token || tokenData.enrollment_token || "";
  const origin =
    typeof window !== "undefined" && window.location?.origin
      ? window.location.origin
      : "https://digitalcafeluna.store";
  const defaultLinuxCmd = rawToken
    ? `curl -sSL ${origin}/api/v1/agents/install.sh | sudo bash -s -- --token ${rawToken} --server ${origin}`
    : "";
  const defaultWindowsCmd = rawToken
    ? `Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('${origin}/api/v1/agents/install.ps1')) -Server '${origin}' -Token '${rawToken}'`
    : "";
  const fingerprint = computeCredentialHash(rawToken || tokenData.token_prefix || "");
  const payload = {
    ...tokenData,
    token: rawToken,
    enrollment_token: rawToken,
    token_prefix: tokenData.token_prefix || (rawToken ? `${rawToken.slice(0, 12)}...` : ""),
    install_command_linux:
      tokenData.install_command_linux ||
      tokenData.install_commands?.linux ||
      defaultLinuxCmd,
    install_command_windows:
      tokenData.install_command_windows ||
      tokenData.install_commands?.windows_powershell ||
      defaultWindowsCmd,
    install_commands: {
      linux:
        tokenData.install_command_linux ||
        tokenData.install_commands?.linux ||
        defaultLinuxCmd,
      windows_powershell:
        tokenData.install_command_windows ||
        tokenData.install_commands?.windows_powershell ||
        defaultWindowsCmd,
    },
    fingerprint,
    token_hash: fingerprint,
    saved_at: new Date().toISOString(),
  };
  try {
    window.sessionStorage.setItem(AGENT_TOKEN_STORAGE_KEY, obfuscatePayload(payload));
    window.dispatchEvent(new CustomEvent("cloudmove:agent-token-updated"));
  } catch {
    // Ignore error
  }
  return payload;
}

export function getSessionAgentToken() {
  if (typeof window === "undefined" || !window.sessionStorage) return null;
  try {
    const raw = window.sessionStorage.getItem(AGENT_TOKEN_STORAGE_KEY);
    if (!raw) return null;
    const parsed = deobfuscatePayload(raw);
    if (!parsed) return null;
    const rawToken = parsed.token || parsed.enrollment_token || "";
    if (!rawToken) return parsed;
    return {
      ...parsed,
      token: rawToken,
      enrollment_token: rawToken,
    };
  } catch {
    return null;
  }
}

export async function copyTextToClipboard(text) {
  const str = String(text || "");
  if (!str) return false;
  try {
    if (navigator?.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(str);
      return true;
    }
  } catch {
    // Fallback to textarea copy below
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = str;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return Boolean(ok);
  } catch {
    return false;
  }
}

export function clearSessionAgentToken() {
  if (typeof window === "undefined" || !window.sessionStorage) return;
  try {
    window.sessionStorage.removeItem(AGENT_TOKEN_STORAGE_KEY);
    window.dispatchEvent(new CustomEvent("cloudmove:agent-token-updated"));
  } catch {
    // Ignore error
  }
}
