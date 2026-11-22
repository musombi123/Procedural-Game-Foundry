const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);
const DEFAULT_AGENT = "http://127.0.0.1:8765";

export function localAgentBase(configured?: string, fallback = DEFAULT_AGENT): string {
  const candidate = (configured || fallback).replace(/\/$/, "");
  try {
    const url = new URL(candidate);
    if (LOOPBACK_HOSTS.has(url.hostname) && url.port === "8765") return candidate;
  } catch { /* use the fixed loopback default */ }
  return fallback.replace(/\/$/, "");
}

export function localAgentFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const token = typeof sessionStorage === "undefined" ? "" : sessionStorage.getItem("nexora:local-agent-token") ?? "";
  const headers = new Headers(init.headers ?? {});
  let loopback = false;
  try {
    const rawUrl = input instanceof Request ? input.url : String(input);
    const url = new URL(rawUrl, typeof window === "undefined" ? DEFAULT_AGENT : window.location.origin);
    loopback = LOOPBACK_HOSTS.has(url.hostname) && url.port === "8765";
  } catch { /* invalid destinations do not receive local credentials */ }
  if (loopback && token && !headers.has("Authorization")) headers.set("Authorization", "Bearer " + token);
  if (!loopback) headers.delete("Authorization");
  return fetch(input, { ...init, headers }).then(response => {
    if (response.status === 401 && loopback && typeof window !== "undefined") window.dispatchEvent(new Event("nexora:local-agent-session-expired"));
    return response;
  });
}
