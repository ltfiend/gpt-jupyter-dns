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
on DNS-over-TLS forwarding. Two notebooks:

- `data/dot-forwarding-lab.ipynb` — self-contained transport proof against
  the lab-auth upstream pair (marker TXT proves TLS was used upstream).
- `data/dot-real-upstream-lab.ipynb` — servers forward everything over TLS
  to **your real upstreams** (`global-forwarder-dot` profiles, system CA,
  DNSSEC validation on); config areas for upstreams and query names; the
  report shows rcode, header flags (AD), DO/EDNS, EDE, and RRSIG presence.

```python
import dnslab
dnslab.registry()                              # available server modules
dnslab.start('lab-auth')                       # transport-isolated upstream pair
dnslab.start('unbound', profile='forwarder-dot')
dnslab.checks.run_matrix(dnslab.targets())     # PASS/FAIL/SKIP matrix
dnslab.nuke()                                  # tear everything down
```

### Server modules

Server modules are auto-discovered from `dnslab/servers/<name>/` (manifest +
jinja2 config templates, no central registry). Current roster:

| Module | Runs as | Roles | Profiles |
|--------|---------|-------|----------|
| `unbound` (1.23.1) | docker, local Alpine build | recursive, forwarder | `recursive`, `forwarder-do53`, `forwarder-dot`, `global-forwarder-dot` |
| `bind` (9.20) | docker, `internetsystemsconsortium/bind9:9.20` | recursive, forwarder | `recursive`, `forwarder-do53`, `forwarder-dot`, `global-forwarder-dot` |
| `knot-resolver` (5.7.8) | docker, `cznic/knot-resolver:v5.7.8` | recursive, forwarder | `recursive`, `forwarder-do53`, `forwarder-dot`, `global-forwarder-dot` |
| `knot` (3.5.4) | docker, `cznic/knot:v3.5.4` | authoritative | `auth-do53`, `auth-dot`, `auth-both` |
| `nsd` (4.12.0) | docker, local Alpine build | authoritative | `auth-do53`, `auth-dot`, `auth-both` |
| `lab-auth` | docker, local Alpine build | framework upstream pair | `auth-do53` + `auth-dot` (both start) |
| `windows-dns` | EC2, Windows Server 2025 AMI | Do53 forwarder | `forwarder-do53` |
| `windows-client-dot` | EC2, Windows Server 2025 AMI | stub-resolver DoT **client** | `stub-dot` |

Capability flags in each manifest are verified against the pinned
image/AMI; a check for an unsupported feature reports SKIP, never FAIL
(e.g. Windows DNS Server has no DoT listener, so its DoT checks skip).

### Running servers

```python
dnslab.start('knot')                            # default profile (auth-dot)
dnslab.start('knot', profile='auth-both')       # plain 53 + TLS 853 together
dnslab.start('unbound', profile='global-forwarder-dot',
             upstreams=[{'ip': '9.9.9.9', 'port': 853,
                         'tls_hostname': 'dns.quad9.net'}])
dnslab.start('unbound', force=True)             # recreate even if healthy
dnslab.status()                                 # all instances, both providers
dnslab.logs('unbound')
dnslab.stop('unbound')                          # or dnslab.stop(all=True)
```

- **Idempotent start** — `dnslab.start()` reuses a running instance when
  the profile and rendered config are unchanged and it still answers its
  healthcheck (status `reused`). Config drift replaces it; `force=True`
  always recreates; an instance still booting is waited for, never
  relaunched.
- **Per-server start budgets** — with `timeout=None` (the default) each
  server uses its manifest `start_timeout` (60s docker default, 600s EC2,
  900s for the Windows modules, which install roles and reboot on first
  boot).
- **EC2 stop/resume** — `dnslab.stop()`/`nuke()` **terminate** EC2
  instances. To pause billing instead, `aws ec2 stop-instances`; the next
  `dnslab.start()` resumes the stopped instance (status `resumed`) rather
  than relaunching, and re-scopes the security group to your current
  public IP.
- **Windows DoT client** — `windows-client-dot` is a client, not a server:
  its stub resolver sends queries over DoT/853. It carries an SSM instance
  profile (`dnslab-ssm`, created on demand), and
  `dnslab.checks.windows_dot_client_report('windows-client-dot')` proves
  DoT on-box: resolution succeeds with plaintext 53 blocked while holding
  an established `:853` connection.

The package also runs directly on the host (no notebook container):
`pip install -e .` from the repo root, then `import dnslab` uses the
docker socket and AWS credentials directly.

Notes:
- The compose file mounts `/var/run/docker.sock` and adds the container to
  the host `docker` group (`group_add`). If your host's docker gid is not
  `958`, set `DOCKER_GID` in a `.env` file (`getent group docker`).
- Server containers join the `dnslab` docker network with hostnames like
  `unbound.dnslab.test`; certificates are issued by a throwaway lab CA in
  `workspace/certs/dnslab/` (`dnslab.ca_file()`).
- Config templates are editable on the host under
  `dnslab/servers/<name>/profiles/` — re-run `dnslab.start()` to
  apply, no image rebuild needed.
- The EC2 tier launches instances tagged `dnslab=1` with a 4h expiry tag
  and a security group scoped to your public IP; `dnslab.nuke()` removes
  everything.

## Transferring to another server

The simplest move is `git clone` on the new host, but if copying files
directly, these are required:

**Required (image build + runtime):**

| Path | Purpose |
|------|---------|
| `Dockerfile` | notebook image definition |
| `compose.yaml` | service, ports, mounts, dnslab network |
| `entrypoint.sh` | startup (Git/S3 sync, extra pip, JupyterLab launch) — copied into the image |
| `jupyter_server_config.py` | Jupyter server settings — copied into the image |
| `dnslab/` | entire orchestration package, including `dnslab/servers/**` (manifests, config templates, zone files, per-server Dockerfiles) |
| `data/` | git-tracked source notebooks (the dnslab notebooks live here) |

**Optional:**

| Path | Purpose |
|------|---------|
| `pyproject.toml` | only for host-side `pip install -e .` use |
| `test/` | smoke test + dnslab lint (CI) |
| `.github/`, `docs/` | CI workflow and runner docs |
| `.env` | `DOCKER_GID` override if the new host's docker gid ≠ 958 |
| `workspace/notebooks/` | only if you want to carry over working notebooks |

**Not transferable / recreated on the new host:**

- `workspace/` is gitignored runtime state — `certs/` (throwaway lab CA,
  regenerated) and `dnslab-state/` are host-specific; let them regenerate.
- `~/.aws` credentials for the EC2 tier are mounted from the host's home
  directory, not the repo — configure them on the new host.

**Must be edited after copying:** `compose.yaml` uses absolute host paths
(`/home/peter/Git/gpt-jupyter-dns/...`) in three places — the two volume
mounts for `workspace` and `dnslab`, and the matching
`DNSLAB_HOST_WORKSPACE` / `DNSLAB_HOST_DNSLAB` environment variables
(dnslab passes these to the docker daemon when starting sibling
containers, so they must be the *host-side* paths on the new machine).
Also check the host's docker gid (`getent group docker`) and set
`DOCKER_GID` in `.env` if it isn't 958.

Rather than rebuilding, the image itself can be moved with
`docker save registry.devries.tv/gpt-jupyter-dns:latest | ssh newhost docker load`
or pulled from the registry/GHCR (see CI/CD below).

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
