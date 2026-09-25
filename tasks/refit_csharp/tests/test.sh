#!/bin/bash
# Offline grading for the refit (C#/.NET) task. Everything (.NET 10 SDK, NuGet feed, pytest) is
# pre-baked in the per-task image; there is NO network. No `set -e` — the reward logic captures the
# pytest exit code.
#
# The harness is split into independent per-aspect group projects under tests/harness/groups/. Each is
# built on its own so that if the solution under test can't implement one aspect (a missing public type
# or a broken generated class for one interface), only THAT group fails to compile — the other groups
# still grade. This preserves a fractional f2p signal instead of cascading the whole suite to zero.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

export DOTNET_ROOT=/opt/dotnet
export PATH=/opt/dotnet:$PATH
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1

# 1. Build the solution under test (agent's, or GT's) into /app/dist/{lib,analyzers}. setup.sh was
#    written by the agent (or by solve.sh for GT eval) and builds OFFLINE against the baked feed.
#    Run it in a SUBSHELL (not `source`): agents routinely start their setup.sh with `set -e`, and if
#    sourced that leaks into this script so the FIRST later non-zero command (e.g. a harness group that
#    the solution can't compile) would abort grading before pytest runs -> no CTRF -> grading_error.
#    Executing in a subshell contains `set -e`/`exit`/`cd`; test.sh sets DOTNET_ROOT/PATH itself and
#    uses absolute paths, so nothing here depends on env leaking out of setup.sh.
bash ./setup.sh
set +e  # belt-and-suspenders: a group build failure must never abort grading before pytest

# 2. Build each harness group independently. A group links the shared code (_shared/*.cs) plus its own
#    interfaces+scenarios file, references /app/dist/lib and loads /app/dist/analyzers as analyzers.
HARNESS=/tests/harness
SHARED="$HARNESS/_shared"
BUILDROOT=/tmp/harness-build
MANIFEST=/tmp/harness_manifest.txt
rm -rf "$BUILDROOT"; mkdir -p "$BUILDROOT"
: > "$MANIFEST"

for g in "$HARNESS"/groups/*.cs; do
  name=$(basename "$g" .cs)
  proj="$BUILDROOT/$name"
  mkdir -p "$proj"
  cat > "$proj/$name.csproj" <<EOF
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net10.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <LangVersion>latest</LangVersion>
    <AssemblyName>Harness</AssemblyName>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
    <NoWarn>\$(NoWarn);IL2026;IL3050;CS1591;RF001</NoWarn>
  </PropertyGroup>
  <ItemGroup>
    <Compile Include="$SHARED/*.cs" />
    <Compile Include="$g" />
    <Reference Include="/app/dist/lib/*.dll" Private="true" />
    <Analyzer Include="/app/dist/analyzers/*.dll" />
  </ItemGroup>
</Project>
EOF
  echo "=== building harness group: $name ==="
  dotnet build "$proj/$name.csproj" -c Release -p:RestoreConfigFile=/opt/nuget/NuGet.Config -m:1 -v:minimal
  dll="$proj/bin/Release/net10.0/Harness.dll"
  if [ -f "$dll" ]; then
    for sc in $(dotnet "$dll" --list 2>/dev/null); do
      printf '%s\t%s\n' "$sc" "$dll" >> "$MANIFEST"
    done
  else
    echo "GROUP BUILD FAILED (its tests will fail, others still grade): $name" >&2
  fi
done
export HARNESS_MANIFEST="$MANIFEST"

# 3. Run the suite. Each test looks its scenario up in the manifest and invokes that group's harness;
#    a scenario whose group failed to build fails only its own test(s).
pytest --ctrf /logs/verifier/ctrf.json /tests/test_refit.py -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
