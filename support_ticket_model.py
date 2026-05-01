"""
Support Ticket Model
Add this class to models.py (before the init_db function)
"""

class SupportTicket(db.Model):
    __tablename__ = "support_tickets"

    id            = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    user_id       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject       = db.Column(db.String(200), nullable=False)
    description   = db.Column(db.Text, nullable=False)
    category      = db.Column(db.String(50), nullable=False, default="general")
    priority      = db.Column(db.String(20), nullable=False, default="medium")
    status        = db.Column(db.String(20), nullable=False, default="open", index=True)
    assigned_to   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    browser_info  = db.Column(db.String(300), nullable=True)
    page_url      = db.Column(db.String(500), nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at   = db.Column(db.DateTime, nullable=True)

    submitter    = db.relationship("User", foreign_keys=[user_id],  backref="submitted_tickets")
    assignee     = db.relationship("User", foreign_keys=[assigned_to], backref="assigned_tickets")
    replies      = db.relationship("TicketReply", backref="ticket",
                                   cascade="all, delete-orphan",
                                   order_by="TicketReply.created_at")

    CATEGORIES = [
        ("bug",          "Bug / Error"),
        ("access",       "Login / Access Issue"),
        ("data",         "Data / Assessment Issue"),
        ("performance",  "Performance Problem"),
        ("feature",      "Feature Request"),
        ("general",      "General Enquiry"),
    ]

    PRIORITIES = [
        ("low",      "Low"),
        ("medium",   "Medium"),
        ("high",     "High"),
        ("critical", "Critical"),
    ]

    STATUSES = [
        ("open",        "Open"),
        ("in_progress", "In Progress"),
        ("waiting",     "Waiting on User"),
        ("resolved",    "Resolved"),
        ("closed",      "Closed"),
    ]

    def priority_color(self):
        return {"low": "success", "medium": "warning",
                "high": "danger", "critical": "dark"}.get(self.priority, "secondary")

    def status_color(self):
        return {"open": "primary", "in_progress": "info",
                "waiting": "warning", "resolved": "success",
                "closed": "secondary"}.get(self.status, "secondary")

    def __repr__(self):
        return f"<SupportTicket {self.ticket_number} – {self.status}>"


class TicketReply(db.Model):
    __tablename__ = "ticket_replies"

    id         = db.Column(db.Integer, primary_key=True)
    ticket_id  = db.Column(db.Integer, db.ForeignKey("support_tickets.id"),
                           nullable=False, index=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message    = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, default=False)   # admin-only internal note
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship("User", foreign_keys=[user_id], backref="ticket_replies")

    def __repr__(self):
        return f"<TicketReply ticket={self.ticket_id} by user={self.user_id}>"
