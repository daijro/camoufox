# syntax=docker/dockerfile:1
# The Camoufox REST API (`camoufox rest`) and its web page.
#
#   docker build -t camoufox-rest pythonlib
#   docker run --rm -p 127.0.0.1:8000:8000 -e CAMOUFOX_REST_TOKEN camoufox-rest
#
# The service binds 0.0.0.0 inside the container, so it refuses to start
# without CAMOUFOX_REST_TOKEN.
#
# Layers run from least to most often changed, so an edit rebuilds only what
# follows the first layer it touches.
FROM python:3.12-slim-bookworm

WORKDIR /src

# Dependencies come from pyproject.toml alone: install them against an empty
# stand-in package, then drop it.
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir camoufox && touch camoufox/__init__.py README.md \
    && pip install . \
    && pip uninstall --yes camoufox \
    && rm -r camoufox README.md

# The system libraries Firefox, and so Camoufox, links against.
RUN playwright install-deps firefox && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home camoufox

# Fetch the browser at build time, so a container starts without a download.
# The download is the slowest step. Which build it fetches depends on the
# package but not on the REST service, so the service is left out here and an
# edit to it reuses this layer. `camoufox fetch` reports a failed download
# without failing, so check the install, or the image would have no browser.
COPY --exclude=rest.* camoufox camoufox
USER camoufox
RUN python -m camoufox fetch \
    && python -c "from camoufox.pkgman import installed_verstr; print(installed_verstr())"

USER root
COPY . .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps . && rm -rf /src

USER camoufox
WORKDIR /home/camoufox
EXPOSE 8000
ENTRYPOINT ["camoufox", "rest", "--host", "0.0.0.0", "--port", "8000"]
