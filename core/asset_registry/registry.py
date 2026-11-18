from pathlib import Path
import hashlib,json

class AssetRegistry:
    """Local asset manifest registry. It records provenance; it does not infer licenses."""
    def __init__(self,root: Path): self.root=root.resolve(); self.root.mkdir(parents=True,exist_ok=True)
    def register(self,asset_id: str,relative_path: str,kind: str,license_name: str,source: str="local",author: str="",metadata: dict|None=None) -> dict:
        candidate=(self.root/relative_path).resolve()
        if self.root not in candidate.parents or not candidate.is_file(): raise ValueError("Asset path must reference a file inside the library")
        if not asset_id.strip() or not license_name.strip(): raise ValueError("asset_id and explicit license are required")
        checksum=hashlib.sha256(candidate.read_bytes()).hexdigest()
        item={"asset_id":asset_id,"kind":kind,"path":relative_path,"source":source,"author":author,"license":license_name,"checksum":checksum,"metadata":metadata or {}}
        index=self.root/"assets.json"; data=json.loads(index.read_text()) if index.exists() else {"assets":[]}
        if any(x["asset_id"]==asset_id for x in data["assets"]): raise ValueError("Duplicate asset_id")
        data["assets"].append(item); index.write_text(json.dumps(data,indent=2),encoding="utf-8")
        return item
    def list(self) -> list[dict]:
        index=self.root/"assets.json"
        return json.loads(index.read_text(encoding="utf-8"))["assets"] if index.exists() else []
