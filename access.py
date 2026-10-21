"""Local prototype staff gate. Production must use bank SSO/MFA and assignments."""
from dataclasses import dataclass
import hashlib
import hmac
import os
import re
from time import time


@dataclass(frozen=True)
class StaffPrincipal:
    actor_id: str
    customer_scope: tuple
    expires_at: float


def authenticate_staff(token):
    expected = os.environ.get('STAFF_ACCESS_TOKEN_SHA256', '')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', expected):
        raise PermissionError('Staff access is not configured.')
    if not isinstance(token, str) or not 32 <= len(token) <= 512 or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected.lower()):
        raise PermissionError('Staff sign-in failed.')
    scope = tuple(c.strip() for c in os.environ.get('STAFF_ALLOWED_CUSTOMERS', 'C-001').split(',') if re.fullmatch(r'C-\d{3,8}', c.strip()))
    return StaffPrincipal('staff-demo', scope, time() + 900)


def require_staff(principal, customer_id):
    if not isinstance(principal, StaffPrincipal) or principal.expires_at <= time() or customer_id not in principal.customer_scope:
        raise PermissionError('Authenticated staff access to this customer is required.')
    return principal
