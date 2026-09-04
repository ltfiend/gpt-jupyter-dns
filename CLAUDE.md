# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Dockerized JupyterLab environment pre-loaded with DNS diagnostic tools and Python libraries. Used for interactive DNS testing, DNSSEC validation, and DNS infrastructure analysis via Jupyter notebooks.

## Running

```bash
# Build and start the container (JupyterLab on http://localhost:8888)
docker compose up --build

# Run detached
docker compose up -d --build
```

The container mounts this repo's `workspace/` to `/workspace` inside the container. Notebooks live in `/workspace/notebooks`; git-tracked source notebooks live in `data/`.

## Container Environment

**DNS CLI tools available inside the container:** `dig`, `kdig` (Knot), `drill` (ldns), `dnsviz`, `named-checkconf`, `named-checkzone`

**Python libraries:** `dnspython`, `boto3`, `gitpython`, `matplotlib`, `pandas`, `rich`, `tabulate`, `jupyterlab`, `ipywidgets`

**Environment variables (optional, set in compose.yaml):**
- `GIT_URL` — clone/pull a notebook repo on startup
- `S3_URI` — sync notebooks from S3 on startup
- `EXTRA_PIP` — install additional pip packages at container start

## Architecture

- `Dockerfile` — Python 3.13-slim base, installs OS-level DNS tools + Python packages, creates non-root `nbuser` (uid 1000)
- `entrypoint.sh` — startup script handling optional Git clone, S3 sync, and extra pip installs before launching JupyterLab
- `compose.yaml` — service definition with port mapping (8888), volume mounts (workspace, dnslab package, docker socket), the shared `dnslab` network, and user mapping
- `data/dns-examples.ipynb` — example notebook with DNS verification and DNSSEC validation tests using `dnspython`
- `dnslab/` — importable orchestration package for the multi-server DNS-over-TLS test lab (see below)

## dnslab (multi-server DoT test lab)

`dnslab/` is bind-mounted to `/opt/dnslab/dnslab` (on `PYTHONPATH`) so notebooks can start, target, and functionally test DNS servers across three tiers: local Docker containers (opensource), free/license-included AWS AMIs via boto3, and paid marketplace AMIs.

- Server modules live in `dnslab/servers/<name>/` — a `manifest.yaml` (provider, pinned image, **verified** capability flags, profiles), jinja2 config templates under `profiles/`, and a README. There is no central registry file; the directory is auto-discovered, so per-server work never conflicts.
- Notebook API: `dnslab.start('unbound', profile='forwarder-dot')`, `dnslab.targets()`, `dnslab.checks.run_matrix(...)`, `dnslab.stop()/nuke()`. Main notebook: `data/dot-forwarding-lab.ipynb`.
- Forwarding-over-DoT is proven via the framework-owned `lab-auth` upstream pair: the DoT upstream listens only on 853/TLS and serves `transport-marker.lab.test TXT "dot"` (the Do53 one serves `"do53"`), so answer content identifies the transport used upstream.
- Lab CA + per-instance certs are generated into `workspace/certs/dnslab/` (throwaway; keys deliberately world-readable).
- CI lints all manifests/templates via `test/dnslab-lint.sh` → `python -m dnslab.selfcheck` (no network/docker/AWS).
- Capability flags must stay honest: set true only after verifying against the pinned image/AMI; checks report unsupported behavior as SKIP, never FAIL.

## Image Registry

Built images are tagged `registry.devries.tv/gpt-jupyter-dns:latest`.
