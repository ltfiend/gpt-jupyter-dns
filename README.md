# gpt-jupyter-dns

Dockerized JupyterLab environment pre-loaded with DNS diagnostic, debugging, and performance testing tools.

## Quick Start

```bash
docker compose up --build
```

JupyterLab will be available at `http://localhost:8888` with the default token `dnslab`.

## Authentication

JupyterLab requires a token to connect. The default token is `dnslab`. Override it via environment variable:

```yaml
# compose.yaml
environment:
  JUPYTER_TOKEN: "your-secret-token"
```

Or at runtime:

```bash
docker compose run -e JUPYTER_TOKEN=mysecret dns-notebook
```

## Included Tools

### DNS Query & Debugging
| Tool | Command | Description |
|------|---------|-------------|
| dig | `dig` | BIND DNS lookup utility |
| kdig | `kdig` | Knot DNS lookup utility |
| drill | `drill` | LDNS DNS lookup utility |
| q | `q` | Multi-protocol DNS client (UDP, TCP, DoT, DoH, DoQ, ODoH) |
| dnsviz | `dnsviz` | DNSSEC visualization and analysis |
| stubby | `stubby` | DNS-over-TLS stub resolver |
| dot-cert-tester | `dot-cert-tester` | DNS-over-TLS certificate testing |

### DNS Performance Testing
| Tool | Command | Description |
|------|---------|-------------|
| flamethrower | `flame` | DNS load generator (UDP, TCP, DoT, DoH) |
| dnsperf | `dnsperf` | DNS-OARC performance testing (UDP, TCP, DoT) |
| dnspyre | `dnspyre` | DNS benchmarking with latency histograms |
| dnsperftest | `bash /opt/dnsperftest/dnstest.sh` | Quick comparison of public DNS resolvers |

### DNS Server Utilities
| Tool | Command | Description |
|------|---------|-------------|
| named-checkconf | `named-checkconf` | BIND config syntax checker |
| named-checkzone | `named-checkzone` | BIND zone file validator |

### Python Libraries
`dnspython`, `boto3`, `gitpython`, `matplotlib`, `pandas`, `rich`, `tabulate`, `ipywidgets`, `nbconvert`

## PDF Export

Notebooks can be exported to PDF with results included. This image uses
`nbconvert[webpdf]` (headless Chromium via pyppeteer) instead of a LaTeX
toolchain — the Chromium build is pre-downloaded during image build so
PDF export works offline.

- **JupyterLab UI:** File → Save and Export Notebook As → WebPDF
- **CLI:** `jupyter nbconvert --to webpdf notebook.ipynb`

## Configuration

Optional environment variables (set in `compose.yaml`):

| Variable | Description |
|----------|-------------|
| `JUPYTER_TOKEN` | JupyterLab authentication token (default: `dnslab`) |
| `GIT_URL` | Clone/pull a notebook repo on startup |
| `S3_URI` | Sync notebooks from S3 on startup |
| `EXTRA_PIP` | Install additional pip packages at container start |

## dnslab — multi-server DNS-over-TLS test lab

The `dnslab/` package (bind-mounted at `/opt/dnslab/dnslab`, already on
`PYTHONPATH`) lets notebooks launch, target, and functionally test DNS
servers — locally as Docker containers or in AWS via boto3 — with a focus
on DNS-over-TLS forwarding. See `data/dot-forwarding-lab.ipynb`.

```python
import dnslab
dnslab.registry()                              # available server modules
dnslab.start('lab-auth')                       # transport-isolated upstream pair
dnslab.start('unbound', profile='forwarder-dot')
dnslab.checks.run_matrix(dnslab.targets())     # PASS/FAIL/SKIP matrix
dnslab.nuke()                                  # tear everything down
```

Notes:
- The compose file mounts `/var/run/docker.sock` and adds the container to
  the host `docker` group (`group_add`). If your host's docker gid is not
  `958`, set `DOCKER_GID` in a `.env` file (`getent group docker`).
- Server containers join the `dnslab` docker network with hostnames like
  `unbound.dnslab.test`; certificates are issued by a throwaway lab CA in
  `workspace/certs/dnslab/` (`dnslab.ca_file()`).
- Config templates are editable on the host under
  `dnslab/dnslab/servers/<name>/profiles/` — re-run `dnslab.start()` to
  apply, no image rebuild needed.
- The EC2 tier launches instances tagged `dnslab=1` with a 4h expiry tag
  and a security group scoped to your public IP; `dnslab.nuke()` removes
  everything.

## CI/CD

GitHub Actions (`.github/workflows/build.yml`) lints, builds, tests, scans,
and publishes the image. It runs on a **self-hosted runner** labelled
`[self-hosted, Linux, X64]` with Docker available — see
[`docs/self-hosted-runner.md`](docs/self-hosted-runner.md) for registering
one and for running a single runner box across multiple repos.

| Trigger | What runs |
|---------|-----------|
| Pull request | hadolint → build → smoke test → Trivy scan (no push) |
| Push to `main` | the above, then push `:latest` + `:sha-<short>` |
| Tag `v*` | the above, then push semver tags (`1.2.3`, `1.2`) |
| Weekly schedule | rebuild for base-image/pip security fixes, re-scan, republish |
| Manual dispatch | same as a `main` build |

**Publish targets:**
- **GHCR** (`ghcr.io/<owner>/gpt-jupyter-dns`) — always, via the built-in `GITHUB_TOKEN`.
- **Private registry** (`registry.devries.tv/gpt-jupyter-dns`) — only when these
  repository secrets are set:

  | Secret | Purpose |
  |--------|---------|
  | `REGISTRY_USERNAME` | login for `registry.devries.tv` |
  | `REGISTRY_PASSWORD` | password/token for `registry.devries.tv` |

  With the secrets unset, the private push is skipped (a workflow notice is
  logged) and GHCR still publishes.

Trivy results (CRITICAL/HIGH, fixable) upload to the repo's **Security → Code
scanning** tab. The scan is report-only — it does not block the build, since
DNS base-image CVEs are often unfixable upstream.

The smoke test (`test/smoke-test.sh`) asserts every CLI tool and Python
library the notebooks rely on is present in the built image.
