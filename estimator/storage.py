"""Local storage for settings and saved jobs (plain JSON files on disk)."""
import base64
import json
import os
import platform
import shutil
import uuid
from datetime import datetime
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("QUOTE_HELPER_DATA")
    if override:
        d = Path(override)
    elif platform.system() == "Darwin":
        d = Path.home() / "Library" / "Application Support" / "QuoteHelper"
    else:
        d = Path.home() / ".quote-helper"
    (d / "jobs").mkdir(parents=True, exist_ok=True)
    return d


DEFAULT_SETTINGS = {
    "api_key": "",
    "business_name": "",
    "trade": "general contracting / handyman",
    "city": "",
    "state": "",
    "zip": "",
    "sales_tax_pct": 0.0,
    "preferred_suppliers": "Home Depot, Lowe's, local supply houses",
    "default_waste_pct": 10.0,
}


def load_settings() -> dict:
    path = data_dir() / "settings.json"
    settings = dict(DEFAULT_SETTINGS)
    if path.exists():
        try:
            settings.update(json.loads(path.read_text()))
        except json.JSONDecodeError:
            pass
    return settings


def save_settings(new: dict) -> dict:
    settings = load_settings()
    for key, default in DEFAULT_SETTINGS.items():
        if key not in new:
            continue
        value = new[key]
        if isinstance(default, float):
            try:
                value = float(value or 0)
            except (TypeError, ValueError):
                value = default
        else:
            value = str(value).strip()
        settings[key] = value
    path = data_dir() / "settings.json"
    path.write_text(json.dumps(settings, indent=2))
    try:
        path.chmod(0o600)  # file holds the API key
    except OSError:
        pass
    return settings


def save_job(job: dict) -> dict:
    job.setdefault("id", datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
    job.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    job["updated_at"] = datetime.now().isoformat(timespec="seconds")
    (data_dir() / "jobs" / f"{job['id']}.json").write_text(json.dumps(job, indent=2))
    return job


def _safe_id(job_id: str) -> str:
    return "".join(c for c in job_id if c.isalnum() or c in "-_")


def load_job(job_id: str) -> dict | None:
    path = data_dir() / "jobs" / f"{_safe_id(job_id)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _photo_dir(job_id: str) -> Path:
    return data_dir() / "jobs" / f"{_safe_id(job_id)}_photos"


def save_photos(job_id: str, blocks: list[dict]) -> None:
    """Store the processed JPEGs so a later quote check can reuse them."""
    if not blocks:
        return
    d = _photo_dir(job_id)
    d.mkdir(exist_ok=True)
    start = len(list(d.glob("*.jpg")))
    for i, block in enumerate(blocks, start=start + 1):
        (d / f"photo_{i:02d}.jpg").write_bytes(base64.standard_b64decode(block["source"]["data"]))


def load_photos(job_id: str) -> list[dict]:
    d = _photo_dir(job_id)
    if not d.exists():
        return []
    return [{
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg",
                   "data": base64.standard_b64encode(p.read_bytes()).decode("ascii")},
    } for p in sorted(d.glob("*.jpg"))]


def photo_count(job_id: str) -> int:
    d = _photo_dir(job_id)
    return len(list(d.glob("*.jpg"))) if d.exists() else 0


def delete_job(job_id: str) -> bool:
    path = data_dir() / "jobs" / f"{_safe_id(job_id)}.json"
    shutil.rmtree(_photo_dir(job_id), ignore_errors=True)
    if path.exists():
        path.unlink()
        return True
    return False


def list_jobs() -> list[dict]:
    jobs = []
    for path in sorted((data_dir() / "jobs").glob("*.json"), reverse=True):
        try:
            job = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        jobs.append({
            "id": job.get("id"),
            "name": job.get("name") or "(untitled job)",
            "created_at": job.get("created_at"),
            "has_estimate": bool(job.get("estimate")),
            "has_quote_check": bool(job.get("quote_check")),
        })
    return jobs
