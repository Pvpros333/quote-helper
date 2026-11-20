"""Totals and profit math. Done in Python, never trusted to the model."""


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def material_totals(result: dict, sales_tax_pct: float) -> dict:
    items = result.get("line_items") or []
    expected = low = high = 0.0
    for it in items:
        qty = _num(it.get("quantity"))
        price = _num(it.get("unit_price"))
        lo = _num(it.get("price_low")) or price
        hi = _num(it.get("price_high")) or price
        it["line_total"] = round(qty * price, 2)
        expected += qty * price
        low += qty * lo
        high += qty * hi

    waste_pct = _num(result.get("waste_pct"))
    consumables = _num(result.get("consumables_allowance"))
    tax_rate = _num(sales_tax_pct) / 100

    def total(subtotal: float) -> float:
        with_waste = subtotal * (1 + waste_pct / 100) + consumables
        return round(with_waste * (1 + tax_rate), 2)

    waste_amt = expected * waste_pct / 100
    pre_tax = expected + waste_amt + consumables
    return {
        "items_subtotal": round(expected, 2),
        "waste_pct": waste_pct,
        "waste_amount": round(waste_amt, 2),
        "consumables": round(consumables, 2),
        "pre_tax": round(pre_tax, 2),
        "sales_tax_pct": _num(sales_tax_pct),
        "sales_tax": round(pre_tax * tax_rate, 2),
        "expected": total(expected),
        "low": total(low),
        "high": total(high),
    }


def profit(quote_check: dict, totals: dict, labor_hours: float = 0, labor_rate: float = 0,
           other_costs: float = 0) -> dict:
    """Profit is measured against the pre-tax quote amount when Jobber shows one."""
    quote_total = _num(quote_check.get("quote_total"))
    revenue = _num(quote_check.get("quote_subtotal_before_tax")) or quote_total
    labor = _num(labor_hours) * _num(labor_rate)
    other = _num(other_costs)

    def calc(material: float) -> dict:
        gross = revenue - material
        net = gross - labor - other
        return {
            "material_cost": round(material, 2),
            "gross_after_materials": round(gross, 2),
            "gross_margin_pct": round(gross / revenue * 100, 1) if revenue else 0.0,
            "net_profit": round(net, 2),
            "net_margin_pct": round(net / revenue * 100, 1) if revenue else 0.0,
        }

    return {
        "quote_total": round(quote_total, 2),
        "revenue_basis": round(revenue, 2),
        "labor_cost": round(labor, 2),
        "other_costs": round(other, 2),
        "material_pct_of_quote": round(totals["expected"] / revenue * 100, 1) if revenue else 0.0,
        "expected": calc(totals["expected"]),
        "best_case": calc(totals["low"]),
        "worst_case": calc(totals["high"]),
    }
