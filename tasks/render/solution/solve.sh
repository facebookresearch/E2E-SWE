#!/bin/bash
set -e

# Ground-truth builder for the render task. Runs in the GT flow's Container A (internet on); the
# grading Container B is offline. Clones the reference template engine (flosch/pongo2), wraps its
# stdlib-only library in the exact `render` CLI the task specifies, and builds /app/render — the same
# artifact the agent's own setup.sh must produce. The agent never sees this script or the reference.
git clone https://github.com/flosch/pongo2 /tmp/repo
cd /tmp/repo
git checkout v4.0.2

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# pongo2's engine is pure Go stdlib; its only go.mod requires are test-only (check.v1, pretty).
# Drop them so the build is fully offline with no module cache.
rm -f /app/go.sum
cat > /app/go.mod <<'GOMOD'
module github.com/flosch/pongo2/v4

go 1.14
GOMOD

# Inject the render CLI wrapper over the reference engine. This defines the exact I/O contract the
# hidden tests grade: `render <template-file>` reads a JSON context object from stdin and writes the
# rendered template to stdout. Integer-valued JSON numbers are passed to the template as integers.
mkdir -p /app/cmd/render
cat > /app/cmd/render/main.go <<'MAINGO'
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/flosch/pongo2/v4"
)

func normalize(v interface{}) interface{} {
	switch x := v.(type) {
	case json.Number:
		if i, err := x.Int64(); err == nil {
			return i
		}
		f, _ := x.Float64()
		return f
	case map[string]interface{}:
		for k, e := range x {
			x[k] = normalize(e)
		}
		return x
	case []interface{}:
		for i, e := range x {
			x[i] = normalize(e)
		}
		return x
	default:
		return v
	}
}

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: render <template-file>  (JSON context on stdin)")
		os.Exit(2)
	}
	tpl, err := pongo2.FromFile(os.Args[1])
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
	ctx := pongo2.Context{}
	data, _ := io.ReadAll(os.Stdin)
	if len(data) > 0 {
		dec := json.NewDecoder(bytes.NewReader(data))
		dec.UseNumber()
		var m map[string]interface{}
		if err := dec.Decode(&m); err != nil {
			fmt.Fprintf(os.Stderr, "error: bad JSON context: %v\n", err)
			os.Exit(2)
		}
		for k, v := range m {
			ctx[k] = normalize(v)
		}
	}
	out, err := tpl.Execute(ctx)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
	io.WriteString(os.Stdout, out)
}
MAINGO

# Offline build. Pure stdlib, single local module -> no network needed. Produces /app/render.
echo 'go build -o /app/render ./cmd/render' > ./setup.sh
