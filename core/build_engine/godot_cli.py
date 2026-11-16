from pathlib import Path
import shutil,subprocess
def executable(): return shutil.which("godot") or shutil.which("godot4")
def headless_check(project: Path) -> dict:
    exe=executable()
    if not exe: return {"available":False,"success":False,"message":"Godot 4 not found on PATH"}
    result=subprocess.run([exe,"--headless","--path",str(project),"--editor","--quit"],capture_output=True,text=True,timeout=120)
    return {"available":True,"success":result.returncode==0,"returncode":result.returncode,"stdout":result.stdout[-6000:],"stderr":result.stderr[-6000:]}
