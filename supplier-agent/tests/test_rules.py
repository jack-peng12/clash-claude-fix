from app.services import rules as R
from app.services.extractor import company_name, extract_contacts, normalize_phone, registered_domain
from app.services.requirement_parser import parse_rules
from app.skills.defaults import CRITERIA, INTENT_SIGNALS, OPT_OUT_PATTERNS, RISK_RULES

HANDOFF = {"signals": INTENT_SIGNALS, "levels": {"high": 60, "medium": 35, "low": 10}, "handoff_threshold": 60,
           "hard_combos": [["has_inventory", "provided_price"], ["provided_price", "matches_criteria"]],
           "single_keyword_cap": 15}


def test_parse_chinese_requirement_levels():
    spec = parse_rules("找10家英国现成公司，必须带VAT，企业银行账户最好有，董事待确认，不要求EORI，预算3000英镑", CRITERIA)
    assert [c["iso"] for c in spec["countries"]] == ["GB"]
    lv = spec["levels"]
    assert lv["vat_registered"] == "required"
    assert lv["bank_account"] == "preferred"
    assert lv["director_continue"] == "to_confirm"
    assert lv["eori"] == "not_required"
    assert spec["params"]["max_price"] == 3000 and spec["params"]["currency"] == "GBP"
    assert spec["target_suppliers"] == 10


def test_parse_any_country_and_multiple():
    spec = parse_rules("捷克和马耳他的s.r.o.现成公司，埃及也可以", CRITERIA)
    assert {c["iso"] for c in spec["countries"]} == {"CZ", "MT", "EG"}
    assert "s.r.o." in spec["company_types"]


def test_prices_various_formats():
    p = R.find_prices("Price GBP 1,500 or €2.900 or 3 400 EUR, also $99.99 and 12% off")
    amounts = {(x["currency"], x["amount"]) for x in p}
    assert ("GBP", 1500) in amounts and ("EUR", 2900) in amounts and ("EUR", 3400) in amounts
    assert ("USD", 99.99) in amounts
    assert all(x["amount"] >= 50 for x in p)


def test_negative_keywords_win():
    d = R.detect_criteria("The company is sold without bank account but VAT registered.", CRITERIA)
    assert d["bank_account"]["polarity"] == "no"
    assert d["vat_registered"]["polarity"] == "yes"


def test_strip_quoted_removes_our_questions():
    body = "We have 2 companies.\n\nOn Mon, 1 Jan 2026 Buyer wrote:\n> Is the company VAT registered?\n> bank account?"
    assert "VAT" not in R.strip_quoted(body)
    assert "bank account" not in R.answered_keys(body, CRITERIA)


def test_screening_categories():
    rules = {"criteria": CRITERIA, "weights": {"required": 3, "preferred": 1}}
    lv = {"vat_registered": "required", "bank_account": "preferred"}
    assert R.screen(True, lv, {"vat_registered": "yes"}, "low", rules)["category"] == "match"
    assert R.screen(True, lv, {}, "low", rules)["category"] == "insufficient"
    assert R.screen(True, lv, {"vat_registered": "no"}, "low", rules)["category"] == "no_match"
    assert R.screen(True, lv, {"vat_registered": "yes"}, "high", rules)["category"] == "high_risk"
    assert R.screen(False, lv, {"vat_registered": "yes"}, "low", rules)["category"] == "no_match"


def test_intent_requires_multiple_signals():
    weak = R.compute_intent("Can you send the contract and invoice details? payment by card?", HANDOFF, CRITERIA, [],
                            OPT_OUT_PATTERNS)
    assert not weak["handoff"], weak
    strong = R.compute_intent("We currently have 2 UK companies. Price is £1,900 each.", HANDOFF, CRITERIA, [],
                              OPT_OUT_PATTERNS)
    assert strong["handoff"] and "provided_price" in strong["signals"]
    refusal = R.compute_intent("Sorry, we don't sell companies. Please remove us.", HANDOFF, CRITERIA, [],
                               OPT_OUT_PATTERNS)
    assert refusal["refusal"] and not refusal["handoff"]


def test_out_of_stock_is_not_inventory_signal():
    r = R.compute_intent("Unfortunately no companies available right now.", HANDOFF, CRITERIA, [], OPT_OUT_PATTERNS)
    assert "has_inventory" not in r["signals"]


def test_next_questions_never_repeat_answered_or_overasked():
    lv = {"vat_registered": "required", "bank_account": "required", "director_continue": "preferred"}
    q = R.next_questions(lv, {"vat_registered": {"answered": True}, "bank_account": {"asked_count": 2}},
                         {"max_asks_per_question": 2, "max_questions_per_message": 3})
    assert q == ["director_continue"]


def test_followup_decisions():
    rules = {"schedule_days": [3, 7, 14], "max_followups": 3, "stop_statuses": ["human_takeover", "opted_out"]}
    assert R.followup_decision({"status": "contacted", "days_since_out": 2, "followups": 0}, rules)["action"] == "wait"
    assert R.followup_decision({"status": "contacted", "days_since_out": 8, "followups": 1}, rules)["action"] == "followup"
    assert R.followup_decision({"status": "opted_out", "days_since_out": 99, "followups": 0}, rules)["action"] == "stop"
    assert R.followup_decision({"status": "contacted", "days_since_out": 99, "followups": 0,
                                "replied_after": True}, rules)["action"] == "wait"


def test_risk_levels():
    assert R.detect_risk("We offer guaranteed amazon approval", RISK_RULES)["level"] == "high"
    assert R.detect_risk("Payment via Western Union only", RISK_RULES)["level"] == "medium"
    assert R.detect_risk("Standard UK shelf companies", RISK_RULES)["level"] == "low"


def test_forbidden_phrases():
    assert R.check_forbidden("Great, we will pay tomorrow", ["we will pay"])
    assert not R.check_forbidden("Could you share your price?", ["we will pay"])


def test_extract_contacts_and_name():
    html = """<html><head><title>Foo Formations | Shelf companies</title>
    <script type="application/ld+json">{"@type":"Organization","name":"Foo Formations GmbH"}</script></head>
    <body><a href="mailto:info@foo.de">mail</a> <a href="tel:+49 30 1234567">call</a>
    <a href="https://wa.me/4915112345678">wa</a> <a href="https://t.me/foo_formations">tg</a>
    <span class="__cf_email__" data-cfemail="4f262129200f292020612b2a">[email protected]</span>
    image@2x.png noreply@foo.de</body></html>"""
    text = "Write to sales@foo.de or call 0049 30 7654321"
    cs = extract_contacts(html, text)
    got = {(c["ctype"], c["normalized"]) for c in cs}
    assert ("email", "info@foo.de") in got and ("email", "sales@foo.de") in got
    assert ("email", "info@foo.de") in got
    assert ("whatsapp", "+4915112345678") in got and ("telegram", "foo_formations") in got
    assert ("phone", "+49307654321") in got
    assert not any("noreply" in n or "2x" in n for _, n in got)
    assert company_name(html, "Foo Formations | Shelf companies", "foo.de") == "Foo Formations GmbH"
    assert normalize_phone("0044 20 7946 0000") == "+442079460000"
    assert registered_domain("https://www.shop.example.co.uk/x") == "example.co.uk"
