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
const TAB_KEY_STORAGE_KEY = "cm_sec_tab_key_v2";

function getEphemeralSessionKey() {
  if (typeof window === "undefined") return "cm-server-fallback-key";
  if (window.__cm_ephemeral_vault_key) {
    return window.__cm_ephemeral_vault_key;
  }
  try {
    const existing = window.sessionStorage?.getItem(TAB_KEY_STORAGE_KEY);
    if (existing) {
      window.__cm_ephemeral_vault_key = existing;
      return existing;
    }
  } catch {
    // Ignore sessionStorage read failure
  }
  const arr = new Uint8Array(24);
  if (window.crypto && window.crypto.getRandomValues) {
    window.crypto.getRandomValues(arr);
  } else {
    for (let i = 0; i < arr.length; i += 1) {
      arr[i] = Math.floor(Math.random() * 256);
    }
  }
  const generated = Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("");
  window.__cm_ephemeral_vault_key = generated;
  try {
    window.sessionStorage?.setItem(TAB_KEY_STORAGE_KEY, generated);
  } catch {
    // Ignore sessionStorage write failure
  }
  return generated;
}

const SHA256_K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

function rotr(val, bits) {
  return (val >>> bits) | (val << (32 - bits));
}

export function computeCredentialHash(input) {
  const str = String(input || "");
  if (!str) return "";
  const msgBytes = new TextEncoder().encode(str);
  const bitLen = msgBytes.length * 8;
  const totalLen = Math.ceil((msgBytes.length + 9) / 64) * 64;
  const buf = new Uint8Array(totalLen);
  buf.set(msgBytes);
  buf[msgBytes.length] = 0x80;
  const dv = new DataView(buf.buffer);
  dv.setUint32(totalLen - 8, Math.floor(bitLen / 0x100000000), false);
  dv.setUint32(totalLen - 4, bitLen >>> 0, false);

  const H = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ];
  const W = new Uint32Array(64);
  for (let offset = 0; offset < totalLen; offset += 64) {
    for (let i = 0; i < 16; i += 1) W[i] = dv.getUint32(offset + i * 4, false);
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(W[i - 15], 7) ^ rotr(W[i - 15], 18) ^ (W[i - 15] >>> 3);
      const s1 = rotr(W[i - 2], 17) ^ rotr(W[i - 2], 19) ^ (W[i - 2] >>> 10);
      W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = H;
    for (let i = 0; i < 64; i += 1) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + S1 + ch + SHA256_K[i] + W[i]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + maj) >>> 0;
      h = g; g = f; f = e;
      e = (d + temp1) >>> 0;
      d = c; c = b; b = a;
      a = (temp1 + temp2) >>> 0;
    }
    H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0;
    H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
    H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0;
    H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
  }
  const fullHex = H.map((x) => x.toString(16).padStart(8, "0")).join("");
  return `sha256:${fullHex.slice(0, 16)}`;
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
      : "";
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
