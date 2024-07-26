FROM python:3.11-slim-bullseye

WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install necessary packages
RUN apt-get update && apt-get install -y \
	# Makefile utils
    build-essential make git msitools wget unzip \
	# Camoufox build system utils
	p7zip-full golang-go

RUN make fetch && make mozbootstrap

ENTRYPOINT ["python3", "./multibuild.py"]
