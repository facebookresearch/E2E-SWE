// Command ctrf converts `go test -json` output into a CTRF report the WRG grader reads.
//
// Usage: ctrf <gotest-json-in> <ctrf-json-out> <reward-out>
//
// One top-level `func TestXxx` == one CTRF entry (the hidden suite uses no subtests). If the
// test binary fails to compile there are zero test events; in that case a synthetic BUILD entry
// is emitted so an empty report can never be scored as a pass. Standard library only.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// canonicalTotal must match [verifier].test_case_count in task.toml: the number of top-level
// `func TestXxx` in the hidden suite. Reward is 1 only when every one of them actually passed.
const canonicalTotal = 15

type event struct {
	Action  string  `json:"Action"`
	Test    string  `json:"Test"`
	Package string  `json:"Package"`
	Elapsed float64 `json:"Elapsed"`
	Output  string  `json:"Output"`
}

type ctrfTest struct {
	Name     string `json:"name"`
	Status   string `json:"status"`
	Duration int    `json:"duration"`
	Message  string `json:"message,omitempty"`
}

func main() {
	if len(os.Args) < 4 {
		fmt.Fprintln(os.Stderr, "usage: ctrf <gotest-json> <ctrf-out> <reward-out>")
		os.Exit(2)
	}
	inPath, outPath, rewardPath := os.Args[1], os.Args[2], os.Args[3]

	raw, err := os.ReadFile(inPath)
	if err != nil {
		raw = nil
	}

	type acc struct {
		status  string
		elapsed float64
		output  strings.Builder
	}
	order := []string{}
	tests := map[string]*acc{}
	var loose strings.Builder

	scanner := bufio.NewScanner(strings.NewReader(string(raw)))
	scanner.Buffer(make([]byte, 0, 1024*1024), 16*1024*1024)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(strings.TrimSpace(line), "{") {
			loose.WriteString(line)
			loose.WriteString("\n")
			continue
		}
		var e event
		if err := json.Unmarshal([]byte(line), &e); err != nil {
			loose.WriteString(line)
			loose.WriteString("\n")
			continue
		}
		if e.Test == "" {
			// Package-level event.
			if e.Action == "output" {
				loose.WriteString(e.Output)
			}
			continue
		}
		// Fold subtests (name contains '/') into their top-level parent.
		top := e.Test
		if i := strings.IndexByte(top, '/'); i >= 0 {
			top = top[:i]
		}
		a, ok := tests[top]
		if !ok {
			a = &acc{}
			tests[top] = a
			order = append(order, top)
		}
		switch e.Action {
		case "pass":
			if a.status != "failed" {
				a.status = "passed"
			}
			if e.Test == top {
				a.elapsed = e.Elapsed
			}
		case "fail":
			a.status = "failed"
			if e.Test == top {
				a.elapsed = e.Elapsed
			}
		case "skip":
			if a.status == "" {
				a.status = "skipped"
			}
		case "output":
			a.output.WriteString(e.Output)
		}
	}

	var out []ctrfTest
	passed, failed, skipped, other := 0, 0, 0, 0
	for _, name := range order {
		a := tests[name]
		status := a.status
		if status == "" {
			status = "failed"
		}
		entry := ctrfTest{Name: name, Status: status, Duration: int(a.elapsed * 1000)}
		if status == "failed" {
			msg := a.output.String()
			if len(msg) > 4000 {
				msg = msg[len(msg)-4000:]
			}
			entry.Message = msg
		}
		out = append(out, entry)
		switch status {
		case "passed":
			passed++
		case "failed":
			failed++
		case "skipped":
			skipped++
		default:
			other++
		}
	}

	if len(out) == 0 {
		msg := strings.TrimSpace(loose.String())
		if msg == "" {
			msg = "no go test -json events captured"
		}
		if len(msg) > 4000 {
			msg = msg[len(msg)-4000:]
		}
		out = append(out, ctrfTest{Name: "BUILD", Status: "failed", Duration: 0, Message: msg})
		failed++
	}

	report := map[string]any{
		"results": map[string]any{
			"tool": map[string]any{"name": "go-test"},
			"summary": map[string]any{
				"tests":   len(out),
				"passed":  passed,
				"failed":  failed,
				"skipped": skipped,
				"pending": 0,
				"other":   other,
				"start":   0,
				"stop":    0,
			},
			"tests": out,
		},
	}

	data, _ := json.MarshalIndent(report, "", "  ")
	_ = os.WriteFile(outPath, data, 0o644)

	reward := "0"
	if passed == canonicalTotal && failed == 0 && other == 0 && skipped == 0 {
		reward = "1"
	}
	_ = os.WriteFile(rewardPath, []byte(reward), 0o644)
}
