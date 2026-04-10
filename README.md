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
