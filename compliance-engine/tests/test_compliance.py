from engine.outreach.compliance import lint_email

FOOTER = "\n\nReply unsubscribe to stop.\nTest Co LLC, 1 Test St, Testville, TS 00000"


def _lint(subject, body, allowed=(149000,)):
    return lint_email(subject=subject, body_text=body + FOOTER, allowed_cents=allowed,
                      postal_address="1 Test St, Testville, TS 00000", legal_name="Test Co LLC")


def test_clean_email_passes():
    r = _lint("A few fixable issues on example.com", "We estimate the fix at $1,490. Reply if interested.")
    assert r.ok, r.problems


def test_forbidden_claims_and_deceptive_subjects_fail():
    r = _lint("Re: URGENT legal notice", "We guarantee you will be fully compliant and certified. Act now.")
    joined = " ".join(r.problems)
    assert not r.ok
    for word in ("re:", "urgent", "legal", "notice", "guarantee", "fully compliant", "certified", "act now"):
        assert word in joined, word


def test_invented_dollar_figures_fail():
    r = _lint("Quick note about example.com", "Lawsuits cost $75,000 on average (estimate). Our fee is $1,490.")
    assert not r.ok
    assert any("$75,000" in p for p in r.problems)


def test_missing_footer_fails():
    r = lint_email(subject="Quick note", body_text="Hello there, estimate $1,490.", allowed_cents=[149000],
                   postal_address="1 Test St", legal_name="Test Co LLC")
    assert {"body lacks an unsubscribe instruction", "body lacks the postal address", "body lacks the sender's legal name"} <= set(r.problems)
