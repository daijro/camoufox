#!/bin/bash

python3 -m venv venv
venv/bin/pip3 install -r local-requirements.txt

# Install Firefox as well (Playwright freaks out when it's missing)
venv/bin/playwright install firefox
