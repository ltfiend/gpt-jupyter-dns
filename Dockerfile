# dns-notebook/Dockerfile

# ── builder stage: compile flamethrower and dnspyre ──
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git \
    # flamethrower build deps
    g++ meson pkgconf ninja-build \
    libldns-dev libuv1-dev libgnutls28-dev libnghttp2-dev \
  && rm -rf /var/lib/apt/lists/*

# Install Go from official tarball (Debian's version is too old for dnstrace deps)
RUN curl -fsSL https://go.dev/dl/go1.24.4.linux-amd64.tar.gz | tar -C /usr/local -xz
ENV PATH="/usr/local/go/bin:${PATH}"

# Build flamethrower and strip symbols to shrink the binary
RUN git clone --branch v0.12.0 --depth 1 https://github.com/DNS-OARC/flamethrower.git /tmp/flamethrower \
  && cd /tmp/flamethrower \
  && meson setup build --buildtype=release --strip \
  && ninja -C build \
  && cp build/flame /usr/local/bin/flame \
  && strip --strip-unneeded /usr/local/bin/flame

# Build dnspyre (actively maintained dnstrace successor) from source.
# CGO_ENABLED=0 + -s -w strips the resulting binary (~40MB → ~15MB).
RUN git clone --branch v3.10.2 --depth 1 https://github.com/Tantalor93/dnspyre.git /tmp/dnspyre \
  && cd /tmp/dnspyre \
  && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /usr/local/bin/dnspyre .

# ── runtime stage ──
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    JUPYTER_PLATFORM_DIRS=1 \
    # Playwright: share the bundled Chromium across all users via a
    # world-readable path (nbconvert[webpdf] uses playwright internally).
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# OS deps + DNS tools + dnsviz CLI + Graphviz + Git
# Notes on what was dropped vs. the old Dockerfile:
#   - texlive-xetex/fonts/plain-generic + pandoc  (~800MB): replaced by
#     nbconvert[webpdf] which uses a headless Chromium (~130MB) to render
#     notebooks → PDF. See README "PDF Export" section.
#   - awscli (debian pkg, ~120MB w/ deps): replaced by the pip-installed
#     awscli v1 which shares botocore with boto3 (~20MB net).
#   - vim: Jupyter ships its own editor; containers should stay lean.
#   - Chromium sandboxing libs are pulled in as runtime deps below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git jq less tini \
    bind9-dnsutils \
    knot-dnsutils \
    ldnsutils \
    dnsviz \
    graphviz \
    iputils-ping \
    bind9-utils \
    stubby \
    dnsperf \
    bc \
    # flamethrower runtime libs
    libldns3 libuv1t64 libgnutls30t64 libnghttp2-14 \
    # Chromium runtime deps for nbconvert[webpdf] / pyppeteer
    libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 libgbm1 libgtk-3-0 \
    libnss3 libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 \
    libpango-1.0-0 libasound2 fonts-liberation fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/*

# Copy built binaries from builder
COPY --from=builder /usr/local/bin/flame /usr/local/bin/flame
COPY --from=builder /usr/local/bin/dnspyre /usr/local/bin/dnspyre

# Install q (natesales/q) DNS client
RUN curl -fsSL https://github.com/natesales/q/releases/download/v0.19.12/q_0.19.12_linux_amd64.tar.gz \
    | tar -xz -C /usr/local/bin q

# Install dnsperftest (shell script). Remove .git to save a few hundred KB.
RUN git clone --depth 1 https://github.com/cleanbrowsing/dnsperftest.git /opt/dnsperftest \
  && rm -rf /opt/dnsperftest/.git

# Install dot-cert-tester (DoT certificate testing tool)
RUN curl -fsSL https://raw.githubusercontent.com/ltfiend/dns-scripts/main/dot-cert-tester.py \
    -o /opt/dot-cert-tester.py \
  && chmod +x /opt/dot-cert-tester.py \
  && ln -s /opt/dot-cert-tester.py /usr/bin/dot-cert-tester

# Python libs for notebooks, DNS, and S3/Git integration.
# - `jupyterlab` already bundles `jupyter-server` + `nbconvert`, so the old
#   `notebook` dep was removed as redundant.
# - `awscli` is installed via pip to replace the heavy Debian package.
# - `nbconvert[webpdf]` pulls in pyppeteer for Chromium-based PDF export.
# - `--no-compile` skips writing .pyc files during install (~15% smaller);
#   Python will compile on demand at runtime.
# Post-install cleanup trims test suites and caches that ship inside wheels.
RUN pip install --no-cache-dir --no-compile \
        jupyterlab \
        ipywidgets \
        dnspython \
        boto3 \
        awscli \
        gitpython \
        matplotlib \
        pandas \
        rich \
        tabulate \
        "nbconvert[webpdf]" \
  && find /usr/local/lib/python3.12 -depth \
        \( -type d \( -name tests -o -name test -o -name __pycache__ \) \
        -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
        -exec rm -rf {} + \
  && rm -rf /root/.cache

# Pre-download the Chromium build playwright uses so the first
# `nbconvert --to webpdf` call doesn't need network access. Install it
# under $PLAYWRIGHT_BROWSERS_PATH (set above) and make it world-readable
# so nbuser can use it. --only-shell pulls headless chromium without the
# full UI binary (~170MB saved vs `playwright install chromium`).
RUN mkdir -p "${PLAYWRIGHT_BROWSERS_PATH}" \
  && playwright install --only-shell chromium \
  && chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"

# Non-root user
RUN groupadd -g 53 named; useradd -m -u 1000 -G 53 -s /bin/bash nbuser
RUN mkdir /workspace; chown nbuser:named /workspace

# Jupyter server config — disables kernel culling, raises iopub rate
# limits, and enables websocket keepalive so 30min+ cells survive.
COPY jupyter_server_config.py /etc/jupyter/jupyter_server_config.py

# Startup helper: pull from Git or S3 if configured
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER nbuser
WORKDIR /workspace

EXPOSE 8888
ENTRYPOINT ["tini","--","/usr/local/bin/entrypoint.sh"]
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser"]
