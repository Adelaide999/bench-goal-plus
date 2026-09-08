FROM python:3.11.15@sha256:d0199e2a90bf7a206a485b115323a75bc946f30b463d704c5435a454aca084dd AS base

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl jq build-essential sudo \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash agent \
    && echo 'agent ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers \
    && git config --global safe.directory '*'
WORKDIR /home/workspace/sebench_performance_takehome

FROM base AS work
LABEL org.bench-goal-plus.platform="linux/arm64" \
    org.bench-goal-plus.source-image="seededge/edgebench.work.vliw_kernel_optimization@sha256:f4e9334beef8b304fd942b44ad3ec6a01c7369c305d5afc8b394075d0aff3b58" \
    org.bench-goal-plus.dataset-revision="47846a4c3669ad447e0ea984833b0d352460c5f9"
COPY --chown=agent:agent work/ /home/workspace/sebench_performance_takehome/
# WORKDIR created the destination itself as root before COPY.
RUN chown agent:agent /home/workspace/sebench_performance_takehome
USER agent
RUN python -c 'import tempfile; f = tempfile.TemporaryFile(dir="."); f.close(); d = tempfile.TemporaryDirectory(dir="."); d.cleanup()'

FROM base AS judge
LABEL org.bench-goal-plus.platform="linux/arm64" \
    org.bench-goal-plus.source-image="seededge/edgebench.judge.vliw_kernel_optimization@sha256:3aa13f35dc05dcf33df7cad2c8c21908f02d8d72dde80857286397cfd984b2f9" \
    org.bench-goal-plus.dataset-revision="47846a4c3669ad447e0ea984833b0d352460c5f9"
COPY judge/ /home/workspace/sebench_performance_takehome/
