#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/edinburgh-genome-foundry/dnachisel.git /tmp/repo
cd /tmp/repo
git checkout 68c09304341c3656f3dfe63eda37757d6a7b3917

# cp -a carries .git too, but dnachisel uses a static version in pyproject.toml (no setuptools_scm),
# so the offline editable build does not depend on it.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the runtime deps + the setuptools build backend are
# pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked
# backend instead of trying to fetch an isolated build env (which would fail with no network). The
# [reports] extra is intentionally NOT installed — the tests do not exercise report generation, and
# its deps (pdf_reports, matplotlib, dna_features_viewer, ...) are not baked offline.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
