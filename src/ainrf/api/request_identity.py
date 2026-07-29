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


def client_ip(request: Request, trusted_cidrs: tuple[str, ...] | None = None) -> str:
    """Extract a client IP while trusting forwarding only from configured proxies."""

    direct_ip = request.client.host if request.client else "0.0.0.0"
    if trusted_cidrs:
        networks = parse_cidrs(trusted_cidrs)
        try:
            address = ipaddress.ip_address(direct_ip)
            host_network = ipaddress.ip_network(
                f"{address}/128" if address.version == 6 else f"{address}/32"
            )
            if any(network.supernet_of(host_network) for network in networks):
                forwarded = request.headers.get("x-forwarded-for")
                if forwarded:
                    return forwarded.split(",")[0].strip()
        except ValueError:
            pass
    elif request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    return direct_ip
