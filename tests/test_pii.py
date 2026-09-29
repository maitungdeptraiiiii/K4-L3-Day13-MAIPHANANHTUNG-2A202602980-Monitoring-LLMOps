from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_cccd() -> None:
    out = scrub_text("CCCD cua toi la 012345678901")
    assert "012345678901" not in out
    assert "REDACTED_CCCD" in out


def test_scrub_credit_card_formats() -> None:
    for card in ("4111111111111111", "4111 1111 1111 1111", "4111-1111-1111-1111"):
        out = scrub_text(f"Card: {card}")
        assert card not in out
        assert "REDACTED_CREDIT_CARD" in out


def test_scrub_passport() -> None:
    out = scrub_text("Passport B1234567 please")
    assert "B1234567" not in out
    assert "REDACTED_PASSPORT_VN" in out


def test_scrub_leaves_clean_text_untouched() -> None:
    text = "Explain metrics, logs and traces."
    assert scrub_text(text) == text


def test_scrub_event_masks_payload_and_event() -> None:
    from app.logging_config import scrub_event

    out = scrub_event(None, "info", {"event": "mail a@b.co", "payload": {"m": "call 0901234567"}})
    assert "a@b.co" not in out["event"]
    assert "0901234567" not in out["payload"]["m"]
