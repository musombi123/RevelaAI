"""Revenue enforcement and signed license issuance for RevelaCode."""
from .licensing import LicenseError, verify_license_token

__all__ = ["LicenseError", "verify_license_token"]
