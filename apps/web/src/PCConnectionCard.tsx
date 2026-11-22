import { useCallback, useEffect, useState } from "react";

const AGENT = (import.meta.env.VITE_NEXORA_LOCAL_AGENT ?? "http://127.0.0.1:8765").replace(/\/$/, "");
type Profile = { machine?: Record<string, unknown>; gpu?: Record<string, unknown>; readiness?: number | null; [key: string]: unknown };

export default function PCConnectionCard({ onConnected }: { onConnected?: () => void }) {
  const [token, setToken] = useState(() => sessionStorage.getItem("nexora:local-agent-token") ?? "");
  const [agent, setAgent] = useState<"checking" | "running" | "offline">("checking");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [state, setState] = useState<"not-connected" | "connected" | "permission">("not-connected");
  const [message, setMessage] = useState("Checking whether the NEXORA Local Agent is running on this PC…");
  const [busy, setBusy] = useState(false);

  const checkHealth = useCallback(async () => {
    try {
      const response = await fetch(AGENT + "/health", { signal: AbortSignal.timeout(2500) });
      if (!response.ok) throw new Error("Agent health check failed");
      setAgent("running");
      setMessage("Local Agent detected. Connect with the short-lived pairing token from your PC pairing flow.");
    } catch {
      setAgent("offline");
      setState("not-connected");
      setProfile(null);
      setMessage("Local Agent not detected. Install and start the NEXORA PC app, then retry.");
    }
  }, []);

  useEffect(() => { void checkHealth(); }, [checkHealth]);

  async function connect() {
    setBusy(true);
    try {
      const response = await fetch(AGENT + "/system/capabilities", {
        headers: { Authorization: "Bearer " + token.trim() },
        signal: AbortSignal.timeout(8000)
      });
      const body = await response.json().catch(() => ({}));
      if (response.status === 401) {
        setState("permission");
        throw new Error(body.detail ?? "Pairing token expired or is invalid. Pair this browser again.");
      }
      if (!response.ok) throw new Error(body.detail ?? "Could not read PC capabilities.");
      const readinessResponse = await fetch(AGENT + "/requirements/check", {
        method: "POST",
        headers: { Authorization: "Bearer " + token.trim(), "Content-Type": "application/json" },
        body: JSON.stringify({ profile: "movie_processing" }),
        signal: AbortSignal.timeout(8000)
      });
      const readinessBody = await readinessResponse.json().catch(() => ({}));
      const checks = Array.isArray(readinessBody.checks) ? readinessBody.checks : [];
      const passCount = checks.filter((item: { status?: string }) => item.status === "pass").length;
      setProfile({ ...(body as Profile), readiness: checks.length ? Math.round(passCount / checks.length * 100) : null });
      setState("connected");
      sessionStorage.setItem("nexora:local-agent-token", token.trim());
      window.dispatchEvent(new Event("nexora:local-agent-connected"));
      setMessage(readinessBody.summary ?? "PC connected for this browser session. Hardware profile loaded.");
      onConnected?.();
    } catch (error) {
      if (state !== "permission") setState("not-connected");
      setMessage(error instanceof Error ? error.message : "PC connection failed. Retry.");
    } finally { setBusy(false); }
  }

  const readiness = typeof profile?.readiness === "number" ? Math.max(0, Math.min(100, profile.readiness)) : null;
  return <section className="pc-connect-card" data-tour="connect-pc" aria-labelledby="pc-connect-title">
    <div className="pc-connect-copy">
      <small>LOCAL COMPUTE · DEVICE STATUS</small>
      <h3 id="pc-connect-title">Connect your PC</h3>
      <p>Heavy processing runs on your own computer through the loopback-only Local Agent. Project files stay in the local project folder.</p>
      <div className="pc-connect-status" role="status"><span className={"pc-led " + (state === "connected" ? "online" : state === "permission" ? "warning" : "")}/>{state === "connected" ? "Connected" : state === "permission" ? "Permission needed" : agent === "offline" ? "Not connected · PC app not detected" : "Not connected"}</div>
      <label className="pc-token-label">Paired Local Agent token
        <input type="password" value={token} onChange={event => setToken(event.target.value)} placeholder="Paste your PC pairing token" autoComplete="off"/>
      </label>
      <div className="pc-connect-actions">
        <button className="button primary" onClick={() => void connect()} disabled={busy || agent !== "running" || !token.trim()}>{busy ? "Connecting…" : "Connect PC"}</button>
        <button className="button secondary" onClick={() => void checkHealth()}>Retry detection</button>
      </div>
      <p className="pc-connect-message" aria-live="polite">{message}</p>
    </div>
    <div className="pc-readiness">
      <b>Device readiness</b>
      <strong>{readiness === null ? "Awaiting connection" : readiness + "%"}</strong>
      <div className="pc-readiness-track"><span style={{ width: (readiness ?? 0) + "%" }}/></div>
      <small>{profile ? "Capabilities read from this PC. Device access permissions remain controlled by the PC app." : "Connect to read CPU, memory and GPU capability data."}</small>
      {agent === "offline" && import.meta.env.VITE_NEXORA_PC_DOWNLOAD_URL && <a href={import.meta.env.VITE_NEXORA_PC_DOWNLOAD_URL} target="_blank" rel="noreferrer">Download NEXORA PC app</a>}
    </div>
  </section>;
}
