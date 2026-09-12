# dns-notebook/Dockerfile — Red Hat UBI9 variant (branch: feature/ubi9)
#
# EL9 port of the Debian image for corporate-compliance environments.
# Follows the neodocker:dns-ubi9 subscription-manager pattern: RHSM org id
# + activation key arrive as a BuildKit secret (never ARG/ENV — those
# persist in image history), each entitled sequence registers, installs,
# unregisters, and scrubs all entitlement state within a single layer.
#
# Build:  docker compose build          (secret wired in compose.yaml from
#                                        ~/.rhsm-activation: RHSM_ORG_ID=…,
#                                        RHSM_ACTIVATION_KEY=… lines)
#    or:  docker build --secret id=rhsm,src=$HOME/.rhsm-activation .
#
# Package sourcing (verified against these repos 2026-09-12):
#   free UBI repos    dig (bind-utils), graphviz, python3.12(+pip), jq, bc,
#                     iputils, git-core, less, gcc/meson/ninja
#   entitled rhel-9   bind (named-checkconf/-checkzone), Chromium runtime
#                     deps for nbconvert[webpdf]; libuv-devel via CRB
#   EPEL 9            knot-utils (kdig), dnsperf, dnsviz, stubby, tini
#   built from source ldns/drill (not packaged anywhere on EL9),
#                     flamethrower, dnspyre, q (same rationale as Debian:
#                     upstream q binaries ship stale toolchains)
#
# The runtime uses ubi9 (standard, not minimal): subscription-manager and
# dnf are preinstalled so there is no install-then-strip dance, and next to
# the multi-GB Jupyter/Chromium payload the ~90MB base delta is noise.

# ── builder stage: ldns/drill, flamethrower, dnspyre, q ──
FROM registry.access.redhat.com/ubi9/ubi:latest@sha256:206b65b8ee0f04b992818c9a51b29081b14974630d4850bc358097d0c44ea156 AS builder

# Entitled build deps in one self-cleaning layer: gnutls/nghttp2/libuv devel
# headers live in the entitled appstream/CRB repos, not in free UBI. The
# builder stage never ships, but unregister anyway so no orphaned consumers
# accumulate at console.redhat.com; the `|| rc=$?` capture runs it even
# when the install fails, and the layer still fails with the real rc.
RUN --mount=type=secret,id=rhsm \
  set -eu; \
  . /run/secrets/rhsm; \
  rm -f /etc/rhsm-host /etc/pki/entitlement-host; \
  subscription-manager register --org "$RHSM_ORG_ID" --activationkey "$RHSM_ACTIVATION_KEY"; \
  rc=0; { \
    dnf install -y --setopt=install_weak_deps=False \
      --enablerepo=codeready-builder-for-rhel-9-x86_64-rpms \
      gcc gcc-c++ make cmake ninja-build git-core xz \
      python3.12 python3.12-pip \
      openssl-devel gnutls-devel libnghttp2-devel; \
  } || rc=$?; \
  subscription-manager unregister || true; \
  subscription-manager clean || true; \
  dnf clean all; \
  exit $rc

# Install Go from official tarball (EL9's go-toolset lags what dnspyre/q
# deps need, and this keeps parity with the Debian image)
RUN curl -fsSL https://go.dev/dl/go1.27.1.linux-amd64.tar.gz | tar -C /usr/local -xz
ENV PATH="/usr/local/go/bin:${PATH}"

# EL9's packaged meson (0.63.3) predates flamethrower's >= 1.3.0 floor;
# take a current meson from pip on the free python3.12 instead.
RUN pip3.12 install --no-cache-dir meson

# Build libuv from source: flamethrower's vendored uvw needs
# uv_pipe_connect2 (libuv >= 1.46) but EL9 ships 1.42. Installs into
# /usr/local; the runtime copies libuv.so.1*.
ARG LIBUV_VERSION=1.51.0
WORKDIR /tmp/libuv
RUN curl -fsSL "https://dist.libuv.org/dist/v${LIBUV_VERSION}/libuv-v${LIBUV_VERSION}.tar.gz" \
    | tar -xz --strip-components=1 \
  && cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
       -DCMAKE_INSTALL_PREFIX=/usr/local -DLIBUV_BUILD_TESTS=OFF \
  && cmake --build build \
  && cmake --install build

