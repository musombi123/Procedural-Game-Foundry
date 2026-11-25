# PyInstaller specification for the NEXORA Windows Local Agent.
from pathlib import Path
from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
datas = []
binaries = []
hiddenimports = []

# FastAPI and Foundry use some dynamically imported submodules. Collecting
# these packages explicitly keeps the frozen executable independent of a
# system-wide Python installation.
for package in (
    "fastapi",
    "starlette",
    "uvicorn",
    "pydantic",
    "multipart",
    "psycopg",
    "keyring",
    "services",
    "core",
    "generators",
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        # Optional runtime integrations are detected and reported by the
        # agent; an unavailable optional package must not block packaging.
        try:
            hiddenimports += collect_submodules(package)
        except Exception:
            pass

# Foundry templates and procedural assets are runtime resources rather than
# Python modules, so include them beside the frozen application.
for folder in ("blender", "runtime", "libraries", "gameplay", "simulation"):
    source = ROOT / folder
    if source.is_dir():
        datas += Tree(str(source), prefix=folder)

a = Analysis(
    [str(ROOT / "scripts" / "nexora_local_agent_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "IPython", "matplotlib", "pytest", "tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NEXORA.LocalAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="NEXORA.LocalAgent",
)
