FROM ubuntu:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

RUN apt-get update && apt-get install -y \
    # Mach build tools
    build-essential \
    make \
    msitools \
    wget \
    unzip \
    # Python
    python3 \
    python3-dev \
    python3-pip \
    # Camoufox build system tools
    git \
    p7zip-full \
    golang-go \
    aria2 \
    curl \
    rsync \
    # CA certificates
    ca-certificates \
    && update-ca-certificates \
    && curl https://sh.rustup.rs -sSf | bash -s -- -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Run setup and bootstrap
RUN make setup-minimal && \
    make mozbootstrap && \
    mkdir -p /app/dist

VOLUME ["/root/.mozbuild", "/app/dist"]

ENTRYPOINT ["python3", "./multibuild.py"]
