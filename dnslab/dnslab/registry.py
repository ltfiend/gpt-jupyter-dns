"""Server-module discovery.

There is deliberately no central registry file: every directory under
dnslab/servers/ containing a manifest.yaml *is* the registry. Per-server
integrations therefore never touch a shared file and cannot conflict.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .model import Capabilities, Profile, ServerSpec
from .state import SERVERS_DIR

REQUIRED_KEYS = ("name", "provider", "capabilities", "profiles", "ports")
VALID_PROVIDERS = ("docker", "ec2", "external")


class ManifestError(ValueError):
    pass


def load_manifest(path: Path) -> ServerSpec:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ManifestError(f"{path}: manifest is not a mapping")
    for key in REQUIRED_KEYS:
        if key not in raw:
            raise ManifestError(f"{path}: missing required key {key!r}")
    if raw["provider"] not in VALID_PROVIDERS:
        raise ManifestError(
            f"{path}: provider {raw['provider']!r} not one of {VALID_PROVIDERS}"
        )
    if raw["name"] != path.parent.name:
        raise ManifestError(
            f"{path}: name {raw['name']!r} must match directory {path.parent.name!r}"
        )

    profiles = {
        pname: Profile.from_dict(pname, pdata)
        for pname, pdata in raw["profiles"].items()
    }
    if not profiles:
        raise ManifestError(f"{path}: no profiles defined")
    for prof in profiles.values():
        tpl = path.parent / prof.template
        if not tpl.is_file():
            raise ManifestError(f"{path}: profile {prof.name!r} template missing: {tpl}")

    instances = {
        iname: idata["profile"] if isinstance(idata, dict) else str(idata)
        for iname, idata in raw.get("instances", {}).items()
    }
    for iname, pname in instances.items():
        if pname not in profiles:
            raise ManifestError(f"{path}: instance {iname!r} references unknown profile {pname!r}")

    return ServerSpec(
        name=raw["name"],
        dir=path.parent,
        provider=raw["provider"],
        tier=int(raw.get("tier", 1)),
        capabilities=Capabilities.from_dict(raw["capabilities"]),
        profiles=profiles,
        ports={k: int(v) for k, v in raw["ports"].items()},
        healthcheck=raw.get("healthcheck", {"qname": ".", "qtype": "SOA"}),
        image=raw.get("image"),
        build=raw.get("build"),
        command=raw.get("command"),
        default_profile=raw.get("default_profile"),
        instances=instances,
        raw=raw,
    )


def discover(servers_dir: Path | None = None) -> dict[str, ServerSpec]:
    root = servers_dir or SERVERS_DIR
    specs: dict[str, ServerSpec] = {}
    if not root.is_dir():
        return specs
    for manifest in sorted(root.glob("*/manifest.yaml")):
        spec = load_manifest(manifest)
        specs[spec.name] = spec
    return specs


def get(name: str) -> ServerSpec:
    specs = discover()
    try:
        return specs[name]
    except KeyError:
        raise KeyError(f"unknown server {name!r}; available: {sorted(specs)}") from None
