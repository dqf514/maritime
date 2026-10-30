"""Email classification regressions — noon reports must not become NOR."""

from app.services.email_intelligence import classify_email


def test_noon_report_subjects_are_not_nor():
    for subject in (
        "MV. Lestari Kuala Lumpur / Noon Report at Port on 30 Oct 2026",
        "RE: REMINDER: CARL OLDENDORFF NOON REPORT 25.10.2026",
        "GUO HAI LIAN 806//NOON REPORT",
        "Guo Hai Lian 681// Daily NOON  REPORT 2026/10/30/1200LT",
        "GUO HAI LIAN 568 Mirror noon Auto Generated",
    ):
        assert classify_email(subject, "")["type"] == "noon_report", subject


def test_noon_report_body_wins_over_nor_text():
    assert classify_email("Daily update", "NOON REPORT\nNOR tendered yesterday")["type"] == "noon_report"


def test_real_nor_still_detected():
    assert classify_email("NOR tendered at Rotterdam", "")["type"] == "nor"
    assert classify_email("Notice of Readiness", "")["type"] == "nor"
    assert classify_email("M/V DEMO - NOR.", "")["type"] == "nor"
