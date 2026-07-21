FROM python:3.12-slim

ARG DEBIAN_MIRROR=http://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=http://deb.debian.org/debian-security
ARG NODEJS_SOURCE=nodesource
ARG NPM_REGISTRY=https://registry.npmjs.org

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# This is the upstream task-base image with configurable package mirrors. The
# default arguments preserve upstream behavior. NODEJS_SOURCE=debian keeps the
# same Node 20 major version while avoiding the external NodeSource repository.
RUN sed -i \
      -e "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
      -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
      /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      bash \
      ca-certificates \
      curl \
      gcc \
      git \
      gnupg \
      jq \
      ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN if [ "${NODEJS_SOURCE}" = "nodesource" ]; then \
      curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
      && apt-get install -y --no-install-recommends nodejs; \
    elif [ "${NODEJS_SOURCE}" = "debian" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends nodejs npm; \
    else \
      echo "unsupported NODEJS_SOURCE=${NODEJS_SOURCE}" >&2; exit 2; \
    fi \
    && rm -rf /var/lib/apt/lists/* \
    && npm config set registry "${NPM_REGISTRY}" \
    && npm install -g --registry="${NPM_REGISTRY}" \
      @openai/codex \
      @anthropic-ai/claude-code \
      @mariozechner/pi-coding-agent \
    && pi install npm:pi-subagents

COPY pi-extensions /opt/pi-extensions
RUN node /opt/pi-extensions/patch-bedrock-mantle.mjs \
    && node /opt/pi-extensions/patch-pi-subagents-final-output.js --required

WORKDIR /benchmark
CMD ["sleep", "infinity"]
