// Command ctrf converts `go test -json` output into a CTRF report for the WRG grader.
//
// Usage: ctrf <go-test-json-file> <ctrf-output-path>
//
// Only top-level tests (no "/" in the name, i.e. not subtests) become CTRF entries,
// so one `func TestXxx` == one CTRF entry. A build failure yields zero tests -> reward 0.
//
// Go-native and standard-library-only, so the offline grading harness needs no Python
// (or any other) runtime beyond the Go toolchain already baked into the per-task image.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// event is one line of `go test -json` output. Package-level events omit "Test".
type event struct {
	Action  string  `json:"Action"`
	Test    string  `json:"Test"`
	Elapsed float64 `json:"Elapsed"`
}

// ctrfTest is a single CTRF test entry. Field order is fixed by the struct so the
// emitted JSON is stable across runs.
type ctrfTest struct {
	Name     string `json:"name"`
	Status   string `json:"status"`
	Duration int    `json:"duration"`
}

type ctrfSummary struct {
	Tests   int `json:"tests"`
	Passed  int `json:"passed"`
	Failed  int `json:"failed"`
	Skipped int `json:"skipped"`
	Pending int `json:"pending"`
	Other   int `json:"other"`
	Start   int `json:"start"`
	Stop    int `json:"stop"`
}

type ctrfTool struct {
	Name string `json:"name"`
}

type ctrfResults struct {
	Tool    ctrfTool    `json:"tool"`
	Summary ctrfSummary `json:"summary"`
	Tests   []ctrfTest  `json:"tests"`
}

type ctrfReport struct {
	Results ctrfResults `json:"results"`
}

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: ctrf <go-test-json-file> <ctrf-output-path>")
		os.Exit(2)
	}
	inPath, outPath := os.Args[1], os.Args[2]

	f, err := os.Open(inPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "open %s: %v\n", inPath, err)
		os.Exit(1)
	}
	defer f.Close()

	byName := map[string]*ctrfTest{}
	var order []string

	sc := bufio.NewScanner(f)
	// go test -json can emit long lines (captured build output); grow the buffer.
	sc.Buffer(make([]byte, 0, 1024*1024), 16*1024*1024)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		var e event
		if err := json.Unmarshal([]byte(line), &e); err != nil {
			continue // non-JSON lines (e.g. raw build output) are ignored
		}
		if e.Test == "" || strings.Contains(e.Test, "/") {
			continue // top-level tests only (skip subtests)
		}
		t, ok := byName[e.Test]
		if !ok {
			t = &ctrfTest{Name: e.Test, Status: "pending", Duration: 0}
			byName[e.Test] = t
			order = append(order, e.Test)
		}
		switch e.Action {
		case "pass":
			t.Status, t.Duration = "passed", int(e.Elapsed*1000)
		case "fail":
			t.Status, t.Duration = "failed", int(e.Elapsed*1000)
		case "skip":
			t.Status, t.Duration = "skipped", int(e.Elapsed*1000)
		}
	}
	if err := sc.Err(); err != nil {
		fmt.Fprintf(os.Stderr, "read %s: %v\n", inPath, err)
		os.Exit(1)
	}

	report := ctrfReport{Results: ctrfResults{Tool: ctrfTool{Name: "go-test"}}}
	for _, n := range order {
		t := byName[n]
		report.Results.Tests = append(report.Results.Tests, *t)
		switch t.Status {
		case "passed":
			report.Results.Summary.Passed++
		case "failed":
			report.Results.Summary.Failed++
		case "skipped":
			report.Results.Summary.Skipped++
		}
	}
	report.Results.Summary.Tests = len(report.Results.Tests)

	if dir := filepath.Dir(outPath); dir != "" {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			fmt.Fprintf(os.Stderr, "mkdir %s: %v\n", dir, err)
			os.Exit(1)
		}
	}
	of, err := os.Create(outPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "create %s: %v\n", outPath, err)
		os.Exit(1)
	}
	defer of.Close()
	enc := json.NewEncoder(of)
	enc.SetIndent("", "  ")
	if err := enc.Encode(report); err != nil {
		fmt.Fprintf(os.Stderr, "write %s: %v\n", outPath, err)
		os.Exit(1)
	}

	s := report.Results.Summary
	fmt.Printf("go-test -> %d/%d passed (%d failed, %d skipped)\n", s.Passed, s.Tests, s.Failed, s.Skipped)
}
