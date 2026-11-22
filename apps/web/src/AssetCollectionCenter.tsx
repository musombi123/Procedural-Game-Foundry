import { useCallback, useEffect, useMemo, useState } from "react";
import AvatarPreview from "./AvatarPreview";

type Asset = {
  id: string; filename: string; content_type: string; size: number;
  created_at: string; status: string; kind: string; license?: string;
  sha256?: string | null; metadata?: Record<string, unknown>; origin?: string;
};
type Props = { projectId: string; api: string };
type Filter = "all" | "character" | "environment" | "prop" | "audio" | "animation" | "texture" | "other";
const categories: { id: Filter; label: string }[] = [
  { id: "all", label: "All assets" }, { id: "character", label: "Characters" },
  { id: "environment", label: "Environments" }, { id: "prop", label: "Props" },
  { id: "audio", label: "Audio" }, { id: "animation", label: "Animation" },
  { id: "texture", label: "Textures" }, { id: "other", label: "Other" }
];
const fileUrl = (api: string, pid: string, id: string) =>
  api + "/api/v1/workspace/projects/" + encodeURIComponent(pid) + "/assets/" + encodeURIComponent(id) + "/file";
const humanSize = (bytes: number) => bytes < 1024 * 1024
  ? Math.max(1, Math.round(bytes / 1024)) + " KB"
  : (bytes / (1024 * 1024)).toFixed(1) + " MB";

