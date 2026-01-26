# Sovereign Ghost Protocol Deployment

## Windows Setup
```bash
pip install -r requirements.txt
```

## Linux Full Deployment
```bash
# eBPF Requirements
sudo apt install clang llvm libelf-dev

# vTPM Setup
sudo apt install swtpm-tools
mkdir -p /tmp/swtpm

# Docker
sudo apt install docker.io
docker compose -f genesis/docker-compose.yml up -d
```
