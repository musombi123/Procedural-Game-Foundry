import { useCallback, useEffect, useMemo, useState } from "react";

type Entry = { name: string; path: string; kind: "directory" | "file"; size_bytes: number; editable: boolean };
type OpenFile = { path: string; content: string; sha256: string; size_bytes: number };
const LOCAL_AGENT = (import.meta.env.VITE_NEXORA_LOCAL_AGENT ?? "http://127.0.0.1:8765").replace(/\/$/, "") + "/engine";

export default function InternalIDE({ projectId, projectName }: { projectId: string; projectName: string }) {
  const [token, setToken] = useState("");
  const [connected, setConnected] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [directory, setDirectory] = useState("game");
  const [file, setFile] = useState<OpenFile | null>(null);
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState("");
  const [newPath, setNewPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Connect to the paired Local Agent to edit this project's source files.");
  const dirty = Boolean(file && draft !== file.content);
  const headers = useMemo(() => ({ Authorization: "Bearer " + token }), [token]);

  const request = useCallback(async (path: string, init: RequestInit = {}) => {
    const response = await fetch(LOCAL_AGENT + path, { ...init, headers: { ...headers, ...(init.headers ?? {}) } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail ?? "Local Agent request failed (" + response.status + ")");
    return body;
  }, [headers]);

  const loadDirectory = useCallback(async (nextDirectory: string) => {
    if (!token.trim()) { setMessage("Enter your Local Agent pairing token first."); return; }
    setBusy(true);
    try {
      const result = await request("/api/v1/desktop/projects/" + encodeURIComponent(projectId) + "/files?path=" + encodeURIComponent(nextDirectory));
      setEntries(result.entries ?? []);
      setDirectory(nextDirectory);
      setConnected(true);
      setMessage("Connected · " + (result.entries ?? []).length + " entries in " + (nextDirectory || "project root"));
    } catch (error) {
      setConnected(false);
      setMessage(error instanceof Error ? error.message : "Could not load the project directory.");
    } finally { setBusy(false); }
  }, [projectId, request, token]);

  async function openFile(path: string) {
    if (dirty && !window.confirm("Discard unsaved changes and open another file?")) return;
    setBusy(true);
    try {
      const result = await request("/api/v1/desktop/projects/" + encodeURIComponent(projectId) + "/file?path=" + encodeURIComponent(path));
      const opened = result as OpenFile;
      setFile(opened); setDraft(opened.content);
      setMessage("Opened " + path + " · " + opened.size_bytes.toLocaleString() + " bytes");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not open this file.");
    } finally { setBusy(false); }
  }

  async function saveFile() {
    if (!file || !dirty) return;
    setBusy(true);
    try {
      const result = await request("/api/v1/desktop/projects/" + encodeURIComponent(projectId) + "/file", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: file.path, content: draft, expected_sha256: file.sha256 }),
      });
      setFile({ ...file, content: draft, sha256: result.sha256, size_bytes: result.size_bytes });
      setMessage("Saved " + file.path + " · local project updated");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Save failed. Reload the file before retrying.");
    } finally { setBusy(false); }
  }

  async function createFile() {
    const path = newPath.trim();
    if (!path) return;
    setBusy(true);
    try {
      await request("/api/v1/desktop/projects/" + encodeURIComponent(projectId) + "/file", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path, content: "" }),
      });
      setNewPath("");
      const slash = path.lastIndexOf("/");
      await loadDirectory(slash >= 0 ? path.slice(0, slash) : "");
      await openFile(path);
      setMessage("Created local source file " + path);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create the source file.");
    } finally { setBusy(false); }
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault(); void saveFile();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const visibleEntries = entries.filter((entry) => entry.name.toLowerCase().includes(filter.toLowerCase()));
  const parentDirectory = directory.includes("/") ? directory.slice(0, directory.lastIndexOf("/")) : "";

  return <section className="ide-shell">
    <header className="ide-header">
      <div><small>NEXORA INTERNAL IDE · LOCAL-FIRST</small><h2>{projectName}</h2><p>Source files stay on this computer. Saves use file-version checks to prevent silent overwrites.</p></div>
      <div className="ide-connect"><label htmlFor="ide-token">Local Agent token</label><input id="ide-token" type="password" autoComplete="off" value={token} onChange={(event) => { setToken(event.target.value); setConnected(false); }} placeholder="Paste paired Local Agent token"/><button className="button primary" disabled={!token.trim() || busy} onClick={() => void loadDirectory("game")}>Connect</button></div>
    </header>
    <div className="ide-status"><span className={connected ? "ide-led online" : "ide-led"}/>{message}</div>
    <div className="ide-workbench">
      <aside className="ide-files">
        <div className="ide-pane-title"><b>EXPLORER</b><button disabled={!connected || busy} onClick={() => void loadDirectory(directory)}>↻</button></div>
        <div className="ide-breadcrumb"><button onClick={() => void loadDirectory("")}>PROJECT</button><span>/</span><button onClick={() => void loadDirectory("game")}>GAME</button>{directory !== "game" && <><span>/</span><span>{directory}</span></>}</div>
        <input className="ide-filter" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter files…"/>
        {directory && <button className="ide-entry directory" onClick={() => void loadDirectory(parentDirectory)}>↰ ..</button>}
        <div className="ide-entry-list">
          {visibleEntries.map((entry) => <button key={entry.path} className={"ide-entry " + (file?.path === entry.path ? "active" : "")} disabled={!connected || busy} onClick={() => entry.kind === "directory" ? void loadDirectory(entry.path) : entry.editable ? void openFile(entry.path) : setMessage("This file is binary or outside the supported text editor formats.")}>
            <span>{entry.kind === "directory" ? "▸" : entry.editable ? "◇" : "▧"}</span><span>{entry.name}</span><small>{entry.kind === "directory" ? "" : entry.editable ? "TEXT" : "BINARY"}</small>
          </button>)}
          {connected && !visibleEntries.length && <p className="ide-empty">No matching files in this folder.</p>}
        </div>
        <div className="ide-new-file"><label htmlFor="ide-new-path">New source file</label><input id="ide-new-path" value={newPath} onChange={(event) => setNewPath(event.target.value)} placeholder="game/scripts/player.gd"/><button className="button secondary full-width" disabled={!connected || busy || !newPath.trim()} onClick={() => void createFile()}>＋ Create file</button></div>
      </aside>
      <section className="ide-editor">
        <div className="ide-pane-title"><b>{file ? file.path : "NO FILE OPEN"}</b><div><span>{dirty ? "UNSAVED" : file ? "SAVED" : "READY"}</span><button className="button primary" disabled={!file || !dirty || busy} onClick={() => void saveFile()}>Save · Ctrl S</button></div></div>
        {file ? <><div className="ide-editor-meta"><span>{file.path.split(".").pop()?.toUpperCase()} · UTF-8</span><span>{new Blob([draft]).size.toLocaleString()} bytes · 2 MiB limit</span></div><textarea className="ide-code" spellCheck={false} autoCapitalize="off" autoCorrect="off" value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="Source code editor"/></> : <div className="ide-placeholder"><span>⌘</span><b>Open a source file</b><p>Choose a text file in the explorer or create a new source file. The editor reads and writes directly to the paired computer's project folder.</p></div>}
      </section>
    </div>
    <footer className="ide-footer"><span>LOCAL FILE SYSTEM · NO CLOUD SOURCE UPLOAD</span><span>{connected ? "AGENT CONNECTED" : "NOT CONNECTED"}</span></footer>
  </section>;
}
