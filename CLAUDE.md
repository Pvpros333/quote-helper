# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Quote Helper is a local Flask web app for a contractor who quotes in Jobber. It estimates **material** costs from an assessment (transcript, notes, photos) and checks a finished Jobber quote's material cost and profit. Pricing comes from Claude using server-side web search and web fetch. The end user is non-technical and runs it on macOS by double-clicking `Start Quote Helper.command`, which creates `.venv`, reinstalls requirements only when `requirements.txt` changes (stamp file in `.venv/`), and runs `app.py`.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py                      # serves http://127.0.0.1:5055 and opens a browser
.venv/bin/python -m pytest                   # all tests (pytest.ini sets pythonpath=.)
.venv/bin/python -m pytest tests/test_calc.py::test_material_totals   # one test
```

Environment variables: `QUOTE_HELPER_DATA` (data dir override; tests use tmp_path), `QUOTE_HELPER_PORT`, `QUOTE_HELPER_NO_BROWSER=1`, `ANTHROPIC_API_KEY` (used when no key is saved in Settings).

## Architecture

- `app.py` holds the Flask routes. The AI endpoints (`/api/estimate`, `/api/check-quote`) start a background thread. Its status and progress lines go in the in-memory `TASKS` dict, and the front end polls `/api/tasks/<id>`. Results are saved as a "job".
- `estimator/ai.py` is the only module that calls Claude: model `claude-opus-5-5`, adaptive thinking, effort `high`, `web_search_20260209` + `web_fetch_20260209` (with `user_location` taken from Settings), and server-side refusal fallback (`fallbacks="default"` + beta header) via `client.beta.messages.stream`. It loops on `pause_turn`. It requests structured output (`output_config.format`, schemas in `estimator/schemas.py`). On a 400 about format/citations it retries without the schema and parses JSON out of the text (`extract_json`/`_final_json`). Progress messages come from `content_block_stop` stream events.
- `estimator/calc.py` does **all** money math: line totals, waste, consumables, tax, the low/high range, and profit. The model only supplies quantities and unit prices. Totals are **never stored**. `app._with_totals()` recomputes them on every read, so changes to tax rate or hand edits flow through. Profit is measured against the quote's pre-tax subtotal when one was extracted.
- `estimator/storage.py` saves JSON files under `~/Library/Application Support/QuoteHelper/` on macOS (`~/.quote-helper` elsewhere): `settings.json` (holds the API key, chmod 600; the API never returns the key) and `jobs/<id>.json` + `jobs/<id>_photos/*.jpg`. A job can hold both an `estimate` and a `quote_check`. A quote check linked to a job reuses its transcript, notes, saved photos and earlier line items.
- `estimator/images.py` turns uploads (including iPhone HEIC via pillow-heif) into JPEG image blocks: EXIF-rotated, downscaled to 1568px. Quote PDFs are sent as `document` blocks.
- Front end: `templates/index.html` + `static/app.js` + `static/style.css`. Vanilla JS, no build step.

When changing a schema in `schemas.py`, keep every property in `required` with `additionalProperties: false` (a structured-outputs requirement), and update the rendering in `app.js` and the CSV export in `app.py`.
