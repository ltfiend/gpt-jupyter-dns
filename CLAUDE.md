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

The container mounts `/home/peter/Git/dns-manager` to `/workspace` inside the container. Notebooks live in `/workspace/notebooks`.

## Container Environment

**DNS CLI tools available inside the container:** `dig`, `kdig` (Knot), `drill` (ldns), `dnsviz`, `named-checkconf`, `named-checkzone`

**Python libraries:** `dnspython`, `boto3`, `gitpython`, `matplotlib`, `pandas`, `rich`, `tabulate`, `jupyterlab`, `ipywidgets`

**Environment variables (optional, set in compose.yaml):**
- `GIT_URL` — clone/pull a notebook repo on startup
- `S3_URI` — sync notebooks from S3 on startup
- `EXTRA_PIP` — install additional pip packages at container start

## Architecture

- `Dockerfile` — Python 3.12-slim base, installs OS-level DNS tools + Python packages, creates non-root `nbuser` (uid 1000)
- `entrypoint.sh` — startup script handling optional Git clone, S3 sync, and extra pip installs before launching JupyterLab
- `compose.yaml` — service definition with port mapping (8888), volume mount, and user mapping
- `data/dns-examples.ipynb` — example notebook with DNS verification and DNSSEC validation tests using `dnspython`

## Image Registry

Built images are tagged `registry.devries.tv/gpt-jupyter-dns:latest`.
