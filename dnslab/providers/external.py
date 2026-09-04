"""Provider for servers dnslab does not manage: host-run daemons, existing
appliances, anything reachable at a static address. start/stop are no-ops;
the manifest supplies the connection details under an ``external:`` key:

    provider: external
    external:
      host: myserver.example.net     # used for TLS validation
      ip: 192.0.2.10                 # optional; defaults to resolving host
      ca_file: /workspace/certs/corp-ca.pem   # optional; defaults to lab CA
"""

from __future__ import annotations

import socket

from .. import certs
from ..model import Instance, Profile, ServerSpec, Target
from .base import Provider


class ExternalProvider(Provider):
    name = "external"

    def start(self, spec: ServerSpec, profile: Profile, instance_name: str,
              *, wait: bool = True, timeout: float = 60, **overrides) -> Instance:
        ext = spec.raw.get("external", {})
        host = ext.get("host") or instance_name
        ip = ext.get("ip") or socket.gethostbyname(host)
        return Instance(
            name=instance_name, server=spec.name, profile=profile.name,
            provider=self.name, id="external", host=host, ip=ip, status="running",
            extra={"ca_file": ext.get("ca_file")},
        )

    def stop(self, instance: Instance) -> None:
        pass

    def discover(self) -> list[Instance]:
        return []  # nothing persistent to rediscover; start() is free to re-run

    def target(self, instance: Instance) -> Target:
        from ..registry import get
        spec = get(instance.server)
        caps = spec.capabilities
        return Target(
            name=instance.name,
            host=instance.host,
            ip=instance.ip or "",
            port_do53=spec.ports.get("do53") if caps.do53_listener else None,
            port_dot=spec.ports.get("dot") if caps.dot_listener or caps.dot_listener_via_proxy else None,
            tls_hostname=instance.host,
            ca_file=instance.extra.get("ca_file") or str(certs.ca_file()),
            provider=self.name,
            profile=instance.profile,
            capabilities=caps,
        )
