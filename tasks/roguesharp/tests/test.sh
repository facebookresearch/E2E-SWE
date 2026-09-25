#!/bin/bash

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

# Collect the candidate's sources into a flat build dir. Sort for deterministic traversal order and
# dedup by basename so a duplicated clone tree (two copies of the same file) compiles as ONE coherent
# set instead of silently dropping one copy in a find-order-dependent way.
declare -A seen
while IFS= read -r f; do
  bn=$(basename "$f")
  [ -n "${seen[$bn]}" ] && continue
  seen[$bn]=1
  cp "$f" "$BUILD/src/$bn"
done < <(find /app -name '*.cs' ! -path '*/bin/*' ! -path '*/obj/*' ! -path '*/test*/*' \
           ! -path '*/Test*/*' ! -path '*/examples/*' ! -path '*/benchmark/*' ! -path '*/nuget/*' \
           | sort)

cp /tests/ctrf_test.cs /tests/test_roguesharp.cs "$BUILD/src/"

cat > "$BUILD/grade.csproj" <<'EOF'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>disable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <StartupObject>CtrfRunner</StartupObject>
    <AssemblyName>grade</AssemblyName>
    <SignAssembly>false</SignAssembly>
    <TreatWarningsAsErrors>false</TreatWarningsAsErrors>
    <NoWarn>$(NoWarn);CS8632;CS0436</NoWarn>
  </PropertyGroup>
  <!-- Match the net8.0 default (ImplicitUsings=enable) that the spec's `dotnet build` uses, so
       idiomatic sources that omit explicit BCL usings compile. Drop only the implicit System.IO:
       RogueSharp has its own public `Path` type, and a global `using System.IO;` would make the
       unqualified `Path` in the test sources ambiguous with System.IO.Path (ctrf_test.cs keeps
       its own explicit `using System.IO;`). -->
  <ItemGroup>
    <Using Remove="System.IO" />
  </ItemGroup>
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
