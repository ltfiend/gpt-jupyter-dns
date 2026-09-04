"""CI lint: validate every server manifest and render every profile template
with a dummy context. Runs with no network, no docker socket, no AWS.

Usage:  python -m dnslab.selfcheck [server ...]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import jinja2

# NB: import from the submodule directly — the package facade exposes a
# registry() *function* that shadows the submodule attribute.
from .registry import ManifestError, discover

DUMMY_UPSTREAM = {"host": "upstream.dnslab.test", "ip": "192.0.2.53",
                  "port": 53, "tls_hostname": "upstream.dnslab.test"}


def dummy_context(spec, profile) -> dict:
    return {
        "instance_name": spec.name,
        "tls_hostname": f"{spec.name}.dnslab.test",
        "tls_cert_path": f"/dnslab/certs/{spec.name}.pem",
        "tls_key_path": f"/dnslab/certs/{spec.name}.key",
        "ca_path": "/dnslab/certs/dnslab-ca.pem",
        "zones_dir": "/dnslab/zones",
        "listen_do53": "do53" in profile.listeners,
        "listen_dot": "dot" in profile.listeners,
        "port_do53": spec.ports.get("do53", 53),
        "port_dot": spec.ports.get("dot", 853),
        "upstream_do53": DUMMY_UPSTREAM,
        "upstream_dot": {**DUMMY_UPSTREAM, "port": 853},
        **profile.extra,
    }


def lint_rendered(spec, profile, rendered: str) -> str | None:
    """Optional per-server syntax lint, e.g. manifest 'lint: named-checkconf'."""
    tool = spec.raw.get("lint")
    if not tool or not shutil.which(tool.split()[0]):
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
        f.write(rendered)
        path = f.name
    try:
        cmd = tool.format(config=path).split() if "{config}" in tool else [*tool.split(), path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return f"{tool}: {r.stderr.strip() or r.stdout.strip()}"
    finally:
        Path(path).unlink(missing_ok=True)
    return None


def main(argv: list[str]) -> int:
    only = set(argv)
    specs = discover()
    if only:
        missing = only - specs.keys()
        if missing:
            print(f"unknown servers: {sorted(missing)}", file=sys.stderr)
            return 2
        specs = {k: v for k, v in specs.items() if k in only}
    if not specs:
        print("no server manifests found", file=sys.stderr)
        return 2

    failures = 0
    for name, spec in sorted(specs.items()):
        for pname, profile in sorted(spec.profiles.items()):
            label = f"{name}:{pname}"
            try:
                env = jinja2.Environment(
                    loader=jinja2.FileSystemLoader(spec.dir),
                    undefined=jinja2.StrictUndefined,
                )
                rendered = env.get_template(profile.template).render(**dummy_context(spec, profile))
                err = lint_rendered(spec, profile, rendered)
                if err:
                    print(f"FAIL {label}: {err}")
                    failures += 1
                else:
                    print(f"ok   {label}")
            except (jinja2.TemplateError, ManifestError) as e:
                print(f"FAIL {label}: {e}")
                failures += 1
        for pname in spec.instances.values():
            if pname not in spec.profiles:
                print(f"FAIL {name}: instance profile {pname!r} missing")
                failures += 1
    print(f"\n{len(specs)} server(s) checked, {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
