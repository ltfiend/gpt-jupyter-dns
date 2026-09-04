"""Core datatypes for the dnslab framework.

Everything the registry, providers, and checks exchange is defined here so
the contract between per-server modules and the framework stays explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Capabilities:
    """Honest, verified capability flags for a server implementation.

    Per-server agents must only set a flag true after verifying it against
    the pinned image/AMI. Checks use these flags to SKIP (not FAIL) tests
    the implementation cannot support.
    """

    roles: frozenset[str] = frozenset()  # {"recursive", "forwarder", "authoritative"}
    do53_listener: bool = True
    dot_listener: bool = False
    dot_upstream_forwarding: bool = False
    dot_listener_via_proxy: bool = False  # non-native DoT termination (e.g. stunnel)
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Capabilities":
        return cls(
            roles=frozenset(d.get("roles", [])),
            do53_listener=bool(d.get("do53_listener", True)),
            dot_listener=bool(d.get("dot_listener", False)),
            dot_upstream_forwarding=bool(d.get("dot_upstream_forwarding", False)),
            dot_listener_via_proxy=bool(d.get("dot_listener_via_proxy", False)),
            notes=str(d.get("notes", "")),
        )


@dataclass(frozen=True)
class Profile:
    """One runnable configuration of a server (a rendered config template)."""

    name: str
    template: str  # path relative to the server dir, e.g. profiles/forwarder-dot.conf.j2
    config_path: str  # absolute path *inside the server container/instance*
    listeners: tuple[str, ...] = ("do53", "dot")  # which listeners this profile enables
    requires: tuple[str, ...] = ()  # capability flags that must be true to start
    extra: dict = field(default_factory=dict)  # server-module-specific knobs

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "Profile":
        known = {"template", "config_path", "listeners", "requires"}
        return cls(
            name=name,
            template=d["template"],
            config_path=d["config_path"],
            listeners=tuple(d.get("listeners", ["do53", "dot"])),
            requires=tuple(d.get("requires", [])),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass(frozen=True)
class ServerSpec:
    """Parsed manifest.yaml for one server module (servers/<name>/)."""

    name: str
    dir: Path
    provider: str  # docker | ec2 | external
    tier: int
    capabilities: Capabilities
    profiles: dict[str, Profile]
    ports: dict[str, int]  # {"do53": 53, "dot": 853}
    healthcheck: dict
    image: str | None = None  # pinned image ref (docker provider)
    build: str | None = None  # subdir with a Dockerfile, alternative to image
    command: list[str] | None = None  # container command override
    default_profile: str | None = None
    instances: dict[str, str] = field(default_factory=dict)  # instance name -> profile
    raw: dict = field(default_factory=dict)  # full manifest for provider-specific keys

    def profile_for(self, requested: str | None) -> Profile:
        name = requested or self.default_profile or next(iter(self.profiles))
        try:
            return self.profiles[name]
        except KeyError:
            raise KeyError(
                f"server {self.name!r} has no profile {name!r}; "
                f"available: {sorted(self.profiles)}"
            ) from None


@dataclass
class Instance:
    """A running (or discovered) server instance."""

    name: str  # instance name, e.g. "unbound" or "lab-auth-dot"
    server: str  # server module name, e.g. "unbound" or "lab-auth"
    profile: str
    provider: str
    id: str  # container id / EC2 instance id / "external"
    host: str  # TLS-valid hostname, e.g. "unbound.dnslab.test"
    ip: str | None = None
    status: str = "unknown"
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Target:
    """Everything a test needs to point at one server instance."""

    name: str
    host: str
    ip: str
    port_do53: int | None
    port_dot: int | None
    tls_hostname: str
    ca_file: str
    provider: str
    profile: str
    capabilities: Capabilities

    @property
    def address(self) -> str:
        return self.ip or self.host


@dataclass
class CheckResult:
    """Outcome of one functional check against one target."""

    check: str
    target: str
    status: str  # PASS | FAIL | SKIP
    detail: str = ""
    latency_ms: float | None = None

    def __bool__(self) -> bool:
        return self.status == "PASS"
