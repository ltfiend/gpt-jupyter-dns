# dns-notebook/docker/entrypoint.sh
#!/usr/bin/env bash
set -euo pipefail

# Default workspace layout
mkdir -p /workspace/notebooks

# Optional: install extra pip packages at runtime
if [ -n "${EXTRA_PIP:-}" ]; then
  echo "[startup] Installing EXTRA_PIP: ${EXTRA_PIP}"
  python -m pip install --no-cache-dir ${EXTRA_PIP}
fi

# Optional: pull notebooks from Git on every start if GIT_URL is set
if [ -n "${GIT_URL:-}" ]; then
  echo "[startup] Cloning/Updating Git repo: ${GIT_URL}"
  if [ ! -d "/workspace/notebooks/.git" ]; then
    git clone --depth 1 "${GIT_URL}" /workspace/notebooks || true
  else
    git -C /workspace/notebooks pull --ff-only || true
  fi
fi

# Optional: sync notebooks from S3 if S3_URI is set
if [ -n "${S3_URI:-}" ]; then
  echo "[startup] Syncing from S3: ${S3_URI}"
  aws s3 sync "${S3_URI}" /workspace/notebooks --only-show-errors || true
fi

# Set default Jupyter token if not provided via environment
export JUPYTER_TOKEN="${JUPYTER_TOKEN:-dnslab}"

exec "$@"