export default function AssetCollectionCenter({ projectId, api }: Props) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [usedIds, setUsedIds] = useState<string[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Asset | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("Generated assets and uploaded assets will appear here.");
  const [kind, setKind] = useState("character");
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");

  const refresh = useCallback(async () => {
    setBusy(true); setError("");
    try {
      const [assetResponse, worldResponse] = await Promise.all([
        fetch(api + "/api/v1/workspace/projects/" + encodeURIComponent(projectId) + "/assets"),
        fetch(api + "/api/projects/" + encodeURIComponent(projectId) + "/world")
      ]);
      if (!assetResponse.ok) {
        const body = await assetResponse.json().catch(() => ({}));
        throw new Error(body.detail || "Asset collection returned HTTP " + assetResponse.status);
      }
      const payload = await assetResponse.json() as { assets?: Asset[] };
      setAssets(Array.isArray(payload.assets) ? payload.assets : []);
      if (worldResponse.ok) {
        const world = await worldResponse.json();
        const ids = (world.objects ?? []).map((item: { model_asset_id?: string }) => item.model_asset_id).filter(Boolean);
        setUsedIds(ids);
      } else setUsedIds([]);
      setNotice("Asset collection refreshed · " + (payload.assets?.length ?? 0) + " available asset(s).");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load project assets.");
      setNotice("Asset scan failed. Check the local Foundry connection, then re-scan.");
    } finally { setBusy(false); }
  }, [api, projectId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const visible = useMemo(() => assets.filter((asset) => {
    const text = (asset.filename + " " + asset.kind + " " + (asset.license ?? "")).toLowerCase();
    if (query.trim() && !text.includes(query.trim().toLowerCase())) return false;
    const type = asset.content_type.toLowerCase();
    if (filter === "audio") return type.startsWith("audio/") || ["wav", "ogg", "mp3"].includes(String(asset.metadata?.format ?? "").toLowerCase());
    if (filter === "texture") return type.startsWith("image/") || ["png", "jpg", "jpeg", "webp"].includes(String(asset.metadata?.format ?? "").toLowerCase());
    if (filter === "other") return !["character", "environment", "prop", "animation"].includes(asset.kind) && !type.startsWith("audio/") && !type.startsWith("image/");
    return filter === "all" || asset.kind === filter;
  }), [assets, filter, query]);

  async function upload(file?: File) {
    if (!file) return;
    setBusy(true); setError("");
    try {
      const data = new FormData();
      data.append("file", file);
      data.append("kind", kind);
      data.append("license_name", "Creator confirms usage rights");
      data.append("source", "creator-upload");
      const response = await fetch(api + "/api/v1/workspace/projects/" + encodeURIComponent(projectId) + "/assets", { method: "POST", body: data });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail?.message || body.detail || "Upload failed with HTTP " + response.status);
      setNotice("Uploaded " + file.name + " and registered it in the project library.");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Asset upload failed.");
    } finally { setBusy(false); }
  }

  async function remove(asset: Asset) {
    if (asset.origin === "movie-pipeline") return;
    if (!window.confirm("Delete " + asset.filename + " from this project?")) return;
    setBusy(true);
    try {
      const response = await fetch(api + "/api/v1/workspace/projects/" + encodeURIComponent(projectId) + "/assets/" + encodeURIComponent(asset.id), { method: "DELETE" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "Asset deletion failed.");
      if (selected?.id === asset.id) setSelected(null);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Asset deletion failed.");
    } finally { setBusy(false); }
  }

  const selectedUrl = selected ? fileUrl(api, projectId, selected.id) : "";
  const selectedType = selected?.content_type.toLowerCase() ?? "";
  return <section data-tour="asset-center" style={{ marginTop: 22, padding: 18, border: "1px solid #2c4564", borderRadius: 14, background: "#0b1422", color: "#e7eefb" }}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
      <div><small style={{ color: "#8da9d2", letterSpacing: 1.4 }}>NEXORA STUDIO PRO · PROJECT LIBRARY</small><h2 style={{ margin: "6px 0", fontSize: 21 }}>Asset Collection Center</h2><p style={{ margin: 0, color: "#91a2bd", fontSize: 12 }}>One project library for generated characters, worlds, props, animation, textures and audio.</p></div>
      <div style={{ display: "flex", gap: 7 }}><button type="button" aria-pressed={viewMode === "grid"} onClick={() => setViewMode("grid")} style={{ padding: "9px 11px", border: "1px solid #3a5476", borderRadius: 8, background: viewMode === "grid" ? "#263f62" : "#101b2b", color: "#dce9ff" }}>Grid</button><button type="button" aria-pressed={viewMode === "list"} onClick={() => setViewMode("list")} style={{ padding: "9px 11px", border: "1px solid #3a5476", borderRadius: 8, background: viewMode === "list" ? "#263f62" : "#101b2b", color: "#dce9ff" }}>List</button><button disabled={busy} onClick={() => void refresh()} style={{ padding: "9px 13px", border: "1px solid #3a5476", borderRadius: 8, background: "#172943", color: "#dce9ff" }}>{busy ? "Scanning…" : "↻ Re-scan assets"}</button></div>
    </div>
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 15 }}>
      <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search assets…" aria-label="Search assets" style={{ flex: "1 1 180px", minWidth: 140, padding: 10, border: "1px solid #344a67", borderRadius: 8, background: "#101d30", color: "#edf4ff" }} />
      <select value={kind} onChange={e => setKind(e.target.value)} aria-label="Upload asset category" style={{ padding: 10, border: "1px solid #344a67", borderRadius: 8, background: "#101d30", color: "#edf4ff" }}>
        <option value="character">Character</option><option value="environment">Environment</option><option value="prop">Prop</option><option value="animation">Animation / audio</option><option value="dependency">Texture / dependency</option><option value="model">3D model</option>
      </select>
      <label style={{ padding: "10px 13px", borderRadius: 8, background: "#80a9f2", color: "#091426", fontWeight: 800, fontSize: 12, cursor: busy ? "not-allowed" : "pointer", opacity: busy ? .5 : 1 }}>
        + Add asset <input type="file" accept=".glb,.gltf,.bin,.png,.jpg,.jpeg,.webp,.wav,.ogg,.mp3" disabled={busy} onChange={e => { void upload(e.target.files?.[0]); e.currentTarget.value = ""; }} style={{ display: "none" }} />
      </label>
    </div>
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "13px 0" }}>
      {categories.map(item => <button key={item.id} onClick={() => setFilter(item.id)} style={{ padding: "7px 10px", border: "1px solid " + (filter === item.id ? "#79a8fa" : "#2c405b"), borderRadius: 20, background: filter === item.id ? "#1a3153" : "#101b2b", color: filter === item.id ? "#e7f0ff" : "#9eafc8", fontSize: 10 }}>{item.label}</button>)}
    </div>
    {error && <p role="alert" style={{ color: "#ff9b9b", fontSize: 12 }}>{error}</p>}
    <p aria-live="polite" style={{ color: "#8fa5c6", fontSize: 11 }}>{notice}</p>
    <div style={viewMode === "grid" ? { display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(175px,1fr))", gap: 10 } : { display: "grid", gridTemplateColumns: "1fr", gap: 7 }}>
      {visible.map(asset => <article key={asset.id} style={{ display: viewMode === "list" ? "grid" : "block", gridTemplateColumns: viewMode === "list" ? "minmax(0,1fr) auto" : undefined, alignItems: "center", minWidth: 0, padding: 11, border: "1px solid " + (selected?.id === asset.id ? "#78a8fa" : "#293c57"), borderRadius: 10, background: selected?.id === asset.id ? "#162943" : "#101a29" }}>
        <button onClick={() => setSelected(asset)} style={{ width: "100%", border: 0, padding: 0, background: "transparent", color: "inherit", textAlign: "left" }}>
          <div style={{ height: 76, display: "grid", placeItems: "center", borderRadius: 7, background: "#0a1320", color: "#91b5f4", fontSize: 28 }}>{asset.content_type.startsWith("image/") ? "▧" : asset.content_type.startsWith("audio/") ? "♫" : asset.content_type.includes("gltf") || asset.filename.endsWith(".glb") ? "◇" : "▤"}</div>
          <b style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 9, fontSize: 11 }}>{asset.filename}</b>
          <small style={{ display: "block", color: "#91a2bb", marginTop: 5, fontSize: 9 }}>{asset.kind} · {humanSize(asset.size)}{asset.metadata?.stage ? " · " + String(asset.metadata.stage) : ""}</small>
        </button>
        <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 8 }}>
          <span style={{ fontSize: 9, color: "#8ed2aa" }}>{asset.status}</span>
          {usedIds.includes(asset.id) && <span style={{ fontSize: 9, color: "#f0ca82" }}>Used in level</span>}
          {asset.origin === "movie-pipeline" && <span style={{ fontSize: 9, color: "#9db9f6" }}>Generated</span>}
        </div>
      </article>)}
      {!visible.length && <div style={{ gridColumn: "1/-1", padding: 22, border: "1px dashed #354a66", borderRadius: 10, color: "#9aabc4", fontSize: 12 }}>{assets.length ? "No assets match this search or filter." : "No registered assets found yet. Generate a character or environment, or add a local asset."}</div>}
    </div>
    {selected && <div style={{ marginTop: 16, padding: 13, border: "1px solid #314967", borderRadius: 10, background: "#0e1a2a" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <div><b style={{ fontSize: 12 }}>{selected.filename}</b><p style={{ margin: "4px 0", color: "#8fa3c0", fontSize: 10 }}>{selected.license || "Generated locally"} · {selected.content_type}</p></div>
        <div style={{ display: "flex", gap: 8 }}><a href={selectedUrl} target="_blank" rel="noreferrer" style={{ color: "#9bc1ff", fontSize: 11 }}>Open / download</a>{selected.origin !== "movie-pipeline" && <button disabled={busy} onClick={() => void remove(selected)} style={{ border: "1px solid #69414b", borderRadius: 6, background: "#2b1b27", color: "#ffb5bd", padding: "5px 8px", fontSize: 10 }}>Delete</button>}</div>
      </div>
      {selectedType.includes("gltf") || [".glb", ".gltf"].some(ext => selected.filename.toLowerCase().endsWith(ext))
        ? <AvatarPreview src={selectedUrl} />
        : selectedType.startsWith("image/")
          ? <img src={selectedUrl} alt={selected.filename} style={{ maxWidth: "100%", maxHeight: 320, objectFit: "contain", borderRadius: 8 }} />
          : selectedType.startsWith("audio/")
            ? <audio controls preload="metadata" src={selectedUrl} style={{ width: "100%" }} />
            : <p style={{ color: "#9aabc4", fontSize: 11 }}>Preview is not available for this file type. Use Open / download to inspect it.</p>}
    </div>}
  </section>;
}
