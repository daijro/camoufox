FROM debian:trixie-slim
ARG FFARCH
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl xz-utils python3 fonts-dejavu-core \
      libgtk-3-0t64 libasound2t64 libx11-xcb1 libxtst6 libdbus-1-3 libpci3 libegl1 libgl1 libgl1-mesa-dri \
    && rm -rf /var/lib/apt/lists/*
RUN curl -sfL --limit-rate 10M -o /tmp/ff.tar.xz https://ftp.mozilla.org/pub/firefox/releases/159.0/${FFARCH}/en-US/firefox-159.0.tar.xz \
    && tar -C /opt -xf /tmp/ff.tar.xz && rm /tmp/ff.tar.xz
WORKDIR /probe
