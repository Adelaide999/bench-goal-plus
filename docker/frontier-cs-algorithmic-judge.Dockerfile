FROM ubuntu:22.04

ARG UBUNTU_MIRROR=http://archive.ubuntu.com/ubuntu
ARG UBUNTU_SECURITY_MIRROR=http://security.ubuntu.com/ubuntu
ARG NPM_REGISTRY=https://registry.npmjs.org
ARG NPM_VERSION=10.8.2
ARG GO_JUDGE_VERSION=v1.11.1

ENV DEBIAN_FRONTEND=noninteractive

# Mirrors are configurable; defaults preserve the upstream Dockerfile.
RUN sed -i \
      -e "s|http://security.ubuntu.com/ubuntu|${UBUNTU_SECURITY_MIRROR}|g" \
      -e "s|http://archive.ubuntu.com/ubuntu|${UBUNTU_MIRROR}|g" \
      /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      jq \
      git \
      unzip \
      zip \
      build-essential \
      pkg-config \
      python3 \
      python3-pip \
      pypy3 \
      openjdk-17-jdk \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm config set registry "${NPM_REGISTRY}" \
    && npm install -g --registry="${NPM_REGISTRY}" "npm@${NPM_VERSION}"

RUN set -eux; \
  arch="$(uname -m)"; \
  case "$arch" in \
    x86_64) goarch="amd64v2" ;; \
    aarch64) goarch="arm64" ;; \
    *) echo "Unsupported arch: $arch"; exit 1 ;; \
  esac; \
  version="${GO_JUDGE_VERSION#v}"; \
  url="https://github.com/criyle/go-judge/releases/download/${GO_JUDGE_VERSION}/go-judge_${version}_linux_${goarch}.tar.gz"; \
  curl -fsSL "$url" | tar -xz -C /usr/local/bin go-judge; \
  chmod +x /usr/local/bin/go-judge

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --omit=dev --ignore-scripts --registry="${NPM_REGISTRY}"

COPY server.js entrypoint.sh ./
COPY judge/src/ ./src/
COPY judge/include/ ./include/
COPY judge/config/ ./config/
COPY judge/include/ /lib/testlib/

RUN chmod +x entrypoint.sh && sed -i 's/\r$//' entrypoint.sh

ENV PORT=8081 \
    GJ_ADDR=http://127.0.0.1:5050

ENTRYPOINT ["/app/entrypoint.sh"]
