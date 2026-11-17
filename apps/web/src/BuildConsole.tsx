import { useCallback, useEffect, useMemo, useState } from "react";

type Props = { api: string; projectId: string; projectName: string };
type ToolState = { available: boolean; path?: string | null };
type ToolReport = {
  godot: ToolState; java: ToolState; android_sdk: ToolState; adb: ToolState;
  apksigner: ToolState; aapt: ToolState; android_export_templates: boolean;
  android_export_template_version?: string | null; android_export_template_path?: string | null;
  missing_android_templates?: string[];
  android_sdk_components?: { available: boolean; missing: string[] };
  godot_android_settings_configured?: boolean; godot_android_settings_auto_configure?: boolean;
};
type Device = { serial: string; state: string; model?: string; product?: string };
type BuildEntry = {
  id: string; created_at: string; app_name: string; package_id: string;
  version_name: string; version_code: number; output_format: "apk" | "aab";
  build_type: "debug" | "release"; size: number; sha256: string; signature_verified: boolean;
};
type Job = { id: string; state: string; progress: number; message: string; error?: string | null; result?: Record<string, any> | null };
type PermissionName = "internet" | "access_network_state" | "camera" | "record_audio" | "access_coarse_location" | "access_fine_location" | "vibrate" | "wake_lock";

const permissionLabels: Record<PermissionName, string> = {
  internet: "Internet", access_network_state: "Network state", camera: "Camera",
  record_audio: "Microphone", access_coarse_location: "Approximate location",
  access_fine_location: "Precise location", vibrate: "Vibration", wake_lock: "Keep screen awake",
};
const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

