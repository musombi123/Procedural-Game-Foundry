import hashlib
from pathlib import Path
from fastapi import UploadFile

class UploadRejected(ValueError):
    pass

PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
VIDEO_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-matroska": ".mkv", "video/webm": ".webm", "video/x-msvideo": ".avi"}
PHOTO_LIMIT = 20 * 1024 * 1024
VIDEO_LIMIT = 8 * 1024 * 1024 * 1024


def _signature_ok(kind: str, content_type: str, head: bytes) -> bool:
    if kind == "photo":
        return ((content_type == "image/jpeg" and head.startswith(bytes.fromhex("ffd8ff"))) or
                (content_type == "image/png" and head.startswith(bytes.fromhex("89504e470d0a1a0a"))) or
                (content_type == "image/webp" and head.startswith(b"RIFF") and head[8:12] == b"WEBP"))
    if content_type in ("video/mp4", "video/quicktime"):
        return len(head) >= 12 and head[4:8] == b"ftyp"
    if content_type in ("video/x-matroska", "video/webm"):
        return head.startswith(bytes.fromhex("1a45dfa3"))
    if content_type == "video/x-msvideo":
        return head.startswith(b"RIFF") and head[8:12] == b"AVI "
    return False

async def store_upload(upload: UploadFile, kind: str, destination: Path, max_bytes: int | None = None) -> dict:
    allowed = PHOTO_TYPES if kind == "photo" else VIDEO_TYPES
    limit = PHOTO_LIMIT if kind == "photo" else VIDEO_LIMIT
    if max_bytes is not None:
        limit = min(limit, max_bytes)
    content_type = (upload.content_type or "").lower()
    if content_type not in allowed:
        raise UploadRejected(f"Unsupported {kind} content type")
    destination.mkdir(parents=True, exist_ok=True)
    suffix = allowed[content_type]
    final_path = destination / ("player-portrait" + suffix if kind == "photo" else "source-movie" + suffix)
    temporary = final_path.with_suffix(final_path.suffix + ".uploading")
    digest = hashlib.sha256()
    total = 0
    first = b""
    try:
        with temporary.open("wb") as stream:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                if not first:
                    first = chunk[:32]
                    if not _signature_ok(kind, content_type, first):
                        raise UploadRejected("File signature does not match its declared media type")
                total += len(chunk)
                if total > limit:
                    raise UploadRejected(f"{kind.capitalize()} exceeds the {limit // (1024 * 1024)} MB upload limit")
                digest.update(chunk)
                stream.write(chunk)
        if total == 0:
            raise UploadRejected("Uploaded file is empty")
        temporary.replace(final_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"filename": final_path.name, "content_type": content_type, "size_bytes": total,
            "sha256": digest.hexdigest(), "storage_key": str(final_path.relative_to(destination.parent))}
