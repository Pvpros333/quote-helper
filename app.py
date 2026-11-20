"""Quote Helper - local web app for estimating job material costs while quoting in Jobber.

Run:  python app.py   (opens http://127.0.0.1:5055 in your browser)
"""
import csv
import io
import os
import platform
import subprocess
import threading
import traceback
import uuid
import webbrowser

from flask import Flask, Response, jsonify, render_template, request

from estimator import ai, calc, images, storage

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # many full-size phone photos

PORT = int(os.environ.get("QUOTE_HELPER_PORT", "5055"))
TASKS: dict[str, dict] = {}  # in-memory background job status


# ---------- helpers ----------

def _num(name: str) -> float:
    try:
        return float(request.form.get(name) or 0)
    except ValueError:
        return 0.0


def _photos_from_request() -> list[dict]:
    blocks = []
    for f in request.files.getlist("photos")[: images.MAX_PHOTOS]:
        if not f or not f.filename:
            continue
        try:
            blocks.append(images.photo_to_block(f.read()))
        except Exception:
            raise ValueError(f"Couldn't read photo '{f.filename}'. Use JPG, PNG or HEIC.")
    return blocks


def _have_credentials(settings: dict) -> bool:
    return bool(settings.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _start_task(work) -> str:
    task_id = uuid.uuid4().hex
    task = {"status": "running", "progress": [], "job_id": None, "error": None}
    TASKS[task_id] = task

    def runner():
        try:
            task["job_id"] = work(task["progress"].append)
            task["status"] = "done"
        except ai.EstimateError as e:
            task["status"], task["error"] = "error", str(e)
        except Exception as e:  # surface anything unexpected in the UI
            traceback.print_exc()
            task["status"], task["error"] = "error", f"Unexpected error: {e}"

    threading.Thread(target=runner, daemon=True).start()
    return task_id


def _with_totals(job: dict) -> dict:
    """Recompute totals from line items so edits to tax rate etc. flow through."""
    tax = storage.load_settings().get("sales_tax_pct", 0)
    if job.get("estimate"):
        job["estimate"]["totals"] = calc.material_totals(job["estimate"], tax)
    if job.get("quote_check"):
        qc = job["quote_check"]
        qc["totals"] = calc.material_totals(qc, tax)
        labor = qc.get("labor", {})
        qc["profit"] = calc.profit(qc, qc["totals"], labor.get("hours", 0), labor.get("rate", 0),
                                   labor.get("other", 0))
    job["photo_count"] = storage.photo_count(job["id"])
    return job


# ---------- pages ----------

@app.get("/")
def index():
    return render_template("index.html")


# ---------- settings ----------

@app.get("/api/settings")
def get_settings():
    s = storage.load_settings()
    key = s.pop("api_key", "")
    s["api_key_set"] = bool(key) or bool(os.environ.get("ANTHROPIC_API_KEY"))
    s["api_key_hint"] = f"…{key[-4:]}" if key else ""
    return jsonify(s)


@app.post("/api/settings")
def post_settings():
    data = request.get_json(force=True) or {}
    if not data.get("api_key"):
        data.pop("api_key", None)  # blank field = keep existing key
    storage.save_settings(data)
    return get_settings()


# ---------- AI tasks ----------

class FormError(Exception):
    pass


def _estimate_form():
    transcript = request.form.get("transcript", "")
    notes = request.form.get("notes", "")
    try:
        photos = _photos_from_request()
    except ValueError as e:
        raise FormError(str(e))
    if not (transcript.strip() or notes.strip() or photos):
        raise FormError("Add a transcript, notes, or photos first.")
    job = storage.load_job(request.form.get("job_id", "")) or {}
    job.update(name=request.form.get("name", "").strip() or job.get("name", ""),
               transcript=transcript, notes=notes)
    return job, transcript, notes, photos


def _quote_form():
    quote_text = request.form.get("quote_text", "")
    pdf = request.files.get("quote_pdf")
    quote_pdf = images.pdf_to_block(pdf.read()) if pdf and pdf.filename else None
    if not (quote_text.strip() or quote_pdf):
        raise FormError("Paste the Jobber quote or attach its PDF.")
    try:
        new_photos = _photos_from_request()
    except ValueError as e:
        raise FormError(str(e))
    job = storage.load_job(request.form.get("job_id", "")) or {}
    prior = dict(job) if job.get("transcript") or job.get("notes") or job.get("estimate") else None
    saved_photos = storage.load_photos(job["id"]) if job.get("id") else []
    labor = {"hours": _num("labor_hours"), "rate": _num("labor_rate"), "other": _num("other_costs")}
    if request.form.get("name", "").strip():
        job["name"] = request.form["name"].strip()
    return job, prior, quote_text, quote_pdf, new_photos, saved_photos, labor


def _store_result(job: dict, kind: str, result: dict, new_photos: list[dict]) -> str:
    job[kind] = result
    job.pop("pending", None)
    if not job.get("name"):
        job["name"] = result.get("job_name", "")
    saved = storage.save_job(job)
    storage.save_photos(saved["id"], new_photos)
    return saved["id"]


@app.post("/api/estimate")
def start_estimate():
    settings = storage.load_settings()
    if not _have_credentials(settings):
        return jsonify(error="Add your Anthropic API key in Settings, or use \"Copy prompt\" instead."), 400
    try:
        job, transcript, notes, photos = _estimate_form()
    except FormError as e:
        return jsonify(error=str(e)), 400

    def work(progress):
        result = ai.build_estimate(settings, transcript, notes, photos, progress)
        return _store_result(job, "estimate", result, photos)

    return jsonify(task_id=_start_task(work))


@app.post("/api/check-quote")
def start_quote_check():
    settings = storage.load_settings()
    if not _have_credentials(settings):
        return jsonify(error="Add your Anthropic API key in Settings, or use \"Copy prompt\" instead."), 400
    try:
        job, prior, quote_text, quote_pdf, new_photos, saved_photos, labor = _quote_form()
    except FormError as e:
        return jsonify(error=str(e)), 400
    photos = (saved_photos + new_photos)[: images.MAX_PHOTOS]

    def work(progress):
        result = ai.check_quote(settings, quote_text, quote_pdf, prior, photos, progress)
        result.update(labor=labor, quote_text=quote_text)
        return _store_result(job, "quote_check", result, new_photos)

    return jsonify(task_id=_start_task(work))


# ---------- manual mode (no API key): copy prompt -> Claude app -> paste reply ----------

@app.post("/api/prompt/estimate")
def prompt_estimate():
    try:
        job, transcript, notes, photos = _estimate_form()
    except FormError as e:
        return jsonify(error=str(e)), 400
    text = ai.estimate_request_text(transcript, notes, len(photos))
    job["pending"] = {"kind": "estimate", "prompt": ai.manual_prompt(storage.load_settings(), text, "estimate"),
                      "photos": len(photos), "pdf": False}
    saved = storage.save_job(job)
    storage.save_photos(saved["id"], photos)
    return jsonify(job_id=saved["id"])


@app.post("/api/prompt/check-quote")
def prompt_quote_check():
    try:
        job, prior, quote_text, quote_pdf, new_photos, saved_photos, labor = _quote_form()
    except FormError as e:
        return jsonify(error=str(e)), 400
    n_photos = min(len(saved_photos) + len(new_photos), images.MAX_PHOTOS)
    text = ai.quote_request_text(quote_text, bool(quote_pdf), prior, n_photos)
    job["pending"] = {"kind": "quote_check", "prompt": ai.manual_prompt(storage.load_settings(), text, "quote_check"),
                      "photos": n_photos, "pdf": bool(quote_pdf), "labor": labor, "quote_text": quote_text}
    saved = storage.save_job(job)
    storage.save_photos(saved["id"], new_photos)
    return jsonify(job_id=saved["id"])


@app.post("/api/jobs/<job_id>/import")
def import_reply(job_id):
    j = storage.load_job(job_id)
    if not j or not j.get("pending"):
        return jsonify(error="This job isn't waiting for a Claude reply."), 404
    pending = j["pending"]
    try:
        result = ai.parse_pasted_reply((request.get_json(force=True) or {}).get("text", ""), pending["kind"])
    except ai.EstimateError as e:
        return jsonify(error=str(e)), 400
    if pending["kind"] == "quote_check":
        result.update(labor=pending.get("labor", {}), quote_text=pending.get("quote_text", ""))
    _store_result(j, pending["kind"], result, [])
    return jsonify(_with_totals(j))


@app.post("/api/jobs/<job_id>/cancel-pending")
def cancel_pending(job_id):
    j = storage.load_job(job_id)
    if not j:
        return jsonify(error="Job not found"), 404
    j.pop("pending", None)
    if not (j.get("estimate") or j.get("quote_check")):
        storage.delete_job(job_id)
        return jsonify(deleted=True)
    storage.save_job(j)
    return jsonify(_with_totals(j))


@app.post("/api/jobs/<job_id>/reveal-photos")
def reveal_photos(job_id):
    """Open the job's saved photos in Finder so they can be dragged into the Claude app."""
    d = storage.photo_dir(job_id)
    if not d.exists() or not any(d.iterdir()):
        return jsonify(error="No saved photos for this job."), 404
    if platform.system() != "Darwin":
        return jsonify(path=str(d))
    subprocess.run(["open", str(d)], check=False)
    return jsonify(opened=True, path=str(d))


@app.get("/api/tasks/<task_id>")
def task_status(task_id):
    task = TASKS.get(task_id)
    if not task:
        return jsonify(error="Unknown task (the app may have restarted)."), 404
    return jsonify(task)


# ---------- jobs ----------

@app.get("/api/jobs")
def jobs():
    rows = storage.list_jobs()
    for row in rows:
        j = _with_totals(storage.load_job(row["id"]))
        row["estimate_total"] = (j.get("estimate") or {}).get("totals", {}).get("expected")
        row["quote_total"] = (j.get("quote_check") or {}).get("profit", {}).get("quote_total")
    return jsonify(rows)


@app.get("/api/jobs/<job_id>")
def job(job_id):
    j = storage.load_job(job_id)
    if not j:
        return jsonify(error="Job not found"), 404
    return jsonify(_with_totals(j))


@app.delete("/api/jobs/<job_id>")
def remove_job(job_id):
    return jsonify(deleted=storage.delete_job(job_id))


@app.post("/api/jobs/<job_id>/labor")
def update_labor(job_id):
    """Change labor hours/rate on a quote check and recompute profit (no AI call)."""
    j = storage.load_job(job_id)
    if not j or not j.get("quote_check"):
        return jsonify(error="No quote check on this job"), 404
    data = request.get_json(force=True) or {}
    j["quote_check"]["labor"] = {k: float(data.get(k) or 0) for k in ("hours", "rate", "other")}
    storage.save_job(j)
    return jsonify(_with_totals(j))


@app.post("/api/jobs/<job_id>/items")
def update_items(job_id):
    """Save hand-edited quantities/prices for an estimate or quote check."""
    j = storage.load_job(job_id)
    data = request.get_json(force=True) or {}
    kind = data.get("kind")
    if not j or kind not in ("estimate", "quote_check") or not j.get(kind):
        return jsonify(error="Nothing to update"), 404
    items = j[kind].get("line_items", [])
    for edit in data.get("edits", []):
        i = int(edit.get("index", -1))
        if 0 <= i < len(items):
            for field in ("quantity", "unit_price"):
                if field in edit:
                    items[i][field] = float(edit[field] or 0)
    if data.get("delete") is not None:
        i = int(data["delete"])
        if 0 <= i < len(items):
            items.pop(i)
    storage.save_job(j)
    return jsonify(_with_totals(j))


@app.get("/api/jobs/<job_id>/csv")
def job_csv(job_id):
    kind = request.args.get("kind", "estimate")
    j = storage.load_job(job_id)
    if not j or not j.get(kind):
        return jsonify(error="Nothing to export"), 404
    j = _with_totals(j)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Category", "Item", "Spec", "Qty", "Unit", "Unit price", "Line total",
                "Low", "High", "Supplier", "Local", "Confidence", "Source"])
    for it in j[kind].get("line_items", []):
        w.writerow([it.get("category"), it.get("item"), it.get("spec"), it.get("quantity"), it.get("unit"),
                    it.get("unit_price"), it.get("line_total"), it.get("price_low"), it.get("price_high"),
                    it.get("supplier"), "yes" if it.get("is_local") else "no", it.get("confidence"),
                    it.get("source_url")])
    t = j[kind]["totals"]
    w.writerow([])
    for label, key in (("Items subtotal", "items_subtotal"), ("Waste", "waste_amount"),
                       ("Consumables", "consumables"), ("Sales tax", "sales_tax"),
                       ("TOTAL (expected)", "expected"), ("Range low", "low"), ("Range high", "high")):
        w.writerow(["", label, "", "", "", "", t[key]])
    name = "".join(c if c.isalnum() else "_" for c in (j.get("name") or "job"))[:40]
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}_{kind}.csv"'})


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  Quote Helper is running at {url}\n  Keep this window open. Press Ctrl+C to quit.\n")
    if not os.environ.get("QUOTE_HELPER_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
