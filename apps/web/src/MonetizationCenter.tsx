import { useEffect, useState } from "react";

const LOCAL_AGENT = (import.meta.env.VITE_NEXORA_LOCAL_AGENT ?? "http://127.0.0.1:8765").replace(/\/$/, "") + "/engine";
const ADDONS = [
  { id: "analytics", name: "Game analytics", description: "Prepare a privacy-conscious local event schema for sessions, progression and retention.", status: "Local event schema" },
  { id: "rewarded_ads", name: "Rewarded ads", description: "Configure opt-in rewarded placements. A platform SDK is required before ads can be served.", status: "AdMob SDK required" },
  { id: "in_app_purchases", name: "In-app purchases", description: "Prepare product and purchase configuration for supported app stores.", status: "Google Play Billing SDK required" },
  { id: "premium_content", name: "Premium content", description: "Define premium game content that can later be unlocked by verified entitlements.", status: "Runtime entitlement integration required" },
] as const;
const PLACEMENTS = [
  { id: "rewarded_continue", label: "Rewarded continue", detail: "Optional revive after a failed level" },
  { id: "rewarded_bonus", label: "Rewarded bonus", detail: "Optional bonus reward after a level" },
  { id: "interstitial_between_levels", label: "Between levels", detail: "Interstitial only at a level transition" },
  { id: "banner_menu", label: "Main menu banner", detail: "Banner shown in the menu, never over gameplay" },
] as const;
type Manifest = {
  addons: Record<string, boolean>;
  ads: { provider: "none" | "admob"; app_id: string; android_unit_id: string; ios_unit_id: string; placements: string[]; test_mode: boolean; consent_required: boolean };
  integrations?: Record<string, string>;
};

const emptyManifest: Manifest = {
  addons: { analytics: false, rewarded_ads: false, in_app_purchases: false, premium_content: false },
  ads: { provider: "none", app_id: "", android_unit_id: "", ios_unit_id: "", placements: [], test_mode: true, consent_required: true },
};

