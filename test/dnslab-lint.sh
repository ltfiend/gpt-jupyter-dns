#!/usr/bin/env bash
# Lint the dnslab package inside the built image: import check + manifest
# validation + profile-template rendering. No network, docker socket, or
# AWS access needed — safe for CI.
#
# Usage (from CI, against a built image tag, repo checked out at $PWD):
#   docker run --rm \
#     -v "$PWD/dnslab:/opt/dnslab/dnslab:ro" \
#     -e PYTHONPATH=/opt/dnslab \
#     --entrypoint bash <image> /t/dnslab-lint.sh
set -euo pipefail

python - <<'EOF'
import dnslab, dnslab.checks, dnslab.certs, dnslab.registry
print(f"dnslab import ok — {len(dnslab.registry())} server module(s) discovered")
EOF

exec python -m dnslab.selfcheck
