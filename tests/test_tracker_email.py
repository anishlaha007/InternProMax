"""Application status machine + email classification/matching."""

from internpromax import db, emails, inbox, tracker


def test_status_machine_never_moves_backwards():
    assert tracker.is_advance("applied", "interviewing")
    assert not tracker.is_advance("interviewing", "applied")
    assert tracker.is_advance("interviewing", "rejected")
    assert not tracker.is_advance("offer", "rejected")
    assert not tracker.is_advance("rejected", "interviewing")
    assert tracker.is_advance("ghosted", "interviewing")


def test_mark_applied_creates_then_logs():
    with db.session() as conn:
        app = tracker.mark_applied(conn, url="https://jobs.lever.co/globex/d5486403-c050-4920-b2e0-91b69b61ebb2/apply", title="Intern")
        assert app["status"] == "applied" and app["company"] == "Globex"
        again = tracker.mark_applied(conn, url="https://jobs.lever.co/globex/d5486403-c050-4920-b2e0-91b69b61ebb2")
        assert again["id"] == app["id"]
        tracker.set_status(conn, app["id"], "interviewing")
        tracker.mark_applied(conn, url="https://jobs.lever.co/globex/d5486403-c050-4920-b2e0-91b69b61ebb2")
        full = tracker.get(conn, app["id"])
        assert full["status"] == "interviewing"
        assert [e["type"] for e in full["events"]].count("submitted") == 3


def test_stats():
    with db.session() as conn:
        for i, s in enumerate(["applied", "applied", "rejected", "interviewing", "saved"]):
            tracker.create(conn, company=f"C{i}", status=s)
        st = tracker.stats(conn)
    assert st["submitted"] == 4 and st["counts"]["saved"] == 1
    assert st["response_rate"] == 0.5
    assert sum(w["count"] for w in st["weekly"]) == 4


def test_classify_emails():
    cases = [
        ("Your application to Stripe", "Thank you for applying! We have received your application.", "applied"),
        ("Update", "Thank you for your interest. Unfortunately, we have decided to move forward with other candidates.", "rejected"),
        ("Next steps", "Please complete the HackerRank coding challenge as the next step in your interview process.", "oa"),
        ("Interview invitation", "We'd love to schedule a phone screen. Please share your availability via calendly.com/acme", "interviewing"),
        ("Congratulations!", "We are pleased to offer you a Software Engineering Internship.", "offer"),
        ("Weekly newsletter", "Top 10 tips for your garden", None),
    ]
    for subject, body, expected in cases:
        assert emails.classify(subject, body)["status"] == expected, subject


def test_match_by_domain_subject_and_body():
    apps = [{"id": 1, "company": "Stripe, Inc.", "title": "SWE Intern", "status": "applied"},
            {"id": 2, "company": "Jane Street", "title": "Quant Intern", "status": "applied"}]
    app, score, why = emails.match_application("Stripe Recruiting <recruiting@stripe.com>", "Hi", "text", apps)
    assert app["id"] == 1 and "domain" in why
    app, _, why = emails.match_application("no-reply@greenhouse.io", "Your Jane Street application", "", apps)
    assert app["id"] == 2 and "subject" in why
    app, _, _ = emails.match_application("no-reply@myworkday.com", "Update", "Thanks for applying to Jane Street.", apps)
    assert app["id"] == 2
    assert emails.match_application("friend@gmail.com", "hey", "lunch?", apps)[0] is None


def test_inbox_suggestions_and_auto_apply():
    with db.session() as conn:
        app = tracker.create(conn, company="Globex", title="Data Intern", status="applied")
        db.save_settings(conn, {"email_auto_apply": False})
        settings = db.get_settings(conn)
        out = inbox.ingest_message(conn, "<m1>", "talent@globex.com", "Globex: coding challenge",
                                   "Please complete the CodeSignal assessment.", 1790000000, settings)
        assert out == "suggested"
        assert inbox.ingest_message(conn, "<m1>", "talent@globex.com", "x", "y", None, settings) == "seen"
        sugg = inbox.list_suggestions(conn)
        assert sugg[0]["suggested_status"] == "oa" and sugg[0]["application_id"] == app["id"]
        inbox.accept(conn, sugg[0]["id"])
        assert tracker.get(conn, app["id"])["status"] == "oa"

        settings = db.save_settings(conn, {"email_auto_apply": True, "email_auto_apply_min_confidence": 0.8})
        out = inbox.ingest_message(conn, "<m2>", "talent@globex.com", "Globex interview",
                                   "We'd like to schedule an interview. Share your availability.", None, settings)
        assert out == "applied"
        assert tracker.get(conn, app["id"])["status"] == "interviewing"


class _FakeIMAP:
    """Just enough of imaplib.IMAP4_SSL for imap_sync()."""

    messages = []

    def __init__(self, host, port):
        self.host = host

    def login(self, user, password):
        assert user == "me@example.com" and password == "app-pw"

    def select(self, folder, readonly=False):
        assert readonly is True  # never modify the mailbox
        return "OK", [b"2"]

    def search(self, charset, *criteria):
        assert criteria[0] == "SINCE"
        return "OK", [" ".join(str(i + 1) for i in range(len(self.messages))).encode()]

    def fetch(self, num, what):
        return "OK", [(b"1 (BODY[] {100})", self.messages[int(num) - 1])]

    def logout(self):
        pass


def test_imap_sync_creates_suggestions(monkeypatch):
    raw_rejection = (b"From: Careers <careers@globex.com>\r\nSubject: Your Globex application\r\n"
                     b"Message-ID: <r1@globex.com>\r\nDate: Mon, 28 Sep 2026 10:00:00 +0000\r\n"
                     b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
                     b"Thank you for your interest. Unfortunately, we will not be moving forward with your application.\r\n")
    raw_spam = (b"From: Shop <deals@shop.com>\r\nSubject: 50% off\r\nMessage-ID: <s1@shop.com>\r\n"
                b"Content-Type: text/html; charset=utf-8\r\n\r\n<p>Big sale this weekend</p>\r\n")
    _FakeIMAP.messages = [raw_rejection, raw_spam]
    monkeypatch.setattr("imaplib.IMAP4_SSL", _FakeIMAP)
    with db.session() as conn:
        app = tracker.create(conn, company="Globex", title="Intern", status="applied")
        db.save_settings(conn, {"imap": {"host": "imap.example.com", "username": "me@example.com", "password": "app-pw"}})
    counts = inbox.imap_sync()
    assert counts["checked"] == 2 and counts["suggested"] == 1 and counts["ignored"] == 1
    with db.session() as conn:
        sugg = inbox.list_suggestions(conn)
        assert sugg[0]["application_id"] == app["id"] and sugg[0]["suggested_status"] == "rejected"
    assert inbox.imap_sync()["seen"] == 1  # the rejection isn't suggested twice
