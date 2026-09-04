"""Tier-2/3 provider: DNS servers on EC2 instances launched via boto3.

CONTRACT (implemented by the windows-dns integration, first consumer):

* start(): launch the AMI named by the manifest — either a direct ``ami:``
  id, or preferably ``ami_ssm_parameter:`` (SSM public parameter lookup,
  e.g. /aws/service/ami-windows-latest/Windows_Server-2025-English-Full-Base)
  so AMI ids stay region-portable. Instance type from manifest
  ``instance_type`` (default t3.medium).
* Tag every resource: dnslab=1, dnslab-server=<name>,
  dnslab-session=<uuid4>, dnslab-expires=<iso8601 utc now+4h>.
* Security group dnslab-<session> scoped to the caller's public IP /32
  (via https://checkip.amazonaws.com): udp/53, tcp/53, tcp/853, and
  tcp/3389 only when manifest ``rdp: true``.
* Configuration via user-data (the profile's template is a .j2 in the
  server dir, rendered with the same context names as docker profiles).
* State manifest via state.save_state("ec2", ...) so a restarted kernel
  rediscovers; discover() must ALSO re-describe by tag filter and
  reconcile, treating tags as the source of truth.
* status() surfaces running-hours; anything past dnslab-expires is flagged.
* nuke(): terminate all dnslab=1 instances and delete dnslab-* SGs.
* No AWS calls at import time; boto3 imported lazily inside methods.

Region/credentials come from the normal boto3 chain (env vars,
``AWS_PROFILE``, instance metadata); nothing is hardcoded here. Every AWS
failure is re-raised as a RuntimeError naming what to configure.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import jinja2

from ..model import Instance, Profile, ServerSpec, Target
from ..state import load_state, save_state, state_dir
from .base import Provider

TAG = "dnslab"
DOMAIN = "dnslab.test"
DEFAULT_INSTANCE_TYPE = "t3.medium"
EXPIRES_HOURS = 4
CHECKIP_URL = "https://checkip.amazonaws.com"
# every non-terminated lifecycle state — discover() must see instances that
# are still winding up or down so nuke()/status() never miss a billed box
ACTIVE_STATES = ("pending", "running", "shutting-down", "stopping", "stopped")
SG_DELETE_RETRY_S = 240  # ENIs linger after terminate; retry DependencyViolation


# ---------------------------------------------------------------------------
# pure helpers (no AWS) — unit-testable without credentials
# ---------------------------------------------------------------------------

def expires_at(now: datetime | None = None) -> str:
    """ISO8601 UTC expiry stamp for the dnslab-expires tag (now + 4h)."""
    now = now or datetime.now(timezone.utc)
    exp = (now + timedelta(hours=EXPIRES_HOURS)).astimezone(timezone.utc)
    return exp.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_expired(expires: str, now: datetime | None = None) -> bool:
    """True when an ISO8601 dnslab-expires tag lies in the past."""
    now = now or datetime.now(timezone.utc)
    try:
        exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return False  # unparseable tag: don't cry wolf
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp <= now


def running_hours(launched_iso: str, now: datetime | None = None) -> float | None:
    now = now or datetime.now(timezone.utc)
    try:
        t0 = datetime.fromisoformat(launched_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    return max((now - t0).total_seconds() / 3600.0, 0.0)


def resolve_ami_source(raw: dict) -> tuple[str, str]:
    """Manifest -> ("ssm", parameter-name) or ("ami", ami-id)."""
    if raw.get("ami_ssm_parameter"):
        return "ssm", str(raw["ami_ssm_parameter"])
    if raw.get("ami"):
        return "ami", str(raw["ami"])
    raise ValueError(
        f"server {raw.get('name', '?')!r}: manifest needs 'ami_ssm_parameter' "
        "(preferred, region-portable) or a literal 'ami' id for the ec2 provider"
    )


def sg_ingress_rules(caller_cidr: str, rdp: bool) -> list[dict]:
    """IpPermissions for the session SG, all scoped to the caller's /32."""
    def rule(proto: str, port: int, what: str) -> dict:
        return {
            "IpProtocol": proto, "FromPort": port, "ToPort": port,
            "IpRanges": [{"CidrIp": caller_cidr, "Description": f"dnslab {what}"}],
        }
    rules = [
        rule("udp", 53, "do53/udp"),
        rule("tcp", 53, "do53/tcp"),
        rule("tcp", 853, "dot"),
    ]
    if rdp:
        rules.append(rule("tcp", 3389, "rdp"))
    return rules


