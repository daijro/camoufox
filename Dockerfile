FROM ubuntu:latest

WORKDIR /app

# Copy the current directory into the container at /app
COPY . /app

# Install necessary packages
RUN apt-get update && apt-get install -y \
    # Mach build tools
    build-essential make msitools wget unzip rustc \
    # Python
    python3 python3-dev python3-pip \
    # Camoufox build system tools
    git p7zip-full golang-go aria2 curl rsync \
    # Platform-specific libraries for Linux builds
    libsqlite3-dev \
    # CA certificates
    ca-certificates \
    && update-ca-certificates

RUN curl https://sh.rustup.rs -sSf | bash -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Fetch Firefox & apply initial patches
RUN make setup-minimal && \
    make mozbootstrap && \
    mkdir -p /app/dist

# Mount .mozbuild directory and dist folder
VOLUME /root/.mozbuild
VOLUME /app/dist

ENTRYPOINT ["python3", "./multibuild.py"]