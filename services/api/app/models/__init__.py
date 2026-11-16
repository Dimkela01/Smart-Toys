"""SQLAlchemy models for the M1 tables (DATA_MODEL.md §2.1, §2.2).

Conversation, memory and evaluation tables (§2.3–§2.5) arrive with the milestones that
use them: turns/sessions/metrics in M2, events/alerts in M3/M5, memory in M5, models and
evaluation in M6.
"""

from app.models.accounts import (
    ACTOR_TYPES,
    CONSENT_TYPES,
    USER_TYPES,
    Admin,
    AuditLog,
    Consent,
    Parent,
    RefreshToken,
)
from app.models.base import Base
from app.models.children import (
    ACTIVITIES,
    DAILY_LIMIT_CHOICES,
    MAX_BLOCKED_TOPICS,
    MAX_CHILDREN_PER_PARENT,
    MAX_INTERESTS,
    Child,
    ChildSettings,
)

__all__ = [
    "ACTIVITIES",
    "ACTOR_TYPES",
    "CONSENT_TYPES",
    "DAILY_LIMIT_CHOICES",
    "MAX_BLOCKED_TOPICS",
    "MAX_CHILDREN_PER_PARENT",
    "MAX_INTERESTS",
    "USER_TYPES",
    "Admin",
    "AuditLog",
    "Base",
    "Child",
    "ChildSettings",
    "Consent",
    "Parent",
    "RefreshToken",
]
