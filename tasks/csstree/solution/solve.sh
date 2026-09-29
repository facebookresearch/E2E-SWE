#!/bin/bash
set -e

# Ground-truth setup for the `stylesheet-tree` task (JavaScript, aliased from the upstream
# css-tree / csstree library). This is the ONLY network operation in the GT flow (GT eval keeps
# internet on for it); test.sh runs fully offline. Pin to the exact release commit (v3.2.1) for
# reproducibility.
git clone https://github.com/csstree/csstree.git /tmp/repo
cd /tmp/repo
git checkout 8a6caba481be4cae4b0e8690af643ff8e59271f2

# The library is pure ESM ("type": "module"). Only the library source is in scope:
#   - lib/                     the whole implementation (parser/generator/walker/lexer/tokenizer/…)
#   - data/patch.json          csstree-authored CSS syntax patch dictionary the lexer reads at load
#                              (lib/data-patch.js does `require('../data/patch.json')`)
# The repo's own test/, fixtures/, docs/, scripts/, dist/, cjs/ and build config are NOT part of
# the graded surface and are not copied — the agent implements the library, not the repo tooling.
mkdir -p /app/src
cp -a /tmp/repo/lib/. /app/src/
cp -a /tmp/repo/data /app/data

# --- Anti-contamination: deep identifier aliasing (README §2.4) ---
# The upstream library is prominent enough that a package-name alias alone does NOT stop a model
# reproducing its internals from memory by name (verified: a first eval reproduced the reference
# near-verbatim, incl. byte-identical core files). To force the agent to IMPLEMENT rather than
# RECALL, rename the recognizable CSS-AST node-type vocabulary to neutral synonyms, consistently
# across (a) this ground-truth source, (b) the hidden tests, and (c) instruction.md. csstree keys
# every node type by the same identifier everywhere (the `type:` string, the module export name,
# `structure` cross-references, parseContext/walkContext values, and the physical filename), so a
# whole-word rename plus a matching filename rename keeps the engine internally consistent while
# defeating by-name recall. The renamed names collide with no JS built-in or tokenizer token type.
# Node types NOT renamed (e.g. Value, Block, Rule, Identifier, Hash, Dimension, Raw, and the
# definition-syntax internal types) either collide with token types / built-ins or are generic
# enough that recall of them alone does not reconstruct the library.
RENAME_SED=/tmp/rename.sed
cat > "$RENAME_SED" <<'SED'
s/\bPseudoElementSelector\b/PseudoElemMatch/g
s/\bPseudoClassSelector\b/PseudoClassMatch/g
s/\bAttributeSelector\b/AttrMatch/g
s/\bDeclarationList\b/DeclSet/g
s/\bClassSelector\b/ClassMatch/g
s/\bAtrulePrelude\b/AtruleHead/g
s/\bTypeSelector\b/TypeMatch/g
s/\bSelectorList\b/MatchGroup/g
s/\bDeclaration\b/Decl/g
s/\bStyleSheet\b/Rootsheet/g
s/\bIdSelector\b/IdMatch/g
s/\bCombinator\b/Joiner/g
s/\bSelector\b/MatchSeq/g
SED
# 1. rename file CONTENTS across the whole source tree
find /app/src -name '*.js' -exec sed -i -f "$RENAME_SED" {} +
# 2. rename the physical node module files whose basename is a renamed type
cd /app/src/syntax/node
for pair in 'StyleSheet:Rootsheet' 'ClassSelector:ClassMatch' 'IdSelector:IdMatch' \
            'TypeSelector:TypeMatch' 'AttributeSelector:AttrMatch' \
            'PseudoClassSelector:PseudoClassMatch' 'PseudoElementSelector:PseudoElemMatch' \
            'SelectorList:MatchGroup' 'Selector:MatchSeq' 'Combinator:Joiner' \
            'Declaration:Decl' 'DeclarationList:DeclSet' 'AtrulePrelude:AtruleHead'; do
  old="${pair%%:*}"; new="${pair##*:}"
  [ -f "$old.js" ] && mv "$old.js" "$new.js"
done
cd /app

# --- Anti-contamination: neutralize the upstream identity ---
# The hidden tests import the library under the aliased package name `stylesheet-tree` and
# instruction.md never mentions csstree / css-tree / mdn. The only place the real name survives a
# source copy is the version string that lib/version.js reads from ../package.json, so write a
# minimal, name-neutral package.json at /app that (a) marks the tree as ESM and (b) exposes the
# same version value the reference returns, without leaking the origin.
cat > /app/package.json <<'PKG'
{
  "name": "stylesheet-tree",
  "version": "3.2.1",
  "type": "module",
  "main": "./src/index.js"
}
PKG

cd /app
rm -rf /tmp/repo /app/.git

# setup.sh builds the project OFFLINE — exactly what the agent is expected to produce. The library
# is native ESM and runs on the image's Node 20 with NO transpile step; it imports two THIRD-PARTY
# runtime deps by bare specifier (`mdn-data` for the lexer dictionaries and `source-map-js` for
# generate({sourceMap:true})). Those are pre-installed in the image at /opt/deps/node_modules and
# are NOT reimplemented. ESM bare-specifier resolution ignores NODE_PATH and only walks up the
# directory tree for node_modules, so setup.sh links the baked deps in as /app/node_modules. The
# package entry point is /app/src/index.js. test.sh runs `bash ./setup.sh` in the (offline) grading
# container, then runs the hidden Node test drivers, which import the built package as
# `stylesheet-tree` (mapped to /app/src/index.js) and reach the baked deps via /app/node_modules.
cat > ./setup.sh <<'SETUP'
#!/bin/bash
set -e
DEPS_DIR="${DEPS_DIR:-/opt/deps/node_modules}"
# Link the pre-baked runtime deps into the project so ESM bare-specifier resolution
# (`import 'mdn-data/...'`, `import 'source-map-js/...'`) finds them. Copy as a fallback if the
# symlink target is unavailable.
rm -rf node_modules
if [ -d "$DEPS_DIR" ]; then
  ln -sfn "$DEPS_DIR" ./node_modules
else
  echo "WARNING: baked deps not found at $DEPS_DIR" >&2
fi
SETUP
chmod +x ./setup.sh
