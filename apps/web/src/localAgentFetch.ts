export function localAgentFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const token = typeof sessionStorage === "undefined" ? "" : sessionStorage.getItem("nexora:local-agent-token") ?? "";
  const headers = new Headers(init.headers ?? {});
  if (token && !headers.has("Authorization")) headers.set("Authorization", "Bearer " + token);
  return fetch(input, { ...init, headers }).then(response => {
    if (response.status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event("nexora:local-agent-session-expired"));
    return response;
  });
}
