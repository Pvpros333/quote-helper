"""Claude calls: build the request, run web-search pricing research, return parsed JSON."""
import json
import re
from typing import Callable

import anthropic

from . import schemas

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_CONTINUATIONS = 8  # pause_turn resumes when the server-side search loop runs long

Progress = Callable[[str], None]


class EstimateError(Exception):
    pass


def _location(settings: dict) -> str:
    parts = [settings.get("city"), settings.get("state"), settings.get("zip")]
    loc = ", ".join(p for p in parts if p)
    return loc or "(no location set - use typical US pricing)"


def system_prompt(settings: dict) -> str:
    return f"""You are a material cost estimator for a {settings.get('trade') or 'contracting'} business \
that builds quotes in Jobber. The business is located in {_location(settings)}. \
Preferred suppliers: {settings.get('preferred_suppliers') or 'any'}.

Your job is to produce an accurate MATERIAL cost (not labor) for a job, using live prices from the web.

How to work:
1. Read everything provided (assessment transcript, notes, photos, quote). Work out the full scope and the \
material list, with quantities calculated from any measurements given. Look at photos for sizes, existing \
materials, finishes, fixture types, and conditions that change what's needed. Show the quantity math.
2. Use web search and web fetch to find CURRENT prices. Prioritize stores where the business can pick up \
near {settings.get('zip') or 'the job location'} (local store pages for big-box stores, local lumber yards and \
supply houses), then compare with major online retailers. Spend searches on the most expensive items first; \
small consumables can go in the consumables allowance instead of being itemized.
3. For every itemized line give a realistic unit_price, the low and high unit prices you saw, the supplier, \
and the exact source_url you read the price from. Never invent a URL: if you could not verify a price, \
estimate it from what you know, leave source_url empty, and set confidence to "low".
4. Set waste_pct sensibly for the materials involved (business default is {settings.get('default_waste_pct', 10)}%). \
Do not include sales tax or labor - the app adds tax itself.
5. List assumptions you made and questions the contractor should confirm with the customer.

Your final answer must be the JSON object only."""


def _client(settings: dict) -> anthropic.Anthropic:
    key = settings.get("api_key") or None  # None -> env var / `ant auth login` profile
    return anthropic.Anthropic(api_key=key, max_retries=3)


def _tools(settings: dict) -> list[dict]:
    search = {"type": "web_search_20260209", "name": "web_search", "max_uses": 30}
    loc = {k: v for k, v in {
        "type": "approximate",
        "city": settings.get("city"),
        "region": settings.get("state"),
        "country": "US",
    }.items() if v}
    if len(loc) > 2:  # more than type + country
        search["user_location"] = loc
    return [search, {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 20}]


def _report(block, progress: Progress) -> None:
    btype = getattr(block, "type", "")
    if btype == "server_tool_use":
        inp = getattr(block, "input", {}) or {}
        if block.name == "web_search":
            progress(f"Searching: {inp.get('query', '')}")
        elif block.name == "web_fetch":
            progress(f"Reading: {inp.get('url', '')}")
    elif btype == "web_search_tool_result":
        content = getattr(block, "content", None)
        if isinstance(content, list):
            progress(f"  found {len(content)} results")
    elif btype == "fallback":
        progress("Primary model declined; continuing on fallback model")


def extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("no JSON object found")


def _final_json(content) -> dict:
    texts = [b.text for b in content if getattr(b, "type", "") == "text"]
    # Prefer the trailing text block(s): narration may precede tool calls.
    for i in range(len(texts) - 1, -1, -1):
        for candidate in (texts[i], "".join(texts[i:])):
            try:
                return extract_json(candidate)
            except ValueError:
                continue
    raise EstimateError("Claude finished but did not return a readable result. Try again.")


