"""Tests for hostname normalization and outbound request policy."""

import pytest
from src.security.hostname import (
    normalize_hostname,
    extract_hostname_from_url,
    HostnameAllowlist,
)
from src.security.policy import OutboundRequestPolicy


class TestNormalizeHostname:
    def test_trailing_dot_removal(self):
        assert normalize_hostname("example.com.") == "example.com"

    def test_case_insensitive(self):
        assert normalize_hostname("EXAMPLE.COM") == "example.com"
        assert normalize_hostname("Example.Com") == "example.com"

    def test_punycode_idna(self):
        # IDNA punycode normalization
        normalized = normalize_hostname("xn--mnchen-3ya.de")
        assert normalized in ("xn--mnchen-3ya.de", "münchen.de")

    def test_percent_encoded(self):
        # URL-encoded characters in hostname
        normalized = normalize_hostname("%65xample.com")
        assert "e" in normalized

    def test_empty_hostname(self):
        assert normalize_hostname("") == ""

    def test_port_stripping(self):
        assert normalize_hostname("api.example.com:8080") == "api.example.com"


class TestExtractHostname:
    def test_standard_url(self):
        hostname = extract_hostname_from_url("https://api.example.com/v1/users")
        assert hostname == "api.example.com"

    def test_url_with_port(self):
        hostname = extract_hostname_from_url("http://localhost:8000/health")
        assert hostname == "localhost"

    def test_invalid_url(self):
        assert extract_hostname_from_url("not-a-valid-url") is None

    def test_url_trailing_dot(self):
        hostname = extract_hostname_from_url("https://example.com./path")
        assert hostname == "example.com"


class TestHostnameAllowlist:
    def test_exact_match(self):
        allowlist = HostnameAllowlist(["api.example.com"])
        assert allowlist.is_allowed("api.example.com") is True
        assert allowlist.is_allowed("api.example.com.") is True
        assert allowlist.is_allowed("API.EXAMPLE.COM") is True

    def test_wildcard_match(self):
        allowlist = HostnameAllowlist(["*.example.com"])
        assert allowlist.is_allowed("api.example.com") is True
        assert allowlist.is_allowed("other.example.com") is True
        assert allowlist.is_allowed("api.other.com") is False

    def test_not_allowed(self):
        allowlist = HostnameAllowlist(["api.example.com"])
        assert allowlist.is_allowed("evil.com") is False

    def test_add_and_remove(self):
        allowlist = HostnameAllowlist(["a.com"])
        allowlist.add("b.com")
        assert allowlist.is_allowed("b.com") is True
        allowlist.remove("b.com")
        assert allowlist.is_allowed("b.com") is False

    def test_multiple_patterns(self):
        allowlist = HostnameAllowlist(["api.example.com", "*.internal.net", "localhost"])
        assert allowlist.is_allowed("api.example.com") is True
        assert allowlist.is_allowed("service.internal.net") is True
        assert allowlist.is_allowed("localhost") is True
        assert allowlist.is_allowed("external.com") is False


class TestOutboundRequestPolicy:
    def test_allowed_request(self):
        policy = OutboundRequestPolicy(["api.example.com"])
        allowed, _ = policy.evaluate("https://api.example.com/v1/data")
        assert allowed is True

    def test_denied_request(self):
        policy = OutboundRequestPolicy(["api.example.com"])
        allowed, reason = policy.evaluate("https://evil.com/steal")
        assert allowed is False
        assert "not in allowlist" in reason

    def test_audit_log(self):
        policy = OutboundRequestPolicy(["api.example.com"])
        policy.evaluate("https://api.example.com/v1")
        policy.evaluate("https://evil.com/v1")
        log = policy.get_audit_log()
        assert len(log) == 2
        assert log[0]["allowed"] is True
        assert log[1]["allowed"] is False

    def test_invalid_url(self):
        policy = OutboundRequestPolicy(["api.example.com"])
        allowed, reason = policy.evaluate("not-a-url")
        assert allowed is False
        assert "Invalid URL" in reason

    def test_normalized_hostname_in_audit(self):
        policy = OutboundRequestPolicy(["api.example.com"])
        policy.evaluate("https://API.EXAMPLE.COM./path")
        log = policy.get_audit_log()
        assert log[0]["hostname"] == "api.example.com"