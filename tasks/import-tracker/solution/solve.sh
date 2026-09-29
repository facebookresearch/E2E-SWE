#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it).
git clone https://github.com/IBM/import-tracker.git /tmp/repo
cd /tmp/repo
git checkout 0735385206ba68315493385a7f5a86486b7a4165

# cp -a carries .git too (harmless here; the version comes from RELEASE_VERSION, not scm).
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# Patch _get_op_number for Python 3.13+ compatibility.
# Python 3.13 changed dis.Bytecode.dis() output format:
#   - Some lines omit the bytecode offset before the opcode name
#   - Exception handler lines use labels like "L3:" instead of numeric offsets
# Replace the assertion and int() with safe checks. No-op on older Python (the source already
# matches), so it is safe to apply regardless of the base image's interpreter version.
python3 << 'PYEOF'
path = "import_tracker/import_tracker.py"
with open(path, "r") as f:
    src = f.read()

old = '''    assert opcode_idx > 0, f"Opcode found at the beginning of line! [{dis_line}]"
    return int(line_parts[opcode_idx - 1])'''

new = '''    if opcode_idx == 0:
        return None
    prev = line_parts[opcode_idx - 1]
    if not prev.isnumeric():
        return None
    return int(prev)'''

src = src.replace(old, new)
with open(path, "w") as f:
    f.write(src)
PYEOF

# setup.sh installs the project offline: the build backend (setuptools/wheel) is pre-baked and the
# image sets PIP_NO_INDEX, so --no-build-isolation is REQUIRED (pip must not try to fetch an isolated
# build env). RELEASE_VERSION is REQUIRED: the repo's setup.py asserts it is set and derives the
# package version from it.
echo 'RELEASE_VERSION=0.0.0 pip install -e . --no-build-isolation' > ./setup.sh