def _run(settings: dict, user_content: list, schema: dict, progress: Progress) -> dict:
    client = _client(settings)
    messages = [{"role": "user", "content": user_content}]
    use_schema = True
    continuations = 0
    progress("Sending job details to Claude…")

    while True:
        kwargs = dict(
            model=MODEL,
            max_tokens=64000,
            system=system_prompt(settings),
            thinking={"type": "adaptive"},
            tools=_tools(settings),
            messages=messages,
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        if use_schema:
            kwargs["output_config"] = {"effort": "high", "format": {"type": "json_schema", "schema": schema}}
        else:
            kwargs["output_config"] = {"effort": "high"}
        try:
            with client.beta.messages.stream(**kwargs) as stream:
                for event in stream:
                    if event.type == "content_block_stop":
                        _report(event.content_block, progress)
                response = stream.get_final_message()
        except anthropic.BadRequestError as e:
            if use_schema and ("format" in str(e).lower() or "citation" in str(e).lower()):
                # Fall back to asking for JSON in plain text.
                use_schema = False
                messages[0]["content"] = user_content + [{
                    "type": "text",
                    "text": "Return the final answer as one JSON object matching this schema, and nothing else:\n"
                            + json.dumps(schema),
                }]
                progress("Retrying in compatibility mode…")
                continue
            raise EstimateError(f"Request rejected: {e.message}") from e
        except anthropic.AuthenticationError as e:
            raise EstimateError("Your Anthropic API key was rejected. Check it in Settings.") from e
        except anthropic.RateLimitError as e:
            raise EstimateError("Rate limited by the Anthropic API. Wait a minute and try again.") from e
        except anthropic.APIConnectionError as e:
            raise EstimateError("Could not reach the Anthropic API. Check your internet connection.") from e
        except anthropic.APIStatusError as e:
            raise EstimateError(f"Anthropic API error ({e.status_code}): {e.message}") from e

        if response.stop_reason == "pause_turn" and continuations < MAX_CONTINUATIONS:
            continuations += 1
            messages.append({"role": "assistant", "content": response.content})
            progress("Still researching prices…")
            continue
        if response.stop_reason == "refusal":
            raise EstimateError("Claude declined this request. Try rewording the notes.")
        if response.stop_reason == "max_tokens":
            raise EstimateError("The response was too long. Try splitting the job into smaller parts.")

        usage = response.usage
        progress(f"Done. ({usage.input_tokens:,} input / {usage.output_tokens:,} output tokens)")
        return _final_json(response.content)


def estimate_request_text(transcript: str, notes: str, n_photos: int) -> str:
    return (
        "Estimate the material cost for this job.\n\n"
        f"<assessment_transcript>\n{transcript.strip() or '(none provided)'}\n</assessment_transcript>\n\n"
        f"<job_notes>\n{notes.strip() or '(none provided)'}\n</job_notes>\n\n"
        f"{n_photos} photo(s) from the assessment are attached."
    )


def quote_request_text(quote_text: str, has_pdf: bool, prior_job: dict | None, n_photos: int) -> str:
    parts = [
        "Here is a finished quote from Jobber. Extract the quote's line items and totals, then work out "
        "the materials needed to do exactly the quoted work and price them with current prices.",
        f"<jobber_quote>\n{quote_text.strip() or '(see the attached quote PDF)'}\n</jobber_quote>",
    ]
    if has_pdf and quote_text.strip():
        parts.append("The quote PDF is also attached.")
    if prior_job:
        parts.append(
            "This job was assessed earlier. Use it for context and to reuse prices already found "
            "(re-check the expensive items). Note any scope differences between the quote and the assessment.\n"
            f"<assessment_transcript>\n{prior_job.get('transcript', '')}\n</assessment_transcript>\n"
            f"<job_notes>\n{prior_job.get('notes', '')}\n</job_notes>"
        )
        if prior_job.get("estimate"):
            est = {k: prior_job["estimate"].get(k) for k in ("scope_of_work", "line_items", "assumptions")}
            parts.append(f"<earlier_material_estimate>\n{json.dumps(est)}\n</earlier_material_estimate>")
    if n_photos:
        parts.append(f"{n_photos} photo(s) from the assessment are attached.")
    return "\n\n".join(parts)


def build_estimate(settings: dict, transcript: str, notes: str, photos: list[dict],
                   progress: Progress) -> dict:
    content: list = list(photos)
    content.append({"type": "text", "text": estimate_request_text(transcript, notes, len(photos))})
    return normalize(_run(settings, content, schemas.ESTIMATE, progress), schemas.ESTIMATE)


def check_quote(settings: dict, quote_text: str, quote_pdf: dict | None, prior_job: dict | None,
                photos: list[dict], progress: Progress) -> dict:
    content: list = list(photos)
    if quote_pdf:
        content.append(quote_pdf)
    content.append({"type": "text",
                    "text": quote_request_text(quote_text, bool(quote_pdf), prior_job, len(photos))})
    return normalize(_run(settings, content, schemas.QUOTE_CHECK, progress), schemas.QUOTE_CHECK)


# ---------- manual mode: run the prompt in the Claude app, paste the reply back ----------

SCHEMAS = {"estimate": schemas.ESTIMATE, "quote_check": schemas.QUOTE_CHECK}


def manual_prompt(settings: dict, request_text: str, kind: str) -> str:
    """One self-contained prompt to paste into the Claude app (claude.ai / desktop / mobile)."""
    return f"""{system_prompt(settings)}

Use web search to look up current prices. Do not skip the searching.

{request_text}

When you are finished, reply with ONLY one JSON object inside a ```json code block, matching this JSON schema \
(every field is required; use "" or 0 when something is unknown). It will be pasted into a program, so do not \
put any text after the code block.

{json.dumps(SCHEMAS[kind], separators=(",", ":"))}
"""


def parse_pasted_reply(text: str, kind: str) -> dict:
    try:
        data = extract_json(text)
    except (ValueError, json.JSONDecodeError) as e:
        raise EstimateError(
            "Couldn't find the results in what you pasted. Copy Claude's whole final reply "
            "(the part in the code block) and paste it again."
        ) from e
    if not isinstance(data, dict) or not isinstance(data.get("line_items"), list):
        raise EstimateError("The pasted reply doesn't contain a material list. Ask Claude to finish, then paste again.")
    return normalize(data, SCHEMAS[kind])


def _coerce(value, schema: dict):
    t = schema.get("type")
    if t == "object":
        return normalize(value if isinstance(value, dict) else {}, schema)
    if t == "array":
        if not isinstance(value, list):
            return []
        return [_coerce(v, schema.get("items", {})) for v in value]
    if t in ("number", "integer"):
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(re.sub(r"[^0-9.\-]", "", str(value)) or 0)
        except ValueError:
            return 0.0
    if t == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "y", "1")
        return bool(value)
    if t == "string":
        value = "" if value is None else str(value)
        enum = schema.get("enum")
        if enum and value not in enum:
            return "low" if "low" in enum else enum[0]
        return value
    return value


def normalize(data: dict, schema: dict) -> dict:
    """Fill in missing fields and fix types so slightly-off JSON still renders and totals correctly."""
    out = dict(data)
    for key, sub in schema.get("properties", {}).items():
        out[key] = _coerce(data.get(key), sub)
    return out