def caller_public_ip(timeout: float = 10) -> str:
    import ipaddress
    import urllib.request
    try:
        with urllib.request.urlopen(CHECKIP_URL, timeout=timeout) as r:
            ip = r.read().decode("ascii", errors="replace").strip()
        ipaddress.ip_address(ip)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"could not determine the caller's public IP via {CHECKIP_URL} "
            f"({e}); the session security group is scoped to that IP"
        ) from e
    return ip


# ---------------------------------------------------------------------------
# AWS plumbing (all lazy)
# ---------------------------------------------------------------------------

def _boto3():
    try:
        import boto3  # noqa: PLC0415 — lazy so import/selfcheck need no AWS
    except ImportError as e:
        raise RuntimeError(
            "the 'boto3' python package is required for the ec2 provider "
            "(pip install boto3)"
        ) from e
    return boto3


def _session():
    s = _boto3().session.Session()
    if not s.region_name:
        raise RuntimeError(
            "no AWS region configured — set AWS_REGION / AWS_DEFAULT_REGION, "
            "or point AWS_PROFILE at a profile with a region (aws configure)"
        )
    return s


def _wrap(e: Exception, doing: str) -> RuntimeError:
    return RuntimeError(
        f"AWS error while {doing}: {e}\n"
        "Check credentials (aws configure / AWS_PROFILE / env keys), the "
        "region, and IAM permissions for ec2:* on dnslab-tagged resources "
        "plus ssm:GetParameter on public AMI parameters."
    )


def _tags_dict(aws_tags: list[dict] | None) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in (aws_tags or [])}


