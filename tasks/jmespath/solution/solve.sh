#!/bin/bash
set -e

# Ground-truth setup for the jmespath (Go) task. Runs in Container A (internet ON) only; the grading
# Container B is offline and builds from /app with GOPROXY=off.
#
# The reference JMESPath engine is jmespath/go-jmespath (pure standard library). We build the CLI by
# cloning that repo at the pinned release, injecting a small `cmd/jp` main package that wires the
# engine to the documented CLI contract, and stripping the test-only dependency so the build needs no
# module proxy or vendored modules (CASE A, pure stdlib).

git clone https://github.com/jmespath/go-jmespath.git /tmp/repo   # git is pre-baked in the image
cd /tmp/repo
git checkout v0.4.0                # immutable release tag; go.sum pins the content hash

# Inject the CLI entry point. It imports the engine from the same module (github.com/jmespath/
# go-jmespath), so no external modules are required at build time.
mkdir -p cmd/jp
cat > cmd/jp/main.go <<'GOEOF'
package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/jmespath/go-jmespath"
)

func errMsg(format string, a ...interface{}) int {
	fmt.Fprintf(os.Stderr, format, a...)
	fmt.Fprintln(os.Stderr)
	return 1
}

func main() { os.Exit(run()) }

func run() int {
	compact := false
	unquoted := false
	filename := ""
	var positional []string
	rest := os.Args[1:]
	for i := 0; i < len(rest); i++ {
		switch rest[i] {
		case "-c", "--compact":
			compact = true
		case "-u", "--unquoted":
			unquoted = true
		case "-f", "--filename":
			i++
			if i >= len(rest) {
				return errMsg("Missing value for -f")
			}
			filename = rest[i]
		default:
			positional = append(positional, rest[i])
		}
	}
	if len(positional) == 0 {
		return errMsg("Must provide at least one argument.")
	}
	expression := positional[0]

	var input interface{}
	var dec *json.Decoder
	if filename != "" {
		f, err := os.Open(filename)
		if err != nil {
			return errMsg("Error opening input file: %s", err)
		}
		dec = json.NewDecoder(f)
	} else {
		dec = json.NewDecoder(os.Stdin)
	}
	if err := dec.Decode(&input); err != nil {
		fmt.Fprintf(os.Stderr, "Error parsing input json: %s\n", err)
		return 2
	}

	result, err := jmespath.Search(expression, input)
	if err != nil {
		return errMsg("Error evaluating JMESPath expression: %s", err)
	}

	s, isString := result.(string)
	if unquoted && isString {
		os.Stdout.WriteString(s)
	} else {
		var out []byte
		if compact {
			out, err = json.Marshal(result)
		} else {
			out, err = json.MarshalIndent(result, "", "  ")
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error marshalling result to JSON: %s\n", err)
			return 3
		}
		os.Stdout.Write(out)
	}
	os.Stdout.WriteString("\n")
	return 0
}
GOEOF

# Strip the test-only dependency (internal/testify) and its go.mod require + go.sum, so the offline
# build pulls nothing. The CLI binary does not use any test code.
find . -name '*_test.go' -delete
sed -i '/internal\/testify/d' go.mod
rm -f go.sum

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# Offline build — exactly the artifact the agent must produce at /app/jp (the agent, using only the
# standard library, writes its own equivalent build command).
echo 'go build -o /app/jp ./cmd/jp' > ./setup.sh
