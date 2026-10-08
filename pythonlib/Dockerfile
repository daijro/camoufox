# The Camoufox REST API (`camoufox rest`) and its web page.
#
#   docker build -t camoufox-rest pythonlib
#   docker run --rm -p 127.0.0.1:8000:8000 -e CAMOUFOX_REST_TOKEN camoufox-rest
#
# The service binds 0.0.0.0 inside the container, so it refuses to start
# without CAMOUFOX_REST_TOKEN.
FROM python:3.12-slim-bookworm

WORKDIR /src
COPY . .
# install-deps pulls in the system libraries Firefox, and so Camoufox, links against.
RUN pip install --no-cache-dir . \
    && playwright install-deps firefox \
    && rm -rf /src /var/lib/apt/lists/*

RUN useradd --create-home camoufox
USER camoufox
WORKDIR /home/camoufox
# Fetch the browser at build time, so a container starts without a download.
# `camoufox fetch` reports a failed download without failing, so check the
# install, or the image would build without a browser.
RUN camoufox fetch \
    && python -c "from camoufox.pkgman import installed_verstr; print(installed_verstr())"

EXPOSE 8000
ENTRYPOINT ["camoufox", "rest", "--host", "0.0.0.0", "--port", "8000"]
