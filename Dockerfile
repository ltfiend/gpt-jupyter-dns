# dns-notebook/Dockerfile

# ── builder stage: compile flamethrower and dnstrace ──
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

# Build flamethrower
RUN git clone --branch v0.12.0 --depth 1 https://github.com/DNS-OARC/flamethrower.git /tmp/flamethrower \
  && cd /tmp/flamethrower \
  && meson setup build \
  && ninja -C build \
  && cp build/flame /usr/local/bin/flame

# Build dnspyre (actively maintained dnstrace successor) from source
RUN git clone --branch v3.10.2 --depth 1 https://github.com/Tantalor93/dnspyre.git /tmp/dnspyre \
  && cd /tmp/dnspyre \
  && go build -o /usr/local/bin/dnspyre .

# ── runtime stage ──
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    JUPYTER_PLATFORM_DIRS=1

# OS deps + DNS tools + dnsviz CLI + Graphviz + AWS CLI + Git
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git jq less vim tini \
    bind9-dnsutils \
    knot-dnsutils \
    ldnsutils \
    dnsviz \
    graphviz \
    awscli \
    iputils-ping \
    bind9-utils \
    stubby \
    dnsperf \
    bc \
    # flamethrower runtime libs
    libldns3 libuv1t64 libgnutls30t64 libnghttp2-14 \
  && rm -rf /var/lib/apt/lists/*

# Copy built binaries from builder
COPY --from=builder /usr/local/bin/flame /usr/local/bin/flame
COPY --from=builder /usr/local/bin/dnspyre /usr/local/bin/dnspyre

# Install q (natesales/q) DNS client
RUN curl -fsSL https://github.com/natesales/q/releases/download/v0.19.12/q_0.19.12_linux_amd64.tar.gz \
    | tar -xz -C /usr/local/bin q

# Install dnsperftest (shell script)
RUN git clone --depth 1 https://github.com/cleanbrowsing/dnsperftest.git /opt/dnsperftest

# Install dot-cert-tester (DoT certificate testing tool)
RUN curl -fsSL https://raw.githubusercontent.com/ltfiend/dns-scripts/main/dot-cert-tester.py \
    -o /opt/dot-cert-tester.py \
  && chmod +x /opt/dot-cert-tester.py \
  && ln -s /opt/dot-cert-tester.py /usr/bin/dot-cert-tester

# Python libs for notebooks, DNS, and S3/Git integration
RUN pip install --no-cache-dir \
    jupyterlab \
    notebook \
    ipywidgets \
    dnspython \
    boto3 \
    gitpython \
    matplotlib \
    pandas \
    rich \
    tabulate

# Non-root user
RUN groupadd -g 53 named; useradd -m -u 1000 -G 53 -s /bin/bash nbuser
RUN mkdir /workspace; chown nbuser:named /workspace
USER nbuser
WORKDIR /workspace

# Startup helper: pull from Git or S3 if configured
USER root
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
USER nbuser

EXPOSE 8888
ENTRYPOINT ["tini","--","/usr/local/bin/entrypoint.sh"]
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser"]
