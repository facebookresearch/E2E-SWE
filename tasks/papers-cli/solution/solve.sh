#!/bin/bash
set -e

git clone https://github.com/perrette/papers.git /tmp/repo
cd /tmp/repo
git checkout 0b21c3b3e97a65fb6633365d2e184766623ea90a

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# The repomate base image ships an empty /app/repo dir. papers uses setuptools flat-layout
# auto-discovery, so a stray top-level dir beside the `papers` package makes the editable build
# abort ("Multiple top-level packages discovered in a flat-layout"). The real repo has no such
# dir, so removing it is faithful to groundtruth and keeps the offline install single-package.
rm -rf /app/repo

# Honour PAPERS_CROSSREF_API as the crossref base URL (required by tests; spec
# documents the env var as a fairness-preserving testability hook).
python3 - <<'PY'
import io, re
path = 'papers/extract.py'
text = open(path).read()
old = 'def fetch_crossref_by_doi(doi):\n    url = "http://api.crossref.org/works/"+doi'
new = ('def fetch_crossref_by_doi(doi):\n'
       '    base = os.environ.get("PAPERS_CROSSREF_API", "http://api.crossref.org").rstrip("/")\n'
       '    url = base + "/works/" + doi')
assert old in text, "expected substring not found in extract.py (groundtruth drift?)"
open(path, 'w').write(text.replace(old, new))
PY

# setup.sh installs the project offline: runtime deps + the build backend (setuptools +
# setuptools_scm) are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED
# so pip uses the baked backend instead of fetching an isolated build env (which would fail
# offline). The `cp -a` above carried /app/.git, so setuptools_scm resolves the dynamic version
# offline. test.sh runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
