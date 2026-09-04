"""dnslab — multi-server DNS-over-TLS test lab orchestration.

Notebook-facing facade:

    import dnslab
    dnslab.registry()                          # what can I start?
    dnslab.start('lab-auth')                   # the transport-isolated upstream pair
    dnslab.start('unbound', profile='forwarder-dot')
    dnslab.status()                            # running instances (kernel-restart safe)
    t = dnslab.target('unbound')
    dnslab.checks.run_matrix([t])              # PASS/FAIL/SKIP DataFrame
    dnslab.stop('unbound')                     # or dnslab.nuke()
"""

from __future__ import annotations

from . import certs, checks, registry as _registry
from .model import Instance, Target
from .providers import get_provider

__all__ = ["start", "stop", "status", "target", "targets", "registry",
           "logs", "nuke", "ca_file", "checks", "certs"]


def registry() -> dict:
    return _registry.discover()


def ca_file() -> str:
    return str(certs.ca_file())


def start(name: str, profile: str | None = None, *,
          wait: bool = True, timeout: float = 60, **overrides) -> list[Instance]:
    """Start a server (all of its declared instances, or its single default one).

    Returns the list of started Instances. Capability `requires` on the
    chosen profile are enforced here so an unsupported combination fails
    fast with a clear message instead of a hung container.
    """
    spec = _registry.get(name)
    provider = get_provider(spec.provider)

    plan: list[tuple[str, str | None]]  # (instance_name, profile_name)
    if spec.instances:
        if profile is not None:
            plan = [(i, p) for i, p in spec.instances.items() if p == profile]
            if not plan:
                raise KeyError(f"{name}: no declared instance uses profile {profile!r}")
        else:
            plan = list(spec.instances.items())
    else:
        plan = [(name, profile)]

    started = []
    for instance_name, prof_name in plan:
        prof = spec.profile_for(prof_name)
        for flag in prof.requires:
            if not getattr(spec.capabilities, flag, False):
                raise RuntimeError(
                    f"{name}: profile {prof.name!r} requires capability {flag!r} "
                    f"which this server does not have ({spec.capabilities.notes or 'see manifest'})"
                )
        started.append(provider.start(spec, prof, instance_name,
                                      wait=wait, timeout=timeout, **overrides))
    return started


def _all_instances() -> list[Instance]:
    out = []
    for pname in ("docker", "ec2"):
        try:
            out.extend(get_provider(pname).discover())
        except (RuntimeError, NotImplementedError):
            continue  # provider unavailable in this environment (no socket / no creds)
    return out


def status(as_df: bool = True):
    insts = _all_instances()
    if not as_df:
        return insts
    import pandas as pd
    return pd.DataFrame(
        [{"instance": i.name, "server": i.server, "profile": i.profile,
          "provider": i.provider, "status": i.status, "ip": i.ip, "host": i.host}
         for i in insts]
    )


def _find(name: str) -> list[Instance]:
    return [i for i in _all_instances() if name in (i.name, i.server)]


def target(name: str) -> Target:
    matches = _find(name)
    if not matches:
        spec = _registry.get(name)
        if spec.provider == "external":
            prov = get_provider("external")
            inst = prov.start(spec, spec.profile_for(None), name)
            return prov.target(inst)
        raise RuntimeError(f"{name!r} is not running — dnslab.start({name!r}) first")
    if len(matches) > 1:
        raise RuntimeError(
            f"{name!r} matches multiple instances {[i.name for i in matches]}; "
            "use the instance name"
        )
    inst = matches[0]
    return get_provider(inst.provider).target(inst)


def targets(*names: str) -> list[Target]:
    if names:
        return [target(n) for n in names]
    return [get_provider(i.provider).target(i) for i in _all_instances()]


def logs(name: str, tail: int = 100) -> str:
    matches = _find(name)
    if not matches:
        return f"{name}: not running"
    return "\n\n".join(
        f"== {i.name} ==\n" + get_provider(i.provider).logs(i, tail) for i in matches
    )


def stop(name: str | None = None, *, all: bool = False) -> list[str]:
    stopped = []
    insts = _all_instances() if (all or name is None) else _find(name)
    if name and not insts:
        return []
    for inst in insts:
        get_provider(inst.provider).stop(inst)
        stopped.append(inst.name)
    return stopped


def nuke() -> dict[str, list[str]]:
    """Tear down everything dnslab ever started, across all providers."""
    removed = {}
    for pname in ("docker", "ec2"):
        try:
            removed[pname] = get_provider(pname).nuke()
        except (RuntimeError, NotImplementedError):
            removed[pname] = []
    return removed
