"""NEXORA Creator Workflow: episode planning, workload policy, asset conversion,
review-gated movie-to-game stages and Pochi payment reconciliation.

Heavy ML inference is delegated to an optional isolated TripoSR GPU worker.
The rest of the pipeline uses Blender, FFmpeg and Godot already present in PGF.
"""
from __future__ import annotations

import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.asset_registry.gltf_validator import validate_gltf
from core.asset_registry.registry import AssetRegistry
from core.movie_pipeline.models import RightsDeclaration, StageId, StageState, new_pipeline
from core.movie_pipeline.service import PipelineError, PipelineStore
from core.movie_pipeline.story import StoryBrief
from core.movie_pipeline.procedural_world import build_world_spec
from core.orchestration.jobs import Job, JobState
from core.project_engine.models import WorldDocument
from core.build_engine.godot_cli import executable as godot_executable

PLANS: dict[str, dict[str, Any]] = {
    "basic": {
        "id":"basic","name":"Basic","video_limit_seconds":30,"target_class":"mobile",
        "allowed_platforms":["android","web"],"max_episodes":1,"max_enemies":3,
        "max_vehicles":1,"max_workload_units":12,"max_world_scale":"small",
        "max_video_bytes":256*1024*1024,
    },
    "standard": {
        "id":"standard","name":"Standard","video_limit_seconds":120,"target_class":"mobile",
        "allowed_platforms":["android","web"],"max_episodes":3,"max_enemies":6,
        "max_vehicles":2,"max_workload_units":28,"max_world_scale":"medium",
        "max_video_bytes":1024*1024*1024,
    },
    "pro": {
        "id":"pro","name":"Pro","video_limit_seconds":300,"target_class":"pc",
        "allowed_platforms":["windows","linux","web"],"max_episodes":5,"max_enemies":12,
        "max_vehicles":4,"max_workload_units":80,"max_world_scale":"large",
        "max_video_bytes":4*1024*1024*1024,
    },
    "studio": {
        "id":"studio","name":"Studio","video_limit_seconds":600,"target_class":"pc",
        "allowed_platforms":["windows","linux","web"],"max_episodes":12,"max_enemies":24,
        "max_vehicles":8,"max_workload_units":160,"max_world_scale":"large",
        "max_video_bytes":8*1024*1024*1024,
    },
}
SCALE_UNITS = {"small":2,"medium":5,"large":10}
SCALE_RANK = {"small":1,"medium":2,"large":3}
PACKS: dict[str, dict[str, Any]] = {
    "sci_fi_survival": {
        "id":"sci_fi_survival","name":"Sci-Fi Survival","genre":"science-fiction","world_scale":"medium",
        "environment":["sci_fi_outpost","heavy_door","signal_beacon","rock_formation"],
        "enemies":["robot","npc"],"vehicles":["scout_buggy"],
        "description":"Outpost, perimeter, beacons, hostile patrols and utility transport","palette":{"terrain":[0.10,0.16,0.19],"stone":[0.20,0.27,0.31],"wood":[0.24,0.31,0.37],"foliage":[0.16,0.30,0.22],"road":[0.13,0.18,0.22],"accent":[0.14,0.67,0.78]},"architecture":"sci_fi",
    },
    "urban_action": {
        "id":"urban_action","name":"Urban Action","genre":"modern","world_scale":"medium",
        "environment":["sci_fi_outpost","heavy_door","sci_fi_crate"],
        "enemies":["npc"],"vehicles":["street_car","armored_car"],
        "description":"Street blocks, service buildings, hostile units and road vehicles","palette":{"terrain":[0.13,0.14,0.16],"stone":[0.37,0.39,0.42],"wood":[0.24,0.27,0.31],"foliage":[0.10,0.25,0.13],"road":[0.06,0.07,0.08],"accent":[0.88,0.55,0.18]},"architecture":"urban",
    },
    "fantasy_frontier": {
        "id":"fantasy_frontier","name":"Fantasy Frontier","genre":"fantasy","world_scale":"large",
        "environment":["alien_tree","rock_formation","signal_beacon"],
        "enemies":["animal","npc"],"vehicles":[],
        "description":"Woodland paths, rock formations, creature encounters and landmarks","palette":{"terrain":[0.12,0.24,0.12],"stone":[0.34,0.35,0.30],"wood":[0.30,0.18,0.09],"foliage":[0.07,0.32,0.12],"road":[0.23,0.18,0.12],"accent":[0.71,0.69,0.38]},"architecture":"fantasy",
    },
    "wilderness_expedition": {
        "id":"wilderness_expedition","name":"Wilderness Expedition","genre":"adventure","world_scale":"large",
        "environment":["alien_tree","rock_formation","sci_fi_crate"],
        "enemies":["animal"],"vehicles":["scout_buggy"],
        "description":"Terrain, forests, cliffs, field equipment and expedition vehicles","palette":{"terrain":[0.18,0.27,0.16],"stone":[0.37,0.38,0.34],"wood":[0.30,0.20,0.11],"foliage":[0.09,0.28,0.11],"road":[0.26,0.24,0.18],"accent":[0.76,0.48,0.17]},"architecture":"wilderness",
    },
}
IMAGE_EXTENSIONS = {".png",".jpg",".jpeg",".webp"}
MODEL_EXTENSIONS = {".glb",".gltf",".obj",".fbx",".ply"}
VIDEO_EXTENSIONS = {".mp4",".mov",".mkv",".webm",".avi"}

class EpisodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    title: str = Field(min_length=1,max_length=100)
    synopsis: str = Field(default="",max_length=1500)
    location: str = Field(default="",max_length=160)
    player_goal: str = Field(default="",max_length=500)
    events: list[str] = Field(default_factory=list,max_length=12)
    enemy_count: int = Field(default=2,ge=0,le=24)
    vehicle_count: int = Field(default=0,ge=0,le=8)
    estimated_minutes: int = Field(default=10,ge=1,le=240)

class CreatorWorkflowDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["story","movie"] = "story"
    plan: Literal["basic","standard","pro","studio"] = "basic"
    target_class: Literal["mobile","pc"] = "mobile"
    platform: Literal["android","windows","linux","web"] = "android"
    title: str = Field(min_length=1,max_length=120)
    genre: Literal["science-fiction","fantasy","modern","survival","adventure"] = "science-fiction"
    world_pack: str = "sci_fi_survival"
    world_scale: Literal["small","medium","large"] = "small"
    visual_style: str = Field(default="cinematic stylized realism",max_length=120)
    player_source: Literal["default","consented_portrait"] = "default"
    enemies: int = Field(default=2,ge=0,le=24)
    vehicles: int = Field(default=0,ge=0,le=8)
    environment_variants: int = Field(default=1,ge=1,le=8)
    episodes: list[EpisodeSpec] = Field(min_length=1,max_length=12)
    synopsis: str = Field(default="",max_length=12000)
    copyright_declaration: Literal["original","licensed","public_domain"] = "original"
    has_adaptation_rights: bool = False
    has_music_rights: bool = False
    has_performer_consents: bool = False
    avoids_performer_likeness: bool = False
    created_at: str = Field(default_factory=lambda:datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda:datetime.now(timezone.utc).isoformat())

    @model_validator(mode="after")
    def unique_episode_ids(self):
        ids=[item.id for item in self.episodes]
        if len(ids)!=len(set(ids)): raise ValueError("Episode IDs must be unique.")
        return self

class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: Literal["basic","standard","pro","studio"]
    project_id: str | None = None
    payer_phone: str = Field(min_length=9,max_length=16,pattern=r"^\\+?[0-9]{9,15}$")

class PaymentClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mpesa_receipt: str = Field(min_length=8,max_length=24,pattern=r"^[A-Za-z0-9]+$")
    paid_amount_kes: int = Field(ge=1,le=250000)
    payer_phone: str = Field(min_length=9,max_length=16,pattern=r"^[+0-9]+$")

def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _workflow_path(folder: Path) -> Path:
    return folder / "creator-workflow.json"

def _load_workflow(folder: Path) -> CreatorWorkflowDocument:
    path=_workflow_path(folder)
    if not path.is_file(): raise HTTPException(404,"Create a Creator Flow plan before using these tools.")
    try: return CreatorWorkflowDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc: raise HTTPException(500,"Creator Flow document is invalid.") from exc

def _save_workflow(folder: Path, document: CreatorWorkflowDocument) -> CreatorWorkflowDocument:
    document.updated_at=_utc()
    path=_workflow_path(folder); tmp=path.with_suffix(".json.tmp")
    tmp.write_text(document.model_dump_json(indent=2),encoding="utf-8"); tmp.replace(path)
    return document

def _workload(document: CreatorWorkflowDocument) -> dict[str, Any]:
    episode_units=len(document.episodes)*2
    world_units=SCALE_UNITS[document.world_scale]*document.environment_variants
    enemy_units=document.enemies
    vehicle_units=document.vehicles*2
    mission_units=sum(max(1,len(episode.events)) for episode in document.episodes)
    total=episode_units+world_units+enemy_units+vehicle_units+mission_units
    return {"units":total,"breakdown":{"episodes":episode_units,"world_and_variants":world_units,"enemies":enemy_units,"vehicles":vehicle_units,"gameplay_events":mission_units}}

