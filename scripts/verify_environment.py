from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import metadata


def parse_version(value: str) -> tuple[int, ...]:
    parts = []
    for token in value.split('.'):
        digits = ''.join(ch for ch in token if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def command_version(command: str, *args: str) -> str | None:
    if not shutil.which(command):
        return None
    try:
        return subprocess.check_output([command, *args], text=True, stderr=subprocess.STDOUT).strip()
    except Exception:
        return None


print('JARVIS — Component V2 environment check')
print('-' * 48)
print('Python:', sys.version.split()[0])

try:
    streamlit_version = metadata.version('streamlit')
except metadata.PackageNotFoundError:
    streamlit_version = None

print('Streamlit:', streamlit_version or 'NOT INSTALLED')
if streamlit_version:
    poc_ok = parse_version(streamlit_version) >= (1, 51)
    print('Components V2 POC:', 'READY' if poc_ok else 'UPGRADE REQUIRED (>=1.51)')
else:
    print('Components V2 POC: STREAMLIT REQUIRED')

node = command_version('node', '--version')
npm = command_version('npm', '--version')
print('Node.js:', node or 'NOT INSTALLED')
print('npm:', npm or 'NOT INSTALLED')

if node:
    node_major = int(node.lstrip('v').split('.')[0])
    print('React package phase:', 'READY' if node_major >= 24 else 'NODE 24+ RECOMMENDED BY STREAMLIT')
else:
    print('React package phase: NODE 24+ REQUIRED')

print('\nPhase 1 only needs Streamlit >=1.51.')
print('Node/npm are only required for the React + TypeScript phase.')
