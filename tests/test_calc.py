from estimator import calc


def sample():
    return {
        "line_items": [
            {"quantity": 10, "unit_price": 5.0, "price_low": 4.0, "price_high": 6.0},
            {"quantity": 2, "unit_price": 25.0, "price_low": 0, "price_high": 30.0},
        ],
        "waste_pct": 10,
        "consumables_allowance": 20,
    }


def test_material_totals():
    r = sample()
    t = calc.material_totals(r, sales_tax_pct=8)
    assert t["items_subtotal"] == 100.0
    assert t["waste_amount"] == 10.0
    assert t["pre_tax"] == 130.0
    assert t["sales_tax"] == 10.4
    assert t["expected"] == 140.4
    # low falls back to unit_price when price_low is 0: (40 + 50) * 1.1 + 20 = 119 -> *1.08
    assert t["low"] == round(119 * 1.08, 2)
    assert t["high"] == round((60 + 60) * 1.1 * 1.08 + 20 * 1.08, 2)
    assert r["line_items"][0]["line_total"] == 50.0


def test_profit_uses_pretax_quote_when_available():
    r = sample()
    t = calc.material_totals(r, 0)  # expected = 130
    qc = {"quote_total": 1080, "quote_subtotal_before_tax": 1000}
    p = calc.profit(qc, t, labor_hours=10, labor_rate=40, other_costs=20)
    assert p["revenue_basis"] == 1000
    assert p["expected"]["gross_after_materials"] == 870
    assert p["expected"]["net_profit"] == 870 - 400 - 20
    assert p["expected"]["net_margin_pct"] == 45.0


def test_profit_handles_missing_quote():
    t = calc.material_totals({"line_items": []}, 0)
    p = calc.profit({}, t)
    assert p["expected"]["gross_margin_pct"] == 0.0
