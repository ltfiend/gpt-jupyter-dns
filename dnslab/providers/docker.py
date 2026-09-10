"""Tier-1 provider: DNS servers as sibling Docker containers.

The notebook container talks to the host docker daemon over the mounted
/var/run/docker.sock. Every server container joins the shared ``dnslab``
network with alias ``<instance>.dnslab.test`` so the notebook (also on
that network) reaches it by a TLS-valid hostname; no host ports are
published. Bind-mount sources are translated to host paths via
``state.to_host_path`` because the daemon resolves them on the host.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time

import jinja2

from .. import certs
from ..model import Instance, Profile, ServerSpec, Target
from ..state import network_name, state_dir, to_host_path
from .base import Provider

LABEL = "dnslab"
CERTS_MOUNT = "/dnslab/certs"
ZONES_MOUNT = "/dnslab/zones"
DOMAIN = "dnslab.test"


def _client():
    try:
        import docker  # noqa: PLC0415 — lazy so registry/selfcheck work without the sdk
    except ImportError as e:
        raise RuntimeError(
            "the 'docker' python package is required for the docker provider "
            "(pip install docker) and /var/run/docker.sock must be mounted"
        ) from e
    return docker.from_env()


class DockerProvider(Provider):
    name = "docker"

    def __init__(self):
        self._c = _client()

    # ---- network -----------------------------------------------------------
    def ensure_network(self):
        import docker
        try:
            return self._c.networks.get(network_name())
        except docker.errors.NotFound:
            return self._c.networks.create(network_name(), driver="bridge")

    def _container_ip(self, container) -> str | None:
        container.reload()
        nets = container.attrs["NetworkSettings"]["Networks"]
        net = nets.get(network_name())
        return net["IPAddress"] if net else None

    def upstreams(self) -> dict[str, dict]:
        """Connection info for the running lab-auth upstream pair.

        Returned as template context: ``upstream_do53`` / ``upstream_dot``
        dicts with host/ip/port/tls_hostname, or empty dicts when the
        upstream instance is not running (templates should degrade or the
        server module should require lab-auth to be started first).
        """
        out: dict[str, dict] = {"upstream_do53": {}, "upstream_dot": {}}
        for inst in self.discover():
            if inst.server != "lab-auth":
                continue
            info = {
                "host": inst.host,
                "ip": inst.ip,
                "tls_hostname": inst.host,
            }
            if inst.name.endswith("do53"):
                out["upstream_do53"] = {**info, "port": 53}
            elif inst.name.endswith("dot"):
                out["upstream_dot"] = {**info, "port": 853}
        return out

    # ---- rendering ---------------------------------------------------------
    def render(self, spec: ServerSpec, profile: Profile, instance_name: str,
               overrides: dict | None = None) -> tuple:
        """Render the profile template + stage zone files into the state dir."""
        inst_dir = state_dir(instance_name)
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(spec.dir),
            undefined=jinja2.StrictUndefined,
            keep_trailing_newline=True,
        )
        ctx = {
            "instance_name": instance_name,
            "tls_hostname": f"{instance_name}.{DOMAIN}",
            "tls_cert_path": f"{CERTS_MOUNT}/{instance_name}.pem",
            "tls_key_path": f"{CERTS_MOUNT}/{instance_name}.key",
            "ca_path": f"{CERTS_MOUNT}/{certs.CA_NAME}.pem",
            "zones_dir": ZONES_MOUNT,
            "listen_do53": "do53" in profile.listeners,
            "listen_dot": "dot" in profile.listeners,
            "port_do53": spec.ports.get("do53", 53),
            "port_dot": spec.ports.get("dot", 853),
            **self.upstreams(),
            **profile.extra,
            **(overrides or {}),
        }
        rendered = env.get_template(profile.template).render(**ctx)
        config_file = inst_dir / (profile.template.rsplit("/", 1)[-1].removesuffix(".j2"))
        config_file.write_text(rendered)
        # Bind-mounted into containers whose servers drop to non-root users;
        # don't let the caller's umask (or the checkout's modes, via copytree)
        # make these unreadable there.
        config_file.chmod(0o644)

        zones_src = spec.dir / "zones"
        zones_dst = inst_dir / "zones"
        if zones_src.is_dir():
            if zones_dst.exists():
                shutil.rmtree(zones_dst)
            shutil.copytree(zones_src, zones_dst)
            zones_dst.chmod(0o755)
            for p in zones_dst.rglob("*"):
                p.chmod(0o755 if p.is_dir() else 0o644)
        return config_file, (zones_dst if zones_src.is_dir() else None)

    # ---- lifecycle ---------------------------------------------------------
    @staticmethod
    def _confhash(spec: ServerSpec, config_file, zones_dir) -> str:
        """Fingerprint of everything that shapes a running container, so
        start() can tell an unchanged instance from config drift."""
        h = hashlib.sha256()
        h.update(config_file.read_bytes())
        if zones_dir:
            for f in sorted(p for p in zones_dir.rglob("*") if p.is_file()):
                h.update(f.name.encode())
                h.update(f.read_bytes())
        h.update(json.dumps([spec.image, spec.build, spec.command]).encode())
        return h.hexdigest()[:16]

    def start(self, spec: ServerSpec, profile: Profile, instance_name: str,
              *, wait: bool = True, timeout: float | None = None,
              force: bool = False, **overrides) -> Instance:
        import docker

        if timeout is None:
            timeout = float(spec.raw.get("start_timeout", 60))
        self.ensure_network()
        certs.ensure_cert(instance_name)
        config_file, zones_dir = self.render(spec, profile, instance_name, overrides)
        confhash = self._confhash(spec, config_file, zones_dir)

        # Reuse a running container whose profile AND rendered config are
        # unchanged and that still answers its healthcheck; anything else
        # (drift, unhealthy, force=True) is recreated below.
        cname = f"dnslab-{instance_name}"
        existing = None
        try:
            existing = self._c.containers.get(cname)
        except docker.errors.NotFound:
            pass
        if existing is not None and not force:
            lbl = existing.labels
            if (existing.status == "running"
                    and lbl.get(f"{LABEL}-profile") == profile.name
                    and lbl.get(f"{LABEL}-confhash") == confhash):
                inst = Instance(
                    name=instance_name, server=spec.name, profile=profile.name,
                    provider=self.name, id=existing.id[:12],
                    host=f"{instance_name}.{DOMAIN}",
                    ip=self._container_ip(existing), status="running",
                )
                try:
                    self._wait_healthy(spec, profile, inst, existing,
                                       min(timeout, 15))
                    inst.status = "reused"
                    return inst
                except (TimeoutError, RuntimeError):
                    pass  # running but not answering — fall through to recreate

        image = spec.image
        if spec.build:
            image = f"dnslab/{spec.name}:local"
            self._c.images.build(path=str(spec.dir / spec.build), tag=image, rm=True)
        elif image:
            try:
                self._c.images.get(image)
            except docker.errors.ImageNotFound:
                self._c.images.pull(image)
        else:
            raise ValueError(f"server {spec.name!r}: manifest needs 'image' or 'build'")

        try:
            self._c.containers.get(cname).remove(force=True)
        except docker.errors.NotFound:
            pass

        volumes = {
            to_host_path(config_file): {"bind": profile.config_path, "mode": "ro"},
            to_host_path(certs.certs_dir()): {"bind": CERTS_MOUNT, "mode": "ro"},
        }
        if zones_dir:
            volumes[to_host_path(zones_dir)] = {"bind": ZONES_MOUNT, "mode": "ro"}

        alias = f"{instance_name}.{DOMAIN}"
        container = self._c.containers.create(
            image,
            command=spec.command,
            name=cname,
            hostname=alias,
            labels={
                LABEL: "1",
                f"{LABEL}-server": spec.name,
                f"{LABEL}-instance": instance_name,
                f"{LABEL}-profile": profile.name,
                f"{LABEL}-confhash": confhash,
            },
            volumes=volumes,
            detach=True,
        )
        self._c.networks.get(network_name()).connect(container, aliases=[alias, instance_name])
        container.start()

        inst = Instance(
            name=instance_name, server=spec.name, profile=profile.name,
            provider=self.name, id=container.id[:12], host=alias,
            ip=self._container_ip(container), status="starting",
        )
        if wait:
            self._wait_healthy(spec, profile, inst, container, timeout)
        inst.status = "running"
        return inst

    def _wait_healthy(self, spec, profile, inst, container, timeout: float):
        import dns.message
        import dns.query

        hc = spec.healthcheck or {}
        qname, qtype = hc.get("qname", "."), hc.get("qtype", "SOA")
        use_dot = "do53" not in profile.listeners
        deadline = time.monotonic() + timeout
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            container.reload()
            if container.status == "exited":
                raise RuntimeError(
                    f"{inst.name}: container exited during startup\n"
                    + container.logs(tail=30).decode(errors="replace")
                )
            inst.ip = self._container_ip(container) or inst.ip
            try:
                q = dns.message.make_query(qname, qtype)
                if use_dot:
                    import ssl
                    sslctx = ssl.create_default_context(cafile=str(certs.ca_file()))
                    dns.query.tls(q, inst.ip, timeout=3, port=spec.ports.get("dot", 853),
                                  ssl_context=sslctx, server_hostname=inst.host)
                else:
                    dns.query.udp(q, inst.ip, timeout=3, port=spec.ports.get("do53", 53))
                return
            except Exception as e:  # noqa: BLE001 — retry any transient failure
                last_err = e
                time.sleep(0.5)
        raise TimeoutError(
            f"{inst.name}: not answering after {timeout}s (last error: {last_err})\n"
            + container.logs(tail=30).decode(errors="replace")
        )

    def stop(self, instance: Instance) -> None:
        import docker
        try:
            c = self._c.containers.get(f"dnslab-{instance.name}")
        except docker.errors.NotFound:
            return
        c.remove(force=True)

    def discover(self) -> list[Instance]:
        out = []
        for c in self._c.containers.list(all=True, filters={"label": f"{LABEL}=1"}):
            labels = c.labels
            inst_name = labels.get(f"{LABEL}-instance", c.name.removeprefix("dnslab-"))
            out.append(Instance(
                name=inst_name,
                server=labels.get(f"{LABEL}-server", inst_name),
                profile=labels.get(f"{LABEL}-profile", "?"),
                provider=self.name,
                id=c.id[:12],
                host=f"{inst_name}.{DOMAIN}",
                ip=self._container_ip(c),
                status=c.status,
            ))
        return out

    def target(self, instance: Instance) -> Target:
        from ..registry import get
        spec = get(instance.server)
        profile = spec.profiles.get(instance.profile)
        listeners = profile.listeners if profile else ("do53", "dot")
        caps = spec.capabilities
        return Target(
            name=instance.name,
            host=instance.host,
            ip=instance.ip or "",
            port_do53=spec.ports.get("do53") if "do53" in listeners and caps.do53_listener else None,
            port_dot=spec.ports.get("dot") if "dot" in listeners and (caps.dot_listener or caps.dot_listener_via_proxy) else None,
            tls_hostname=instance.host,
            ca_file=str(certs.ca_file()),
            provider=self.name,
            profile=instance.profile,
            capabilities=caps,
        )

    def logs(self, instance: Instance, tail: int = 100) -> str:
        import docker
        try:
            c = self._c.containers.get(f"dnslab-{instance.name}")
        except docker.errors.NotFound:
            return f"{instance.name}: no container"
        return c.logs(tail=tail).decode(errors="replace")
