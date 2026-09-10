"""Filesystem locations, host-path translation, and instance state.

The package runs in two situations with different filesystem views:

* inside the notebook container — workspace is /workspace, and sibling DNS
  containers must be given *host* paths for bind mounts (the docker daemon
  interprets mount sources on the host, not in this container). The compose
  file provides DNSLAB_HOST_WORKSPACE / DNSLAB_HOST_DNSLAB for translation.
* directly on the host (dev / CI) — paths pass through untranslated.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent  # <repo>/dnslab (the package itself)
SERVERS_DIR = PKG_DIR / "servers"


def workspace_root() -> Path:
    """The persistent workspace dir (certs, state, notebooks live under it)."""
    env = os.environ.get("DNSLAB_WORKSPACE")
    if env:
        return Path(env)
    if Path("/workspace").is_dir():
        return Path("/workspace")
    # host-side fallback: the repo's workspace/ next to the dnslab package
    repo = PKG_DIR.parent  # .../gpt-jupyter-dns
    return repo / "workspace"


def _mkdir_traversable(d: Path, stop: Path) -> Path:
    """mkdir -p, then force 755 on each created level below `stop`.

    Server containers read certs/configs from these trees as arbitrary
    uids; a restrictive umask would otherwise block traversal.
    """
    d.mkdir(parents=True, exist_ok=True)
    p = d
    while p != stop and p != p.parent:
        p.chmod(0o755)
        p = p.parent
    return d


def certs_dir() -> Path:
    root = workspace_root()
    return _mkdir_traversable(root / "certs" / "dnslab", stop=root)


def state_dir(instance: str | None = None) -> Path:
    root = workspace_root()
    d = root / "dnslab-state"
    if instance:
        d = d / instance
    return _mkdir_traversable(d, stop=root)


def to_host_path(path: Path | str) -> str:
    """Translate a path as seen from this process into the host's view.

    Needed whenever a path is handed to the docker daemon as a bind-mount
    source. No-op when the relevant DNSLAB_HOST_* env vars are unset
    (i.e. we are already running on the host).
    """
    p = str(Path(path).resolve())
    mappings = [
        ("/workspace", os.environ.get("DNSLAB_HOST_WORKSPACE")),
        ("/opt/dnslab/dnslab", os.environ.get("DNSLAB_HOST_DNSLAB")),
    ]
    for prefix, host_prefix in mappings:
        if host_prefix and (p == prefix or p.startswith(prefix + "/")):
            return host_prefix + p[len(prefix):]
    return p


def network_name() -> str:
    return os.environ.get("DNSLAB_NETWORK", "dnslab")


# ---- simple JSON state manifests (mainly for the ec2 provider; the docker
# ---- provider rediscovers from container labels and needs no state file) ----

def load_state(name: str) -> dict:
    f = state_dir() / f"{name}.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(name: str, data: dict) -> None:
    f = state_dir() / f"{name}.json"
    f.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
