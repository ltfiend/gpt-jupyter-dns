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
* Configuration via user-data (manifest ``userdata:`` names a .j2 template
  in the server dir, rendered with the same context as docker profiles).
* State manifest via state.save_state("ec2", ...) so a restarted kernel
  rediscovers; discover() must ALSO re-describe by tag filter and
  reconcile, treating tags as the source of truth.
* status() surfaces running-hours; anything past dnslab-expires is flagged.
* nuke(): terminate all dnslab=1 instances and delete session SGs.
* No AWS calls at import time; boto3 imported lazily inside methods.
"""

from __future__ import annotations

from ..model import Instance, Profile, ServerSpec, Target
from .base import Provider


class Ec2Provider(Provider):
    name = "ec2"

    def start(self, spec: ServerSpec, profile: Profile, instance_name: str,
              *, wait: bool = True, timeout: float = 600, **overrides) -> Instance:
        raise NotImplementedError(
            "ec2 provider not yet implemented — delivered with the windows-dns "
            "integration (see module docstring for the contract)"
        )

    def stop(self, instance: Instance) -> None:
        raise NotImplementedError

    def discover(self) -> list[Instance]:
        return []

    def target(self, instance: Instance) -> Target:
        raise NotImplementedError
