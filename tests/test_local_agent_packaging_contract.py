from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_installer_is_a_per_user_background_install():
    installer = (ROOT / "packaging" / "nexora-local-agent.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in installer
    assert "{userstartup}" in installer
    assert "runhidden nowait" in installer
    assert "NEXORA.LocalAgent.exe" in installer
    assert "Python" not in installer


def test_windows_installer_registers_hidden_logon_task_with_crash_recovery():
    installer = (ROOT / "packaging" / "nexora-local-agent.iss").read_text(encoding="utf-8")
    task = (ROOT / "packaging" / "NEXORA-Local-Agent-Task.xml").read_text(encoding="utf-8")
    assert "RegisterManagedAgentTask" in installer
    assert "schtasks.exe" in installer
    assert "__AGENT_PATH__" in task
    assert 'Source: "NEXORA-Local-Agent-Task.xml"; Flags: dontcopy' in installer
    assert "ExtractTemporaryFile('NEXORA-Local-Agent-Task.xml')" in installer
    assert "LoadStringsFromFile" in installer
    assert "Utf8Encode(TaskTemplate)" in installer
    assert '/Delete /TN ""NEXORA Local Agent"" /F' in installer
    assert "<LogonTrigger>" in task
    assert "<LogonType>InteractiveToken</LogonType>" in task
    assert "<RestartOnFailure>" in task
    assert "<Interval>PT1M</Interval>" in task
    assert "<Count>999</Count>" in task
    assert "<RunLevel>LeastPrivilege</RunLevel>" in task


def test_frozen_agent_entrypoint_owns_runtime_paths_and_single_instance():
    entry = (ROOT / "scripts" / "nexora_local_agent_entry.py").read_text(encoding="utf-8")
    assert "LOCALAPPDATA" in entry
    assert "NEXORA_LOCAL_AGENT_DATA" in entry
    assert "PGF_DATA_DIR" in entry
    assert "NEXORA.LocalAgent.Singleton.v1" in entry
    assert 'host="127.0.0.1"' in entry
    assert "RotatingFileHandler" in entry


def test_packaging_workflow_builds_and_publishes_windows_installer():
    workflow = (ROOT / ".github" / "workflows" / "nexora-local-agent-windows.yml").read_text(encoding="utf-8")
    assert "windows-latest" in workflow
    assert "package-nexora-local-agent.ps1" in workflow
    assert "Inno Setup" in workflow
    assert "NEXORA-Local-Agent-Setup.exe" in workflow
    assert "softprops/action-gh-release" in workflow


def test_windows_workflow_runs_real_install_health_task_and_uninstall_smoke_test():
    workflow = (ROOT / ".github" / "workflows" / "nexora-local-agent-windows.yml").read_text(encoding="utf-8")
    assert "Smoke-test Windows install, health, auto-restart task and uninstall" in workflow
    assert "127.0.0.1:8765/health" in workflow
    assert "<RestartOnFailure>" in workflow
    assert "Uninstall left the NEXORA scheduled task registered." in workflow
    assert "Uninstall unexpectedly removed the user's Foundry project data." in workflow


def test_public_releases_require_authenticode_signing():
    workflow = (ROOT / ".github" / "workflows" / "nexora-local-agent-windows.yml").read_text(encoding="utf-8")
    assert "NEXORA_WINDOWS_SIGNING_CERT_BASE64" in workflow
    assert "NEXORA_WINDOWS_SIGNING_CERT_PASSWORD" in workflow
    assert "Require a signing certificate for public releases" in workflow
    assert "Authenticode verification" in workflow
    assert "refs/tags/local-agent-v" in workflow


def test_user_setup_documentation_does_not_request_terminal_commands_or_pairing_pin():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## NEXORA production execution model", 1)[1].split("## Quick start", 1)[0]
    assert "one-click windows installer" in section.lower()
    assert "8-digit" not in section.lower()
    assert "open powershell" in section.lower()
    assert "```powershell" not in section.lower()
    assert "git clone" not in section.lower()
    assert "github.com/musombi123/Procedural-Game-Foundry/releases/latest" in section