# Build ldns with drill from source: EL9/EPEL9 do not package ldns at all,
# and flamethrower needs its headers too. Installs into /usr/local (the
# runtime copies libldns.so.* + drill and runs ldconfig).
ARG LDNS_VERSION=1.8.4
WORKDIR /tmp/ldns
RUN curl -fsSL "https://www.nlnetlabs.nl/downloads/ldns/ldns-${LDNS_VERSION}.tar.gz" \
    | tar -xz --strip-components=1 \
  && ./configure --prefix=/usr/local --with-drill --disable-python \
  && make -j"$(nproc)" \
  && make install \
  && strip /usr/local/bin/drill

# Build flamethrower and strip symbols to shrink the binary (ldns comes
# from /usr/local above, hence the PKG_CONFIG_PATH)
WORKDIR /tmp/flamethrower
RUN git clone --branch v0.12.0 --depth 1 https://github.com/DNS-OARC/flamethrower.git . \
  && PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:/usr/local/lib64/pkgconfig \
       meson setup build --buildtype=release --strip \
  && ninja -C build \
  && cp build/flame /usr/local/bin/flame \
  && strip --strip-unneeded /usr/local/bin/flame

# Build dnspyre (actively maintained dnstrace successor) from source.
# CGO_ENABLED=0 + -s -w strips the resulting binary (~40MB → ~15MB).
# The go.mod pins carry known CVEs (x/crypto, x/image); bump them to the
# latest patched releases before building.
WORKDIR /tmp/dnspyre
RUN git clone --branch v3.12.0 --depth 1 https://github.com/Tantalor93/dnspyre.git . \
  && go get golang.org/x/crypto@latest golang.org/x/image@latest \
  && go mod tidy \
  && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /usr/local/bin/dnspyre .

# Build q (natesales/q, multi-protocol DNS client) from source instead of
# using the release binary: upstream's v0.19.12 build ships a stale Go
# toolchain and x/crypto//x/net/quic-go pins with dozens of known CVEs
# (incl. a CRITICAL in the Go stdlib). Building here with the current Go
# plus dependency bumps clears all of them.
WORKDIR /tmp/q
RUN git clone --branch v0.19.12 --depth 1 https://github.com/natesales/q.git . \
  && go get golang.org/x/crypto@latest golang.org/x/net@latest \
       golang.org/x/text@latest github.com/quic-go/quic-go@latest \
  && go mod tidy \
  && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /usr/local/bin/q .

# ── runtime stage ──
FROM registry.access.redhat.com/ubi9/ubi:latest@sha256:206b65b8ee0f04b992818c9a51b29081b14974630d4850bc358097d0c44ea156

# The venv leads PATH so `python`, `pip`, `jupyter` etc. resolve to the
# python3.12 stack (EL9's system python stays 3.9, owned by dnf/dnsviz).
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    JUPYTER_PLATFORM_DIRS=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    # Playwright: share the bundled Chromium across all users via a
    # world-readable path (nbconvert[webpdf] uses playwright internally).
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# OS deps + DNS tools in one self-cleaning entitled layer (same pattern and
# rationale as the builder stage — register / install / unregister / scrub,
# with the || rc capture keeping cleanup unconditional):
#   entitled  dnf upgrade (point-release security fixes), bind (the only
#             EL9 home of named-checkconf/-checkzone), Chromium runtime
#             deps for nbconvert[webpdf]
#   EPEL      knot-utils dnsperf dnsviz stubby tini (dnsviz rides the
#             system python3.9 — self-contained CLI, not our venv)
#   free UBI  everything else (installed here anyway — one layer)
RUN --mount=type=secret,id=rhsm \
  set -eu; \
  . /run/secrets/rhsm; \
  rm -f /etc/rhsm-host /etc/pki/entitlement-host; \
  subscription-manager register --org "$RHSM_ORG_ID" --activationkey "$RHSM_ACTIVATION_KEY"; \
  rc=0; { \
    dnf upgrade -y --setopt=install_weak_deps=False && \
    dnf install -y --setopt=install_weak_deps=False \
      git-core jq less bc iputils \
      bind bind-utils \
      graphviz \
      python3.12 python3.12-pip \
      gnutls libnghttp2 \
      alsa-lib atk at-spi2-atk cups-libs libdrm mesa-libgbm gtk3 nss \
      libXcomposite libXdamage libXrandr pango libxkbcommon \
      liberation-fonts \
      https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm && \
    dnf install -y --setopt=install_weak_deps=False \
      knot-utils dnsperf dnsviz stubby tini; \
  } || rc=$?; \
  subscription-manager unregister || true; \
  subscription-manager clean || true; \
  dnf clean all; \
  rm -rf /etc/pki/entitlement* /etc/pki/consumer /var/lib/rhsm \
    /etc/yum.repos.d/redhat.repo; \
  exit $rc

