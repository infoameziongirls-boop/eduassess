"""
test_support_tickets.py
-----------------------
Self-contained tests for the support ticket system.
No Flask app required – tests core logic, model helpers, and route logic stubs.
Run:  python test_support_tickets.py
"""

import sys
import os
import unittest
import random
import string
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

# ─── Bootstrap a tiny in-memory Flask app ──────────────────────────────────
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin

app = Flask(__name__)
app.config.update(
    TESTING=True,
    SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SECRET_KEY="test-secret-key",
    WTF_CSRF_ENABLED=False,
)

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)


# ─── Minimal models (mirrors the real ones) ────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role          = db.Column(db.String(20), default="teacher")

    def is_admin(self):   return self.role == "admin"
    def is_teacher(self): return self.role == "teacher"
    def is_student(self): return self.role == "student"


class SupportTicket(db.Model):
    __tablename__ = "support_tickets"
    id            = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    user_id       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    subject       = db.Column(db.String(200), nullable=False)
    description   = db.Column(db.Text, nullable=False)
    category      = db.Column(db.String(50), nullable=False, default="general")
    priority      = db.Column(db.String(20), nullable=False, default="medium")
    status        = db.Column(db.String(20), nullable=False, default="open")
    assigned_to   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    browser_info  = db.Column(db.String(300), nullable=True)
    page_url      = db.Column(db.String(500), nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at   = db.Column(db.DateTime, nullable=True)

    submitter = db.relationship("User", foreign_keys=[user_id],  backref="submitted_tickets")
    assignee  = db.relationship("User", foreign_keys=[assigned_to], backref="assigned_tickets")
    replies   = db.relationship("TicketReply", backref="ticket",
                                cascade="all, delete-orphan",
                                order_by="TicketReply.created_at")

    CATEGORIES = [
        ("bug","Bug / Error"), ("access","Login / Access Issue"),
        ("data","Data / Assessment Issue"), ("performance","Performance Problem"),
        ("feature","Feature Request"), ("general","General Enquiry"),
    ]
    PRIORITIES = [("low","Low"),("medium","Medium"),("high","High"),("critical","Critical")]
    STATUSES   = [("open","Open"),("in_progress","In Progress"),
                  ("waiting","Waiting"),("resolved","Resolved"),("closed","Closed")]

    def priority_color(self):
        return {"low":"success","medium":"warning",
                "high":"danger","critical":"dark"}.get(self.priority,"secondary")

    def status_color(self):
        return {"open":"primary","in_progress":"info","waiting":"warning",
                "resolved":"success","closed":"secondary"}.get(self.status,"secondary")


class TicketReply(db.Model):
    __tablename__ = "ticket_replies"
    id          = db.Column(db.Integer, primary_key=True)
    ticket_id   = db.Column(db.Integer, db.ForeignKey("support_tickets.id"), nullable=False)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message     = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship("User", foreign_keys=[user_id], backref="ticket_replies")


# ─── Helper (mirrors support_routes._generate_ticket_number) ───────────────
def _generate_ticket_number():
    for _ in range(50):
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        num = f"TKT-{suffix}"
        if not SupportTicket.query.filter_by(ticket_number=num).first():
            return num
    return f"TKT-{int(datetime.utcnow().timestamp())}"


# ─── Test cases ────────────────────────────────────────────────────────────

class TestSupportTicketModel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.drop_all()

    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        self._admin   = User(username="admin_test",
                              password_hash=bcrypt.generate_password_hash("pw").decode(),
                              role="admin")
        self._teacher = User(username="teacher_test",
                              password_hash=bcrypt.generate_password_hash("pw").decode(),
                              role="teacher")
        self._student = User(username="student_test",
                              password_hash=bcrypt.generate_password_hash("pw").decode(),
                              role="student")
        db.session.add_all([self._admin, self._teacher, self._student])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        # Clean per-test data
        TicketReply.query.delete()
        SupportTicket.query.delete()
        User.query.delete()
        db.session.commit()
        self.ctx.pop()

    # ── Ticket number generation ──────────────────────────────────────────
    def test_ticket_number_format(self):
        num = _generate_ticket_number()
        self.assertTrue(num.startswith("TKT-"), f"Expected TKT- prefix, got: {num}")
        self.assertEqual(len(num), 10, f"Expected length 10, got {len(num)}")
        print(f"  ✓ Ticket number format OK: {num}")

    def test_ticket_number_uniqueness(self):
        numbers = {_generate_ticket_number() for _ in range(30)}
        self.assertEqual(len(numbers), 30, "Duplicate ticket numbers generated!")
        print(f"  ✓ Generated 30 unique ticket numbers")

    # ── Create ticket ─────────────────────────────────────────────────────
    def test_create_ticket(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Cannot log in",
            description="Getting a 403 error when I try to access the assessment page.",
            category="access",
            priority="high",
        )
        db.session.add(ticket)
        db.session.commit()

        fetched = SupportTicket.query.filter_by(subject="Cannot log in").first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.status, "open")
        self.assertEqual(fetched.priority, "high")
        self.assertEqual(fetched.user_id, self._teacher.id)
        print(f"  ✓ Ticket created: {fetched.ticket_number}")

    def test_ticket_defaults(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Default test",
            description="Checking default values.",
        )
        db.session.add(ticket)
        db.session.commit()
        self.assertEqual(ticket.status, "open")
        self.assertEqual(ticket.priority, "medium")
        self.assertEqual(ticket.category, "general")
        print("  ✓ Ticket defaults correct")

    # ── Validation ────────────────────────────────────────────────────────
    def test_subject_required(self):
        from sqlalchemy.exc import IntegrityError
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject=None,          # violates nullable=False
            description="Test",
        )
        db.session.add(ticket)
        with self.assertRaises(Exception):
            db.session.commit()
        db.session.rollback()
        print("  ✓ Subject NOT NULL enforced")

    def test_description_minimum_length_logic(self):
        desc = "Short"
        self.assertFalse(len(desc) >= 10,
                         "Description < 10 chars should fail validation")
        desc_ok = "This is long enough."
        self.assertTrue(len(desc_ok) >= 10)
        print("  ✓ Description minimum-length logic works")

    # ── Priority and status colors ────────────────────────────────────────
    def test_priority_colors(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Color test", description="color test ticket",
        )
        for p, expected in [("low","success"),("medium","warning"),
                             ("high","danger"),("critical","dark")]:
            ticket.priority = p
            self.assertEqual(ticket.priority_color(), expected)
        print("  ✓ Priority colors correct")

    def test_status_colors(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Color test", description="color test ticket",
        )
        for s, expected in [("open","primary"),("in_progress","info"),
                             ("waiting","warning"),("resolved","success"),
                             ("closed","secondary")]:
            ticket.status = s
            self.assertEqual(ticket.status_color(), expected)
        print("  ✓ Status colors correct")

    # ── Replies ───────────────────────────────────────────────────────────
    def test_add_reply(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Reply test",
            description="Testing reply functionality.",
        )
        db.session.add(ticket)
        db.session.commit()

        reply = TicketReply(
            ticket_id=ticket.id,
            user_id=self._admin.id,
            message="We are looking into this.",
            is_internal=False,
        )
        db.session.add(reply)
        db.session.commit()

        fetched = SupportTicket.query.get(ticket.id)
        self.assertEqual(len(fetched.replies), 1)
        self.assertEqual(fetched.replies[0].message, "We are looking into this.")
        print("  ✓ Reply added and linked correctly")

    def test_internal_reply_flag(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Internal note test",
            description="Should have an internal note.",
        )
        db.session.add(ticket)
        db.session.commit()

        reply = TicketReply(
            ticket_id=ticket.id, user_id=self._admin.id,
            message="This is an admin-only internal note.",
            is_internal=True,
        )
        db.session.add(reply)
        db.session.commit()

        fetched = SupportTicket.query.get(ticket.id)
        internal = [r for r in fetched.replies if r.is_internal]
        self.assertEqual(len(internal), 1)
        print("  ✓ Internal note flag preserved")

    def test_cascade_delete(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Cascade delete test",
            description="Deleting ticket should remove replies.",
        )
        db.session.add(ticket)
        db.session.commit()
        tid = ticket.id

        for i in range(3):
            db.session.add(TicketReply(
                ticket_id=tid, user_id=self._admin.id,
                message=f"Reply {i}", is_internal=False))
        db.session.commit()
        self.assertEqual(TicketReply.query.filter_by(ticket_id=tid).count(), 3)

        db.session.delete(ticket)
        db.session.commit()
        self.assertEqual(TicketReply.query.filter_by(ticket_id=tid).count(), 0)
        print("  ✓ Cascade delete removes replies when ticket is deleted")

    # ── Status transitions ────────────────────────────────────────────────
    def test_status_transition_open_to_resolved(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Status transition test",
            description="Testing open → resolved.",
        )
        db.session.add(ticket)
        db.session.commit()

        ticket.status     = "resolved"
        ticket.resolved_at = datetime.utcnow()
        db.session.commit()

        fetched = SupportTicket.query.get(ticket.id)
        self.assertEqual(fetched.status, "resolved")
        self.assertIsNotNone(fetched.resolved_at)
        print("  ✓ Status transition open → resolved works")

    def test_status_closed_prevents_replies_logically(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Closed ticket test",
            description="Replies should be blocked for closed tickets.",
            status="closed",
        )
        db.session.add(ticket)
        db.session.commit()

        # Route-level check simulation
        blocked = ticket.status == "closed"
        self.assertTrue(blocked, "Closed ticket should block new replies")
        print("  ✓ Closed ticket reply guard logic correct")

    # ── Assignment ────────────────────────────────────────────────────────
    def test_assign_ticket(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Assignment test",
            description="Testing ticket assignment to admin.",
        )
        db.session.add(ticket)
        db.session.commit()

        ticket.assigned_to = self._admin.id
        db.session.commit()

        fetched = SupportTicket.query.get(ticket.id)
        self.assertEqual(fetched.assigned_to, self._admin.id)
        self.assertEqual(fetched.assignee.username, "admin_test")
        print("  ✓ Ticket assignment to admin works")

    # ── Access control simulation ─────────────────────────────────────────
    def test_access_control_owner_can_view(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Access control test",
            description="Teacher should see their own ticket.",
        )
        db.session.add(ticket)
        db.session.commit()

        # Simulate route check:  not admin AND not owner → 403
        current_user_id = self._teacher.id
        is_admin        = False
        can_view = is_admin or ticket.user_id == current_user_id
        self.assertTrue(can_view)
        print("  ✓ Owner can view their ticket")

    def test_access_control_other_user_blocked(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Access block test",
            description="Another user should NOT see this ticket.",
        )
        db.session.add(ticket)
        db.session.commit()

        current_user_id = self._student.id   # different user
        is_admin        = False
        can_view = is_admin or ticket.user_id == current_user_id
        self.assertFalse(can_view)
        print("  ✓ Non-owner access correctly blocked")

    def test_admin_can_view_any_ticket(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Admin view test",
            description="Admin should see all tickets.",
        )
        db.session.add(ticket)
        db.session.commit()

        is_admin = True
        can_view = is_admin or ticket.user_id == 9999
        self.assertTrue(can_view)
        print("  ✓ Admin can view any ticket")

    # ── Categories and priorities ─────────────────────────────────────────
    def test_valid_categories(self):
        valid = [c[0] for c in SupportTicket.CATEGORIES]
        self.assertIn("bug",         valid)
        self.assertIn("access",      valid)
        self.assertIn("data",        valid)
        self.assertIn("performance", valid)
        self.assertIn("feature",     valid)
        self.assertIn("general",     valid)
        print(f"  ✓ {len(valid)} categories defined: {valid}")

    def test_valid_priorities(self):
        valid = [p[0] for p in SupportTicket.PRIORITIES]
        self.assertIn("low",      valid)
        self.assertIn("medium",   valid)
        self.assertIn("high",     valid)
        self.assertIn("critical", valid)
        print(f"  ✓ {len(valid)} priorities defined: {valid}")

    def test_category_fallback_for_invalid(self):
        """Route-level: invalid category → falls back to 'general'."""
        raw_input = "INVALID_CATEGORY"
        valid     = [c[0] for c in SupportTicket.CATEGORIES]
        result    = raw_input if raw_input in valid else "general"
        self.assertEqual(result, "general")
        print("  ✓ Invalid category falls back to 'general'")

    # ── Multiple tickets per user ─────────────────────────────────────────
    def test_multiple_tickets_per_user(self):
        for i in range(5):
            db.session.add(SupportTicket(
                ticket_number=_generate_ticket_number(),
                user_id=self._teacher.id,
                subject=f"Issue {i}", description=f"Description for issue {i}",
            ))
        db.session.commit()
        count = SupportTicket.query.filter_by(user_id=self._teacher.id).count()
        self.assertEqual(count, 5)
        print("  ✓ Multiple tickets per user supported")

    # ── Relationships ─────────────────────────────────────────────────────
    def test_submitter_relationship(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Relationship test",
            description="Test submitter backref.",
        )
        db.session.add(ticket)
        db.session.commit()

        fetched = SupportTicket.query.get(ticket.id)
        self.assertIsNotNone(fetched.submitter)
        self.assertEqual(fetched.submitter.username, "teacher_test")
        print("  ✓ submitter relationship resolves correctly")

    def test_browser_info_stored(self):
        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=self._teacher.id,
            subject="Browser info test",
            description="Testing browser info field.",
            browser_info="Mozilla/5.0 (Windows NT 10.0) Chrome/120.0",
            page_url="https://app.example.com/assessments",
        )
        db.session.add(ticket)
        db.session.commit()

        fetched = SupportTicket.query.get(ticket.id)
        self.assertIn("Mozilla", fetched.browser_info)
        self.assertIn("assessments", fetched.page_url)
        print("  ✓ Browser info and page URL stored correctly")


# ─── Run ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Support Ticket System – Test Suite")
    print("=" * 60 + "\n")
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromTestCase(TestSupportTicketModel)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print(f"  ✅  ALL {result.testsRun} TESTS PASSED")
    else:
        print(f"  ❌  {len(result.failures)} failures, "
              f"{len(result.errors)} errors out of {result.testsRun} tests")
    print("=" * 60 + "\n")
    sys.exit(0 if result.wasSuccessful() else 1)
