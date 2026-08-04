"""Network-boundary validation shared by Core listeners."""

from __future__ import annotations

import ipaddress
import socket


class LoopbackBindHostError(ValueError):
    """A Core listener was asked to bind outside loopback."""


def ensure_loopback_bind_host(host: str) -> None:
    """Reject bind hosts that do not resolve exclusively to loopback addresses."""
    candidate = host.strip()
    if not candidate:
        raise LoopbackBindHostError("Core listeners require a loopback bind host")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        address = None
    if address is not None:
        if address.is_loopback:
            return
        raise LoopbackBindHostError(
            f"Core listeners refuse non-loopback bind host {host!r}",
        )
    try:
        infos = socket.getaddrinfo(candidate, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise LoopbackBindHostError(f"Core bind host cannot be resolved: {host!r}") from exc
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            raise LoopbackBindHostError(f"Core bind host has no address: {host!r}")
        try:
            addresses.add(ipaddress.ip_address(str(sockaddr[0])))
        except ValueError as exc:
            raise LoopbackBindHostError(
                f"Core bind host resolved to an invalid address: {host!r}",
            ) from exc
    if not addresses or not all(address.is_loopback for address in addresses):
        raise LoopbackBindHostError(
            f"Core listeners refuse non-loopback bind host {host!r}",
        )


__all__ = ["LoopbackBindHostError", "ensure_loopback_bind_host"]
