#!/bin/bash
# Offline C# grading for the Clipper2 task. No network — the per-task image bakes the .NET 8 SDK.
#
# The candidate produces the Clipper2Lib library as C# sources (namespace Clipper2Lib) anywhere under
# /app. The grader collects those sources, compiles them together with the hidden harness
# (ctrf_test.cs) and tests (test_clipper2.cs) into one console app whose entry point is forced to
# CtrfRunner.Main (via <StartupObject>, so a stray Main in the candidate's code is harmless), runs it,
# and the binary writes /logs/verifier/ctrf.json directly.
#
# No `set -e` — we capture build/run status and always emit a CTRF.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

bash ./setup.sh 2>/dev/null
mkdir -p /logs/verifier
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1

BUILD=/tmp/grade
rm -rf "$BUILD"; mkdir -p "$BUILD/src"

# Collect the candidate's Clipper2Lib sources: every .cs declaring `namespace Clipper2Lib`, robust to
# whatever directory layout the candidate chose. Skip build/test/example trees. Dedup by basename so a
# duplicated clone tree (two copies of the same files) compiles as ONE coherent set instead of failing
# with duplicate-type errors.
declare -A seen
while IFS= read -r f; do
  bn=$(basename "$f")
  [ -n "${seen[$bn]}" ] && continue
  seen[$bn]=1
  cp "$f" "$BUILD/src/$bn"
done < <(grep -rlE 'namespace[[:space:]]+Clipper2Lib' /app --include='*.cs' 2>/dev/null \
         | grep -ivE '/(bin|obj|tests?|examples?|benchmark|nuget)/')

# Hidden harness + tests.
cp /tests/ctrf_test.cs /tests/test_clipper2.cs "$BUILD/src/"

cat > "$BUILD/grade.csproj" <<'EOF'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>disable</Nullable>
    <ImplicitUsings>disable</ImplicitUsings>
    <StartupObject>CtrfRunner</StartupObject>
    <AssemblyName>grade</AssemblyName>
    <SignAssembly>false</SignAssembly>
    <TreatWarningsAsErrors>false</TreatWarningsAsErrors>
    <NoWarn>$(NoWarn);CS8632;CS0436</NoWarn>
  </PropertyGroup>
</Project>
EOF

cd "$BUILD"
dotnet build -c Release -o "$BUILD/out" grade.csproj > /logs/verifier/build.log 2>&1
BUILD_RC=$?

if [ $BUILD_RC -ne 0 ] || [ ! -f "$BUILD/out/grade.dll" ]; then
  printf '%s' '{"results":{"tool":{"name":"ctrf_test"},"summary":{"tests":1,"passed":0,"failed":1,"pending":0,"skipped":0,"other":0},"tests":[{"name":"BUILD","status":"failed","message":"compilation failed"}]}}' \
    > /logs/verifier/ctrf.json
  echo 0 > /logs/verifier/reward.txt
  exit 0
fi

CTRF_OUT=/logs/verifier/ctrf.json dotnet "$BUILD/out/grade.dll"
if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
