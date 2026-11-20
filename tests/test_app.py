import io

import pytest
from PIL import Image

import app as app_module
from estimator import ai, storage


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTE_HELPER_DATA", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def jpeg_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), "red").save(buf, format="JPEG")
    return buf.getvalue()


FAKE_ESTIMATE = {
    "job_name": "Test job", "job_summary": "s", "scope_of_work": [], "assumptions": [],
    "questions_to_confirm": [], "waste_pct": 10, "consumables_allowance": 5, "consumables_note": "",
    "pricing_notes": "",
    "line_items": [{"category": "Paint", "item": "Paint", "spec": "", "quantity": 2, "unit": "gal",
                    "unit_price": 40, "price_low": 35, "price_high": 45, "supplier": "x", "source_url": "",
                    "is_local": True, "confidence": "high", "quantity_math": "", "notes": ""}],
}


def wait(client, task_id):
    import time
    for _ in range(100):
        t = client.get(f"/api/tasks/{task_id}").get_json()
        if t["status"] != "running":
            return t
        time.sleep(0.05)
    raise AssertionError("task did not finish")


def test_settings_hide_api_key(client):
    client.post("/api/settings", json={"api_key": "sk-ant-secret1234", "zip": "78701", "sales_tax_pct": "8.25"})
    s = client.get("/api/settings").get_json()
    assert "api_key" not in s and s["api_key_set"] and s["api_key_hint"] == "…1234"
    assert s["sales_tax_pct"] == 8.25
    client.post("/api/settings", json={"api_key": "", "zip": "78702"})  # blank keeps key
    assert storage.load_settings()["api_key"] == "sk-ant-secret1234"


def test_estimate_requires_key(client):
    r = client.post("/api/estimate", data={"notes": "x"})
    assert r.status_code == 400


def test_estimate_then_quote_check_flow(client, monkeypatch):
    client.post("/api/settings", json={"api_key": "sk-ant-x", "sales_tax_pct": 0})
    seen = {}

    def fake_estimate(settings, transcript, notes, photos, progress):
        seen["photos"] = photos
        progress("Searching: paint")
        return dict(FAKE_ESTIMATE)

    def fake_check(settings, quote_text, quote_pdf, prior, photos, progress):
        seen["prior"], seen["qphotos"] = prior, photos
        return {**FAKE_ESTIMATE, "quote_summary": "", "quote_line_items": [], "quote_subtotal_before_tax": 0,
                "quote_total": 500, "scope_differences": [], "warnings": []}

    monkeypatch.setattr(ai, "build_estimate", fake_estimate)
    monkeypatch.setattr(ai, "check_quote", fake_check)

    r = client.post("/api/estimate", data={"notes": "paint room", "photos": (io.BytesIO(jpeg_bytes()), "a.jpg")},
                    content_type="multipart/form-data")
    t = wait(client, r.get_json()["task_id"])
    assert t["status"] == "done", t
    assert seen["photos"][0]["source"]["media_type"] == "image/jpeg"

    job = client.get(f"/api/jobs/{t['job_id']}").get_json()
    assert job["name"] == "Test job" and job["photo_count"] == 1
    assert job["estimate"]["totals"]["expected"] == 93.0  # 80 * 1.1 + 5

    r = client.post("/api/check-quote", data={"job_id": job["id"], "quote_text": "Paint $500",
                                              "labor_hours": "4", "labor_rate": "50"})
    t = wait(client, r.get_json()["task_id"])
    assert t["status"] == "done", t
    assert seen["prior"]["notes"] == "paint room" and len(seen["qphotos"]) == 1
    job = client.get(f"/api/jobs/{job['id']}").get_json()
    assert job["quote_check"]["profit"]["expected"]["net_profit"] == 500 - 93 - 200

    job = client.post(f"/api/jobs/{job['id']}/items",
                      json={"kind": "quote_check", "edits": [{"index": 0, "unit_price": 50}]}).get_json()
    assert job["quote_check"]["totals"]["items_subtotal"] == 100

    csv_text = client.get(f"/api/jobs/{job['id']}/csv?kind=estimate").get_data(as_text=True)
    assert "Paint" in csv_text
    assert client.delete(f"/api/jobs/{job['id']}").get_json()["deleted"]