class Ec2Provider(Provider):
    name = "ec2"

    # ---- clients -----------------------------------------------------------
    def _ec2(self):
        return _session().client("ec2")

    def _ssm(self):
        return _session().client("ssm")

    # ---- rendering ---------------------------------------------------------
    def render_userdata(self, spec: ServerSpec, profile: Profile,
                        instance_name: str, overrides: dict | None = None) -> str:
        """Render the profile's user-data template.

        Context mirrors the docker provider's render() (and selfcheck's dummy
        context) so templates are portable: instance_name, tls_hostname,
        tls_*_path, ca_path, zones_dir, listen_*, port_*, upstream_* +
        profile extras. The lab upstream pair is not reachable from EC2, so
        upstream_do53/upstream_dot are empty dicts (templates for this
        provider should use profile extra keys, e.g. ``forwarders``).
        """
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(spec.dir),
            undefined=jinja2.StrictUndefined,
            keep_trailing_newline=True,
        )
        ctx = {
            "instance_name": instance_name,
            "tls_hostname": f"{instance_name}.{DOMAIN}",
            "tls_cert_path": "C:\\dnslab\\certs\\server.pem",
            "tls_key_path": "C:\\dnslab\\certs\\server.key",
            "ca_path": "C:\\dnslab\\certs\\dnslab-ca.pem",
            "zones_dir": "C:\\dnslab\\zones",
            "listen_do53": "do53" in profile.listeners,
            "listen_dot": "dot" in profile.listeners,
            "port_do53": spec.ports.get("do53", 53),
            "port_dot": spec.ports.get("dot", 853),
            "upstream_do53": {},  # lab upstreams are not reachable from EC2
            "upstream_dot": {},
            **profile.extra,
            **(overrides or {}),
        }
        rendered = env.get_template(profile.template).render(**ctx)
        # keep a copy for debugging (config_path is descriptive-only on ec2)
        (state_dir(instance_name) / "userdata.ps1").write_text(rendered)
        return rendered

    # ---- AMI / SG ----------------------------------------------------------
    def _resolve_ami(self, spec: ServerSpec) -> str:
        kind, value = resolve_ami_source({**spec.raw, "name": spec.name})
        if kind == "ami":
            return value
        try:
            resp = self._ssm().get_parameter(Name=value)
            return resp["Parameter"]["Value"]
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            raise _wrap(e, f"resolving AMI via SSM parameter {value!r}") from e

    def _authorize_current_ip(self, ec2, sg_id: str, rdp: bool) -> None:
        """Add ingress for the caller's current /32 (idempotent) so a reused
        instance stays reachable after the caller's public IP changes."""
        cidr = f"{caller_public_ip()}/32"
        try:
            ec2.authorize_security_group_ingress(
                GroupId=sg_id, IpPermissions=sg_ingress_rules(cidr, rdp))
        except Exception as e:  # noqa: BLE001
            if "InvalidPermission.Duplicate" not in str(e):
                raise _wrap(e, f"re-authorizing ingress on {sg_id}") from e

    def _ensure_sg(self, ec2, sg_name: str, rdp: bool, tags: list[dict]) -> str:
        """Create (or reuse) the session SG, scoped to the caller's /32."""
        cidr = f"{caller_public_ip()}/32"
        try:
            sg_id = ec2.create_security_group(
                GroupName=sg_name,
                Description=f"dnslab session SG (auto-created, scoped to {cidr})",
                TagSpecifications=[{"ResourceType": "security-group", "Tags": tags}],
            )["GroupId"]
        except Exception as e:  # noqa: BLE001
            if "InvalidGroup.Duplicate" not in str(e):
                raise _wrap(e, f"creating security group {sg_name!r}") from e
            groups = ec2.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": [sg_name]}]
            )["SecurityGroups"]
            sg_id = groups[0]["GroupId"]
        try:
            ec2.authorize_security_group_ingress(
                GroupId=sg_id, IpPermissions=sg_ingress_rules(cidr, rdp))
        except Exception as e:  # noqa: BLE001
            if "InvalidPermission.Duplicate" not in str(e):
                raise _wrap(e, f"authorizing ingress on {sg_name!r}") from e
        return sg_id

    # ---- lifecycle ---------------------------------------------------------
    def start(self, spec: ServerSpec, profile: Profile, instance_name: str,
              *, wait: bool = True, timeout: float | None = None,
              force: bool = False, **overrides) -> Instance:
        ec2 = self._ec2()
        if timeout is None:
            timeout = float(spec.raw.get("start_timeout", 600))

        itype = str(spec.raw.get("instance_type", DEFAULT_INSTANCE_TYPE))
        userdata = self.render_userdata(spec, profile, instance_name, overrides)
        import hashlib
        confhash = hashlib.sha256(
            (userdata + "\x00" + itype).encode()).hexdigest()[:16]

        # Reuse a live instance whose profile AND rendered user-data are
        # unchanged (dnslab-confhash tag). Crucially, a matching instance is
        # NEVER torn down here — even one still booting — so re-running start()
        # keeps waiting instead of relaunching (Windows takes minutes to come
        # up). Only config drift or force=True reach the replace path below.
        if not force:
            match = None
            for aws_inst in self._describe(states=("pending", "running")):
                tags = _tags_dict(aws_inst.get("Tags"))
                if tags.get(f"{TAG}-instance") == instance_name:
                    match = tags
                    break
            if match is not None and match.get(f"{TAG}-profile") == profile.name \
                    and match.get(f"{TAG}-confhash") == confhash:
                reused = next((i for i in self.discover()
                               if i.name == instance_name), None)
                if reused is not None:
                    # An unchanged instance can be unreachable if the caller's
                    # public IP drifted since launch — re-authorize its SG for
                    # the current /32 rather than relaunch.
                    sg_id = (reused.extra or {}).get("sg_id")
                    if sg_id:
                        self._authorize_current_ip(ec2, sg_id,
                                                   bool(spec.raw.get("rdp")))
                    if wait:
                        try:
                            self._wait_healthy(spec, reused, timeout)
                        except TimeoutError as e:
                            raise TimeoutError(
                                f"{instance_name}: existing instance {reused.id} "
                                f"({reused.status}) is not answering yet — it was "
                                "LEFT RUNNING, not relaunched. Re-run start() to "
                                "keep waiting (Windows first boot takes ~5-10 min), "
                                "or pass force=True to recreate it."
                            ) from e
                    reused.status = "reused " + reused.status
                    self._remember(reused)
                    return reused
            # config drift / different profile → fall through and replace

        # replace a previous instance of the same name (mirrors docker)
        for old in self.discover():
            if old.name == instance_name and old.status.split()[0] != "terminated":
                self.stop(old)

        ami = self._resolve_ami(spec)
        session = str(uuid.uuid4())
        expires = expires_at()
        tags = [
            {"Key": TAG, "Value": "1"},
            {"Key": f"{TAG}-server", "Value": spec.name},
            {"Key": f"{TAG}-instance", "Value": instance_name},
            {"Key": f"{TAG}-profile", "Value": profile.name},
            {"Key": f"{TAG}-session", "Value": session},
            {"Key": f"{TAG}-expires", "Value": expires},
            {"Key": f"{TAG}-confhash", "Value": confhash},
            {"Key": "Name", "Value": f"dnslab-{instance_name}"},
        ]
        sg_id = self._ensure_sg(ec2, f"dnslab-{session}", bool(spec.raw.get("rdp")), tags)

        try:
            resp = ec2.run_instances(
                ImageId=ami,
                InstanceType=itype,
                MinCount=1, MaxCount=1,
                UserData=userdata,
                NetworkInterfaces=[{
                    "DeviceIndex": 0,
                    "AssociatePublicIpAddress": True,
                    "Groups": [sg_id],
                }],
                TagSpecifications=[
                    {"ResourceType": "instance", "Tags": tags},
                    {"ResourceType": "volume", "Tags": tags},
                ],
            )
        except Exception as e:  # noqa: BLE001
            self._delete_sg_quiet(ec2, sg_id)
            raise _wrap(e, f"launching {spec.name} ({ami})") from e
        instance_id = resp["Instances"][0]["InstanceId"]

        try:
            ec2.get_waiter("instance_running").wait(
                InstanceIds=[instance_id],
                WaiterConfig={"Delay": 5, "MaxAttempts": 60},
            )
            desc = ec2.describe_instances(InstanceIds=[instance_id])
            aws_inst = desc["Reservations"][0]["Instances"][0]
        except Exception as e:  # noqa: BLE001
            raise _wrap(e, f"waiting for {instance_id} to enter 'running'") from e

        ip = aws_inst.get("PublicIpAddress")
        host = aws_inst.get("PublicDnsName") or ip or instance_id
        inst = Instance(
            name=instance_name, server=spec.name, profile=profile.name,
            provider=self.name, id=instance_id, host=host, ip=ip,
            status="starting",
            extra={"session": session, "sg_id": sg_id, "expires": expires,
                   "launched": aws_inst["LaunchTime"].isoformat()},
        )
        self._remember(inst)

        if wait:
            self._wait_healthy(spec, inst, timeout)
        inst.status = "running"
        self._remember(inst)
        return inst

    def _wait_healthy(self, spec: ServerSpec, inst: Instance, timeout: float):
        """Poll UDP/53 on the public IP (Windows takes several minutes to run
        user-data through EC2Launch, so the default timeout is generous)."""
        import dns.message
        import dns.query

        if not inst.ip:
            raise RuntimeError(
                f"{inst.name}: instance {inst.id} has no public IP — is the "
                "default subnet configured to assign public IPs?"
            )
        hc = spec.healthcheck or {}
        qname, qtype = hc.get("qname", "."), hc.get("qtype", "SOA")
        deadline = time.monotonic() + timeout
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                q = dns.message.make_query(qname, qtype)
                dns.query.udp(q, inst.ip, timeout=3, port=spec.ports.get("do53", 53))
                return
            except Exception as e:  # noqa: BLE001 — retry until deadline
                last_err = e
                time.sleep(5)
        raise TimeoutError(
            f"{inst.name}: {inst.ip}:{spec.ports.get('do53', 53)} not answering "
            f"after {timeout}s (last error: {last_err}). Windows user-data can "
            "take ~5-10 min; check the instance's console output (dnslab.logs) "
            "and remember dnslab.nuke() cleans up billed instances."
        )

    # ---- state file --------------------------------------------------------
    def _remember(self, inst: Instance) -> None:
        st = load_state("ec2")
        st.setdefault("instances", {})[inst.name] = {
            "id": inst.id, "server": inst.server, "profile": inst.profile,
            "host": inst.host, "ip": inst.ip, "status": inst.status,
            **inst.extra,
        }
        save_state("ec2", st)

    def _forget(self, names_or_ids: set[str]) -> None:
        st = load_state("ec2")
        insts = st.get("instances", {})
        for k in [k for k, v in insts.items()
                  if k in names_or_ids or v.get("id") in names_or_ids]:
            del insts[k]
        save_state("ec2", st)

    # ---- discovery ---------------------------------------------------------
    def _describe(self, states: tuple[str, ...] = ACTIVE_STATES) -> list[dict]:
        ec2 = self._ec2()
        try:
            pages = ec2.get_paginator("describe_instances").paginate(
                Filters=[
                    {"Name": f"tag:{TAG}", "Values": ["1"]},
                    {"Name": "instance-state-name", "Values": list(states)},
                ]
            )
            return [i for page in pages
                    for r in page["Reservations"] for i in r["Instances"]]
        except Exception as e:  # noqa: BLE001
            raise _wrap(e, "describing dnslab-tagged instances") from e

    def discover(self) -> list[Instance]:
        st = load_state("ec2")
        known = st.get("instances", {})
        out, seen = [], set()
        for aws_inst in self._describe():
            tags = _tags_dict(aws_inst.get("Tags"))
            name = tags.get(f"{TAG}-instance") or aws_inst["InstanceId"]
            launched = aws_inst["LaunchTime"].isoformat()
            state = aws_inst["State"]["Name"]
            hours = running_hours(launched)
            status = state if hours is None else f"{state} {hours:.1f}h"
            expires = tags.get(f"{TAG}-expires", "")
            if expires and is_expired(expires):
                status += " EXPIRED"
            extra = {
                "session": tags.get(f"{TAG}-session", ""),
                "expires": expires,
                "launched": launched,
                "sg_id": known.get(name, {}).get("sg_id")
                or next((g["GroupId"] for g in aws_inst.get("SecurityGroups", [])
                         if g.get("GroupName", "").startswith("dnslab-")), None),
            }
            inst = Instance(
                name=name,
                server=tags.get(f"{TAG}-server", name),
                profile=tags.get(f"{TAG}-profile", "?"),
                provider=self.name,
                id=aws_inst["InstanceId"],
                host=aws_inst.get("PublicDnsName") or aws_inst.get("PublicIpAddress") or name,
                ip=aws_inst.get("PublicIpAddress"),
                status=status,
                extra=extra,
            )
            out.append(inst)
            seen.add(name)
        # reconcile: tags are truth — drop state entries AWS no longer knows
        stale = {k for k in known if k not in seen}
        if stale:
            self._forget(stale)
        for inst in out:
            self._remember(inst)
        return out

    # ---- target ------------------------------------------------------------
    def target(self, instance: Instance) -> Target:
        from ..registry import get
        spec = get(instance.server)
        profile = spec.profiles.get(instance.profile)
        listeners = profile.listeners if profile else ("do53",)
        caps = spec.capabilities
        return Target(
            name=instance.name,
            host=instance.host,
            ip=instance.ip or "",
            port_do53=spec.ports.get("do53") if "do53" in listeners and caps.do53_listener else None,
            port_dot=spec.ports.get("dot") if "dot" in listeners and (caps.dot_listener or caps.dot_listener_via_proxy) else None,
            tls_hostname=instance.host,
            ca_file="",  # no lab CA on EC2; DoT checks SKIP while port_dot is None
            provider=self.name,
            profile=instance.profile,
            capabilities=caps,
        )

    # ---- teardown ----------------------------------------------------------
    def stop(self, instance: Instance) -> None:
        ec2 = self._ec2()
        sg_id = (instance.extra or {}).get("sg_id") \
            or load_state("ec2").get("instances", {}).get(instance.name, {}).get("sg_id")
        try:
            ec2.terminate_instances(InstanceIds=[instance.id])
        except Exception as e:  # noqa: BLE001
            if "InvalidInstanceID.NotFound" not in str(e):
                raise _wrap(e, f"terminating {instance.id}") from e
        self._forget({instance.name})
        if sg_id:
            try:
                ec2.get_waiter("instance_terminated").wait(
                    InstanceIds=[instance.id],
                    WaiterConfig={"Delay": 10, "MaxAttempts": 30},
                )
            except Exception:  # noqa: BLE001 — SG delete below still retries
                pass
            self._delete_sg(ec2, sg_id)

    def _delete_sg(self, ec2, sg_id: str, retry_s: float = SG_DELETE_RETRY_S) -> bool:
        """Delete an SG, retrying DependencyViolation while ENIs detach."""
        deadline = time.monotonic() + retry_s
        while True:
            try:
                ec2.delete_security_group(GroupId=sg_id)
                return True
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "InvalidGroup.NotFound" in msg:
                    return True
                if "DependencyViolation" not in msg or time.monotonic() >= deadline:
                    raise _wrap(e, f"deleting security group {sg_id}") from e
                time.sleep(10)

    def _delete_sg_quiet(self, ec2, sg_id: str) -> None:
        try:
            self._delete_sg(ec2, sg_id, retry_s=0)
        except RuntimeError:
            pass

    def nuke(self) -> list[str]:
        """Terminate ALL dnslab=1 instances and delete every dnslab-* SG."""
        ec2 = self._ec2()
        removed: list[str] = []

        instances = self._describe()
        ids = [i["InstanceId"] for i in instances
               if i["State"]["Name"] != "shutting-down"]
        all_ids = [i["InstanceId"] for i in instances]
        if ids:
            try:
                ec2.terminate_instances(InstanceIds=ids)
            except Exception as e:  # noqa: BLE001
                raise _wrap(e, f"terminating {ids}") from e
        for i in instances:
            tags = _tags_dict(i.get("Tags"))
            removed.append(tags.get(f"{TAG}-instance", i["InstanceId"]))
        if all_ids:
            try:
                ec2.get_waiter("instance_terminated").wait(
                    InstanceIds=all_ids,
                    WaiterConfig={"Delay": 10, "MaxAttempts": 60},
                )
            except Exception as e:  # noqa: BLE001
                raise _wrap(e, "waiting for dnslab instances to terminate "
                               "(SGs not deleted yet — rerun nuke())") from e

        try:
            groups = ec2.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": ["dnslab-*"]}]
            )["SecurityGroups"]
        except Exception as e:  # noqa: BLE001
            raise _wrap(e, "describing dnslab-* security groups") from e
        for g in groups:
            self._delete_sg(ec2, g["GroupId"])
            removed.append(g["GroupName"])

        save_state("ec2", {"instances": {}})
        return removed

    # ---- logs --------------------------------------------------------------
    def logs(self, instance: Instance, tail: int = 100) -> str:
        try:
            out = self._ec2().get_console_output(InstanceId=instance.id)
        except Exception as e:  # noqa: BLE001
            return f"{instance.name}: console output unavailable ({e})"
        text = out.get("Output") or ""
        if text:
            # the EC2 API base64-encodes console output; boto3 passes it through
            import base64
            try:
                text = base64.b64decode(text).decode(errors="replace")
            except (ValueError, TypeError):
                pass  # some SDK paths already decode; use as-is
        else:
            text = f"{instance.name}: console output empty (still booting?)"
        return "\n".join(text.splitlines()[-tail:])
