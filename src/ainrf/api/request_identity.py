"""Transport mapper for deriving bounded request identity."""

from __future__ import annotations

import ipaddress

from fastapi import Request


def parse_cidrs(raw: tuple[str, ...]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in raw:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    return networks


def _trusted_proxy_cidrs(request: Request) -> tuple[str, ...]:
    config = getattr(request.app.state, "api_config", None)
    trusted_cidrs = getattr(config, "trusted_proxy_cidrs", ())
    return trusted_cidrs if isinstance(trusted_cidrs, tuple) else ()


def client_ip(request: Request) -> str:
    """Extract the client IP using the configured trusted-proxy chain."""

    direct_ip = request.client.host if request.client else "0.0.0.0"
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return direct_ip

    trusted_cidrs = _trusted_proxy_cidrs(request)
    networks = parse_cidrs(trusted_cidrs)
    try:
        direct_address = ipaddress.ip_address(direct_ip)
    except ValueError:
        return direct_ip

    if trusted_cidrs and (
        not networks or not any(direct_address in network for network in networks)
    ):
        return direct_ip

    forwarded_addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw_address in forwarded.split(","):
        try:
            forwarded_addresses.append(ipaddress.ip_address(raw_address.strip()))
        except ValueError:
            return direct_ip
    if not forwarded_addresses:
        return direct_ip

    if not trusted_cidrs:
        return str(forwarded_addresses[0])

    for address in reversed(forwarded_addresses):
        if not any(address in network for network in networks):
            return str(address)
    return str(forwarded_addresses[0])
