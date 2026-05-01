"""
support_routes.py
-----------------
Blueprint for the end-user support ticket system.
Register in app.py:

    from support_routes import support_bp
    app.register_blueprint(support_bp)
"""

import random
import string
from datetime import datetime

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, abort, jsonify)
from flask_login import login_required, current_user
from sqlalchemy.exc import SQLAlchemyError

from db import db
from models import User, SupportTicket, TicketReply, ActivityLog

support_bp = Blueprint("support", __name__, url_prefix="/support")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _generate_ticket_number():
    """Return a unique ticket number like TKT-A3X9."""
    for _ in range(50):
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        num = f"TKT-{suffix}"
        if not SupportTicket.query.filter_by(ticket_number=num).first():
            return num
    return f"TKT-{int(datetime.utcnow().timestamp())}"


def _log(action, details=None):
    if current_user and current_user.is_authenticated:
        try:
            db.session.add(ActivityLog(
                user_id=current_user.id,
                action=action,
                details=details,
                ip_address=request.remote_addr,
            ))
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()


# ─────────────────────────────────────────────
# User-facing routes
# ─────────────────────────────────────────────

@support_bp.route("/")
@login_required
def support_home():
    """Landing page – shows user's own tickets."""
    my_tickets = (SupportTicket.query
                  .filter_by(user_id=current_user.id)
                  .order_by(SupportTicket.created_at.desc())
                  .all())
    return render_template("support/support_home.html", tickets=my_tickets)


@support_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_ticket():
    """Submit a new support ticket."""
    if request.method == "POST":
        subject     = (request.form.get("subject", "")).strip()
        description = (request.form.get("description", "")).strip()
        category    = request.form.get("category", "general")
        priority    = request.form.get("priority", "medium")
        browser_info = request.form.get("browser_info", "")[:300]
        page_url     = request.form.get("page_url", "")[:500]

        errors = []
        if not subject:
            errors.append("Subject is required.")
        if not description or len(description) < 10:
            errors.append("Please provide a description (at least 10 characters).")
        valid_cats = [c[0] for c in SupportTicket.CATEGORIES]
        if category not in valid_cats:
            category = "general"
        valid_pris = [p[0] for p in SupportTicket.PRIORITIES]
        if priority not in valid_pris:
            priority = "medium"

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("support/new_ticket.html",
                                   categories=SupportTicket.CATEGORIES,
                                   priorities=SupportTicket.PRIORITIES)

        ticket = SupportTicket(
            ticket_number=_generate_ticket_number(),
            user_id=current_user.id,
            subject=subject,
            description=description,
            category=category,
            priority=priority,
            browser_info=browser_info or None,
            page_url=page_url or None,
        )
        db.session.add(ticket)
        db.session.commit()
        _log("submit_support_ticket",
             f"Ticket {ticket.ticket_number}: {subject[:60]}")
        flash(f"Ticket {ticket.ticket_number} submitted successfully. "
              "The support team will respond shortly.", "success")
        return redirect(url_for("support.ticket_detail",
                                ticket_number=ticket.ticket_number))

    return render_template("support/new_ticket.html",
                           categories=SupportTicket.CATEGORIES,
                           priorities=SupportTicket.PRIORITIES)


@support_bp.route("/<ticket_number>")
@login_required
def ticket_detail(ticket_number):
    """View a single ticket and its replies."""
    ticket = SupportTicket.query.filter_by(
        ticket_number=ticket_number).first_or_404()

    # Users can only see their own tickets; admins see all
    if not current_user.is_admin() and ticket.user_id != current_user.id:
        abort(403)

    # Filter out internal notes for non-admins
    replies = ticket.replies
    if not current_user.is_admin():
        replies = [r for r in replies if not r.is_internal]

    admins = User.query.filter_by(role='admin').all()
    return render_template("support/ticket_detail.html",
                           ticket=ticket, replies=replies,
                           statuses=SupportTicket.STATUSES,
                           admins=admins)