def _validate_plan(document: CreatorWorkflowDocument) -> dict[str, Any]:
    plan=PLANS[document.plan]
    if document.target_class != plan["target_class"]:
        raise HTTPException(422,f'{plan["name"]} is restricted to {plan["target_class"].upper()} game targets.')
    if document.platform not in plan["allowed_platforms"]:
        raise HTTPException(422,f'{plan["name"]} does not include the {document.platform} export target.')
    if len(document.episodes)>plan["max_episodes"]:
        raise HTTPException(422,f'{plan["name"]} allows up to {plan["max_episodes"]} episodes.')
    if document.enemies>plan["max_enemies"]:
        raise HTTPException(422,f'{plan["name"]} allows up to {plan["max_enemies"]} enemies.')
    if document.vehicles>plan["max_vehicles"]:
        raise HTTPException(422,f'{plan["name"]} allows up to {plan["max_vehicles"]} vehicles.')
    if SCALE_RANK[document.world_scale]>SCALE_RANK[plan["max_world_scale"]]:
        raise HTTPException(422,f'{plan["name"]} does not support a {document.world_scale} environment.')
    workload=_workload(document)
    if workload["units"]>plan["max_workload_units"]:
        raise HTTPException(422,f'Estimated workload is {workload["units"]} units; {plan["name"]} allows {plan["max_workload_units"]}. Upgrade the plan or reduce environment scale, episodes or actors.')
    return {"plan":plan["id"],"target_class":document.target_class,"max_video_seconds":plan["video_limit_seconds"],"workload":workload,"capacity":plan["max_workload_units"]}

def _database_url() -> str:
    return os.environ.get("NEXORA_DATABASE_URL", "").strip()

def _pochi_merchant_number() -> str:
    """NEXORA's configured Pochi la Biashara collection destination.

    The merchant mobile number is public checkout information, not a secret.
    Keep it server-configurable so production can override it without a code
    change; never put Daraja credentials or payment verification secrets here.
    """
    raw = os.environ.get("NEXORA_POCHI_MERCHANT_NUMBER", "0742466828").strip()
    digits = re.sub(r"[^0-9]", "", raw)
    if digits.startswith("0") and len(digits) == 10:
        return digits
    if digits.startswith("254") and len(digits) == 12:
        return "0" + digits[3:]
    return ""

def _connect():
    url=_database_url()
    if not url: return None
    try:
        import psycopg
        return psycopg.connect(url,autocommit=True)
    except ImportError as exc:
        raise HTTPException(503,"PostgreSQL driver is missing on the billing service.") from exc
    except Exception as exc:
        raise HTTPException(503,"NEXORA billing database is unavailable.") from exc

def _ensure_billing_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS nexora_creator_payments (
          payment_id TEXT PRIMARY KEY, reference TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL,
          project_id TEXT, plan TEXT NOT NULL, amount_kes INTEGER NOT NULL,
          currency TEXT NOT NULL DEFAULT 'KES', status TEXT NOT NULL DEFAULT 'pending',
          payer_phone TEXT NOT NULL, receipt_code TEXT UNIQUE, paid_amount_kes INTEGER,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), claimed_at TIMESTAMPTZ, verified_at TIMESTAMPTZ
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS nexora_creator_entitlements (
          user_id TEXT PRIMARY KEY, plan TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
          target_class TEXT NOT NULL, expires_at TIMESTAMPTZ, payment_reference TEXT NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)

def _price_map() -> dict[str,int]:
    raw=os.environ.get("NEXORA_PLAN_PRICES_KES","")
    if not raw: return {}
    try: values=json.loads(raw)
    except json.JSONDecodeError as exc: raise HTTPException(503,"NEXORA_PLAN_PRICES_KES must be valid JSON.") from exc
    return {key:int(values[key]) for key in PLANS if key in values and int(values[key])>0}

def _payments_dir(manager: Any) -> Path:
    root=Path(os.environ.get("NEXORA_COMMERCE_DIR",str(manager.root.parent/"nexora-commerce"))).resolve()
    root.mkdir(parents=True,exist_ok=True)
    return root

def _json_payments(manager: Any) -> Path:
    if os.environ.get("RENDER") or os.environ.get("NEXORA_ENV","").lower()=="production":
        raise HTTPException(503,"Configure NEXORA_DATABASE_URL (Neon PostgreSQL) before enabling paid Creator Flow plans.")
    return _payments_dir(manager)/"payments.json"

def _find_payment(manager: Any, payment_id: str) -> dict | None:
    conn=_connect()
    if conn:
        _ensure_billing_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT payment_id,reference,user_id,project_id,plan,amount_kes,status,payer_phone,receipt_code,paid_amount_kes,created_at,claimed_at,verified_at FROM nexora_creator_payments WHERE payment_id=%s",(payment_id,))
            row=cur.fetchone()
        conn.close()
        if not row: return None
        keys=["payment_id","reference","user_id","project_id","plan","amount_kes","status","payer_phone","receipt_code","paid_amount_kes","created_at","claimed_at","verified_at"]
        return dict(zip(keys,[value.isoformat() if hasattr(value,"isoformat") else value for value in row]))
    path=_json_payments(manager)
    data=json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"payments":[]}
    return next((item for item in data["payments"] if item["payment_id"]==payment_id),None)

def _save_payment(manager: Any, record: dict, *, create: bool=False) -> dict:
    conn=_connect()
    if conn:
        _ensure_billing_schema(conn)
        with conn.cursor() as cur:
            if create:
                cur.execute("""INSERT INTO nexora_creator_payments(payment_id,reference,user_id,project_id,plan,amount_kes,payer_phone,status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,'pending')""",(record["payment_id"],record["reference"],record["user_id"],record.get("project_id"),record["plan"],record["amount_kes"],record["payer_phone"]))
            else:
                cur.execute("""UPDATE nexora_creator_payments SET status=%s,receipt_code=%s,paid_amount_kes=%s,claimed_at=NOW(),verified_at=CASE WHEN %s='verified' THEN NOW() ELSE verified_at END WHERE payment_id=%s""",(record["status"],record.get("receipt_code"),record.get("paid_amount_kes"),record["status"],record["payment_id"]))
        conn.close()
        return record
    path=_json_payments(manager)
    data=json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"payments":[]}
    if create:
        data["payments"].append(record)
    else:
        for index,item in enumerate(data["payments"]):
            if item["payment_id"]==record["payment_id"]: data["payments"][index]=record; break
    tmp=path.with_suffix(".json.tmp"); tmp.write_text(json.dumps(data,indent=2),encoding="utf-8"); tmp.replace(path)
    return record