async function callApi<T>(api: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(api + path, {
    ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await response.json().catch(() => ({})) as Record<string, any>;
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : body.detail ? JSON.stringify(body.detail) : "Request failed (" + response.status + ")");
  return body as T;
}
function humanSize(bytes: number): string {
  if (!bytes) return "—";
  return bytes < 1048576 ? Math.round(bytes / 1024) + " KB" : (bytes / 1048576).toFixed(1) + " MB";
}

export default function BuildConsole({ api, projectId, projectName }: Props) {
  const projectPath = "/api/projects/" + encodeURIComponent(projectId);
  const [tools, setTools] = useState<ToolReport | null>(null);
  const [builds, setBuilds] = useState<BuildEntry[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [device, setDevice] = useState("");
  const [buildId, setBuildId] = useState("");
  const [runId, setRunId] = useState("");
  const [runLog, setRunLog] = useState("");
  const [deviceLog, setDeviceLog] = useState("");
  const [status, setStatus] = useState("Checking desktop toolchain…");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [report, setReport] = useState<Record<string, any> | null>(null);

  const [appName, setAppName] = useState(projectName || "My Game");
  const [packageId, setPackageId] = useState("com.nexora.mygame");
  const [versionName, setVersionName] = useState("1.0.0");
  const [versionCode, setVersionCode] = useState(1);
  const [format, setFormat] = useState<"apk" | "aab">("apk");
  const [buildType, setBuildType] = useState<"debug" | "release">("debug");
  const [orientation, setOrientation] = useState<"landscape" | "portrait" | "sensor">("landscape");
  const [iconPath, setIconPath] = useState("");
  const [iconName, setIconName] = useState("");
  const [iconUploading, setIconUploading] = useState(false);
  const [minSdk, setMinSdk] = useState(23);
  const [targetSdk, setTargetSdk] = useState(35);
  const [arm64, setArm64] = useState(true);
  const [arm32, setArm32] = useState(false);
  const [permissions, setPermissions] = useState<Record<PermissionName, boolean>>({
    internet: true, access_network_state: true, camera: false, record_audio: false,
    access_coarse_location: false, access_fine_location: false, vibrate: false, wake_lock: false,
  });
  const [keystorePath, setKeystorePath] = useState("");
  const [keyAlias, setKeyAlias] = useState("");
  const [keyPassword, setKeyPassword] = useState("");
  const [wirelessHost, setWirelessHost] = useState("");
  const [wirelessPairPort, setWirelessPairPort] = useState(37123);
  const [wirelessConnectPort, setWirelessConnectPort] = useState(5555);
  const [pairingCode, setPairingCode] = useState("");

  const selectedBuild = useMemo(() => builds.find((item) => item.id === buildId) ?? builds[0] ?? null, [builds, buildId]);
  const readyDevices = devices.filter((item) => item.state === "device");

  const refreshTools = useCallback(async () => {
    const result = await callApi<ToolReport>(api, "/api/local/build-tools");
    setTools(result);
    return result;
  }, [api]);
  const refreshBuilds = useCallback(async () => {
    const result = await callApi<{ builds: BuildEntry[] }>(api, projectPath + "/builds");
    setBuilds(result.builds ?? []);
    setBuildId((current) => current || result.builds?.[0]?.id || "");
  }, [api, projectPath]);
  const refreshDevices = useCallback(async () => {
    const result = await callApi<{ devices: Device[] }>(api, "/api/local/android/devices");
    setDevices(result.devices ?? []);
    setDevice((current) => current && result.devices?.some((item) => item.serial === current && item.state === "device")
      ? current : result.devices?.find((item) => item.state === "device")?.serial ?? "");
  }, [api]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const [toolResult, buildResult] = await Promise.all([
          callApi<ToolReport>(api, "/api/local/build-tools"),
          callApi<{ builds: BuildEntry[] }>(api, projectPath + "/builds"),
        ]);
        if (cancelled) return;
        setTools(toolResult); setBuilds(buildResult.builds ?? []);
        setBuildId(buildResult.builds?.[0]?.id ?? "");
        setStatus("Desktop build environment inspected.");
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Build environment check failed.");
          setStatus("Desktop build API is unavailable.");
        }
      }
      try {
        const result = await callApi<{ devices: Device[] }>(api, "/api/local/android/devices");
        if (!cancelled) {
          setDevices(result.devices ?? []);
          setDevice(result.devices?.find((item) => item.state === "device")?.serial ?? "");
        }
      } catch { if (!cancelled) setDevices([]); }
    }
    void load();
    return () => { cancelled = true; };
  }, [api, projectPath]);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const current = await callApi<{ running: boolean; exit_code: number | null; log: string }>(
          api, projectPath + "/runs/" + encodeURIComponent(runId)
        );
        if (cancelled) return;
        setRunLog(current.log);
        if (!current.running) { setStatus("Godot process exited with code " + (current.exit_code ?? "unknown") + "."); setRunId(""); }
      } catch (reason) {
        if (!cancelled) setRunLog(reason instanceof Error ? reason.message : "Runtime log unavailable.");
      }
    }, 1200);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [api, projectPath, runId]);

  async function uploadIcon(file: File) {
    setIconUploading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(api + projectPath + "/android-icon", { method: "POST", body: form });
      const body = await response.json().catch(() => ({})) as Record<string, any>;
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Launcher icon upload failed.");
      setIconPath(String(body.icon_path));
      setIconName(file.name);
      setStatus("Launcher icon uploaded · " + body.width + "×" + body.height + " PNG");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not upload the launcher icon.");
      setIconPath("");
      setIconName("");
    } finally {
      setIconUploading(false);
    }
  }

  async function pollJob(jobId: string): Promise<Job> {
    for (let attempt = 0; attempt < 1800; attempt += 1) {
      await wait(1000);
      const current = await callApi<Job>(api, "/api/jobs/" + encodeURIComponent(jobId));
      setJob(current);
      setStatus(current.progress + "% · " + current.message);
      if (current.state === "COMPLETED") return current;
      if (current.state === "FAILED") throw new Error(current.error || current.message || "Task failed.");
    }
    throw new Error("The build is still running. Check the job state in this console.");
  }

  async function runTest() {
    setBusy(true); setError(""); setReport(null); setJob(null);
    try {
      const queued = await callApi<Job>(api, projectPath + "/runtime-test", { method: "POST", body: "{}" });
      const finished = await pollJob(queued.id);
      setReport(finished.result ?? null);
      setStatus("Godot runtime validation completed.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Runtime test failed.");
      setStatus("Runtime test failed.");
    } finally { setBusy(false); }
  }

  async function launch(mode: "run" | "debug" | "profile" | "editor") {
    setError("");
    try {
      const result = await callApi<{ run_id: string; process_id: number }>(api, projectPath + "/runs", {
        method: "POST", body: JSON.stringify({ mode }),
      });
      setRunId(result.run_id); setRunLog("");
      setStatus("Godot " + mode + " started · PID " + result.process_id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Godot launch failed."); }
  }

  async function stopRun() {
    if (!runId) return;
    try {
      await callApi(api, projectPath + "/runs/" + encodeURIComponent(runId) + "/stop", { method: "POST", body: "{}" });
      setRunId(""); setStatus("Godot runtime stopped.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not stop runtime."); }
  }

  async function buildAndroid() {
    setBusy(true); setError(""); setJob(null);
    try {
      if (format === "aab" && buildType !== "release") throw new Error("AAB output requires Release signing.");
      if (buildType === "release" && (!keystorePath.trim() || !keyAlias.trim() || !keyPassword)) {
        throw new Error("Release builds require a keystore path, key alias and password.");
      }
      const payload = {
        app_name: appName, package_id: packageId, version_name: versionName, version_code: versionCode,
        output_format: format, build_type: buildType, orientation, icon_path: iconPath.trim() || null,
        min_sdk: minSdk, target_sdk: targetSdk, arm64, arm32, permissions,
        ...(buildType === "release" ? { signing: { keystore_path: keystorePath, key_alias: keyAlias, key_password: keyPassword } } : {}),
      };
      const queued = await callApi<Job>(api, projectPath + "/android-build", { method: "POST", body: JSON.stringify(payload) });
      const finished = await pollJob(queued.id);
      const record = finished.result?.build as BuildEntry | undefined;
      if (record) setBuildId(record.id);
      await refreshBuilds();
      setStatus(format.toUpperCase() + " generated and signature-verified.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Android export failed.");
      setStatus("Android export failed; inspect the build error.");
    } finally {
      setBusy(false);
      setKeyPassword("");
    }
  }

  async function installBuild() {
    if (!selectedBuild || !device) return;
    setError("");
    try {
      const result = await callApi<{ output: string }>(api, projectPath + "/builds/" + encodeURIComponent(selectedBuild.id) + "/install", {
        method: "POST", body: JSON.stringify({ serial: device }),
      });
      setDeviceLog(result.output); setStatus("APK installed on the selected phone.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "APK installation failed."); }
  }

  async function launchBuild() {
    if (!selectedBuild || !device) return;
    setError("");
    try {
      const result = await callApi<{ output: string }>(api, projectPath + "/builds/" + encodeURIComponent(selectedBuild.id) + "/launch", {
        method: "POST", body: JSON.stringify({ serial: device }),
      });
      setDeviceLog(result.output); setStatus("Android launch command sent.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "App launch failed."); }
  }

  async function readLogcat() {
    if (!device) return;
    setError("");
    try {
      const result = await callApi<{ lines: string[] }>(api, "/api/local/android/logs?serial=" + encodeURIComponent(device) + "&lines=800");
      setDeviceLog(result.lines.join("\n")); setStatus("ADB logcat refreshed.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not retrieve device logs."); }
  }

  async function wireless(pair: boolean) {
    setError("");
    try {
      const payload = { host: wirelessHost.trim(), port: pair ? wirelessPairPort : wirelessConnectPort, ...(pair ? { pairing_code: pairingCode } : {}) };
      await callApi(api, pair ? "/api/local/android/pair" : "/api/local/android/connect", {
        method: "POST", body: JSON.stringify(payload),
      });
      setPairingCode("");
      await refreshDevices();
      setStatus(pair ? "ADB pairing sent; refresh the device list to verify it." : "ADB wireless connection requested.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Wireless ADB failed."); }
  }

  const toolRows = tools ? [
    ["Godot 4", tools.godot], ["Java / JDK", tools.java], ["Android SDK", tools.android_sdk],
    ["ADB", tools.adb], ["apksigner", tools.apksigner], ["aapt", tools.aapt],
    ["Android SDK packages", { available: Boolean(tools.android_sdk_components?.available), path: tools.android_sdk_components?.available ? "Required SDK components installed" : "Missing: " + (tools.android_sdk_components?.missing ?? []).join(", ") }],
    ["Godot Android paths", { available: Boolean(tools.godot_android_settings_configured || tools.godot_android_settings_auto_configure), path: tools.godot_android_settings_configured ? "Configured in EditorSettings" : "NEXORA will configure SDK/JDK paths before export" }],
  ] as const : [];
  const canBuild = Boolean(
    tools?.godot.available && tools?.java.available && tools?.android_sdk.available
    && tools?.apksigner.available && tools?.aapt.available && tools?.android_export_templates
  );
  const selected = selectedBuild ?? null;

  return <section className="build-console">
    <div className="build-console-heading">
      <div><span className="eyebrow">NEXORA · DESKTOP PRODUCTION</span><h2>Build Console</h2>
        <p>Test, debug, profile, export and install real games from this desktop workstation.</p></div>
      <button className="button secondary" onClick={() => {
        void refreshTools().catch((reason) => setError(String(reason)));
        void refreshBuilds().catch((reason) => setError(String(reason)));
        void refreshDevices().catch(() => setDevices([]));
      }}>↻ Refresh</button>
    </div>
    <div className="build-status-line"><span className="status-led" />{status}</div>
    {error && <div className="build-error" role="alert">{error}</div>}

    <section className="build-panel">
      <div className="build-panel-title"><div><small>01 · TEST / DEBUG / PROFILE</small><h3>{projectName}</h3>
        <p>Run the assembled Godot project locally, inspect logs and open the generated source in Godot.</p></div>
        <span className={runId ? "build-pill live" : "build-pill"}>{runId ? "SESSION ACTIVE" : "IDLE"}</span>
      </div>
      <div className="build-tools-grid">
        {toolRows.map(([label, item]) => <div className="build-tool" key={label}>
          <span className={item.available ? "tool-dot ready" : "tool-dot"} />
          <div><b>{label}</b><small>{item.available ? item.path || "Available" : "Not detected"}</small></div>
          <strong>{item.available ? "READY" : "MISSING"}</strong>
        </div>)}
        {tools && <div className="build-tool">
          <span className={tools.android_export_templates ? "tool-dot ready" : "tool-dot"} />
          <div><b>Godot Android templates</b><small>Desktop export templates</small></div>
          <strong>{tools.android_export_templates ? "READY" : "CHECK"}</strong>
        </div>}
      </div>
      <div className="build-action-row">
        <button className="button primary" disabled={busy || !tools?.godot.available} onClick={() => void runTest()}>{busy ? "Working…" : "Validate & FPS test"}</button>
        <button className="button secondary" disabled={!tools?.godot.available} onClick={() => void launch("run")}>▶ Run game</button>
        <button className="button secondary" disabled={!tools?.godot.available} onClick={() => void launch("debug")}>Debug run</button>
        <button className="button secondary" disabled={!tools?.godot.available} onClick={() => void launch("profile")}>GPU / FPS profile</button>
        <button className="button secondary" disabled={!tools?.godot.available} onClick={() => void launch("editor")}>Open Godot editor</button>
        {runId && <button className="button danger" onClick={() => void stopRun()}>Stop process</button>}
      </div>
      {job && <div className="build-progress"><div><b>{job.message}</b><span>{job.progress}%</span></div>
        <div className="progress-track"><span style={{ width: job.progress + "%" }} /></div></div>}
      {report && <div className="runtime-report">
        <div className="report-metric"><b>{report.metrics?.average_fps ?? "—"}</b><small>Average sampled FPS</small></div>
        <div className="report-metric"><b>{report.metrics?.minimum_fps ?? "—"}</b><small>Minimum sampled FPS</small></div>
        <div className="report-metric"><b>{report.metrics?.fps_sample_count ?? 0}</b><small>FPS samples</small></div>
        <div className="report-metric"><b>{report.passed ? "PASS" : "REVIEW"}</b><small>Runtime smoke test</small></div>
      </div>}
      <div className="build-log-title"><b>Godot runtime output</b><span>{runId ? "Live process log" : "No active session"}</span></div>
      <pre className="build-log">{runLog || "Start Run, Debug or GPU / FPS profile to stream the local Godot process output here."}</pre>
      <p className="build-note">Use the Godot editor to correct script or scene issues, then rerun validation. Headless FPS is a regression signal; GPU profiling must be reviewed on the target desktop hardware.</p>
    </section>

    <section className="build-panel">
      <div className="build-panel-title"><div><small>02 · ANDROID BUILD SETTINGS</small><h3>Configure package identity and export</h3>
        <p>Godot, Android SDK and Gradle compile the game on this desktop.</p></div><span className="build-pill">LOCAL TOOLCHAIN</span></div>
      <div className="build-form-grid">
        <label>App name<input value={appName} onChange={(event) => setAppName(event.target.value)} maxLength={64} /></label>
        <label>Package ID<input value={packageId} onChange={(event) => setPackageId(event.target.value)} placeholder="com.studio.mygame" /></label>
        <label>Version name<input value={versionName} onChange={(event) => setVersionName(event.target.value)} /></label>
        <label>Version code<input type="number" min={1} value={versionCode} onChange={(event) => setVersionCode(Number(event.target.value))} /></label>
        <label>Output format<select value={format} onChange={(event) => setFormat(event.target.value as "apk" | "aab")}>
          <option value="apk">APK · install and test</option><option value="aab">AAB · Play Store release</option></select></label>
        <label>Signing profile<select value={buildType} onChange={(event) => setBuildType(event.target.value as "debug" | "release")}>
          <option value="debug">Debug · local test key</option><option value="release">Release · your keystore</option></select></label>
        <label>Orientation<select value={orientation} onChange={(event) => setOrientation(event.target.value as "landscape" | "portrait" | "sensor")}>
          <option value="landscape">Landscape</option><option value="portrait">Portrait</option><option value="sensor">Sensor auto-rotate</option></select></label>
        <label>Launcher icon · PNG (432×432 minimum)
          <input type="file" accept="image/png,.png" disabled={iconUploading || busy} onChange={(event) => {
            const selectedFile = event.target.files?.[0];
            if (selectedFile) void uploadIcon(selectedFile);
            event.currentTarget.value = "";
          }} />
          <small>{iconUploading ? "Uploading icon…" : iconName ? "Uploaded: " + iconName : "Choose a square PNG. The adaptive foreground must be at least 432×432."}</small>
        </label>
        <label>Minimum SDK<input type="number" min={23} max={35} value={minSdk} onChange={(event) => setMinSdk(Number(event.target.value))} /></label>
        <label>Target SDK<input type="number" min={28} max={36} value={targetSdk} onChange={(event) => setTargetSdk(Number(event.target.value))} /></label>
      </div>
      <div className="build-subsection"><b>CPU architectures</b><div className="build-checks">
        <label><input type="checkbox" checked={arm64} onChange={(event) => setArm64(event.target.checked)} /> ARM64 (recommended)</label>
        <label><input type="checkbox" checked={arm32} onChange={(event) => setArm32(event.target.checked)} /> ARMv7 (older phones)</label>
      </div></div>
      <div className="build-subsection"><b>Android permissions</b><div className="build-permission-grid">
        {(Object.keys(permissionLabels) as PermissionName[]).map((key) => <label key={key}>
          <input type="checkbox" checked={permissions[key]} onChange={(event) => setPermissions((current) => ({ ...current, [key]: event.target.checked }))} />
          {permissionLabels[key]}
        </label>)}
      </div></div>
      {buildType === "release" && <div className="build-signing">
        <b>Release keystore</b><p>Keystore credentials are sent only to the local desktop API for this build. They are not stored in release history.</p>
        <div className="build-form-grid">
          <label>Keystore file path<input value={keystorePath} onChange={(event) => setKeystorePath(event.target.value)} /></label>
          <label>Key alias<input value={keyAlias} onChange={(event) => setKeyAlias(event.target.value)} /></label>
          <label>Key password<input type="password" autoComplete="new-password" value={keyPassword} onChange={(event) => setKeyPassword(event.target.value)} /></label>
        </div>
      </div>}
      {tools && !tools.android_export_templates && <p className="build-error">Matching Godot Android export templates are missing{tools.android_export_template_version ? " for Godot " + tools.android_export_template_version : ""}. Install the templates for this exact editor version, then refresh the environment.</p>}
      {format === "aab" && <p className="build-note">AAB uses Godot's Gradle Android export. NEXORA installs the per-project Gradle template before building. Build an APK separately when you need direct installation on a phone.</p>}
      <div className="build-action-row">
        <button className="button primary" disabled={busy || !canBuild || !appName.trim() || !packageId.trim() || (!arm64 && !arm32)} onClick={() => void buildAndroid()}>
          {busy ? "Building…" : "Generate " + format.toUpperCase()}
        </button>
        <button className="button secondary" onClick={() => void refreshTools().catch((reason) => setError(String(reason)))}>Recheck toolchain</button>
      </div>
      <p className="build-note">Release distribution requires your own non-debug keystore. Back it up securely and never commit it to Git.</p>
    </section>

    <section className="build-panel">
      <div className="build-panel-title"><div><small>03 · CONNECTED DEVICES</small><h3>Install and test on Android</h3>
        <p>USB or wireless ADB runs from the desktop, not the hosted build worker.</p></div><span className="build-pill">{readyDevices.length} ready</span></div>
      <div className="device-toolbar">
        <button className="button secondary" onClick={() => void refreshDevices().catch((reason) => setError(String(reason)))}>Refresh devices</button>
        <label>Android device<select value={device} onChange={(event) => setDevice(event.target.value)}>
          <option value="">Choose authorized phone</option>
          {devices.map((item) => <option key={item.serial} value={item.serial}>{item.model || item.serial} · {item.state}</option>)}
        </select></label>
      </div>
      <div className="wireless-row">
        <label>Phone IP address<input value={wirelessHost} onChange={(event) => setWirelessHost(event.target.value)} placeholder="192.168.1.25" /></label>
        <label>Pairing port<input type="number" min={1} max={65535} value={wirelessPairPort} onChange={(event) => setWirelessPairPort(Number(event.target.value))} /></label>
        <label>6-digit pairing code<input value={pairingCode} onChange={(event) => setPairingCode(event.target.value)} maxLength={6} /></label>
        <label>Connection port<input type="number" min={1} max={65535} value={wirelessConnectPort} onChange={(event) => setWirelessConnectPort(Number(event.target.value))} /></label>
        <div className="wireless-actions">
          <button className="button secondary" disabled={!wirelessHost.trim() || pairingCode.length !== 6} onClick={() => void wireless(true)}>Pair</button>
          <button className="button secondary" disabled={!wirelessHost.trim()} onClick={() => void wireless(false)}>Connect</button>
        </div>
      </div>
      <p className="build-note">USB: enable Developer options and USB debugging, connect and approve the RSA prompt. Wireless: use Android Wireless debugging; pair with its pairing port/code, then connect using the separate connection port.</p>
      <label className="build-select">Build artifact<select value={buildId} onChange={(event) => setBuildId(event.target.value)}>
        <option value="">Choose a retained package</option>
        {builds.map((item) => <option key={item.id} value={item.id}>{item.app_name} · {item.version_name} · {item.output_format.toUpperCase()}</option>)}
      </select></label>
      {selected && <p className="artifact-meta">{selected.package_id} · {selected.output_format.toUpperCase()} · {humanSize(selected.size)} · SHA-256 {selected.sha256.slice(0, 18)}…</p>}
      <div className="build-action-row">
        <button className="button primary" disabled={!selected || selected.output_format !== "apk" || !device} onClick={() => void installBuild()}>Install APK</button>
        <button className="button secondary" disabled={!selected || selected.output_format !== "apk" || !device} onClick={() => void launchBuild()}>Launch game</button>
        <button className="button secondary" disabled={!device} onClick={() => void readLogcat()}>Read logcat</button>
        {selected && <a className="button secondary" href={api + projectPath + "/builds/" + encodeURIComponent(selected.id) + "/download"} target="_blank" rel="noreferrer">Download</a>}
      </div>
      <div className="build-log-title"><b>Android device output</b><span>{device || "No phone selected"}</span></div>
      <pre className="build-log">{deviceLog || "Install the APK, launch the game and read logcat to inspect Android-side errors."}</pre>
    </section>

    <section className="build-panel">
      <div className="build-panel-title"><div><small>04 · RELEASE VAULT</small><h3>Build history</h3>
        <p>Successful packages remain in this local project with metadata and SHA-256 checksums.</p></div><span className="build-pill">{builds.length} saved</span></div>
      <div className="release-list">
        {builds.map((item) => <div className="release-row" key={item.id}>
          <div className="release-icon">{item.output_format.toUpperCase()}</div>
          <div className="release-info"><b>{item.app_name} · {item.version_name} ({item.version_code})</b>
            <small>{item.package_id} · {new Date(item.created_at).toLocaleString()}</small>
            <small>{item.build_type.toUpperCase()} · {humanSize(item.size)} · SHA-256 {item.sha256.slice(0, 20)}…</small></div>
          <span className={item.signature_verified ? "build-pill live" : "build-pill"}>{item.signature_verified ? "VERIFIED" : "CHECK"}</span>
          <a className="button secondary" href={api + projectPath + "/builds/" + encodeURIComponent(item.id) + "/download"} target="_blank" rel="noreferrer">Download</a>
        </div>)}
        {!builds.length && <p className="empty-state">No Android builds have been generated for this project.</p>}
      </div>
    </section>
  </section>;
}