export default function MonetizationCenter({ projectId, projectName }: { projectId: string; projectName: string }) {
  const [token, setToken] = useState("");
  const [manifest, setManifest] = useState<Manifest>(emptyManifest);
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [message, setMessage] = useState("Pair the Local Agent to configure this project's local monetization manifest.");

  async function request(method: "GET" | "PUT", body?: Manifest) {
    const response = await fetch(LOCAL_AGENT + "/api/v1/desktop/projects/" + encodeURIComponent(projectId) + "/monetization", {
      method, headers: { Authorization: "Bearer " + token, ...(body ? { "Content-Type": "application/json" } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail ?? "Local monetization API returned " + response.status);
    return result;
  }

  async function connect() {
    if (!token.trim()) return;
    setBusy(true);
    try {
      const result = await request("GET");
      setManifest({ ...emptyManifest, ...result, addons: { ...emptyManifest.addons, ...(result.addons ?? {}) }, ads: { ...emptyManifest.ads, ...(result.ads ?? {}) } });
      setConnected(true);
      setMessage("Connected · local settings loaded for " + projectName);
    } catch (error) {
      setConnected(false);
      setMessage(error instanceof Error ? error.message : "Could not load local settings.");
    } finally { setBusy(false); }
  }

  useEffect(() => { setConnected(false); }, [projectId]);

  function toggleAddon(id: string, enabled: boolean) {
    setManifest((current) => ({ ...current, addons: { ...current.addons, [id]: enabled } }));
    if (id === "rewarded_ads" && !enabled) setManifest((current) => ({ ...current, addons: { ...current.addons, rewarded_ads: false }, ads: { ...current.ads, provider: "none", placements: [] } }));
  }

  function togglePlacement(id: string, enabled: boolean) {
    setManifest((current) => ({ ...current, ads: { ...current.ads, placements: enabled ? [...new Set([...current.ads.placements, id])] : current.ads.placements.filter((item) => item !== id) } }));
  }

  async function save() {
    setBusy(true);
    try {
      const result = await request("PUT", manifest);
      setManifest({ ...emptyManifest, ...result.manifest, addons: { ...emptyManifest.addons, ...(result.manifest?.addons ?? {}) }, ads: { ...emptyManifest.ads, ...(result.manifest?.ads ?? {}) } });
      setMessage("Saved locally · no game assets or project files were uploaded");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Settings could not be saved.");
    } finally { setBusy(false); }
  }

  return <section className="monetization-shell">
    <header className="monetization-hero">
      <div><small>NEXORA STUDIO PRO · CREATOR REVENUE</small><h2>Monetize your game.</h2><p>Configure optional revenue modules for <b>{projectName}</b>. All settings are stored in the local project workspace.</p></div>
      <div className="monetization-agent"><label htmlFor="monetization-token">Local Agent pairing token</label><input id="monetization-token" type="password" autoComplete="off" value={token} onChange={(event) => { setToken(event.target.value); setConnected(false); }} placeholder="Paste your paired token"/><button className="button primary" disabled={!token.trim() || busy} onClick={() => void connect()}>Connect local project</button></div>
    </header>
    <div className="monetization-status"><span className={connected ? "ide-led online" : "ide-led"}/>{message}</div>
    <div className="monetization-grid">
      {ADDONS.map((addon) => <article className="monetization-card" key={addon.id}>
        <div className="monetization-card-top"><span className="monetization-icon">{addon.id === "analytics" ? "⌁" : addon.id === "rewarded_ads" ? "▣" : addon.id === "in_app_purchases" ? "◇" : "✦"}</span><label className="monetization-switch"><input type="checkbox" checked={Boolean(manifest.addons[addon.id])} disabled={!connected} onChange={(event) => toggleAddon(addon.id, event.target.checked)}/><span/></label></div>
        <h3>{addon.name}</h3><p>{addon.description}</p><small>{addon.status}</small>
      </article>)}
    </div>
    <section className="monetization-panel">
      <div className="monetization-panel-heading"><div><small>AD CONFIGURATION</small><h3>Rewarded and display placements</h3><p>Consent is mandatory. Test mode stays enabled by default.</p></div><label className="monetization-switch"><input type="checkbox" checked={manifest.ads.test_mode} disabled={!connected || !manifest.addons.rewarded_ads} onChange={(event) => setManifest((current) => ({ ...current, ads: { ...current.ads, test_mode: event.target.checked } }))}/><span/></label></div>
      <label className="monetization-field">Provider<select value={manifest.ads.provider} disabled={!connected || !manifest.addons.rewarded_ads} onChange={(event) => setManifest((current) => ({ ...current, ads: { ...current.ads, provider: event.target.value as "none" | "admob" } }))}><option value="none">Not connected</option><option value="admob">Google AdMob (SDK integration required)</option></select></label>
      <div className="monetization-form-grid"><label className="monetization-field">AdMob app ID<input value={manifest.ads.app_id} disabled={!connected || manifest.ads.provider !== "admob"} onChange={(event) => setManifest((current) => ({ ...current, ads: { ...current.ads, app_id: event.target.value } }))} placeholder="ca-app-pub-…~…"/></label><label className="monetization-field">Android ad unit ID<input value={manifest.ads.android_unit_id} disabled={!connected || manifest.ads.provider !== "admob"} onChange={(event) => setManifest((current) => ({ ...current, ads: { ...current.ads, android_unit_id: event.target.value } }))} placeholder="ca-app-pub-…/…"/></label><label className="monetization-field">iOS ad unit ID<input value={manifest.ads.ios_unit_id} disabled={!connected || manifest.ads.provider !== "admob"} onChange={(event) => setManifest((current) => ({ ...current, ads: { ...current.ads, ios_unit_id: event.target.value } }))} placeholder="Optional · future iOS support"/></label></div>
      <div className="placement-list">{PLACEMENTS.map((placement) => <label className="placement-row" key={placement.id}><span><b>{placement.label}</b><small>{placement.detail}</small></span><input type="checkbox" checked={manifest.ads.placements.includes(placement.id)} disabled={!connected || manifest.ads.provider !== "admob" || !manifest.addons.rewarded_ads} onChange={(event) => togglePlacement(placement.id, event.target.checked)}/></label>)}</div>
      <div className="monetization-consent"><b>Privacy and user consent are enforced in the configuration.</b><span>Consent required · Test mode default · No ads over active gameplay</span></div>
      <button className="button primary" disabled={!connected || busy} onClick={() => void save()}>{busy ? "Saving…" : "Save monetization settings"}</button>
    </section>
    <section className="monetization-disclaimer"><b>Integration status</b><p>This phase adds validated, project-local configuration. It does not claim to serve live ads, process purchases, or pay out revenue. AdMob and store billing require their respective SDKs, platform accounts, policy review and end-to-end device tests before production release.</p></section>
  </section>;
}
