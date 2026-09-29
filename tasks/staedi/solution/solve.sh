#!/bin/bash
set -e

# Ground-truth solution for the staedi task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON for this one clone (git is pre-baked in the image). It places
# the REFERENCE StAEDI source as the agent's deliverable, applies the anti-contamination package
# ALIAS in-container, and writes the offline build script.

git clone https://github.com/xlate/staedi.git /tmp/repo
cd /tmp/repo
git checkout 019c8051fe60b1fab4380684d163f878ce173afa   # pinned (v1.26.3) for reproducibility

# The agent's deliverable = the entire StAEDI library source (all packages under io/ediflow after
# aliasing). Only src/main/java is taken; src/main/java9/module-info.java is intentionally excluded
# (the offline build is a plain classpath javac, not a module build). The .xsd grammar files are NOT
# read at runtime (schema loading is pure StAX), so no resources are needed for the tested surface.
mkdir -p /app/src
cp -a /tmp/repo/src/main/java/. /app/src/

# --- ANTI-CONTAMINATION ALIAS (io.xlate.edi -> io.ediflow) ---
# The real library package is memorized by the model; the agent only ever sees instruction.md (which
# uses io.ediflow), never this source. Rename the package everywhere it appears: package/import/FQN
# and class-name string literals (1), classloader resource-path literals (2), and the EDISchema XML
# namespace URIs the schema reader dispatches on (3, xlate.io -> ediflow.io); then move the package
# directory (4). The hidden test harness imports io.ediflow.* and authors schemas in the
# http://ediflow.io/EDISchema/vN namespace, matching the rewritten constants.
cd /app/src
grep -rlZ 'io\.xlate\.edi'      . | xargs -0 -r sed -i 's/io\.xlate\.edi/io.ediflow/g'
grep -rlZ 'io/xlate/edi'        . | xargs -0 -r sed -i 's#io/xlate/edi#io/ediflow#g'
grep -rlZ 'xlate\.io/EDISchema' . | xargs -0 -r sed -i 's#xlate\.io/EDISchema#ediflow.io/EDISchema#g'
mkdir -p io/ediflow && mv io/xlate/edi/* io/ediflow/ && rm -rf io/xlate

cd /app
rm -rf /tmp/repo

# setup.sh builds the whole library OFFLINE against the baked jars -- exactly what the agent must
# produce. StAEDI uses no annotation processors, so no -processorpath is needed. No `set -e` here so
# a compile failure cannot abort the (no-set-e) test.sh that sources it.
cat > /app/setup.sh <<'EOF'
LIB=/opt/staedi/lib
CP=$(ls $LIB/*.jar | paste -sd:)
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -cp "$CP" -d /app/out
EOF
