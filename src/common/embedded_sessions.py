"""Embedded console session management with JWT validation."""

import hashlib
import hmac
import json
import base64
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field

import jwt
from src.common.errors import AuthenticationError


@dataclass
class EmbeddedSessionConfig:
    """Configuration for embedded console session validation."""

    expected_audience: str = ""
    expected_issuer: str = ""
    allowed_tenants: set = field(default_factory=set)
    max_session_ttl: int = 3600
    require_expiry: bool = True
    require_issuer: bool = True
    require_audience: bool = True
    require_tenant: bool = True


class JWTSessionValidator:
    """Validates JWT tokens for embedded console session creation."""

    def __init__(self, config: EmbeddedSessionConfig, secret: str):
        self.config = config
        self.secret = secret

    def validate(self, token: str) -> Tuple[bool, str, Optional[Dict]]:
        """Validate a JWT token for embedded session creation.

        Returns (is_valid, error_message, claims).
        """
        if not token:
            return False, "Missing JWT token", None

        try:
            # Decode and verify the JWT
            payload = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                options={"verify_exp": self.config.require_expiry},
            )
        except jwt.ExpiredSignatureError:
            return False, "JWT token expired", None
        except jwt.InvalidTokenError as e:
            return False, f"Invalid JWT token: {str(e)}", None
        except Exception as e:
            return False, f"JWT validation failed: {str(e)}", None

        # Validate audience
        if self.config.require_audience:
            aud = payload.get("aud", "")
            if not aud:
                return False, "JWT missing audience claim", None
            if aud != self.config.expected_audience:
                return False, "JWT audience mismatch", None

        # Validate issuer
        if self.config.require_issuer:
            iss = payload.get("iss", "")
            if not iss:
                return False, "JWT missing issuer claim", None
            if iss != self.config.expected_issuer:
                return False, "JWT issuer mismatch", None

        # Validate tenant
        if self.config.require_tenant:
            tenant = payload.get("tenant", "")
            if not tenant:
                return False, "JWT missing tenant claim", None
            if self.config.allowed_tenants and tenant not in self.config.allowed_tenants:
                return False, "JWT tenant not allowed", None

        # Validate expiration explicitly if required
        if self.config.require_expiry:
            exp = payload.get("exp")
            if exp is None:
                return False, "JWT missing expiration claim", None
            if int(time.time()) >= exp:
                return False, "JWT token expired", None

            # Check max session TTL
            iat = payload.get("iat", 0)
            if exp - iat > self.config.max_session_ttl:
                return False, "JWT session TTL exceeds maximum allowed", None

        return True, "", payload


# Global config instances for embedded sessions
_embedded_session_config = EmbeddedSessionConfig(
    expected_audience="agent-orchestrator-embedded",
    expected_issuer="agent-orchestrator",
    allowed_tenants=set(),
    max_session_ttl=3600,
)

_embedded_session_validator = JWTSessionValidator(
    config=_embedded_session_config,
    secret="agent-orchestrator-embedded-secret-key",
)


def create_embedded_session(token: str) -> Dict:
    """Create an embedded console session from a validated JWT."""
    is_valid, error, claims = _embedded_session_validator.validate(token)
    if not is_valid:
        raise AuthenticationError(error)

    session_id = hashlib.sha256(f"{claims['sub']}:{claims.get('jti', '')}:{time.time()}".encode()).hexdigest()[:32]

    return {
        "session_id": session_id,
        "workspace_id": claims.get("sub", ""),
        "tenant": claims.get("tenant", ""),
        "created_at": int(time.time()),
        "expires_at": claims.get("exp", 0),
    }

def configure_embedded_sessions(
    audience: str = None,
    issuer: str = None,
    tenants: set = None,
    secret: str = None,
    max_ttl: int = None,
):
    """Update embedded session configuration at runtime."""
    global _embedded_session_config, _embedded_session_validator

    if audience is not None:
        _embedded_session_config.expected_audience = audience
    if issuer is not None:
        _embedded_session_config.expected_issuer = issuer
    if tenants is not None:
        _embedded_session_config.allowed_tenants = tenants
    if max_ttl is not None:
        _embedded_session_config.max_session_ttl = max_ttl

    _embedded_session_validator = JWTSessionValidator(
        config=_embedded_session_config,
        secret=secret or "agent-orchestrator-embedded-secret-key",
    )
