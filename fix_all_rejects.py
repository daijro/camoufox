#!/usr/bin/env python3
"""
Fix all reject files by finding correct line numbers in Firefox 146 source.
"""
import os
import re
import subprocess
from pathlib import Path

def find_rejects():
    """Find all .rej files"""
    result = subprocess.run(
        ['find', 'camoufox-146.0.1-beta.25', '-name', '*.rej'],
        capture_output=True, text=True
    )
    return sorted(result.stdout.strip().split('\n'))

def read_reject(rej_path):
    """Read and parse reject file"""
    with open(rej_path, 'r') as f:
        content = f.read()
    return content

def main():
    rejects = find_rejects()
    print(f"Found {len(rejects)} rejects")
    for rej in rejects:
        print(f"\n=== {rej} ===")
        content = read_reject(rej)
        print(content[:200] + "...")

if __name__ == '__main__':
    main()
