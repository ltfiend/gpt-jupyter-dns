"""Provider lookup. Providers are instantiated lazily so that importing
dnslab (or running selfcheck in CI) never requires a docker socket or AWS
credentials."""

from __future__ import annotations

from .base import Provider

_cache: dict[str, Provider] = {}


def get_provider(name: str) -> Provider:
    if name not in _cache:
        if name == "docker":
            from .docker import DockerProvider
            _cache[name] = DockerProvider()
        elif name == "ec2":
            from .ec2 import Ec2Provider
            _cache[name] = Ec2Provider()
        elif name == "external":
            from .external import ExternalProvider
            _cache[name] = ExternalProvider()
        else:
            raise KeyError(f"unknown provider {name!r}")
    return _cache[name]
