"""Is this computer inside the institution's network (directly or through its VPN)?"""

from __future__ import annotations

import ipaddress

import httpx

IP_SERVICES = ("https://api.ipify.org", "https://icanhazip.com", "https://ifconfig.me/ip")


def public_ip(client: httpx.Client) -> str | None:
    for url in IP_SERVICES:
        try:
            response = client.get(url, timeout=8)
            candidate = response.text.strip()
            ipaddress.ip_address(candidate)
            return candidate
        except (httpx.HTTPError, ValueError):
            continue
    return None


def in_ranges(ip: str, ranges: list[str]) -> bool:
    address = ipaddress.ip_address(ip)
    return any(address in ipaddress.ip_network(r, strict=False) for r in ranges)
