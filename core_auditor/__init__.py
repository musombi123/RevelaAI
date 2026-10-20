"""Hash-chained audit evidence for security and revenue operations."""
from .ledger import AuditLedger, AuditLedgerError

__all__ = ["AuditLedger", "AuditLedgerError"]

# Enforce owner recipe integrity in hardened deployments.
from core_uncopyable.recipe_lock import guard_core_startup

guard_core_startup()
