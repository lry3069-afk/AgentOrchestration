"""Hostname normalization for security policy evaluation."""

import re
from typing import Optional
from urllib.parse import urlparse


def normalize_hostname(hostname: str) -> str:
    """
    Normalize a hostname for consistent policy evaluation.
    
    Handles:
    - Trailing dots (RFC 1034)
    - IDNA (Internationalized Domain Names)
    - Case-insensitive comparison (lowercase)
    - Percent-encoded hostnames
    
    Args:
        hostname: Raw hostname string (may include port)
        
    Returns:
        Canonicalized hostname string
    """
    if not hostname:
        return ""
    
    # Remove port if present
    if ":" in hostname and not hostname.startswith("["):
        hostname = hostname.split(":", 1)[0]
    
    # Remove trailing dot (RFC 1034)
    hostname = hostname.rstrip(".")
    
    # Convert to lowercase (hostnames are case-insensitive)
    hostname = hostname.lower()
    
    # Decode percent-encoded characters (if any)
    try:
        import urllib.parse
        hostname = urllib.parse.unquote(hostname)
    except Exception:
        pass
    
    # IDNA normalization (punycode)
    try:
        import idna
        hostname = idna.encode(hostname).decode("ascii")
    except (ImportError, idna.IDNAError, UnicodeError):
        # Fallback to simple ASCII normalization
        hostname = hostname.encode("idna").decode("ascii")
    
    return hostname


def extract_hostname_from_url(url: str) -> Optional[str]:
    """
    Extract and normalize hostname from a URL.
    
    Args:
        url: Full URL string
        
    Returns:
        Normalized hostname or None if invalid
    """
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return None
        return normalize_hostname(parsed.netloc)
    except Exception:
        return None


class HostnameAllowlist:
    """Hostname allowlist with normalized comparison."""
    
    def __init__(self, allowed_hosts: list[str]):
        """
        Initialize with a list of allowed host patterns.
        
        Args:
            allowed_hosts: List of hostname patterns (may include wildcards)
        """
        self._allowed = [normalize_hostname(h) for h in allowed_hosts]
    
    def is_allowed(self, hostname: str) -> bool:
        """
        Check if a hostname is allowed.
        
        Args:
            hostname: Hostname to check (raw string)
            
        Returns:
            True if hostname matches any allowed pattern
        """
        normalized = normalize_hostname(hostname)
        
        # Exact match
        if normalized in self._allowed:
            return True
        
        # Wildcard matching (e.g., "*.example.com")
        for pattern in self._allowed:
            if pattern.startswith("*."):
                domain = pattern[2:]
                if normalized.endswith("." + domain) or normalized == domain:
                    return True
        
        return False
    
    def add(self, hostname: str) -> None:
        """Add a hostname to the allowlist."""
        self._allowed.append(normalize_hostname(hostname))
    
    def remove(self, hostname: str) -> None:
        """Remove a hostname from the allowlist."""
        normalized = normalize_hostname(hostname)
        if normalized in self._allowed:
            self._allowed.remove(normalized)