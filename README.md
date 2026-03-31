# gpt-jupyter-dns

Dockerized JupyterLab environment pre-loaded with DNS diagnostic, debugging, and performance testing tools.

## Quick Start

```bash
docker compose up --build
```

JupyterLab will be available at `http://localhost:8888`.

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
`dnspython`, `boto3`, `gitpython`, `matplotlib`, `pandas`, `rich`, `tabulate`, `ipywidgets`

## Configuration

Optional environment variables (set in `compose.yaml`):

| Variable | Description |
|----------|-------------|
| `GIT_URL` | Clone/pull a notebook repo on startup |
| `S3_URI` | Sync notebooks from S3 on startup |
| `EXTRA_PIP` | Install additional pip packages at container start |
