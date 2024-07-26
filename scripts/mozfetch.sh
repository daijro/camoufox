#!/usr/bin/env bash
set -e 

rm -f bootstrap.py
wget -q https://hg.mozilla.org/mozilla-central/raw-file/default/python/mozboot/bin/bootstrap.py
python3 bootstrap.py --no-interactive --application-choice=browser
rm -f bootstrap.py
