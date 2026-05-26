"""Outbound connector request policy."""

import logging
from typing import Optional
from .hostname import HostnameAllowlist, extract_hostname_from_url


logger = logging.getLogger(__name__)


class OutboundRequestPolicy:
    """
    Policy for evaluating outbound connector requests.
    
    Validates that outbound requests are made only to allowed hosts.
    """
    
    def __init__(self, allowed_hosts: list[str] = None):
        """
        Initialize with allowed host patterns.
        
        Args:
            allowed_hosts: List of hostname patterns (may include wildcards)
        """
        self.allowlist = HostnameAllowlist(allowed_hosts or [])
        self._audit_log = []
    
    def evaluate(self, url: str, method: str = "GET") -> tuple[bool, str]:
        """
        Evaluate whether a request is allowed.
        
        Args:
            url: Target URL
            method: HTTP method
            
        Returns:
            Tuple of (allowed, reason)
        """
        hostname = extract_hostname_from_url(url)
        if hostname is None:
            return False, "Invalid URL format"
        
        if self.allowlist.is_allowed(hostname):
            self._audit(hostname, url, method, True, "Allowed by policy")
            return True, "Allowed"
        else:
            self._audit(hostname, url, method, False, "Host not in allowlist")
            return False, f"Host '{hostname}' not in allowlist"
    
    def _audit(self, hostname: str, url: str, method: str, 
               allowed: bool, reason: str) -> None:
        """Record audit event."""
        event = {
            "hostname": hostname,
            "url": url,
            "method": method,
            "allowed": allowed,
            "reason": reason,
            "timestamp": self._current_timestamp()
        }
        self._audit_log.append(event)
        logger.info("Outbound request %s: %s", 
                    "allowed" if allowed else "denied", 
                    reason)
    
    def _current_timestamp(self) -> str:
        """Get current timestamp for audit events."""
        from datetime import datetime
        return datetime.utcnow().isoformat() + "Z"
    
    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """
        Get recent audit events.
        
        Args:
            limit: Maximum number of events to return
            
        Returns:
            List of audit events
        """
        return self._audit_log[-limit:] if self._audit_log else []