@support_bp.route("/<ticket_number>/reply", methods=["POST"])
@login_required
def reply_ticket(ticket_number):
    """Add a reply to an existing ticket."""
    ticket = SupportTicket.query.filter_by(
        ticket_number=ticket_number).first_or_404()

    if not current_user.is_admin() and ticket.user_id != current_user.id:
        abort(403)

    if ticket.status == "closed":
        flash("This ticket is closed and cannot receive new replies.", "warning")
        return redirect(url_for("support.ticket_detail",
                                ticket_number=ticket_number))

    message     = (request.form.get("message", "")).strip()
    is_internal = request.form.get("is_internal") == "1" and current_user.is_admin()

    if not message:
        flash("Reply message cannot be empty.", "danger")
        return redirect(url_for("support.ticket_detail",
                                ticket_number=ticket_number))

    reply = TicketReply(
        ticket_id=ticket.id,
        user_id=current_user.id,
        message=message,
        is_internal=is_internal,
    )
    db.session.add(reply)

    # Auto-update ticket status
    if current_user.is_admin():
        new_status = request.form.get("status_update", "").strip()
        valid = [s[0] for s in SupportTicket.STATUSES]
        if new_status and new_status in valid:
            ticket.status = new_status
            if new_status == "resolved":
                ticket.resolved_at = datetime.utcnow()
            else:
                ticket.resolved_at = None
        elif ticket.status == "open":
            ticket.status = "in_progress"
    else:
        # User replied → move back to open if it was 'waiting'
        if ticket.status == "waiting":
            ticket.status = "open"

    ticket.updated_at = datetime.utcnow()
    db.session.commit()
    _log("ticket_reply", f"Replied to {ticket_number}")
    flash("Reply added.", "success")
    return redirect(url_for("support.ticket_detail",
                            ticket_number=ticket_number))


# ─────────────────────────────────────────────
# Admin-only routes
# ─────────────────────────────────────────────

@support_bp.route("/admin/dashboard")
@login_required
def admin_support_dashboard():
    """Admin: full ticket queue with filters."""
    if not current_user.is_admin():
        abort(403)

    status_filter   = request.args.get("status",   "")
    priority_filter = request.args.get("priority", "")
    category_filter = request.args.get("category", "")
    page            = request.args.get("page", 1, type=int)

    q = SupportTicket.query
    if status_filter:
        q = q.filter_by(status=status_filter)
    if priority_filter:
        q = q.filter_by(priority=priority_filter)
    if category_filter:
        q = q.filter_by(category=category_filter)

    pagination = (q.order_by(SupportTicket.created_at.desc())
                   .paginate(page=page, per_page=20, error_out=False))

    # KPI counts
    total      = SupportTicket.query.count()
    open_count = SupportTicket.query.filter(
        SupportTicket.status.in_(["open", "in_progress"])).count()
    critical   = SupportTicket.query.filter_by(
        status="open", priority="critical").count()
    resolved   = SupportTicket.query.filter_by(status="resolved").count()

    admins = User.query.filter_by(role="admin").all()

    return render_template("support/admin_dashboard.html",
                           pagination=pagination,
                           tickets=pagination.items,
                           total=total,
                           open_count=open_count,
                           critical_count=critical,
                           resolved_count=resolved,
                           statuses=SupportTicket.STATUSES,
                           priorities=SupportTicket.PRIORITIES,
                           categories=SupportTicket.CATEGORIES,
                           admins=admins,
                           status_filter=status_filter,
                           priority_filter=priority_filter,
                           category_filter=category_filter)


@support_bp.route("/admin/<ticket_number>/assign", methods=["POST"])
@login_required
def assign_ticket(ticket_number):
    """Admin: assign ticket to an admin user."""
    if not current_user.is_admin():
        abort(403)
    ticket = SupportTicket.query.filter_by(
        ticket_number=ticket_number).first_or_404()
    assignee_id = request.form.get("assignee_id", type=int)
    if assignee_id:
        assignee = User.query.filter_by(id=assignee_id, role="admin").first()
        if assignee:
            ticket.assigned_to = assignee.id
            ticket.updated_at = datetime.utcnow()
            db.session.commit()
            flash("Ticket assigned.", "success")
        else:
            flash("Selected assignee is not a valid admin.", "danger")
    return redirect(url_for("support.ticket_detail",
                            ticket_number=ticket_number))


@support_bp.route("/admin/<ticket_number>/close", methods=["POST"])
@login_required
def close_ticket(ticket_number):
    """Admin: close a ticket."""
    if not current_user.is_admin():
        abort(403)
    ticket = SupportTicket.query.filter_by(
        ticket_number=ticket_number).first_or_404()
    ticket.status     = "closed"
    ticket.updated_at = datetime.utcnow()
    db.session.commit()
    _log("close_ticket", ticket_number)
    flash("Ticket closed.", "info")
    return redirect(url_for("support.admin_support_dashboard"))


@support_bp.route("/admin/api/stats")
@login_required
def support_stats_api():
    """JSON KPI endpoint for dashboard widgets."""
    if not current_user.is_admin():
        return jsonify({"error": "Forbidden"}), 403
    return jsonify({
        "total":       SupportTicket.query.count(),
        "open":        SupportTicket.query.filter_by(status="open").count(),
        "in_progress": SupportTicket.query.filter_by(status="in_progress").count(),
        "resolved":    SupportTicket.query.filter_by(status="resolved").count(),
        "closed":      SupportTicket.query.filter_by(status="closed").count(),
        "critical":    SupportTicket.query.filter_by(
                           status="open", priority="critical").count(),
    })
