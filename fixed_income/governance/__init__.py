"""Model governance, approvals and tamper-evident audit trails."""

from .audit import AuditTrail, ModelRegistry

__all__ = ["AuditTrail", "ModelRegistry"]
