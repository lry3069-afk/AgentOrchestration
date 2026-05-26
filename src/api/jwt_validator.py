"""JWT token validation for embedded console sessions."""

import json
import os
import time
import hashlib
import hmac
import base64
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class JWTClaims:
    sub: str = ""
    iss: str = ""
    aud: str = ""
    exp: int = 0
    iat: int = 0
    tenant_id: str = ""
    session_type: str = ""

    @classmethod
    def from_dict(cls, data: Dict) -> "JWTClaims":
        return cls(
            sub=data.get("sub", ""),
            iss=data.get("iss", ""),
            aud=data.get("aud", ""),
            exp=data.get("exp", 0),
            iat=data.get("iat", 0),
            tenant_id=data.get("tenant_id", ""),
            session_type=data.get("session_type", "console"),
        )


class JWTValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(f"JWT validation failed: {message}")


# Expected values from configuration
EXPECTED_ISSUER = os.environ.get("JWT_ISSUER", "agent-orchestrator")
EXPECTED_AUDIENCE = os.environ.get("JWT_AUDIENCE", "embedded-console")
ALLOWED_TENANTS = os.environ.get("JWT_ALLOWED_TENANTS", "*").split(",")


def _decode_base64url(data: str) -> bytes:
    """Decode base64url-encoded data with padding fix."""
    data = data.replace("-", "+").replace("_", "/")
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.b64decode(data)


def _decode_jwt(token: str) -> Tuple[Dict, Dict, bytes]:
    """Decode JWT token into header, payload, and signature parts without verification."""
    parts = token.split(".")
    if len(parts) != 3:
        raise JWTValidationError("Malformed token: expected 3 parts")
    header_raw, payload_raw, signature_raw = parts
    header = json.loads(_decode_base64url(header_raw).decode("utf-8"))
    payload = json.loads(_decode_base64url(payload_raw).decode("utf-8"))
    signature = _decode_base64url(signature_raw)
    return header, payload, signature


def _verify_signature(token: str, secret: str) -> bool:
    """Verify the HMAC-SHA256 signature of a JWT token."""
    parts = token.split(".")
    if len(parts) != 3:
        return False
    signing_input = f"{parts[0]}.{parts[1]}"
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    actual_sig = _decode_base64url(parts[2])
    return hmac.compare_digest(expected_sig, actual_sig)


def validate_embedded_session_token(
    token: str,
    secret: str = "",
    expected_audience: str = "",
    expected_issuer: str = "",
    allowed_tenants: Optional[list] = None,
) -> JWTClaims:
    if not secret:
        secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise JWTValidationError("JWT secret not configured")

    if not expected_audience:
        expected_audience = EXPECTED_AUDIENCE
    if not expected_issuer:
        expected_issuer = EXPECTED_ISSUER
    if allowed_tenants is None:
        allowed_tenants = ALLOWED_TENANTS

    # Verify signature
    if not _verify_signature(token, secret):
        raise JWTValidationError("Invalid token signature")

    # Decode claims
    _, payload_dict, _ = _decode_jwt(token)
    claims = JWTClaims.from_dict(payload_dict)

    # Validate expiration
    now = int(time.time())
    if claims.exp > 0 and now >= claims.exp:
        raise JWTValidationError("Token has expired")
    if now < claims.iat:
        raise JWTValidationError("Token issued in the future")

    # Validate issuer
    if claims.iss != expected_issuer:
        raise JWTValidationError(
            f"Issuer mismatch: expected '{expected_issuer}', got '{claims.iss}'"
        )

    # Validate audience
    if claims.aud != expected_audience:
        raise JWTValidationError(
            f"Audience mismatch: expected '{expected_audience}', got '{claims.aud}'"
        )

    # Validate tenant
    if "*" not in allowed_tenants and claims.tenant_id not in allowed_tenants:
        raise JWTValidationError(
            f"Tenant '{claims.tenant_id}' not in allowed tenant list"
        )

    # Validate session type
    if claims.session_type != "console":
        raise JWTValidationError(
            f"Invalid session type: '{claims.session_type}'. Only 'console' sessions are accepted for embedded queries."
        )

    return claims