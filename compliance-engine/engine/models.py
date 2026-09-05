"""Shared enums and small value types."""
from __future__ import annotations

from enum import StrEnum


class LeadStatus(StrEnum):
    NEW = "new"                    # discovered, not yet scanned
    SCANNED = "scanned"            # scan complete, findings stored
    NO_CONTACT = "no_contact"      # scanned but no email found
    CLEAN = "clean"                # scores too good to pitch
    QUEUED = "queued"              # outreach drafted, waiting to send
    CONTACTED = "contacted"        # at least one email sent
    ENGAGED = "engaged"            # they replied and are talking
    ACCEPTED = "accepted"          # they agreed; checkout sent
    PAID = "paid"                  # money received; fixing
    DELIVERED = "delivered"        # fix delivered / applied
    VERIFIED = "verified"          # post-fix rescan confirms improvement
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBED = "unsubscribed"
    BOUNCED = "bounced"
    NEEDS_HUMAN = "needs_human"    # agent hit a policy edge; shown on dashboard
    ARCHIVED = "archived"


class MessageDirection(StrEnum):
    OUT = "out"
    IN = "in"


class MessageStatus(StrEnum):
    DRAFT = "draft"          # composed, failed lint or awaiting approval
    QUEUED = "queued"        # passed lint, will send when gates allow
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    RECEIVED = "received"
    HELD = "held"            # dry-run: would have sent


class ReplyIntent(StrEnum):
    INTERESTED = "interested"
    QUESTION = "question"
    OBJECTION_PRICE = "objection_price"
    OBJECTION_OTHER = "objection_other"
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBE = "unsubscribe"
    WRONG_PERSON = "wrong_person"
    AUTO_REPLY = "auto_reply"
    BOUNCE = "bounce"
    ACCEPT = "accept"
    ALREADY_CUSTOMER = "already_customer"
    UNCLEAR = "unclear"


class DealStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    CHECKOUT_SENT = "checkout_sent"
    PAID = "paid"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    VERIFIED = "verified"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class Package(StrEnum):
    ADA = "ada"
    AISEO = "aiseo"
    BUNDLE = "bundle"


class FixStrategy(StrEnum):
    WORDPRESS_REST = "wordpress_rest"   # apply via WP REST API with an application password
    GITHUB_PR = "github_pr"             # open a PR on the client's repo
    BUNDLE = "bundle"                   # deliver patched files + instructions (any host)
    HEADER_SNIPPET = "header_snippet"   # site builders (Wix/Squarespace): header code injection


class EventKind(StrEnum):
    LEAD_CREATED = "lead_created"
    SCAN_DONE = "scan_done"
    SCAN_FAILED = "scan_failed"
    EMAIL_DRAFTED = "email_drafted"
    EMAIL_LINT_FAILED = "email_lint_failed"
    EMAIL_SENT = "email_sent"
    EMAIL_HELD = "email_held"
    EMAIL_RECEIVED = "email_received"
    REPLY_CLASSIFIED = "reply_classified"
    DEAL_PROPOSED = "deal_proposed"
    DEAL_ACCEPTED = "deal_accepted"
    CHECKOUT_SENT = "checkout_sent"
    PAID = "paid"
    FIX_PLANNED = "fix_planned"
    FIX_APPLIED = "fix_applied"
    FIX_DELIVERED = "fix_delivered"
    FIX_VERIFIED = "fix_verified"
    ESCALATED = "escalated"
    SUPPRESSED = "suppressed"
    BREAKER_TRIPPED = "breaker_tripped"
    STATUS_CHANGED = "status_changed"
    ERROR = "error"
