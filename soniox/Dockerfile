ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:trixie
FROM ${BUILD_FROM}

WORKDIR /usr/src
COPY requirements.txt ./
RUN \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        netcat-traditional \
        python3 \
        python3-venv \
    && python3 -m venv .venv \
    && .venv/bin/pip3 install --no-cache-dir -r requirements.txt \
    && rm -rf /var/lib/apt/lists/*

COPY wyoming_soniox ./wyoming_soniox
ENV PATH="/usr/src/.venv/bin:$PATH" \
    PYTHONPATH="/usr/src"

WORKDIR /
COPY rootfs /

HEALTHCHECK --start-period=1m --start-interval=5s --interval=30s \
    CMD echo '{ "type": "describe" }' \
        | nc -w 1 localhost 10500 \
        | grep -q "Soniox" \
        || exit 1
