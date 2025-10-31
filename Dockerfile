# dns-notebook/Dockerfile
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
  && rm -rf /var/lib/apt/lists/*

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
    rich

# Non-root user
RUN useradd -m -u 1000 -s /bin/bash nbuser
USER nbuser
WORKDIR /workspace

# Simple “hello” notebooks directory for first run
RUN mkdir -p /workspace/notebooks

# Startup helper: pull from Git or S3 if configured
USER root
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
USER nbuser

EXPOSE 8888
ENTRYPOINT ["tini","--","/usr/local/bin/entrypoint.sh"]
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser"]