# Copy built binaries from builder; /usr/local/lib is not on EL9's default
# linker path, so register it for libldns (drill, flame)
COPY --from=builder /usr/local/bin/flame /usr/local/bin/flame
COPY --from=builder /usr/local/bin/dnspyre /usr/local/bin/dnspyre
COPY --from=builder /usr/local/bin/q /usr/local/bin/q
COPY --from=builder /usr/local/bin/drill /usr/local/bin/drill
COPY --from=builder /usr/local/lib/libldns.so.* /usr/local/lib/
COPY --from=builder /usr/local/lib64/libuv.so.* /usr/local/lib64/
RUN printf '/usr/local/lib\n/usr/local/lib64\n' > /etc/ld.so.conf.d/usr-local.conf && ldconfig

# Install dnsperftest (shell script). Remove .git to save a few hundred KB.
RUN git clone --depth 1 https://github.com/cleanbrowsing/dnsperftest.git /opt/dnsperftest \
  && rm -rf /opt/dnsperftest/.git

# Install dot-cert-tester (DoT certificate testing tool)
RUN curl -fsSL https://raw.githubusercontent.com/ltfiend/dns-scripts/refs/heads/main/dot-cert-tester.py \
    -o /opt/dot-cert-tester.py \
  && chmod +x /opt/dot-cert-tester.py \
  && ln -s /opt/dot-cert-tester.py /usr/bin/dot-cert-tester

# Python 3.12 venv with the notebook stack (same package set as the Debian
# image; see that Dockerfile's comments for the individual rationales).
# The pip self-upgrade keeps its _vendor pins current on the weekly rebuild
# (known-unfixable vendored CVEs are documented in .trivyignore).
RUN python3.12 -m venv /opt/venv \
  && pip install --no-cache-dir --no-compile --upgrade pip \
  && pip install --no-cache-dir --no-compile \
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
        ipynbname \
        "nbconvert[webpdf]" \
        docker \
        pyyaml \
        cryptography \
        jinja2 \
  && find /opt/venv/lib/python3.12 -depth \
        \( -type d \( -name tests -o -name test -o -name __pycache__ \) \
        -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
        -exec rm -rf {} + \
  && rm -rf /root/.cache

# Pre-download the Chromium build playwright uses so the first
# `nbconvert --to webpdf` call doesn't need network access. --only-shell
# pulls headless chromium without the full UI binary (~170MB saved).
RUN mkdir -p "${PLAYWRIGHT_BROWSERS_PATH}" \
  && playwright install --only-shell chromium \
  && chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"

# Non-root user; the bind RPM already created the `named` group, add nbuser
# to it for parity with the Debian image
RUN useradd -m -u 1000 -G named -s /bin/bash nbuser
RUN mkdir /workspace; chown nbuser:named /workspace

# Jupyter server config — disables kernel culling, raises iopub rate
# limits, and enables websocket keepalive so 30min+ cells survive.
COPY --chmod=644 jupyter_server_config.py /etc/jupyter/jupyter_server_config.py

# Startup helper: pull from Git or S3 if configured
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

USER nbuser
WORKDIR /workspace

EXPOSE 8888
ENTRYPOINT ["tini","--","/usr/local/bin/entrypoint.sh"]
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser"]
