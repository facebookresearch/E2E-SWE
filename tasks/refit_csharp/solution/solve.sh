#!/bin/bash
set -e

# Ground-truth setup for the (de-branded) type-safe REST client WRG task.
#
# The reference implementation IS the real refit source, but RENAMED to a neutral brand ("Restly") so
# nothing in the graded surface reveals the upstream library. This script (Container A, internet ON)
# clones the source at a pinned commit, de-brands it (Refit -> Restly, RestService -> RestlyClient),
# writes minimal single-TFM csprojs over that source, and writes /app/setup.sh which builds them
# OFFLINE (Container B) into the deliverable layout the hidden test harness references:
#     /app/dist/lib/*.dll        <- runtime assemblies (referenced by the harness)
#     /app/dist/analyzers/*.dll  <- Roslyn source generator (loaded as an analyzer by the harness)
#
# We do NOT build the repo's own multi-target csprojs: they target net8/9/10/11 at once, which no
# single SDK can build. The minimal csprojs pin a single net10.0 (runtime) / netstandard2.0 (generator)
# and pull only the real external deps (ReactiveUI.Primitives; Microsoft.CodeAnalysis.CSharp).

REPO_URL="https://github.com/reactiveui/refit.git"
COMMIT="71634f2c5d0845c311b1cf4f4bb512437fe86fb5"   # tag v14.0.0-beta.2

git clone "$REPO_URL" /tmp/repo
cd /tmp/repo
git checkout "$COMMIT"

mkdir -p /app/refit-src
cp -a /tmp/repo/src /app/refit-src/src
rm -rf /tmp/repo

# De-brand: rename the library identity across the compiled source. "RestService" -> "RestlyClient"
# first (no "Refit" substring), then every "Refit" token -> "Restly" (covers the namespace,
# RefitSettings -> RestlySettings, the RefitLegacy enum member, and the "Refit.MethodName"/… option-key
# string literals the generator emits). Only the compiled directories are touched.
for d in Refit Refit.Reflection InterfaceStubGenerator.Shared Shared Polyfills; do
  find "/app/refit-src/src/$d" -name '*.cs' -type f -print0 2>/dev/null \
    | xargs -0 -r sed -i -e 's/\bRestService\b/RestlyClient/g' -e 's/Refit/Restly/g'
done

mkdir -p /app/build/Refit /app/build/Refit.Reflection /app/build/Generator

# --- runtime core (net10.0) -> Restly.dll ---
cat > /app/build/Refit/Refit.csproj <<'CSPROJ'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <AssemblyName>Restly</AssemblyName>
    <RootNamespace>Restly</RootNamespace>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <LangVersion>latest</LangVersion>
    <GenerateDocumentationFile>false</GenerateDocumentationFile>
    <EnableNETAnalyzers>false</EnableNETAnalyzers>
    <Deterministic>true</Deterministic>
    <NoWarn>$(NoWarn);CS1591</NoWarn>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
    <DisableRuntimeMarshalling>true</DisableRuntimeMarshalling>
  </PropertyGroup>
  <ItemGroup>
    <Compile Include="/app/refit-src/src/Refit/**/*.cs" />
    <Compile Include="/app/refit-src/src/Shared/UniqueName.cs" />
    <Compile Include="/app/refit-src/src/Shared/HttpContentExtensions.cs" />
    <Compile Include="/app/refit-src/src/Shared/AuthenticatedHttpClientHandler.cs" />
  </ItemGroup>
  <ItemGroup>
    <Using Include="System.ArgumentNullException" Alias="ArgumentExceptionHelper" />
    <Using Include="System.ArgumentOutOfRangeException" Alias="ArgumentOutOfRangeExceptionHelper" />
    <Using Include="System.Threading.Lock" Alias="Lock" />
  </ItemGroup>
  <ItemGroup>
    <PackageReference Include="ReactiveUI.Primitives" Version="6.0.0" />
  </ItemGroup>
  <ItemGroup>
    <InternalsVisibleTo Include="Restly.Reflection" />
  </ItemGroup>
</Project>
CSPROJ

