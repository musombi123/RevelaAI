"""Compatibility path for USECT-AUDITOR; import from core_auditor.ledger."""
from core_auditor.ledger import AuditLedger, AuditLedgerError

__all__ = ["AuditLedger", "AuditLedgerError"]
