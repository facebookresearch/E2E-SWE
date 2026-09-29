#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on for it). Pin the exact commit for
# reproducibility.
git clone https://github.com/GitTools/GitVersion.git /tmp/repo
cd /tmp/repo
git checkout 73e858394b84bd67b6d44d58723a57a95cb01ce4

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh publishes the CLI offline, then copies the produced native launcher to the fixed contract
# path /app/dist/gitv (the tests invoke `/app/dist/gitv <args>`). Copying the apphost is robust: it
# locates its own gitversion.dll in the same directory regardless of the launcher's filename, so no
# assembly renaming is needed. Restore + build are fully offline (the image bakes the .NET 10 SDK and
# a local NuGet feed).
cat > ./setup.sh <<'EOF'
dotnet publish src/GitVersion.App/GitVersion.App.csproj -c Release -f net10.0 -o /app/dist
cp /app/dist/gitversion /app/dist/gitv
EOF
