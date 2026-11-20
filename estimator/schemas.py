"""JSON schemas for Claude's structured output (output_config.format).

Every property is required and additionalProperties is false, as structured
outputs require. "Unknown" values are expressed as "" or 0 rather than null.
"""

LINE_ITEM = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "description": "e.g. Lumber, Electrical, Plumbing, Paint, Fasteners, Rental/Disposal"},
        "item": {"type": "string"},
        "spec": {"type": "string", "description": "size / grade / model / color"},
        "quantity": {"type": "number"},
        "unit": {"type": "string", "description": "ea, box, sheet, gal, lf, sqft, bag, roll..."},
        "unit_price": {"type": "number", "description": "best realistic current price per unit, USD"},
        "price_low": {"type": "number", "description": "lowest unit price found"},
        "price_high": {"type": "number", "description": "highest unit price found"},
        "supplier": {"type": "string", "description": "store/site the unit_price came from"},
        "source_url": {"type": "string", "description": "page the price was read from, or empty if estimated"},
        "is_local": {"type": "boolean", "description": "true if available for pickup near the job location"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "quantity_math": {"type": "string", "description": "how the quantity was calculated"},
        "notes": {"type": "string"},
    },
    "required": [
        "category", "item", "spec", "quantity", "unit", "unit_price", "price_low",
        "price_high", "supplier", "source_url", "is_local", "confidence",
        "quantity_math", "notes",
    ],
    "additionalProperties": False,
}

_STR_LIST = {"type": "array", "items": {"type": "string"}}

ESTIMATE = {
    "type": "object",
    "properties": {
        "job_name": {"type": "string", "description": "short name for the job"},
        "job_summary": {"type": "string"},
        "scope_of_work": _STR_LIST,
        "assumptions": _STR_LIST,
        "questions_to_confirm": _STR_LIST,
        "line_items": {"type": "array", "items": LINE_ITEM},
        "waste_pct": {"type": "number"},
        "consumables_allowance": {"type": "number", "description": "USD for small fasteners, caulk, tape, blades etc. not itemized"},
        "consumables_note": {"type": "string"},
        "pricing_notes": {"type": "string"},
    },
    "required": [
        "job_name", "job_summary", "scope_of_work", "assumptions", "questions_to_confirm",
        "line_items", "waste_pct", "consumables_allowance", "consumables_note", "pricing_notes",
    ],
    "additionalProperties": False,
}

QUOTE_LINE = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "quantity": {"type": "number"},
        "unit_price": {"type": "number"},
        "total": {"type": "number"},
    },
    "required": ["name", "description", "quantity", "unit_price", "total"],
    "additionalProperties": False,
}

QUOTE_CHECK = {
    "type": "object",
    "properties": {
        "job_name": {"type": "string"},
        "quote_summary": {"type": "string"},
        "quote_line_items": {"type": "array", "items": QUOTE_LINE},
        "quote_subtotal_before_tax": {"type": "number", "description": "0 if not shown"},
        "quote_total": {"type": "number", "description": "grand total the customer pays"},
        "line_items": {"type": "array", "items": LINE_ITEM, "description": "materials needed to do the quoted work"},
        "waste_pct": {"type": "number"},
        "consumables_allowance": {"type": "number"},
        "consumables_note": {"type": "string"},
        "scope_differences": {**_STR_LIST, "description": "differences between the quote and the assessment/estimate, if one was given"},
        "warnings": {**_STR_LIST, "description": "things that could hurt profit: missing items, underpriced lines, etc."},
        "pricing_notes": {"type": "string"},
    },
    "required": [
        "job_name", "quote_summary", "quote_line_items", "quote_subtotal_before_tax", "quote_total",
        "line_items", "waste_pct", "consumables_allowance", "consumables_note",
        "scope_differences", "warnings", "pricing_notes",
    ],
    "additionalProperties": False,
}
