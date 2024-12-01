FROM debian:latest

# Set working directory
WORKDIR /app

# Install Python and essential tools
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    wget \
    xvfb \
    && apt-get clean

# Install Playwright dependencies
RUN pip3 install --no-cache-dir playwright tabulate camoufox[geoip] --break-system-packages && \
    playwright install-deps && \
    playwright install firefox && \
    python3 -m camoufox fetch

# Copy the benchmark script
COPY benchmark.py /app/

# Default entrypoint to run the benchmark
ENTRYPOINT ["python3", "/app/benchmark.py"]