def _activate_entitlement(manager: Any, user_id: str, plan_id: str, reference: str) -> None:
    plan=PLANS[plan_id]
    conn=_connect()
    if conn:
        _ensure_billing_schema(conn)
        days=max(1,min(365,int(os.environ.get("NEXORA_PLAN_PERIOD_DAYS","30"))))
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO nexora_creator_entitlements(user_id,plan,status,target_class,expires_at,payment_reference,updated_at)
            VALUES(%s,%s,'active',%s,NOW()+(%s * INTERVAL '1 day'),%s,NOW())
            ON CONFLICT(user_id) DO UPDATE SET plan=EXCLUDED.plan,status='active',target_class=EXCLUDED.target_class,
            expires_at=EXCLUDED.expires_at,payment_reference=EXCLUDED.payment_reference,updated_at=NOW()""",
            (user_id,plan_id,plan["target_class"],days,reference))
        conn.close()
        return
    path=_payments_dir(manager)/"entitlements.json"
    data=json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"entitlements":{}}
    days=max(1,min(365,int(os.environ.get("NEXORA_PLAN_PERIOD_DAYS","30"))))
    data["entitlements"][user_id]={"plan":plan_id,"status":"active","target_class":plan["target_class"],"payment_reference":reference,"updated_at":_utc(),"expires_at":(datetime.now(timezone.utc)+timedelta(days=days)).isoformat()}
    tmp=path.with_suffix(".json.tmp"); tmp.write_text(json.dumps(data,indent=2),encoding="utf-8"); tmp.replace(path)

def _get_entitlement(manager: Any, user_id: str) -> dict | None:
    # A local worker never receives Neon credentials. It asks the cloud
    # control plane to validate the short-lived account token captured during
    # device pairing; the token remains in the agent's process memory only.
    if os.environ.get("NEXORA_LOCAL_AGENT", "false").strip().lower() in {"1", "true", "yes"}:
        from urllib.error import HTTPError, URLError
        from urllib.parse import urlparse
        from urllib.request import Request as UrlRequest, urlopen
        from services.worker.local_security import get_cloud_access_token

        account_token = get_cloud_access_token(user_id)
        if not account_token:
            raise HTTPException(401, "The NEXORA account session is no longer paired. Sign in and pair this computer again.")
        cloud_base = os.environ.get("NEXORA_CLOUD_API_URL", "https://nexora-foundry-api.onrender.com").rstrip("/")
        parsed = urlparse(cloud_base)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise HTTPException(503, "NEXORA cloud entitlement checks require HTTPS.")
        request = UrlRequest(
            cloud_base + "/api/v1/creator-flow/plans",
            headers={"Authorization": "Bearer " + account_token, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read(512 * 1024).decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 401:
                raise HTTPException(401, "Your NEXORA account session expired. Sign in again and pair this computer.") from exc
            raise HTTPException(503, f"Could not verify your Creator Flow entitlement (HTTP {exc.code}).") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise HTTPException(503, "NEXORA could not verify your Creator Flow entitlement. Check your internet connection.") from exc
        return payload.get("active_entitlement") if isinstance(payload, dict) else None

    conn=_connect()
    if conn:
        _ensure_billing_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT plan,status,target_class,expires_at,payment_reference FROM nexora_creator_entitlements WHERE user_id=%s",(user_id,))
            row=cur.fetchone()
        conn.close()
        if not row: return None
        return {"plan":row[0],"status":row[1],"target_class":row[2],"expires_at":row[3].isoformat() if row[3] else None,"payment_reference":row[4]}
    if os.environ.get("RENDER") or os.environ.get("NEXORA_ENV","").lower()=="production":
        return None
    path=_payments_dir(manager)/"entitlements.json"
    if not path.is_file(): return None
    return json.loads(path.read_text(encoding="utf-8")).get("entitlements",{}).get(user_id)

def _assert_entitled(manager: Any, user_id: str, plan_id: str) -> dict:
    entitlement=_get_entitlement(manager,user_id)
    if not entitlement or entitlement.get("status")!="active":
        raise HTTPException(402,"Choose a Creator Flow plan and complete Pochi payment verification before starting paid generation.")
    if entitlement.get("expires_at") and datetime.fromisoformat(entitlement["expires_at"])<datetime.now(timezone.utc):
        raise HTTPException(402,"Your Creator Flow plan has expired. Renew to continue.")
    current=entitlement["plan"]
    order=list(PLANS).index(current)
    required=list(PLANS).index(plan_id)
    if order<required:
        raise HTTPException(402,f"Your active {PLANS[current]['name']} plan does not cover the {PLANS[plan_id]['name']} workload.")
    return entitlement

def _assert_project(folder: Path, request: Request, manager: Any) -> tuple[str,Any]:
    try: definition=manager.load(folder.name)
    except FileNotFoundError: raise HTTPException(404,"Project not found.")
    from core.nexora_workspace.api import _assert_owner
    owner=_assert_owner(folder,request)
    return owner,definition

def _pipeline(folder: Path):
    try: return PipelineStore(folder)
    except Exception as exc: raise HTTPException(500,"Could not open the movie-to-game pipeline.") from exc

def _ensure_pipeline(folder: Path, project_id: str, mode: str):
    store=_pipeline(folder)
    try: document=store.load()
    except FileNotFoundError:
        rights=RightsDeclaration(has_video_rights=False,has_photo_rights=False,likeness_consent=False,accepts_original_assets_only=True)
        document=store.save(new_pipeline(project_id,rights))
        if mode=="story":
            records={item.stage:item for item in document.stages}
            records[StageId.ANALYSIS].state=StageState.APPROVED
            records[StageId.ANALYSIS].summary="Skipped by creator: original story-first game, no source movie."
            records[StageId.PLAYER].state=StageState.READY
            document.active_stage=StageId.PLAYER
            store.save(document)
    return store,document

def _write_default_portrait(path: Path) -> None:
    """Create a neutral synthetic PNG reference portrait without a real likeness."""
    width=256; height=256
    rows=[]
    for y in range(height):
        row=bytearray([0])
        for x in range(width):
            r,g,b=(34,44,58)
            dx=(x-128)/56; dy=(y-92)/68
            if dx*dx+dy*dy<1: r,g,b=(152,112,88)
            if 66<x<190 and 31<y<79: r,g,b=(32,31,34)
            if 108<x<148 and 110<y<119: r,g,b=(245,242,234)
            if 84<x<172 and 120<y<128: r,g,b=(74,45,35)
            if 72<x<184 and 159<y<255: r,g,b=(38,78,112)
            row.extend((r,g,b))
        rows.append(bytes(row))
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    raw=zlib.compress(b"".join(rows),level=9)
    payload=b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,2,0,0,0))+chunk(b"IDAT",raw)+chunk(b"IEND",b"")
    path.write_bytes(payload)

def _run_player_build(folder: Path, store: PipelineStore, document: CreatorWorkflowDocument, use_portrait: bool) -> dict:
    pipeline=store.load()
    stage=next(item for item in pipeline.stages if item.stage==StageId.PLAYER)
    if stage.state!=StageState.READY: raise HTTPException(409,"Player stage is not READY.")
    if not (store.folder/"story.json").is_file():
        raise HTTPException(409,"Save the episode story before generating the player.")
    blender=shutil.which("blender")
    if not blender: raise HTTPException(503,"Blender is required for rigged player avatar generation.")
    out_dir=store.folder/"player"/f"revision-{stage.revision}"
    out_dir.mkdir(parents=True,exist_ok=True)
    portrait=store.folder/"uploads"/"player-portrait.png"
    if use_portrait:
        if not pipeline.source_photo: raise HTTPException(409,"Upload a portrait and grant likeness permission, or choose the generated default player.")
        if not (pipeline.rights.has_photo_rights and pipeline.rights.likeness_consent):
            raise HTTPException(403,"Player portrait rights and likeness consent are required.")
        portrait=(folder/pipeline.source_photo["storage_key"]).resolve()
    else:
        portrait=out_dir/"default-player-reference.png"
        _write_default_portrait(portrait)
    spec={"proportions":{"height":1.78,"shoulder_width":0.46,"hip_width":0.34,"leg_ratio":0.52,"build":1.0,"face_center_x":0.5,"face_top":0.035,"face_width":0.22,"face_height":0.16},
          "face_crop":{"center_x":0.5,"top":0.035,"width":0.22,"height":0.16},
          "identity_source":"creator_supplied_portrait" if use_portrait else "synthetic_default","creator_review_required":True}
    spec_path=out_dir/"avatar.json"; spec_path.write_text(json.dumps(spec,indent=2),encoding="utf-8")
    output=out_dir/"player-avatar.glb"
    stage.state=StageState.RUNNING; stage.summary="Building editable humanoid mesh, armature and idle/walk animation with Blender"; store.save(pipeline)
    script=Path(__file__).resolve().parents[2]/"blender"/"scripts"/"build_player_avatar.py"
    try:
        result=subprocess.run([blender,"--background","--python",str(script),"--","--portrait",str(portrait),"--output",str(output),"--spec",str(spec_path)],capture_output=True,text=True,timeout=900,check=True)
    except subprocess.TimeoutExpired as exc:
        current=store.load(); rec=next(item for item in current.stages if item.stage==StageId.PLAYER); rec.state=StageState.FAILED; rec.error="Player/avatar generation exceeded 15 minutes"; store.save(current); raise HTTPException(504,rec.error) from exc
    except subprocess.CalledProcessError as exc:
        current=store.load(); rec=next(item for item in current.stages if item.stage==StageId.PLAYER); rec.state=StageState.FAILED; rec.error=(exc.stderr or exc.stdout or "Blender avatar build failed")[-3000:]; store.save(current); raise HTTPException(500,"Player/avatar generation failed: "+rec.error) from exc
    if not output.is_file() or output.stat().st_size<1024:
        current=store.load(); rec=next(item for item in current.stages if item.stage==StageId.PLAYER); rec.state=StageState.FAILED; rec.error="Blender did not create a valid player-avatar.glb"; store.save(current); raise HTTPException(500,rec.error)
    reviewed=store.mark_review(StageId.PLAYER,{"glb_scene":str(output.relative_to(folder)),"spec":str(spec_path.relative_to(folder)),"glb_bytes":output.stat().st_size,"identity_source":spec["identity_source"],"rigged":True,"animations":["PGF_Idle","PGF_Walk"],"requires_creator_review":True},"Rigged player avatar generated; review proportions, texture, armature and animations.")
    return {"generated":True,"stage":next(item.model_dump(mode="json") for item in reviewed.stages if item.stage==StageId.PLAYER),"glb_scene":str(output.relative_to(folder)),"glb_bytes":output.stat().st_size,"identity_source":spec["identity_source"],"rigged":True}

def _run_environment_build(folder: Path, store: PipelineStore, document: CreatorWorkflowDocument, manager: Any) -> dict:
    pipeline=store.load()
    stage=next(item for item in pipeline.stages if item.stage==StageId.ENVIRONMENT)
    if stage.state!=StageState.READY: raise HTTPException(409,"Environment stage is not READY. Approve the generated player first.")
    story_path=store.folder/"story.json"
    story=json.loads(story_path.read_text(encoding="utf-8"))
    story["world_scale"]=document.world_scale
    story["setting"]=document.synopsis or document.title
    vision={}
    analysis_files=sorted((store.folder/"analysis").glob("revision-*/analysis.json")) if (store.folder/"analysis").exists() else []
    if analysis_files:
        try:
            analysis_doc=json.loads(analysis_files[-1].read_text(encoding="utf-8"))
            candidate=analysis_doc.get("vision_analysis",{})
            if candidate.get("status")=="complete": vision=candidate
        except (OSError,ValueError):
            vision={}
    vision_summary=str(vision.get("environment_summary") or vision.get("movie_summary") or "")
    if vision_summary:
        story["setting"]=str(story.get("setting") or "")+" | Visual analysis: "+vision_summary
    spec=build_world_spec(story)
    pack=PACKS[document.world_pack]
    # Enrich deterministic geometry with creator-selected pack palette and
    # approved visual scene cues. Vision supplies briefs, not final art.
    spec["source_pack"]=pack["id"]; spec["visual_style"]=document.visual_style; spec["palette"]=pack["palette"]; spec["architecture"]=pack["architecture"]
    spec["movie_vision_summary"]=vision_summary
    spec["movie_environment_briefs"]=vision.get("environments",[])[:12]
    spec["movie_action_beats"]=vision.get("action_beats",[])[:24]
    spec["episodes"]=[episode.model_dump(mode="json") for episode in document.episodes]
    visual_environments=vision.get("environments",[]) if isinstance(vision.get("environments",[]),list) else []
    base_landmarks=[dict(item) for item in spec["landmarks"]]
    dimension=float(spec["dimensions"][0])
    # One persistent location is generated for every document/movie episode.
    while len(spec["landmarks"])<len(document.episodes):
        index=len(spec["landmarks"])
        source=dict(base_landmarks[index%len(base_landmarks)])
        angle=(2*math.pi*index)/max(1,len(document.episodes))
        radius=dimension*0.27
        source["position"]=[round(math.cos(angle)*radius,2),0.0,round(math.sin(angle)*radius,2)]
        source["id"]=f"episode-location-{index+1}"
        spec["landmarks"].append(source)
    for episode_index,episode in enumerate(document.episodes):
        landmark=spec["landmarks"][episode_index]
        visual=visual_environments[episode_index%len(visual_environments)] if visual_environments else {}
        landmark["name"]=episode.location or visual.get("label") or episode.title
        landmark["visual_features"]=visual.get("visual_features","")
        landmark["materials"]=visual.get("materials","")
        landmark["id"]=f"episode-{episode_index+1}-location"
    spec["navigation"]["paths"]=[{"from":"spawn","to":item["id"]} for item in spec["landmarks"]]
    # Pack-specific set dressing and requested variations become actual
    # Blender scene objects, not just workload labels in the editor.
    geometry_sets={
        "sci_fi_survival":["crate","rock","beacon","crate"],
        "urban_action":["crate","rock","crate","beacon"],
        "fantasy_frontier":["tree","rock","tree","beacon"],
        "wilderness_expedition":["tree","rock","tree","crate"],
    }
    geometry_set=geometry_sets[document.world_pack]
    for index,prop in enumerate(spec.get("props",[])):
        prop["geometry"]=geometry_set[index%len(geometry_set)]
    for variant in range(1,document.environment_variants):
        for index in range(max(8,len(spec.get("props",[]))//4)):
            angle=(2*math.pi*index)/max(1,len(spec.get("props",[])))
            radius=dimension*(0.18+0.025*variant)
            spec["props"].append({
                "id":f"variant-{variant+1}-prop-{index+1}",
                "geometry":geometry_set[(index+variant)%len(geometry_set)],
                "position":[round(math.cos(angle)*radius,2),0.0,round(math.sin(angle)*radius,2)],
                "scale":round(0.7+0.1*((index+variant)%5),2),"collision":True,
            })
    dimension=max(dimension,48+len(document.episodes)*4+document.environment_variants*6)
    spec["dimensions"]=[dimension,48,dimension]
    output_dir=store.folder/"environment"; output_dir.mkdir(parents=True,exist_ok=True)
    spec_path=output_dir/"world-spec.json"; spec_path.write_text(json.dumps(spec,indent=2),encoding="utf-8")
    blender=shutil.which("blender")
    if not blender: raise HTTPException(503,"Blender is required to generate the 3D environment GLB.")
    output=output_dir/"environment.glb"
    stage.state=StageState.RUNNING; stage.summary=f"Building {pack['name']} environment, terrain, landmarks, paths, collision and set dressing"; store.save(pipeline)
    script=Path(__file__).resolve().parents[2]/"blender"/"scripts"/"build_movie_world.py"
    try:
        subprocess.run([blender,"--background","--python",str(script),"--","--spec",str(spec_path),"--output",str(output)],capture_output=True,text=True,timeout=1200,check=True)
    except subprocess.TimeoutExpired as exc:
        current=store.load(); rec=next(item for item in current.stages if item.stage==StageId.ENVIRONMENT); rec.state=StageState.FAILED; rec.error="Environment build exceeded 20 minutes"; store.save(current); raise HTTPException(504,rec.error) from exc
    except subprocess.CalledProcessError as exc:
        current=store.load(); rec=next(item for item in current.stages if item.stage==StageId.ENVIRONMENT); rec.state=StageState.FAILED; rec.error=(exc.stderr or exc.stdout or "Blender environment build failed")[-3000:]; store.save(current); raise HTTPException(500,"Environment generation failed: "+rec.error) from exc
    if not output.is_file() or output.stat().st_size<1024:
        current=store.load(); rec=next(item for item in current.stages if item.stage==StageId.ENVIRONMENT); rec.state=StageState.FAILED; rec.error="No valid environment GLB was produced"; store.save(current); raise HTTPException(500,rec.error)
    reviewed=store.mark_review(StageId.ENVIRONMENT,{"glb_scene":str(output.relative_to(folder)),"geometry_spec":str(spec_path.relative_to(folder)),"landmarks":len(spec["landmarks"]),"props":len(spec["props"]),"dimensions":spec["dimensions"],"glb_bytes":output.stat().st_size,"pack":pack["id"],"episode_locations":len(document.episodes),"requires_creator_review":True},"Environment and set dressing generated; review each episode location, scale and navigation before approval.")
    return {"generated":True,"stage":next(item.model_dump(mode="json") for item in reviewed.stages if item.stage==StageId.ENVIRONMENT),"glb_scene":str(output.relative_to(folder)),"glb_bytes":output.stat().st_size,"dimensions":spec["dimensions"],"landmark_count":len(spec["landmarks"]),"prop_count":len(spec["props"]),"pack":pack["id"]}

def _latest_vision(folder: Path) -> dict:
    files=sorted((folder/"analysis").glob("revision-*/analysis.json")) if (folder/"analysis").exists() else []
    if not files: return {}
    try:
        analysis=json.loads(files[-1].read_text(encoding="utf-8"))
        vision=analysis.get("vision_analysis",{})
        return vision if vision.get("status")=="complete" else {}
    except (OSError,ValueError):
        return {}

def _default_actor_prop_spec(document: CreatorWorkflowDocument, vision: dict | None = None) -> dict:
    actors=[]; props=[]
    enemy_types=["npc","robot","animal"]
    detected=(vision or {}).get("enemy_archetypes",[])
    for i in range(document.enemies):
        source=detected[i%len(detected)] if detected else {}
        label=str(source.get("label") or source.get("role") or f"Enemy {i+1}")[:80]
        behavior=str(source.get("behavior_hint") or "patrol; detect player; pursue and attack when in range")[:500]
        actors.append({"id":f"enemy-{i+1}","name":label,"kind":enemy_types[i%len(enemy_types)],"behavior":behavior,"scale":1.0,"position":[float((i%4)*4-6),0.0,float(-8-(i//4)*5)]})
    vehicle_names={"sci_fi_survival":"Scout Buggy","urban_action":"Street Vehicle","fantasy_frontier":"Pack Beast","wilderness_expedition":"Expedition Rover"}
    detected_vehicles=(vision or {}).get("vehicles",[])
    for i in range(document.vehicles):
        source=detected_vehicles[i%len(detected_vehicles)] if detected_vehicles else {}
        name=str(source.get("label") or source.get("type") or (vehicle_names[document.world_pack] if i==0 else f"Vehicle {i+1}"))[:80]
        props.append({"id":f"vehicle-{i+1}","name":name,"kind":"vehicle","interaction":"enter; drive; exit","scale":1.2,"position":[float((i%3)*6-6),0.0,float(8+(i//3)*7)]})
    props.extend([
        {"id":"mission-container","name":"Mission Supply Cache","kind":"container","interaction":"open; collect supplies","scale":1.1,"position":[4.0,0.0,2.0]},
        {"id":"objective-tool","name":"Objective Device","kind":"tool","interaction":"activate; advance mission","scale":1.0,"position":[-4.0,0.0,1.0]},
    ])
    return {"actors":actors,"props":props}

def _run_actor_prop_build(folder: Path, store: PipelineStore, document: CreatorWorkflowDocument) -> dict:
    from core.movie_pipeline.actors_api import ActorsPropsRequest
    pipeline=store.load(); stage=next(item for item in pipeline.stages if item.stage==StageId.ACTORS_PROPS)
    if stage.state!=StageState.READY: raise HTTPException(409,"Actors and props stage is not READY. Approve the generated environment first.")
    spec=_default_actor_prop_spec(document,_latest_vision(folder))
    request_model=ActorsPropsRequest.model_validate(spec)
    blender=shutil.which("blender")
    if not blender: raise HTTPException(503,"Blender is required for enemy, vehicle and prop generation.")
    output_dir=store.folder/"actors-props"/f"revision-{stage.revision}"; output_dir.mkdir(parents=True,exist_ok=True)
    spec_path=output_dir/"actors-props.json"; glb=output_dir/"actors-props.glb"
    spec_path.write_text(json.dumps(request_model.model_dump(),indent=2),encoding="utf-8")
    script=Path(__file__).resolve().parents[2]/"blender"/"scripts"/"build_actors_props.py"
    stage.state=StageState.RUNNING; stage.summary="Generating rigged enemies, vehicles, props, collision and interaction metadata"; store.save(pipeline)
    try:
        subprocess.run([blender,"--background","--python",str(script),"--","--spec",str(spec_path),"--output",str(glb)],capture_output=True,text=True,timeout=900,check=True)
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:
        current=store.load(); rec=next(item for item in current.stages if item.stage==StageId.ACTORS_PROPS); rec.state=StageState.FAILED; rec.error=(getattr(exc,"stderr",None) or str(exc))[-3000:]; store.save(current); raise HTTPException(500,"Enemy and vehicle generation failed: "+rec.error) from exc
    manifest=glb.with_suffix(".manifest.json")
    if not glb.is_file() or glb.stat().st_size<1024 or not manifest.is_file(): raise HTTPException(500,"Actor/vehicle generator did not create its GLB and manifest.")
    reviewed=store.mark_review(StageId.ACTORS_PROPS,{"glb_scene":str(glb.relative_to(folder)),"manifest":str(manifest.relative_to(folder)),"spec":str(spec_path.relative_to(folder)),"actor_count":len(spec["actors"]),"prop_count":len(spec["props"]),"glb_bytes":glb.stat().st_size,"requires_creator_review":True},"Generated rigged enemies, vehicles and interactive props; review all character rigs and vehicle geometry.")
    return {"generated":True,"stage":next(item.model_dump(mode="json") for item in reviewed.stages if item.stage==StageId.ACTORS_PROPS),"glb_scene":str(glb.relative_to(folder)),"actor_count":len(spec["actors"]),"prop_count":len(spec["props"]),"vehicle_count":document.vehicles}

def _run_audio_build(folder: Path, store: PipelineStore) -> dict:
    from core.audio_foundry.synth import generate_audio
    pipeline=store.load(); stage=next(item for item in pipeline.stages if item.stage==StageId.AUDIO)
    if stage.state!=StageState.READY: raise HTTPException(409,"Audio stage is not READY. Approve the actors and props stage first.")
    cues=[
        {"id":"player-jump","label":"Player jump","kind":"sweep","frequency":360,"duration":.28,"seed":11,"trigger":"player_jump"},
        {"id":"objective-progress","label":"Objective progress","kind":"pulse","frequency":660,"duration":.35,"seed":12,"trigger":"objective_progress"},
        {"id":"objective-complete","label":"Objective complete","kind":"impact","frequency":880,"duration":.65,"seed":13,"trigger":"objective_complete"},
        {"id":"enemy-alert","label":"Enemy alert","kind":"alarm","frequency":520,"duration":.7,"seed":14,"trigger":"enemy_alert"},
        {"id":"item-collected","label":"Item collected","kind":"tone","frequency":740,"duration":.32,"seed":15,"trigger":"item_collected"},
        {"id":"vehicle-engine","label":"Vehicle engine loop","kind":"noise","frequency":115,"duration":1.2,"seed":16,"trigger":"vehicle_engine"},
    ]
    from core.movie_pipeline.audio_api import MusicSpec
    music={"mood":"adventure","duration":30,"seed":724,"loop":True}
    output_dir=store.folder/"audio"/f"revision-{stage.revision}"
    stage.state=StageState.RUNNING; stage.summary="Synthesizing original game audio and loopable soundtrack"; store.save(pipeline)
    try:
        manifest=generate_audio(output_dir,cues,music)
        files=[output_dir/item["file"] for item in manifest["effects"]]
        if manifest["music"]: files.append(output_dir/manifest["music"]["file"])
        if not files or any(not item.is_file() or item.stat().st_size<44 for item in files): raise RuntimeError("Audio synthesis produced invalid WAV data.")
        relative=lambda path:str(path.relative_to(folder))
        output={"manifest":relative(output_dir/"audio-manifest.json"),"effects":[{**item,"asset":relative(output_dir/item["file"])} for item in manifest["effects"]],"music":({**manifest["music"],"asset":relative(output_dir/manifest["music"]["file"])} if manifest["music"] else None),"requires_creator_review":True}
        reviewed=store.mark_review(StageId.AUDIO,output,"Original procedural sound effects and music created; listen and approve before gameplay compilation.")
    except Exception as exc:
        current=store.load(); rec=next(item for item in current.stages if item.stage==StageId.AUDIO); rec.state=StageState.FAILED; rec.error=str(exc)[:2000]; store.save(current); raise HTTPException(500,"Audio synthesis failed: "+str(exc)) from exc
    return {"generated":True,"stage":next(item.model_dump(mode="json") for item in reviewed.stages if item.stage==StageId.AUDIO),"effects_count":len(manifest["effects"]),"music_generated":bool(manifest["music"])}

def _build_gameplay(folder: Path, store: PipelineStore, document: CreatorWorkflowDocument) -> dict:
    from core.movie_pipeline.gameplay_api import GameplayBuildRequest
    from core.gameplay_compiler.compiler import compile_gameplay
    from core.movie_pipeline.models import StageId,StageState
    pipeline=store.load(); records={item.stage:item for item in pipeline.stages}
    required=[StageId.ANALYSIS,StageId.PLAYER,StageId.ENVIRONMENT,StageId.ACTORS_PROPS,StageId.AUDIO]
    if any(records[stage].state!=StageState.APPROVED for stage in required):
        raise HTTPException(409,"Approve analysis, player, environment, enemies/vehicles and audio before gameplay compilation.")
    stage=records[StageId.GAMEPLAY]
    if stage.state!=StageState.READY: raise HTTPException(409,"Gameplay stage is not READY.")
    actor_manifest_path=store.folder/"actors-props"/f"revision-{records[StageId.ACTORS_PROPS].revision}"/"actors-props.manifest.json"
    audio_manifest_path=store.folder/"audio"/f"revision-{records[StageId.AUDIO].revision}"/"audio-manifest.json"
    if not actor_manifest_path.is_file() or not audio_manifest_path.is_file(): raise HTTPException(409,"Approved actor and audio manifests are missing.")
    actors_data=json.loads(actor_manifest_path.read_text(encoding="utf-8"))
    audio_manifest=json.loads(audio_manifest_path.read_text(encoding="utf-8"))
    actor_ids=[item["id"] for item in actors_data.get("actors",[])]
    prop_ids=[item["id"] for item in actors_data.get("props",[])]
    cue_ids={item["id"] for item in audio_manifest.get("effects",[])}
    missions=[]
    for index,episode in enumerate(document.episodes):
        target=f"episode-{index+1}-location"
        objectives=[{"id":f"reach-episode-{index+1}","title":episode.player_goal or f"Reach {episode.location or episode.title}","description":episode.synopsis or f"Explore and complete the objectives in {episode.title}.","kind":"reach","target_id":target,"required_count":1}]
        if actor_ids:
            enemy_index=index%len(actor_ids)
            objectives.append({"id":f"defeat-episode-{index+1}","title":f"Clear the hostile threat in {episode.title}","description":"Defeat the assigned enemy unit before advancing.","kind":"defeat","target_id":actor_ids[enemy_index],"required_count":1})
        missions.append({"id":f"episode-{index+1}","title":episode.title,"description":episode.synopsis or episode.player_goal or f"Complete {episode.title}.","objectives":objectives})
    behaviours=[{"actor_id":actor_id,"behaviour":"patrol","move_speed":2.5,"detection_range":18,"attack_range":1.8,"damage":10} for actor_id in actor_ids]
    interactions=[]
    for prop_id in prop_ids:
        action="open" if "container" in prop_id else "activate"
        interactions.append({"prop_id":prop_id,"action":action})
    audio_bindings=[]
    event_map={"player_jump":"player-jump","objective_progress":"objective-progress","objective_complete":"objective-complete","item_collected":"item-collected"}
    for event,cue in event_map.items():
        if cue in cue_ids: audio_bindings.append({"event":event,"cue_id":cue})
    if "enemy-alert" in cue_ids: audio_bindings.append({"event":"player_damaged","cue_id":"enemy-alert"})
    request=GameplayBuildRequest.model_validate({"player":{"move_speed":5.0,"jump_velocity":4.5,"gravity":9.8,"health":100,"inventory_capacity":20},"missions":missions,"actor_behaviours":behaviours,"interactions":interactions,"audio_bindings":audio_bindings})
    stage.state=StageState.RUNNING; stage.summary="Compiling one playable mission per creator-defined episode"; store.save(pipeline)
    output_dir=store.folder/"gameplay"/f"revision-{stage.revision}"
    try:
        manifest=compile_gameplay(output_dir,request.model_dump(mode="json"),audio_manifest)
        output={"manifest":str((output_dir/"gameplay-manifest.json").relative_to(folder)),"gameplay_spec":str((output_dir/"gameplay.json").relative_to(folder)),"audio_events":str((output_dir/"audio-events.json").relative_to(folder)),"runtime_files":[str((output_dir/item).relative_to(folder)) for item in manifest["runtime_files"]],"mission_count":manifest["mission_count"],"objective_count":manifest["objective_count"],"audio_binding_count":manifest["audio_binding_count"],"requires_creator_review":True}
        reviewed=store.mark_review(StageId.GAMEPLAY,output,"Episode missions and game mechanics compiled. Playtest all episode transitions, enemy AI and objectives before approval.")
    except Exception as exc:
        current=store.load(); rec=next(item for item in current.stages if item.stage==StageId.GAMEPLAY); rec.state=StageState.FAILED; rec.error=str(exc)[:2000]; rec.summary="Episode gameplay compilation failed"; store.save(current); raise HTTPException(500,"Gameplay compilation failed: "+str(exc)) from exc
    return {"compiled":True,"stage":next(item.model_dump(mode="json") for item in reviewed.stages if item.stage==StageId.GAMEPLAY),"mission_count":manifest["mission_count"],"objective_count":manifest["objective_count"]}


class ConversionRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    target_role: Literal["prop","character","environment"] = "prop"
    confirm_rights: bool
    max_faces: int = Field(default=50000,ge=1000,le=500000)

def _run_asset_conversion(folder: Path, asset_id: str, owner_id: str, target_role: str, max_faces: int, job_id: str, jobs: Any) -> None:
    job=jobs.get(job_id)
    try:
        registry=AssetRegistry(folder/"assets")
        source_record=next((item for item in registry.list() if item.get("asset_id")==asset_id),None)
        if not source_record: raise RuntimeError("Source asset disappeared before conversion.")
        source=(folder/"assets"/Path(source_record["path"]).name).resolve()
        if folder.resolve() not in source.parents or not source.is_file(): raise RuntimeError("Source asset is missing or outside the project asset directory.")
        suffix=source.suffix.lower()
        work=folder/"asset-conversions"/job_id
        work.mkdir(parents=True,exist_ok=True)
        glb=work/"converted.glb"
        jobs.update(job_id,state=JobState.RUNNING,progress=5,message="Preparing source asset and checking conversion tools")
        if suffix in IMAGE_EXTENSIONS:
            root=Path(os.environ.get("NEXORA_TRIPOSR_ROOT","")).expanduser()
            runner=root/"run.py"
            if not runner.is_file():
                raise RuntimeError("TripoSR is not installed on the dedicated GPU worker. Set NEXORA_TRIPOSR_ROOT to the licensed VAST-AI-Research/TripoSR checkout; image-to-3D is not silently replaced with a fake mesh.")
            jobs.update(job_id,progress=12,message="Reconstructing a 3D mesh from the creator-owned image with TripoSR")
            output_dir=work/"triposr"
            output_dir.mkdir(parents=True,exist_ok=True)
            command=[sys.executable,str(runner),str(source),"--output-dir",str(output_dir),"--bake-texture"]
            try:
                result=subprocess.run(command,cwd=str(root),capture_output=True,text=True,timeout=1800,check=True)
            except (subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:
                raise RuntimeError("TripoSR image-to-3D reconstruction failed: "+(getattr(exc,"stderr",None) or str(exc))[-2500:]) from exc
            generated=[item for item in output_dir.rglob("*") if item.is_file() and item.suffix.lower() in {".glb",".gltf",".obj",".fbx",".ply"}]
            if not generated: raise RuntimeError("TripoSR finished without producing a supported mesh file.")
            source_model=next((item for item in generated if item.suffix.lower()==".glb"),generated[0])
        elif suffix in MODEL_EXTENSIONS:
            source_model=source
        else:
            raise RuntimeError("This source file cannot be converted to a game mesh.")
        jobs.update(job_id,progress=65,message="Normalizing the mesh, transforms, materials and polygon budget with Blender")
        if source_model.suffix.lower()==".glb":
            shutil.copy2(source_model,glb)
        else:
            blender=shutil.which("blender")
            if not blender: raise RuntimeError("Blender is required to convert this mesh format into GLB.")
            script=Path(__file__).resolve().parents[2]/"blender"/"scripts"/"convert_asset_to_glb.py"
            result=subprocess.run([blender,"--background","--python",str(script),"--","--input",str(source_model),"--output",str(glb),"--max-faces",str(max_faces)],capture_output=True,text=True,timeout=1200)
            if result.returncode!=0 or not glb.is_file():
                raise RuntimeError("Blender GLB conversion failed: "+(result.stderr or result.stdout or "No GLB was generated")[-2500:])
        jobs.update(job_id,progress=86,message="Validating the converted GLB and registering the derived asset")
        report=validate_gltf(glb)
        if not report.get("valid"): raise RuntimeError("Converted GLB failed structural validation: "+"; ".join(report.get("errors",[])))
        output_name=f"{source.stem[:50]}-nexora-{uuid4().hex[:8]}.glb"
        destination=(folder/"assets"/output_name).resolve()
        if folder.joinpath("assets").resolve() not in destination.parents: raise RuntimeError("Derived asset path escaped the project.")
        shutil.copy2(glb,destination)
        derived_id=f"{destination.stem[:40]}-{uuid4().hex[:8]}"
        licence=source_record.get("license") or "Creator confirms rights to the source image/model and derivative"
        provenance={"source_asset_id":asset_id,"source_filename":source.name,"source_checksum":source_record.get("checksum"),
                    "conversion_engine":"TripoSR + Blender" if suffix in IMAGE_EXTENSIONS else "Blender",
                    "target_role":target_role,"is_rigged":False,"requires_rigging_for_character_animation":target_role=="character",
                    "validation":report,"conversion_job_id":job_id}
        registered=registry.register(derived_id,destination.name,"character" if target_role=="character" else "environment" if target_role=="environment" else "prop",licence,source="NEXORA Creator Asset Converter",metadata=provenance)
        jobs.update(job_id,state=JobState.COMPLETED,progress=100,message="A validated GLB game asset is ready for preview and scene placement",error=None)
    except Exception as exc:
        jobs.update(job_id,state=JobState.FAILED,progress=100,message="Asset conversion failed",error=str(exc))
def _execute_creator_step(job_id: str, project_id: str, owner_id: str, step: str, manager: Any, jobs: Any) -> None:
    from core.orchestration.jobs import JobState
    try:
        folder=manager.path_for(project_id)
        owner_file=folder/"nexora_owner.json"
        if not owner_file.is_file() or json.loads(owner_file.read_text(encoding="utf-8")).get("user_id")!=owner_id:
            raise RuntimeError("NEXORA project ownership changed before this job started.")
        workflow=_load_workflow(folder)
        _assert_entitled(manager,owner_id,workflow.plan)
        _validate_plan(workflow)
        store=_pipeline(folder)
        jobs.update(job_id,state=JobState.RUNNING,progress=5,message="Starting Creator Flow stage: "+step)
        if step=="player":
            _run_player_build(folder,store,workflow,workflow.player_source=="consented_portrait")
            message="Default / player avatar created; creator review is required."
        elif step=="environment":
            if workflow.mode=="movie":
                pipeline=store.load()
                analysis=next(item for item in pipeline.stages if item.stage==StageId.ANALYSIS)
                if analysis.state!=StageState.APPROVED:
                    raise RuntimeError("Review and approve extracted movie scenes before environment generation.")
            _run_environment_build(folder,store,workflow,manager)
            message="3D environment built; review geometry, locations and navigation."
        elif step=="actors_props":
            result=_run_actor_prop_build(folder,store,workflow)
            message=f"Generated {result['actor_count']} enemies and {result['vehicle_count']} vehicles plus props; review before approval."
        elif step=="audio":
            _run_audio_build(folder,store)
            message="Original procedural audio and soundtrack created; listen and approve."
        elif step=="gameplay":
            result=_build_gameplay(folder,store,workflow)
            message=f"Compiled {result['mission_count']} episode missions; playtest before approval."
        elif step=="assembly":
            pipeline=store.load()
            records={item.stage:item for item in pipeline.stages}
            required=[StageId.ANALYSIS,StageId.PLAYER,StageId.ENVIRONMENT,StageId.ACTORS_PROPS,StageId.AUDIO,StageId.GAMEPLAY]
            if any(records[stage].state!=StageState.APPROVED for stage in required):
                raise RuntimeError("Approve analysis, player, environment, enemies/vehicles, audio and gameplay before final assembly.")
            exe=godot_executable()
            if not exe: raise RuntimeError("Godot 4 is not installed on the NEXORA production worker.")
            stage_record=records[StageId.ASSEMBLY]
            if stage_record.state!=StageState.READY: raise RuntimeError("Assembly stage is not READY.")
            from core.movie_pipeline.assembly import assemble_movie_game
            stage_record.state=StageState.RUNNING
            stage_record.summary="Importing, assembling and validating the episode-driven game in Godot"
            store.save(pipeline)
            try:
                report=assemble_movie_game(folder,pipeline,exe)
                store.mark_review(StageId.ASSEMBLY,{"project":"game/project.godot","manifest":"game/assembly-manifest.json","validation":report.get("validation"),"requires_creator_review":True},"Godot assembled the episode-driven game. Creator playtesting and platform export are still required.")
            except Exception as exc:
                current=store.load()
                rec=next(item for item in current.stages if item.stage==StageId.ASSEMBLY)
                rec.state=StageState.FAILED
                rec.error=str(exc)[-3000:]
                rec.summary="Godot assembly failed"
                store.save(current)
                raise
            message="Godot project assembled and validated; inspect and download the game for creator playtesting."
        else:
            raise RuntimeError("Unknown Creator Flow job: "+step)
        jobs.update(job_id,state=JobState.COMPLETED,progress=100,message=message,error=None)
    except Exception as exc:
        jobs.update(job_id,state=JobState.FAILED,progress=100,message="Creator Flow stage failed: "+step,error=str(getattr(exc,"detail",None) or exc))

def _queue_creator_step(pid: str, folder: Path, owner_id: str, step: str, background: BackgroundTasks, manager: Any, jobs: Any) -> dict:
    workflow=_load_workflow(folder)
    _assert_entitled(manager,owner_id,workflow.plan)
    _validate_plan(workflow)
    job=jobs.add(Job.create(pid))
    job_root=folder/"workspace_jobs"
    job_root.mkdir(exist_ok=True)
    (job_root/f"{job.id}.owner.json").write_text(json.dumps({"user_id":owner_id},indent=2),encoding="utf-8")
    background.add_task(_execute_creator_step,job.id,pid,owner_id,step,manager,jobs)
    return {**job.as_dict(),"state":job.state.value.lower(),"kind":"creator."+step,"message":"Queued Creator Flow stage: "+step}

def register_creator_workflow_routes(app: Any, manager: Any, jobs: Any) -> None:
    router=APIRouter()

    @router.get("/api/v1/workspace/assets/conversion-capabilities")
    def conversion_capabilities(request: Request):
        if not getattr(request.state,"nexora_user_id",None): raise HTTPException(401,"Sign in to your NEXORA account.")
        triposr_root=Path(os.environ.get("NEXORA_TRIPOSR_ROOT","")).expanduser()
        return {"image_to_3d":{"available":(triposr_root/"run.py").is_file(),"engine":"TripoSR","minimum_vram_gb":6,"licence":"MIT; retain upstream licence notice"},
                "model_conversion":{"available":bool(shutil.which("blender")),"engine":"Blender","formats":["GLB","glTF","OBJ","FBX","PLY"]},
                "note":"A generated character mesh is static unless a rigging stage is completed. NEXORA does not label a static mesh as animation-ready."}

    @router.post("/api/v1/workspace/projects/{pid}/assets/{asset_id}/convert",status_code=202)
    def queue_asset_conversion(pid: str,asset_id: str,payload: ConversionRequest,request: Request,background: BackgroundTasks):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        owner,_=_assert_project(folder,request,manager)
        if not payload.confirm_rights: raise HTTPException(403,"Confirm that you own or have permission to make a derivative of this asset.")
        workflow_path=_workflow_path(folder)
        suffix=Path(next((item.get("path","") for item in AssetRegistry(folder/"assets").list() if item.get("asset_id")==asset_id),"")).suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            workflow=_load_workflow(folder)
            _assert_entitled(manager,owner,workflow.plan)
            _validate_plan(workflow)
        registry=AssetRegistry(folder/"assets")
        source=next((item for item in registry.list() if item.get("asset_id")==asset_id),None)
        if not source: raise HTTPException(404,"Source asset not found.")
        suffix=Path(source["path"]).suffix.lower()
        if suffix in IMAGE_EXTENSIONS and not (Path(os.environ.get("NEXORA_TRIPOSR_ROOT","")).expanduser()/"run.py").is_file():
            raise HTTPException(503,"Image-to-3D GPU worker is not configured. Install the MIT-licensed TripoSR worker and set NEXORA_TRIPOSR_ROOT; image files are never passed off as generated meshes.")
        if suffix not in IMAGE_EXTENSIONS|MODEL_EXTENSIONS: raise HTTPException(415,"Only image or 3D model assets can be converted.")
        if suffix in MODEL_EXTENSIONS and not shutil.which("blender"): raise HTTPException(503,"Blender is required for model normalization.")
        job=jobs.add(Job.create(pid))
        job_root=folder/"workspace_jobs"; job_root.mkdir(exist_ok=True)
        (job_root/f"{job.id}.owner.json").write_text(json.dumps({"user_id":owner},indent=2),encoding="utf-8")
        background.add_task(_run_asset_conversion,folder,asset_id,owner,payload.target_role,payload.max_faces,job.id,jobs)
        return {**job.as_dict(),"state":job.state.value.lower(),"kind":"asset.convert","target_role":payload.target_role}

    @router.get("/api/v1/creator-flow/plans")
    def get_creator_plans(request: Request):
        user=getattr(request.state,"nexora_user_id",None)
        if not user: raise HTTPException(401,"Sign in to your NEXORA account.")
        prices=_price_map()
        return {"plans":[{**plan,"price_kes":prices.get(plan_id),"price_configured":plan_id in prices} for plan_id,plan in PLANS.items()],"payment":{"method":"Pochi la Biashara","merchant_number_configured":bool(_pochi_merchant_number()),"merchant_number":_pochi_merchant_number() or None,"automatic_confirmation":False,"reason":"Pochi incoming merchant payments are reconciled against merchant records. This deployment uses a receipt claim and verified reconciliation, not a fake STK confirmation."},"active_entitlement":_get_entitlement(manager,user)}

    @router.get("/api/v1/creator-flow/packs")
    def get_creator_packs(request: Request):
        if not getattr(request.state,"nexora_user_id",None): raise HTTPException(401,"Sign in to your NEXORA account.")
        return {"packs":list(PACKS.values()),"templates_source":"NEXORA original procedural templates"}

    @router.post("/api/v1/creator-flow/checkout",status_code=201)
    def create_checkout(payload: CheckoutRequest, request: Request):
        user=getattr(request.state,"nexora_user_id",None)
        if not user: raise HTTPException(401,"Sign in to your NEXORA account.")
        merchant=_pochi_merchant_number()
        prices=_price_map()
        if not merchant: raise HTTPException(503,"Configure NEXORA_POCHI_MERCHANT_NUMBER with the enrolled Pochi merchant mobile number.")
        if payload.plan not in prices: raise HTTPException(503,f"Configure the approved KES price for the {PLANS[payload.plan]['name']} plan in NEXORA_PLAN_PRICES_KES.")
        if _database_url():
            conn=_connect(); _ensure_billing_schema(conn); conn.close()
        else:
            if os.environ.get("RENDER") or os.environ.get("NEXORA_ENV","").lower()=="production":
                raise HTTPException(503,"Configure NEXORA_DATABASE_URL for secure, durable payment and entitlement records.")
        reference="NX"+uuid4().hex[:10].upper()
        payment_id=uuid4().hex
        record={"payment_id":payment_id,"reference":reference,"user_id":str(user),"project_id":payload.project_id,"plan":payload.plan,"amount_kes":prices[payload.plan],"currency":"KES","status":"pending","payer_phone":payload.payer_phone,"created_at":_utc(),"receipt_code":None,"paid_amount_kes":None,"claimed_at":None,"verified_at":None}
        _save_payment(manager,record,create=True)
        return {"payment_id":payment_id,"reference":reference,"plan":payload.plan,"amount_kes":record["amount_kes"],"currency":"KES","status":"pending","merchant_number":merchant,"instructions":["Open M-PESA and choose Pochi la Biashara payment, or dial *334# and select Pochi la Biashara.","Pay the exact KES amount to the enrolled merchant number shown here.","Keep the M-PESA transaction receipt. Return to NEXORA and submit that receipt for verification.","Access is granted only after the transaction is reconciled and approved."],"expires_at":(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()}

    @router.post("/api/v1/creator-flow/payments/{payment_id}/claim")
    def claim_payment(payment_id: str, payload: PaymentClaim, request: Request):
        user=getattr(request.state,"nexora_user_id",None)
        record=_find_payment(manager,payment_id)
        if not record or record["user_id"]!=str(user): raise HTTPException(404,"Payment request not found.")
        if record["status"]=="verified": return {"status":"verified","plan":record["plan"]}
        if payload.paid_amount_kes!=int(record["amount_kes"]): raise HTTPException(422,"The claimed amount does not match this plan invoice.")
        record.update({"status":"claimed","receipt_code":payload.mpesa_receipt.upper(),"paid_amount_kes":payload.paid_amount_kes,"payer_phone":payload.payer_phone,"claimed_at":_utc()})
        _save_payment(manager,record)
        return {"status":"claimed","message":"Receipt submitted. Your plan remains locked until the merchant transaction is verified."}

    @router.get("/api/v1/creator-flow/payments/{payment_id}")
    def get_payment(payment_id: str, request: Request):
        user=getattr(request.state,"nexora_user_id",None)
        record=_find_payment(manager,payment_id)
        if not record or record["user_id"]!=str(user): raise HTTPException(404,"Payment request not found.")
        return {key:value for key,value in record.items() if key!="user_id"}

    @router.post("/api/v1/creator-flow/payments/{payment_id}/verify")
    def verify_payment(payment_id: str, request: Request, x_nexora_payment_secret: str=Header(default="")):
        secret=os.environ.get("NEXORA_PAYMENT_VERIFICATION_SECRET","")
        if not secret or x_nexora_payment_secret!=secret: raise HTTPException(403,"Payment reconciliation authority is required.")
        record=_find_payment(manager,payment_id)
        if not record: raise HTTPException(404,"Payment request not found.")
        if record["status"]=="verified": return {"verified":True,"already_verified":True,"plan":record["plan"]}
        if record["status"]!="claimed" or not record.get("receipt_code") or record.get("paid_amount_kes")!=record.get("amount_kes"):
            raise HTTPException(409,"A matching customer receipt claim is required before reconciliation.")
        record["status"]="verified"; record["verified_at"]=_utc()
        _save_payment(manager,record)
        _activate_entitlement(manager,record["user_id"],record["plan"],record["reference"])
        return {"verified":True,"plan":record["plan"],"target_class":PLANS[record["plan"]]["target_class"]}

    @router.get("/api/v1/workspace/projects/{pid}/creator-workflow")
    def get_workflow(pid: str, request: Request):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        user,definition=_assert_project(folder,request,manager)
        entitlement=_get_entitlement(manager,user)
        path=_workflow_path(folder)
        if not path.is_file(): return {"workflow":None,"entitlement":entitlement}
        doc=CreatorWorkflowDocument.model_validate_json(path.read_text(encoding="utf-8"))
        return {"workflow":doc.model_dump(mode="json"),"plan_check":_validate_plan(doc),"entitlement":entitlement}

    @router.put("/api/v1/workspace/projects/{pid}/creator-workflow")
    def save_workflow(pid: str, payload: CreatorWorkflowDocument, request: Request):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        user,_=_assert_project(folder,request,manager)
        check=_validate_plan(payload)
        entitlement=_get_entitlement(manager,user)
        if entitlement and entitlement.get("status")=="active":
            if list(PLANS).index(entitlement["plan"])<list(PLANS).index(payload.plan):
                raise HTTPException(402,"Your active plan is below the selected workflow plan.")
        # Saving a design document is allowed before payment; generation is not.
        saved=_save_workflow(folder,payload)
        return {"workflow":saved.model_dump(mode="json"),"plan_check":check,"entitlement":entitlement,"copyright_notice":_copyright_notice(payload)}

    @router.post("/api/v1/workspace/projects/{pid}/creator-workflow/pipeline")
    def create_creator_pipeline(pid: str, request: Request):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        user,_=_assert_project(folder,request,manager)
        workflow=_load_workflow(folder)
        _assert_entitled(manager,user,workflow.plan)
        _validate_plan(workflow)
        if workflow.mode=="movie" and not ((workflow.has_adaptation_rights or workflow.copyright_declaration=="public_domain") and (workflow.has_performer_consents or workflow.avoids_performer_likeness)):
            raise HTTPException(403,"Movie-to-game adaptation requires declared adaptation rights and performer/likeness permissions. Choose original/public-domain input or obtain the necessary licences.")
        store,pipeline=_ensure_pipeline(folder,pid,workflow.mode)
        story={"schema_version":"1.0","source":"creator","mode":workflow.mode,"title":workflow.title,"premise":workflow.synopsis,"player_role":"Player","setting":workflow.synopsis or workflow.title,"tone":workflow.visual_style,"instructions":"Episode plan is creator-authored; preserve its order and objectives.","ending":"","mission_count":len(workflow.episodes),"world_scale":workflow.world_scale,"player":{"identity_source":"synthetic_default","role":"Player","is_player_avatar":True},"missions":[{"id":episode.id,"title":episode.title,"objective":episode.player_goal or episode.synopsis} for episode in workflow.episodes],"episodes":[episode.model_dump(mode="json") for episode in workflow.episodes],"approval_required":True}
        store.folder.joinpath("story.json").write_text(json.dumps(story,indent=2),encoding="utf-8")
        return {"created":True,"pipeline":store.load().model_dump(mode="json"),"story":story,"copyright_notice":_copyright_notice(workflow)}

    @router.post("/api/v1/workspace/projects/{pid}/creator-workflow/player/build",status_code=202)
    def build_player(pid: str, request: Request, background: BackgroundTasks):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        user,_=_assert_project(folder,request,manager)
        return _queue_creator_step(pid,folder,user,"player",background,manager,jobs)

    @router.post("/api/v1/workspace/projects/{pid}/creator-workflow/player/portrait",status_code=201)
    async def upload_player_portrait(pid: str, request: Request, file: UploadFile=File(...), has_photo_rights: bool=Form(...), likeness_consent: bool=Form(...)):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        user,_=_assert_project(folder,request,manager)
        workflow=_load_workflow(folder); _assert_entitled(manager,user,workflow.plan)
        if not (has_photo_rights and likeness_consent): raise HTTPException(403,"Ownership of the portrait and the depicted person's likeness consent are both required.")
        store=_pipeline(folder); pipeline=store.load()
        if pipeline.source_photo: raise HTTPException(409,"A player portrait already exists. Regenerate the player or remove the current portrait first.")
        from core.movie_pipeline.ingestion import UploadRejected,store_upload
        try: metadata=await store_upload(file,"photo",store.folder/"uploads")
        except UploadRejected as exc: raise HTTPException(400,str(exc)) from exc
        from core.movie_pipeline.models import RightsDeclaration
        pipeline.source_photo=metadata
        pipeline.rights=RightsDeclaration(has_video_rights=pipeline.rights.has_video_rights,has_photo_rights=True,likeness_consent=True,accepts_original_assets_only=True)
        store.save(pipeline)
        return {"attached":True,"source_photo":metadata,"identity_source":"creator_consented_portrait"}

    @router.post("/api/v1/workspace/projects/{pid}/creator-workflow/environment/build",status_code=202)
    def build_environment(pid: str, request: Request, background: BackgroundTasks):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        user,_=_assert_project(folder,request,manager)
        return _queue_creator_step(pid,folder,user,"environment",background,manager,jobs)

    @router.post("/api/v1/workspace/projects/{pid}/creator-workflow/actors-props/build",status_code=202)
    def build_actors_props(pid: str, request: Request, background: BackgroundTasks):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        user,_=_assert_project(folder,request,manager)
        return _queue_creator_step(pid,folder,user,"actors_props",background,manager,jobs)

    @router.post("/api/v1/workspace/projects/{pid}/creator-workflow/audio/build",status_code=202)
    def build_audio(pid: str, request: Request, background: BackgroundTasks):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        user,_=_assert_project(folder,request,manager)
        return _queue_creator_step(pid,folder,user,"audio",background,manager,jobs)

    @router.post("/api/v1/workspace/projects/{pid}/creator-workflow/gameplay/compile",status_code=202)
    def compile_episodes(pid: str, request: Request, background: BackgroundTasks):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        user,_=_assert_project(folder,request,manager)
        return _queue_creator_step(pid,folder,user,"gameplay",background,manager,jobs)

    @router.post("/api/v1/workspace/projects/{pid}/creator-workflow/assembly/build",status_code=202)
    def assemble_creator_game(pid: str, request: Request, background: BackgroundTasks):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        user,_=_assert_project(folder,request,manager)
        return _queue_creator_step(pid,folder,user,"assembly",background,manager,jobs)

    @router.post("/api/v1/workspace/projects/{pid}/creator-workflow/video-check")
    def check_movie_plan(pid: str, request: Request):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found.")
        user,_=_assert_project(folder,request,manager)
        workflow=_load_workflow(folder); _assert_entitled(manager,user,workflow.plan)
        pipeline=_pipeline(folder).load()
        if not pipeline.source_video: raise HTTPException(409,"Upload the authorized movie first.")
        analysis=next(item for item in pipeline.stages if item.stage==StageId.ANALYSIS)
        output=analysis.output
        return {"stage":analysis.model_dump(mode="json"),"analysis":output,"copyright_notice":_copyright_notice(workflow)}

    app.include_router(router)

def _copyright_notice(document: CreatorWorkflowDocument) -> dict[str, Any]:
    if document.mode=="story": return {"required":False,"status":"creator-authored original","message":"The user-authored story is used as supplied. Asset licences and third-party references still need review."}
    return {"required":True,"status":"creator-declared","message":"NEXORA cannot reliably identify copyright ownership from a video file alone. The creator must hold adaptation rights or a valid licence, plus permissions for depicted performers/likenesses and separately licensed music where reused. NEXORA generates original 3D assets and does not copy protected frames, dialogue, soundtrack or character designs into the game."}