# --- reflection request builder (net10.0) -> Restly.Reflection.dll ---
cat > /app/build/Refit.Reflection/Refit.Reflection.csproj <<'CSPROJ'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <AssemblyName>Restly.Reflection</AssemblyName>
    <RootNamespace>Restly</RootNamespace>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <LangVersion>latest</LangVersion>
    <GenerateDocumentationFile>false</GenerateDocumentationFile>
    <EnableNETAnalyzers>false</EnableNETAnalyzers>
    <Deterministic>true</Deterministic>
    <NoWarn>$(NoWarn);CS1591</NoWarn>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
    <DisableRuntimeMarshalling>true</DisableRuntimeMarshalling>
  </PropertyGroup>
  <ItemGroup>
    <Compile Include="/app/refit-src/src/Refit.Reflection/**/*.cs" />
  </ItemGroup>
  <ItemGroup>
    <Using Include="System.ArgumentNullException" Alias="ArgumentExceptionHelper" />
    <Using Include="System.ArgumentOutOfRangeException" Alias="ArgumentOutOfRangeExceptionHelper" />
    <Using Include="System.Threading.Lock" Alias="Lock" />
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="../Refit/Refit.csproj" />
  </ItemGroup>
</Project>
CSPROJ

# --- source generator (netstandard2.0, Roslyn 5.0) -> RestlyGenerator.dll ---
cat > /app/build/Generator/Refit.Generator.csproj <<'CSPROJ'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.0</TargetFramework>
    <AssemblyName>RestlyGenerator</AssemblyName>
    <RootNamespace>Restly.Generator</RootNamespace>
    <IsRoslynComponent>true</IsRoslynComponent>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <LangVersion>latest</LangVersion>
    <DefineConstants>$(DefineConstants);ROSLYN_4;ROSLYN_5</DefineConstants>
    <EnableNETAnalyzers>false</EnableNETAnalyzers>
    <EnforceExtendedAnalyzerRules>true</EnforceExtendedAnalyzerRules>
    <GenerateDocumentationFile>false</GenerateDocumentationFile>
    <IsPackable>false</IsPackable>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
    <NoWarn>$(NoWarn);CS1591;RS1041</NoWarn>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.CodeAnalysis.CSharp" Version="5.0.0" PrivateAssets="all" />
    <PackageReference Include="Microsoft.CodeAnalysis.Analyzers" Version="5.6.0" PrivateAssets="all" />
  </ItemGroup>
  <ItemGroup>
    <Compile Include="/app/refit-src/src/InterfaceStubGenerator.Shared/**/*.cs" />
    <Compile Include="/app/refit-src/src/Polyfills/ArgumentExceptionHelper.cs" />
    <Compile Include="/app/refit-src/src/Polyfills/ArgumentOutOfRangeExceptionHelper.cs" />
    <Compile Include="/app/refit-src/src/Polyfills/CallerArgumentExpressionAttribute.cs" />
    <Compile Include="/app/refit-src/src/Polyfills/NotNullAttribute.cs" />
  </ItemGroup>
  <ItemGroup>
    <Using Include="Restly.Internal.ArgumentExceptionHelper" Alias="ArgumentExceptionHelper" />
    <Using Include="Restly.Internal.ArgumentOutOfRangeExceptionHelper" Alias="ArgumentOutOfRangeExceptionHelper" />
  </ItemGroup>
</Project>
CSPROJ

# setup.sh: builds the reference implementation OFFLINE into /app/dist/{lib,analyzers}. It is executed
# in a subshell by test.sh in the offline grading container (so a `set -e` here can't abort grading).
cat > /app/setup.sh <<'SETUP'
export DOTNET_ROOT=/opt/dotnet
export PATH=/opt/dotnet:$PATH
NUGET_CFG=/opt/nuget/NuGet.Config
rm -rf /app/dist
mkdir -p /app/dist/lib /app/dist/analyzers
dotnet build /app/build/Refit.Reflection/Refit.Reflection.csproj -c Release \
    -p:RestoreConfigFile="$NUGET_CFG" -m:1 -v:minimal
dotnet build /app/build/Generator/Refit.Generator.csproj -c Release \
    -p:RestoreConfigFile="$NUGET_CFG" -m:1 -v:minimal
cp /app/build/Refit/bin/Release/net10.0/Restly.dll /app/dist/lib/
cp /app/build/Refit.Reflection/bin/Release/net10.0/Restly.Reflection.dll /app/dist/lib/
cp /app/build/Generator/bin/Release/netstandard2.0/RestlyGenerator.dll /app/dist/analyzers/
SETUP
chmod +x /app/setup.sh
