"""JWT token validation with audience enforcement for embedded console sessions."""

import hmac
import hashlib
import time
from typing import Any, Dict, Optional, Tuple


class JWTValidator:
    """Validates JWT tokens with strict audience, issuer, and tenant checks."""

    def __init__(
        self,
        expected_audience: str,
        expected_issuer: str,
        token_secret: str,
        max_age_seconds: int = 3600,
    ):
        self.expected_audience = expected_audience
        self.expected_issuer = expected_issuer
        self.token_secret = token_secret
        self.max_age_seconds = max_age_seconds

    def validate_token(self, token: str, expected_tenant: str) -> Tuple[bool, str, Optional[Dict]]:
        """Validate a JWT token for embedded console session exchange.

        Checks: structure, signature, expiration, audience, issuer, tenant.
        Returns (is_valid, error_message, payload).
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return False, "Malformed JWT: expected 3 parts", None

            header_b64, payload_b64, signature_b64 = parts
            signing_input = f"{header_b64}.{payload_b64}"

            expected_sig = hmac.new(
                self.token_secret.encode(),
                signing_input.encode(),
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(signature_b64, expected_sig):
                return False, "Invalid JWT signature", None

            import json
            import base64

            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding

            payload_json = base64.urlsafe_b64decode(payload_b64).decode()
            payload = json.loads(payload_json)

        except Exception as e:
            return False, f"Malformed JWT payload: {e}", None

        # Validate audience
        token_aud = payload.get("aud", "")
        if token_aud != self.expected_audience:
            return False, (
                f"JWT audience mismatch: expected '{self.expected_audience}', "
                f"got '{token_aud}'"
            ), None

        # Validate issuer
        token_iss = payload.get("iss", "")
        if token_iss != self.expected_issuer:
            return False, (
                f"JWT issuer mismatch: expected '{self.expected_issuer}', "
                f"got '{token_iss}'"
            ), None

        # Validate tenant
        token_tenant = payload.get("tenant", "")
        if token_tenant != expected_tenant:
            return False, (
                f"Tenant mismatch: expected '{expected_tenant}', "
                f"got '{token_tenant}'"
            ), None

        # Validate expiration
        token_exp = payload.get("exp", 0)
        if isinstance(token_exp, str):
            token_exp = int(token_exp)
        now = int(time.time())
        if token_exp != 0 and now > token_exp:
            return False, "JWT token expired", None

        # Validate not-before
        token_nbf = payload.get("nbf", 0)
        if isinstance(token_nbf, str):
            token_nbf = int(token_nbf)
        if now < token_nbf:
            return False, "JWT token not yet valid", None

        # Check max age
        token_iat = payload.get("iat", 0)
        if isinstance(token_iat, str):
            token_iat = int(token_iat)
        if token_iat != 0 and (now - token_iat) > self.max_age_seconds:
            return False, "JWT token exceeded max age", None

        return True, "", payload
