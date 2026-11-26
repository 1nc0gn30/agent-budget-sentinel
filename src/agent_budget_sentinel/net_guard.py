"""Network, Origin & SSRF Guardrails for Agent Budget Sentinel.

100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import urllib.parse
from typing import Optional, Set, Tuple

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
    "instance-data",
})


def is_local_origin(origin: Optional[str]) -> bool:
    """Strict browser Origin check preventing CSRF and hostname-spoof bypasses.

    - No Origin header -> non-browser CLI/agent caller -> allowed.
    - Otherwise requires exact http(s)://(localhost|127.0.0.1|[::1])(:<valid_port>)?
      with no userinfo, path, query, or malformed port suffix like `:8110.evil.com`.
    """
    if origin is None or origin == "":
        return True
    if not isinstance(origin, str):
        return False

    raw = origin.strip()
    if not raw or raw.lower() == "null":
        return False

    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
        return False

    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        return False

    # Accessing parsed.port raises ValueError on spoofed suffixes like `:8110.evil.com`
    try:
        port = parsed.port
    except ValueError:
        return False

    if port is not None and not (1 <= port <= 65535):
        return False

    canonical_host = f"[{host}]" if ":" in host else host
    expected_netloc = f"{canonical_host}:{port}" if port is not None else canonical_host
    return parsed.netloc.lower() == expected_netloc


def _allowed_local_upstreams() -> Set[str]:
    """Parse opt-in AGENT_BUDGET_ALLOW_LOCAL_UPSTREAMS env var (comma-separated host or host:port)."""
    raw = os.environ.get("AGENT_BUDGET_ALLOW_LOCAL_UPSTREAMS", "")
    entries: Set[str] = set()
    for part in raw.split(","):
        cleaned = part.strip().lower()
        if cleaned:
            entries.add(cleaned)
    return entries


def _is_ip_restricted(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if IP is loopback, private, link-local/IMDS, multicast, reserved, or unspecified."""
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
        ip_obj = ip_obj.ipv4_mapped
    return bool(
        ip_obj.is_loopback
        or ip_obj.is_private
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def validate_upstream_url(
    url: str,
    *,
    allow_configured_local: bool = False,
) -> Tuple[bool, str]:
    """Validate an upstream proxy target URL against SSRF, local file access, and cloud IMDS.

    - Strictly allows only http:// and https:// schemes.
    - Rejects embedded credentials and malformed ports.
    - Blocks loopback, RFC1918 private networks, link-local/IMDS (169.254.0.0/16, fe80::/10),
      multicast, and reserved ranges unless explicitly opted in via:
        * allow_configured_local=True (operator-configured --upstream), or
        * AGENT_BUDGET_ALLOW_LOCAL_UPSTREAMS=host:port[,...]
    """
    if not url or not isinstance(url, str):
        return False, "Empty upstream URL."

    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return False, "Malformed upstream URL."

    if parsed.scheme not in ("http", "https"):
        return False, f"Disallowed upstream URL scheme '{parsed.scheme or 'none'}'; only http/https allowed."

    if parsed.username is not None or parsed.password is not None:
        return False, "Credentials embedded in upstream URL are not allowed."

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False, "Upstream URL is missing a hostname."

    try:
        port = parsed.port
    except ValueError:
        return False, "Invalid port in upstream URL."

    effective_port = port if port is not None else (443 if parsed.scheme == "https" else 80)
    if not (1 <= effective_port <= 65535):
        return False, "Upstream port out of valid range (1-65535)."

    # Check explicit opt-in allowlist for trusted local upstreams (e.g., Ollama / isolated tests)
    allowlist = _allowed_local_upstreams()
    host_key = f"[{host}]" if ":" in host else host
    host_port_key = f"{host_key}:{effective_port}"
    is_opted_in = (
        allow_configured_local
        or host_port_key in allowlist
        or host_key in allowlist
        or host in allowlist
    )

    if is_opted_in:
        return True, "Allowed by explicit local upstream policy."

    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost") or host.endswith(".local"):
        return False, f"Blocked restricted upstream host '{host}'."

    # Direct IP literal check before DNS resolution
    try:
        literal_ip = ipaddress.ip_address(host)
        if _is_ip_restricted(literal_ip):
            return False, f"Blocked restricted upstream IP '{host}'."
        return True, "ok"
    except ValueError:
        pass

    # Resolve hostname via getaddrinfo and inspect all returned addresses
    try:
        infos = socket.getaddrinfo(host, effective_port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return False, f"Failed to resolve upstream host '{host}': {exc}"

    if not infos:
        return False, f"No DNS records found for upstream host '{host}'."

    for _family, _type, _proto, _canon, sockaddr in infos:
        addr_str = sockaddr[0]
        try:
            resolved_ip = ipaddress.ip_address(addr_str)
        except ValueError:
            return False, f"Unparseable resolved address '{addr_str}'."
        if _is_ip_restricted(resolved_ip):
            return False, f"Blocked upstream host '{host}' resolving to restricted IP '{addr_str}'."

    return True, "ok"
