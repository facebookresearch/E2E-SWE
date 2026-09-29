// Package mindwalkgrading is the hidden black-box e2e suite for the mindwalk Go
// task. It builds the agent's compiled `mindwalk` binary (path in MINDWALK_BIN)
// and drives it through the three in-scope CLI commands — build, trace, analyze —
// asserting exact values on the emitted JSON and validating each artifact against
// the bundled JSON Schemas. It never imports the agent's packages.
//
// One top-level func TestXxx == one CTRF entry (no subtests, no t.Skip).
package mindwalkgrading

import (
	"bytes"
	"encoding/json"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime/debug"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// ---------------------------------------------------------------------------
// Harness helpers
// ---------------------------------------------------------------------------

// failOnPanic converts any panic raised while a test runs into an isolated
// failure of THAT test, instead of letting the panic crash the whole `go test`
// binary and take every downstream test down with it (a measurement/fairness
// bug: one missing feature would otherwise register as a multi-test loss). It
// does not weaken any assertion — a test that expected data and got empty still
// fails; it just fails alone, with an explicit diagnostic, rather than aborting
// the suite. (t.Fatalf/t.FailNow use runtime.Goexit, not panic, so this recover
// never masks a normal assertion failure.) Deferred as the first statement of
// every TestXxx.
func failOnPanic(t *testing.T) {
	t.Helper()
	if r := recover(); r != nil {
		t.Errorf("test panicked on malformed/empty agent output (isolated to this test, suite not aborted): %v\n%s", r, debug.Stack())
	}
}

func mindwalkBin() string {
	if bin := os.Getenv("MINDWALK_BIN"); bin != "" {
		return bin
	}
	return "mindwalk"
}

// runMindwalk executes the binary with an isolated HOME (so the judge report
// cache and workdir never leak across tests) and returns stdout, stderr and the
// process exit code.
func runMindwalk(t *testing.T, home string, args ...string) (string, string, int) {
	t.Helper()
	cmd := exec.Command(mindwalkBin(), args...)
	cmd.Env = append(os.Environ(), "HOME="+home)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	code := 0
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			code = ee.ExitCode()
		} else {
			t.Fatalf("running mindwalk %v: %v (stderr: %s)", args, err, stderr.String())
		}
	}
	return stdout.String(), stderr.String(), code
}

// validateSchema validates raw JSON against a bundled schema (path relative to
// the /tests working directory).
func validateSchema(t *testing.T, schemaRel string, raw []byte) {
	t.Helper()
	var value any
	if err := json.Unmarshal(raw, &value); err != nil {
		t.Fatalf("emitted JSON is not valid JSON: %v\n%s", err, raw)
	}
	compiler := jsonschema.NewCompiler()
	schema, err := compiler.Compile(schemaRel)
	if err != nil {
		t.Fatalf("compiling schema %s: %v", schemaRel, err)
	}
	if err := schema.Validate(value); err != nil {
		t.Fatalf("JSON violates %s: %v\n%s", schemaRel, err, raw)
	}
}

func writeRepoFile(t *testing.T, root, rel, content string) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func gitInit(t *testing.T, root string) {
	t.Helper()
	git(t, root, "init", "-q")
}

func git(t *testing.T, root string, args ...string) {
	t.Helper()
	base := []string{
		"-c", "user.email=t@example.com",
		"-c", "user.name=Test",
		"-c", "commit.gpgsign=false",
		"-c", "init.defaultBranch=main",
		"-C", root,
	}
	cmd := exec.Command("git", append(base, args...)...)
	cmd.Env = append(os.Environ(), "HOME="+root, "GIT_CONFIG_NOSYSTEM=1")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
}

func writeJSONL(t *testing.T, path string, lines ...any) {
	t.Helper()
	var b strings.Builder
	for _, line := range lines {
		switch v := line.(type) {
		case string:
			b.WriteString(v)
		default:
			data, err := json.Marshal(v)
			if err != nil {
				t.Fatal(err)
			}
			b.Write(data)
		}
		b.WriteByte('\n')
	}
	if err := os.WriteFile(path, []byte(b.String()), 0o644); err != nil {
		t.Fatal(err)
	}
}

func quoteJSON(t *testing.T, v any) string {
	t.Helper()
	data, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

// ---------------------------------------------------------------------------
// Black-box JSON structs (independent of the agent's package layout). Go's
// case-insensitive field matching lets these omit most json tags.
// ---------------------------------------------------------------------------

type rect struct{ X, Z, W, D float64 }

type cityFile struct {
	ID    int
	Path  string
	Dir   string
	Lines int
	Bytes int64
	Lang  string
	Rect  rect
	Ghost bool
}

type cityDir struct {
	Path      string
	Depth     int
	Rect      rect
	FileCount int
	Lines     int
}

type cityMap struct {
	Version int
	Repo    struct {
		Root        string
		Commit      string
		Dirty       bool
		GeneratedAt string
	}
	Files  []cityFile
	Dirs   []cityDir
	Layout struct {
		Algorithm string
		Weight    string
	}
}

type target struct {
	Path  string
	Touch string
	Lines [][2]int
	Weak  bool
}

type outsideTouch struct {
	Scope string
	Path  string
}

type actionCounts struct {
	Search, Read, Edit, Exec, Verify, Other int
}

type traceEvent struct {
	Seq         int
	Tool        string
	Action      string
	Targets     []target
	Outside     []outsideTouch
	ResultBytes int
	IsError     bool
	Summary     string
}

type traceMark struct {
	Seq  int
	Type string
	Note string
}

type traceStats struct {
	FilesInRepo           int
	Fovea                 int
	Parafovea             int
	Edited                int
	EventsBeforeFirstEdit int
	RegressionRate        float64
	ErrorRate             float64
	Actions               actionCounts
	Errors                actionCounts
	MaxEditsPerFile       int
	ChurnFiles            int
	UserTurns             int
	Compactions           int
	Subagents             int
	ResultBytes           int64
	EditsAfterLastVerify  int
	Observability         struct {
		Reads  string
		Errors string
	}
}

type traceDoc struct {
	Version int
	Session struct {
		ID         string
		Harness    string
		Model      string
		Title      string
		Cwd        string
		Commit     string
		EventCount int
	}
	Events []traceEvent
	Marks  []traceMark
	Stats  traceStats
}

type finding struct {
	Claim        string
	Severity     string
	EvidenceSeqs []int
}

type dimension struct {
	Name     string
	Verdict  string
	Findings []finding
}

type reportDoc struct {
	Version int
	Session struct {
		ID         string
		Harness    string
		Model      string
		EventCount int
		UserTurns  int
	}
	Judge struct {
		CLI            string
		Model          string
		RequestedModel string
		PromptVersion  int
		GeneratedAt    string
		InputDigest    string
	}
	TaskSummary    string
	Dimensions     []dimension
	NotableMoments []struct {
		Seq  int
		Note string
	}
	Narrative string
}

func decodeCityMap(t *testing.T, raw []byte) cityMap {
	t.Helper()
	var c cityMap
	if err := json.Unmarshal(raw, &c); err != nil {
		t.Fatalf("decoding citymap: %v\n%s", err, raw)
	}
	return c
}

func decodeTrace(t *testing.T, raw []byte) traceDoc {
	t.Helper()
	var tr traceDoc
	if err := json.Unmarshal(raw, &tr); err != nil {
		t.Fatalf("decoding trace: %v\n%s", err, raw)
	}
	return tr
}

func decodeReport(t *testing.T, raw []byte) reportDoc {
	t.Helper()
	var r reportDoc
	if err := json.Unmarshal(raw, &r); err != nil {
		t.Fatalf("decoding report: %v\n%s", err, raw)
	}
	return r
}

func filesByPath(files []cityFile) map[string]cityFile {
	m := map[string]cityFile{}
	for _, f := range files {
		m[f.Path] = f
	}
	return m
}

func dirsByPath(dirs []cityDir) map[string]cityDir {
	m := map[string]cityDir{}
	for _, d := range dirs {
		m[d.Path] = d
	}
	return m
}

var shortSHA = regexp.MustCompile(`^[0-9a-f]{7,40}$`)

// ---------------------------------------------------------------------------
// Codex JSONL builders (a subset of the harness's own record shapes)
// ---------------------------------------------------------------------------

func codexSessionMeta(ts string, payload map[string]any) map[string]any {
	return map[string]any{"timestamp": ts, "type": "session_meta", "payload": payload}
}

func codexTurnContext(ts, cwd, model string) map[string]any {
	return map[string]any{"timestamp": ts, "type": "turn_context",
		"payload": map[string]any{"cwd": cwd, "model": model}}
}

func codexUserMessage(ts, text string) map[string]any {
	return map[string]any{"timestamp": ts, "type": "response_item",
		"payload": map[string]any{"type": "message", "role": "user",
			"content": []any{map[string]any{"type": "input_text", "text": text}}}}
}

func codexCall(ts, id, callID, name string, args map[string]any) map[string]any {
	data, _ := json.Marshal(args)
	return map[string]any{"timestamp": ts, "type": "response_item",
		"payload": map[string]any{"type": "function_call", "id": id, "name": name,
			"arguments": string(data), "call_id": callID}}
}

func codexCustomCall(ts, id, callID, name string, input any) map[string]any {
	return map[string]any{"timestamp": ts, "type": "response_item",
		"payload": map[string]any{"type": "custom_tool_call", "id": id, "name": name,
			"input": input, "call_id": callID}}
}

func codexOutput(ts, callID, text string) map[string]any {
	return map[string]any{"timestamp": ts, "type": "response_item",
		"payload": map[string]any{"type": "function_call_output", "call_id": callID, "output": text}}
}

func codexCustomOutput(ts, callID string, value any) map[string]any {
	return map[string]any{"timestamp": ts, "type": "response_item",
		"payload": map[string]any{"type": "custom_tool_call_output", "call_id": callID, "output": value}}
}

func codexEventMsg(ts string, payload map[string]any) map[string]any {
	return map[string]any{"timestamp": ts, "type": "event_msg", "payload": payload}
}

// ===========================================================================
// Group 1 — citymap build
// ===========================================================================

// TestBuildCitymapLayoutMetadataAndDeterminism drives `build` over a committed
// git repo and asserts the full artifact: version, repo state, per-file
// metadata (path ordering, ids, lang, lines, bytes), directory rollups, the
// layout descriptor, positive rects for every leaf, schema conformance, and
// byte-for-byte determinism across two runs (ignoring the wall-clock stamp).
func TestBuildCitymapLayoutMetadataAndDeterminism(t *testing.T) {
	defer failOnPanic(t)
	repo := t.TempDir()
	readme := "# Demo\n"
	main := "package main\n\nfunc main() {}\n" // 3 lines
	util := "package main\n"                   // 1 line
	writeRepoFile(t, repo, "README.md", readme)
	writeRepoFile(t, repo, "src/main.go", main)
	writeRepoFile(t, repo, "src/util.go", util)
	gitInit(t, repo)
	git(t, repo, "add", ".")
	git(t, repo, "commit", "-qm", "init")

	stdout, _, code := runMindwalk(t, t.TempDir(), "build", repo)
	if code != 0 {
		t.Fatalf("build exit = %d", code)
	}
	validateSchema(t, "fixtures/schema/citymap.schema.json", []byte(stdout))
	city := decodeCityMap(t, []byte(stdout))

	if city.Version != 1 {
		t.Fatalf("version = %d", city.Version)
	}
	absRepo, _ := filepath.Abs(repo)
	if city.Repo.Root != absRepo {
		t.Fatalf("root = %q, want %q", city.Repo.Root, absRepo)
	}
	if city.Repo.Dirty {
		t.Fatalf("committed repo reported dirty")
	}
	if !shortSHA.MatchString(city.Repo.Commit) {
		t.Fatalf("commit = %q, not a short sha", city.Repo.Commit)
	}
	if city.Repo.GeneratedAt == "" {
		t.Fatalf("generatedAt empty")
	}
	if city.Layout.Algorithm != "squarified-treemap-v1" {
		t.Fatalf("algorithm = %q", city.Layout.Algorithm)
	}
	if city.Layout.Weight != "sqrt(max(lines, bytes/4096, 16))" {
		t.Fatalf("weight = %q", city.Layout.Weight)
	}

	if len(city.Files) != 3 {
		t.Fatalf("files = %d, want 3", len(city.Files))
	}
	wantOrder := []string{"README.md", "src/main.go", "src/util.go"}
	for i, f := range city.Files {
		if f.Path != wantOrder[i] {
			t.Fatalf("files[%d].path = %q, want %q", i, f.Path, wantOrder[i])
		}
		if f.ID != i {
			t.Fatalf("files[%d].id = %d, want %d", i, f.ID, i)
		}
		if f.Ghost {
			t.Fatalf("build must not mark files as ghost: %#v", f)
		}
		if f.Rect.W <= 0 || f.Rect.D <= 0 {
			t.Fatalf("files[%d] empty rect: %#v", i, f.Rect)
		}
	}
	fm := filesByPath(city.Files)
	if got := fm["README.md"]; got.Lang != "markdown" || got.Lines != 1 || got.Bytes != int64(len(readme)) || got.Dir != "" {
		t.Fatalf("README.md = %#v", got)
	}
	if got := fm["src/main.go"]; got.Lang != "go" || got.Lines != 3 || got.Bytes != int64(len(main)) || got.Dir != "src" {
		t.Fatalf("src/main.go = %#v", got)
	}
	if got := fm["src/util.go"]; got.Lang != "go" || got.Lines != 1 || got.Dir != "src" {
		t.Fatalf("src/util.go = %#v", got)
	}

	if len(city.Dirs) != 1 {
		t.Fatalf("dirs = %#v", city.Dirs)
	}
	src := city.Dirs[0]
	if src.Path != "src" || src.Depth != 1 || src.FileCount != 2 || src.Lines != 4 {
		t.Fatalf("src dir = %#v", src)
	}
	if src.Rect.W <= 0 || src.Rect.D <= 0 {
		t.Fatalf("src dir empty rect: %#v", src.Rect)
	}

	// Determinism: a second build produces an identical artifact once the
	// wall-clock stamp is factored out.
	stdout2, _, _ := runMindwalk(t, t.TempDir(), "build", repo)
	city2 := decodeCityMap(t, []byte(stdout2))
	city.Repo.GeneratedAt = ""
	city2.Repo.GeneratedAt = ""
	a, _ := json.Marshal(city)
	b, _ := json.Marshal(city2)
	if string(a) != string(b) {
		t.Fatalf("build is not deterministic\nfirst=%s\nsecond=%s", a, b)
	}
}

// TestBuildHonorsGitTrackingAndDirtyState confirms `build` enumerates files via
// git: tracked and untracked-but-not-ignored files appear, .gitignore'd files
// do not, and an untracked file in the worktree flips repo.dirty to true while
// commit stays populated.
func TestBuildHonorsGitTrackingAndDirtyState(t *testing.T) {
	defer failOnPanic(t)
	repo := t.TempDir()
	writeRepoFile(t, repo, "tracked.go", "package main\n")
	writeRepoFile(t, repo, ".gitignore", "*.log\n")
	gitInit(t, repo)
	git(t, repo, "add", "tracked.go", ".gitignore")
	git(t, repo, "commit", "-qm", "init")
	// Untracked (kept) and ignored (dropped).
	writeRepoFile(t, repo, "new.go", "package main\nfunc New() {}\n")
	writeRepoFile(t, repo, "debug.log", "noise\n")

	stdout, _, code := runMindwalk(t, t.TempDir(), "build", repo)
	if code != 0 {
		t.Fatalf("build exit = %d", code)
	}
	validateSchema(t, "fixtures/schema/citymap.schema.json", []byte(stdout))
	city := decodeCityMap(t, []byte(stdout))

	got := map[string]bool{}
	for _, f := range city.Files {
		got[f.Path] = true
	}
	for _, want := range []string{".gitignore", "new.go", "tracked.go"} {
		if !got[want] {
			t.Fatalf("missing tracked/untracked file %q in %#v", want, got)
		}
	}
	if got["debug.log"] {
		t.Fatalf("gitignored file leaked into citymap: %#v", got)
	}
	if len(city.Files) != 3 {
		t.Fatalf("files = %d (%#v), want 3", len(city.Files), got)
	}
	if !city.Repo.Dirty {
		t.Fatalf("worktree with an untracked file must be dirty")
	}
	if !shortSHA.MatchString(city.Repo.Commit) {
		t.Fatalf("commit = %q", city.Repo.Commit)
	}
}

// TestBuildNonGitFallbackAndFileClassification exercises the non-git path: with
// no repository, `build` walks the tree (skipping node_modules), leaves
// commit empty and dirty false, and classifies files — text line counts (no
// trailing newline, empty file), binary-by-extension line clamping, and the
// language mapping.
func TestBuildNonGitFallbackAndFileClassification(t *testing.T) {
	defer failOnPanic(t)
	repo := t.TempDir()
	writeRepoFile(t, repo, "a.txt", "line1\nline2") // no trailing newline -> 2 lines
	writeRepoFile(t, repo, "empty.txt", "")         // 0 lines
	writeRepoFile(t, repo, "logo.png", "\x89PNG")   // binary by extension -> 1 line
	writeRepoFile(t, repo, "sub/b.go", "package b\n")
	writeRepoFile(t, repo, "node_modules/dep.js", "module.exports = 1\n")

	stdout, _, code := runMindwalk(t, t.TempDir(), "build", repo)
	if code != 0 {
		t.Fatalf("build exit = %d", code)
	}
	validateSchema(t, "fixtures/schema/citymap.schema.json", []byte(stdout))
	city := decodeCityMap(t, []byte(stdout))

	if city.Repo.Commit != "" {
		t.Fatalf("non-git repo reported commit %q", city.Repo.Commit)
	}
	if city.Repo.Dirty {
		t.Fatalf("non-git repo reported dirty")
	}
	fm := filesByPath(city.Files)
	if _, ok := fm["node_modules/dep.js"]; ok {
		t.Fatalf("node_modules was not skipped: %#v", fm)
	}
	if got := fm["a.txt"]; got.Lines != 2 || got.Lang != "txt" || got.Bytes != int64(len("line1\nline2")) {
		t.Fatalf("a.txt = %#v", got)
	}
	if got := fm["empty.txt"]; got.Lines != 0 || got.Bytes != 0 {
		t.Fatalf("empty.txt = %#v", got)
	}
	if got := fm["logo.png"]; got.Lines != 1 || got.Lang != "png" {
		t.Fatalf("logo.png = %#v", got)
	}
	if got := fm["sub/b.go"]; got.Lines != 1 || got.Lang != "go" || got.Dir != "sub" {
		t.Fatalf("sub/b.go = %#v", got)
	}
	if _, ok := dirsByPath(city.Dirs)["sub"]; !ok {
		t.Fatalf("sub dir missing: %#v", city.Dirs)
	}
}

// ===========================================================================
// Group 2 — Claude Code adapter trace
// ===========================================================================

// TestTraceClaudeWorkflowEventsAndStats parses a realistic Claude Code session
// (read -> search -> edit -> failed verify) and asserts the normalized events
// (tool, action, targets, touch states, line ranges, error flag), the
// user-message mark, and the full derived stats block including fovea/parafovea
// classification, action/error tallies, first-edit index, error rate and the
// exact/exact observability grade Claude logs earn.
func TestTraceClaudeWorkflowEventsAndStats(t *testing.T) {
	defer failOnPanic(t)
	repo := t.TempDir()
	writeRepoFile(t, repo, "src/parser.go", "package parser\n")
	writeRepoFile(t, repo, "src/util.go", "package parser\n")
	cwd := quoteJSON(t, filepath.ToSlash(repo))
	session := filepath.Join(t.TempDir(), "claude.jsonl")
	writeJSONL(t, session,
		`{"type":"user","timestamp":"2026-07-09T00:00:00Z","cwd":`+cwd+`,"sessionId":"wf","message":{"role":"user","content":"fix the parser"}}`,
		`{"type":"assistant","timestamp":"2026-07-09T00:00:01Z","cwd":`+cwd+`,"sessionId":"wf","message":{"role":"assistant","model":"claude-test","content":[{"type":"tool_use","id":"r1","name":"Read","input":{"file_path":`+cwd[:len(cwd)-1]+`/src/parser.go","offset":10,"limit":5}}]}}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:02Z","cwd":`+cwd+`,"sessionId":"wf","message":{"role":"user","content":[{"tool_use_id":"r1","type":"tool_result","content":"10\tpackage parser\n","is_error":false}]}}`,
		`{"type":"assistant","timestamp":"2026-07-09T00:00:03Z","cwd":`+cwd+`,"sessionId":"wf","message":{"role":"assistant","content":[{"type":"tool_use","id":"g1","name":"Grep","input":{"pattern":"TODO","path":"src"}}]}}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:04Z","cwd":`+cwd+`,"sessionId":"wf","message":{"role":"user","content":[{"tool_use_id":"g1","type":"tool_result","content":"src/util.go:42:  // TODO\n","is_error":false}]}}`,
		`{"type":"assistant","timestamp":"2026-07-09T00:00:05Z","cwd":`+cwd+`,"sessionId":"wf","message":{"role":"assistant","content":[{"type":"tool_use","id":"e1","name":"Edit","input":{"file_path":`+cwd[:len(cwd)-1]+`/src/parser.go","old_string":"parser","new_string":"lexer"}}]}}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:06Z","cwd":`+cwd+`,"sessionId":"wf","message":{"role":"user","content":[{"tool_use_id":"e1","type":"tool_result","content":"ok","is_error":false}]}}`,
		`{"type":"assistant","timestamp":"2026-07-09T00:00:07Z","cwd":`+cwd+`,"sessionId":"wf","message":{"role":"assistant","content":[{"type":"tool_use","id":"v1","name":"Bash","input":{"command":"go test ./..."}}]}}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:08Z","cwd":`+cwd+`,"sessionId":"wf","message":{"role":"user","content":[{"tool_use_id":"v1","type":"tool_result","content":"FAIL","is_error":true}]}}`,
	)

	stdout, _, code := runMindwalk(t, t.TempDir(), "trace", session)
	if code != 0 {
		t.Fatalf("trace exit = %d", code)
	}
	validateSchema(t, "fixtures/schema/trace.schema.json", []byte(stdout))
	tr := decodeTrace(t, []byte(stdout))

	if tr.Version != 1 || tr.Session.Harness != "claude-code" || tr.Session.ID != "wf" {
		t.Fatalf("session = %#v", tr.Session)
	}
	if tr.Session.Model != "claude-test" || tr.Session.EventCount != 4 {
		t.Fatalf("session = %#v", tr.Session)
	}
	if len(tr.Events) != 4 {
		t.Fatalf("events = %d", len(tr.Events))
	}
	read := tr.Events[0]
	if read.Seq != 0 || read.Tool != "Read" || read.Action != "read" || read.IsError {
		t.Fatalf("read event = %#v", read)
	}
	if len(read.Targets) != 1 || read.Targets[0].Path != "src/parser.go" || read.Targets[0].Touch != "read" {
		t.Fatalf("read targets = %#v", read.Targets)
	}
	if got := read.Targets[0].Lines; len(got) != 1 || got[0] != [2]int{10, 14} {
		t.Fatalf("read lines = %#v", got)
	}
	search := tr.Events[1]
	if search.Action != "search" || len(search.Targets) != 1 || search.Targets[0].Path != "src/util.go" || search.Targets[0].Touch != "hit" {
		t.Fatalf("search event = %#v", search)
	}
	if got := search.Targets[0].Lines; len(got) != 1 || got[0] != [2]int{42, 42} {
		t.Fatalf("search lines = %#v", got)
	}
	edit := tr.Events[2]
	if len(edit.Targets) != 1 {
		t.Fatalf("edit event = %#v, want exactly 1 target", edit)
	}
	if edit.Action != "edit" || edit.Targets[0].Path != "src/parser.go" || edit.Targets[0].Touch != "edit" {
		t.Fatalf("edit event = %#v", tr.Events[2])
	}
	if verify := tr.Events[3]; verify.Action != "verify" || !verify.IsError {
		t.Fatalf("verify event = %#v", tr.Events[3])
	}

	if len(tr.Marks) != 1 || tr.Marks[0].Type != "user-message" || tr.Marks[0].Note != "fix the parser" {
		t.Fatalf("marks = %#v", tr.Marks)
	}

	s := tr.Stats
	if s.Actions != (actionCounts{Read: 1, Search: 1, Edit: 1, Verify: 1}) {
		t.Fatalf("actions = %#v", s.Actions)
	}
	if s.Errors != (actionCounts{Verify: 1}) {
		t.Fatalf("errors = %#v", s.Errors)
	}
	if s.Edited != 1 || s.Fovea != 1 || s.Parafovea != 1 {
		t.Fatalf("fovea stats = %#v", s)
	}
	if s.EventsBeforeFirstEdit != 2 {
		t.Fatalf("eventsBeforeFirstEdit = %d", s.EventsBeforeFirstEdit)
	}
	if s.MaxEditsPerFile != 1 || s.ChurnFiles != 0 {
		t.Fatalf("edit stats = %#v", s)
	}
	if math.Abs(s.ErrorRate-0.25) > 1e-9 {
		t.Fatalf("errorRate = %v", s.ErrorRate)
	}
	if s.UserTurns != 1 {
		t.Fatalf("userTurns = %d", s.UserTurns)
	}
	if s.Observability.Reads != "exact" || s.Observability.Errors != "exact" {
		t.Fatalf("observability = %#v", s.Observability)
	}
}

// TestTraceClaudeMarksAndUserMessages verifies the timeline marks a Claude
// session produces: a real user-message mark keeps its text, a Task tool_use
// raises a subagent mark, a compact_boundary system line raises a compaction
// mark, harness-injected messages (system-reminder markup and AGENTS.md) are
// filtered out of marks and user-turn counts, and an over-long message note is
// truncated to the 2000-rune budget with an ellipsis.
func TestTraceClaudeMarksAndUserMessages(t *testing.T) {
	defer failOnPanic(t)
	long := strings.Repeat("字", 2100)
	session := filepath.Join(t.TempDir(), "marks.jsonl")
	writeJSONL(t, session,
		`{"type":"user","timestamp":"2026-07-09T00:00:00Z","cwd":"/repo","sessionId":"mk","message":{"role":"user","content":"fix the parser bug"}}`,
		`{"type":"assistant","timestamp":"2026-07-09T00:00:01Z","cwd":"/repo","sessionId":"mk","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Task","input":{"description":"review","subagent_type":"reviewer","prompt":"look at the diff"}}]}}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:02Z","cwd":"/repo","sessionId":"mk","message":{"role":"user","content":[{"tool_use_id":"t1","type":"tool_result","content":"done","is_error":false}]}}`,
		`{"type":"system","subtype":"compact_boundary","content":"","timestamp":"2026-07-09T00:00:03Z","sessionId":"mk"}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:04Z","cwd":"/repo","sessionId":"mk","message":{"role":"user","content":"<system-reminder>ignore me</system-reminder>"}}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:05Z","cwd":"/repo","sessionId":"mk","message":{"role":"user","content":"# AGENTS.md instructions for /repo\n\nproject rules"}}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:06Z","cwd":"/repo","sessionId":"mk","message":{"role":"user","content":"`+long+`"}}`,
	)

	stdout, _, code := runMindwalk(t, t.TempDir(), "trace", session)
	if code != 0 {
		t.Fatalf("trace exit = %d", code)
	}
	validateSchema(t, "fixtures/schema/trace.schema.json", []byte(stdout))
	tr := decodeTrace(t, []byte(stdout))

	if len(tr.Marks) != 4 {
		t.Fatalf("marks = %#v", tr.Marks)
	}
	if tr.Marks[0].Type != "user-message" || tr.Marks[0].Note != "fix the parser bug" {
		t.Fatalf("marks[0] = %#v", tr.Marks[0])
	}
	if tr.Marks[1].Type != "subagent" || tr.Marks[1].Note != "Task" {
		t.Fatalf("marks[1] = %#v", tr.Marks[1])
	}
	if tr.Marks[2].Type != "compaction" {
		t.Fatalf("marks[2] = %#v", tr.Marks[2])
	}
	if tr.Marks[3].Type != "user-message" {
		t.Fatalf("marks[3] = %#v", tr.Marks[3])
	}
	note := []rune(tr.Marks[3].Note)
	if len(note) != 2000 || note[len(note)-1] != '…' {
		t.Fatalf("truncated note runes = %d, last = %q", len(note), string(note[len(note)-1]))
	}
	for _, m := range tr.Marks {
		if strings.Contains(m.Note, "system-reminder") || strings.Contains(m.Note, "AGENTS.md") {
			t.Fatalf("injected message leaked into marks: %#v", m)
		}
	}
	if tr.Stats.Subagents != 1 || tr.Stats.Compactions != 1 {
		t.Fatalf("mark stats = %#v", tr.Stats)
	}
	if tr.Stats.UserTurns != 2 {
		t.Fatalf("userTurns = %d, want 2 (injected filtered)", tr.Stats.UserTurns)
	}
}

// TestTraceClaudeBashActionClassification checks the shell-command classifier
// that maps Bash invocations onto read/search/verify/exec actions: a grep is a
// search, a cat of an existing repo file is a read, a test command is a verify,
// and an arbitrary program stays exec.
func TestTraceClaudeBashActionClassification(t *testing.T) {
	defer failOnPanic(t)
	repo := t.TempDir()
	writeRepoFile(t, repo, "README.md", "# Demo\n")
	cwd := quoteJSON(t, filepath.ToSlash(repo))
	session := filepath.Join(t.TempDir(), "bash.jsonl")
	bash := func(id, ts, cmd, result string, i int) []string {
		return []string{
			`{"type":"assistant","timestamp":"` + ts + `","cwd":` + cwd + `,"sessionId":"bash","message":{"role":"assistant","content":[{"type":"tool_use","id":"` + id + `","name":"Bash","input":{"command":` + quoteJSON(t, cmd) + `}}]}}`,
			`{"type":"user","timestamp":"` + ts + `","cwd":` + cwd + `,"sessionId":"bash","message":{"role":"user","content":[{"tool_use_id":"` + id + `","type":"tool_result","content":` + quoteJSON(t, result) + `,"is_error":false}]}}`,
		}
	}
	var lines []any
	lines = append(lines, `{"type":"user","timestamp":"2026-07-09T00:00:00Z","cwd":`+cwd+`,"sessionId":"bash","message":{"role":"user","content":"inspect"}}`)
	for _, l := range bash("b1", "2026-07-09T00:00:01Z", "grep -rn TODO src/", "", 0) {
		lines = append(lines, l)
	}
	for _, l := range bash("b2", "2026-07-09T00:00:02Z", "cat README.md", "# Demo\n", 1) {
		lines = append(lines, l)
	}
	for _, l := range bash("b3", "2026-07-09T00:00:03Z", "go test ./...", "ok\n", 2) {
		lines = append(lines, l)
	}
	for _, l := range bash("b4", "2026-07-09T00:00:04Z", "python build.py", "built\n", 3) {
		lines = append(lines, l)
	}
	writeJSONL(t, session, lines...)

	stdout, _, code := runMindwalk(t, t.TempDir(), "trace", session)
	if code != 0 {
		t.Fatalf("trace exit = %d", code)
	}
	validateSchema(t, "fixtures/schema/trace.schema.json", []byte(stdout))
	tr := decodeTrace(t, []byte(stdout))
	if len(tr.Events) != 4 {
		t.Fatalf("events = %d", len(tr.Events))
	}
	wantActions := []string{"search", "read", "verify", "exec"}
	for i, want := range wantActions {
		if tr.Events[i].Action != want {
			t.Fatalf("events[%d] (%s) action = %q, want %q", i, tr.Events[i].Summary, tr.Events[i].Action, want)
		}
	}
	// The cat read resolves the existing file to a weak read target.
	catTargets := tr.Events[1].Targets
	if len(catTargets) != 1 || catTargets[0].Path != "README.md" || catTargets[0].Touch != "read" || !catTargets[0].Weak {
		t.Fatalf("cat targets = %#v", catTargets)
	}
	if tr.Stats.Actions != (actionCounts{Search: 1, Read: 1, Verify: 1, Exec: 1}) {
		t.Fatalf("actions = %#v", tr.Stats.Actions)
	}
}

// TestTraceClaudeOutsidePathsAndNormalization checks that file references
// resolving outside the session cwd become classified outside-touches rather
// than repo targets: a system path scopes "other", a path under $HOME scopes
// "home", and a path under the temp dir scopes "tmp".
func TestTraceClaudeOutsidePathsAndNormalization(t *testing.T) {
	defer failOnPanic(t)
	home := t.TempDir()
	homeFile := filepath.ToSlash(filepath.Join(home, "secret.txt"))
	session := filepath.Join(t.TempDir(), "outside.jsonl")
	read := func(id, ts, path string) []string {
		return []string{
			`{"type":"assistant","timestamp":"` + ts + `","cwd":"/repo","sessionId":"out","message":{"role":"assistant","content":[{"type":"tool_use","id":"` + id + `","name":"Read","input":{"file_path":` + quoteJSON(t, path) + `}}]}}`,
			`{"type":"user","timestamp":"` + ts + `","cwd":"/repo","sessionId":"out","message":{"role":"user","content":[{"tool_use_id":"` + id + `","type":"tool_result","content":"x","is_error":false}]}}`,
		}
	}
	var lines []any
	lines = append(lines, `{"type":"user","timestamp":"2026-07-09T00:00:00Z","cwd":"/repo","sessionId":"out","message":{"role":"user","content":"look around"}}`)
	for _, l := range read("o1", "2026-07-09T00:00:01Z", "/etc/hostname") {
		lines = append(lines, l)
	}
	for _, l := range read("o2", "2026-07-09T00:00:02Z", homeFile) {
		lines = append(lines, l)
	}
	for _, l := range read("o3", "2026-07-09T00:00:03Z", "/tmp/scratch.go") {
		lines = append(lines, l)
	}
	writeJSONL(t, session, lines...)

	stdout, _, code := runMindwalk(t, home, "trace", session)
	if code != 0 {
		t.Fatalf("trace exit = %d", code)
	}
	validateSchema(t, "fixtures/schema/trace.schema.json", []byte(stdout))
	tr := decodeTrace(t, []byte(stdout))
	if len(tr.Events) != 3 {
		t.Fatalf("events = %d", len(tr.Events))
	}
	want := []struct {
		scope string
		path  string
	}{
		{"other", "/etc/hostname"},
		{"home", homeFile},
		{"tmp", "/tmp/scratch.go"},
	}
	for i, w := range want {
		ev := tr.Events[i]
		if len(ev.Targets) != 0 {
			t.Fatalf("events[%d] should have no repo targets: %#v", i, ev.Targets)
		}
		if len(ev.Outside) != 1 || ev.Outside[0].Scope != w.scope || ev.Outside[0].Path != w.path {
			t.Fatalf("events[%d] outside = %#v, want scope %q path %q", i, ev.Outside, w.scope, w.path)
		}
	}
}

// ===========================================================================
// Group 3 — Codex adapter trace
// ===========================================================================

// TestTraceCodexWorkflowEventsAndStats parses a Codex rollout (sed read ->
// apply_patch edit -> failed test) and asserts the harness/model/commit
// metadata, the user-message mark, the read/edit/verify events with their error
// flags inferred from command output text, and the estimated/estimated
// observability grade Codex logs earn (no structural read or error signal).
func TestTraceCodexWorkflowEventsAndStats(t *testing.T) {
	defer failOnPanic(t)
	repo := t.TempDir()
	writeRepoFile(t, repo, "README.md", "# Demo\n")
	root := filepath.ToSlash(repo)
	session := filepath.Join(t.TempDir(), "rollout-codex-wf.jsonl")
	writeJSONL(t, session,
		codexSessionMeta("2026-07-09T00:00:00Z", map[string]any{
			"id": "codex-wf", "session_id": "codex-wf", "timestamp": "2026-07-09T00:00:00Z",
			"cwd": root, "git": map[string]any{"branch": "main", "commit_hash": "abc123"}}),
		codexTurnContext("2026-07-09T00:00:01Z", root, "gpt-5.5"),
		codexUserMessage("2026-07-09T00:00:02Z", "inspect the repo"),
		codexCall("2026-07-09T00:00:03Z", "fc-read", "call-read", "exec_command",
			map[string]any{"cmd": "sed -n '1,40p' README.md", "workdir": root}),
		codexOutput("2026-07-09T00:00:04Z", "call-read", "Chunk ID: read\nProcess exited with code 0\nOutput:\n# Demo\n"),
		codexCustomCall("2026-07-09T00:00:05Z", "ctc-edit", "call-edit", "apply_patch",
			"*** Begin Patch\n*** Update File: README.md\n@@\n-# Demo\n+# Demo v2\n*** End Patch\n"),
		codexCustomOutput("2026-07-09T00:00:06Z", "call-edit", "Success. Updated the following files:\nM README.md\n"),
		codexCall("2026-07-09T00:00:07Z", "fc-test", "call-test", "exec_command",
			map[string]any{"cmd": "go test ./...", "workdir": root}),
		codexOutput("2026-07-09T00:00:08Z", "call-test", "Chunk ID: test\nProcess exited with code 1\nOutput:\nFAIL ./...\n"),
	)

	stdout, _, code := runMindwalk(t, t.TempDir(), "trace", session)
	if code != 0 {
		t.Fatalf("trace exit = %d", code)
	}
	validateSchema(t, "fixtures/schema/trace.schema.json", []byte(stdout))
	tr := decodeTrace(t, []byte(stdout))

	if tr.Session.Harness != "codex" || tr.Session.ID != "codex-wf" || tr.Session.Commit != "abc123" || tr.Session.Model != "gpt-5.5" {
		t.Fatalf("session = %#v", tr.Session)
	}
	if len(tr.Marks) != 1 || tr.Marks[0].Type != "user-message" || tr.Marks[0].Note != "inspect the repo" {
		t.Fatalf("marks = %#v", tr.Marks)
	}
	if len(tr.Events) != 3 {
		t.Fatalf("events = %d", len(tr.Events))
	}
	if r := tr.Events[0]; r.Tool != "exec_command" || r.Action != "read" || len(r.Targets) != 1 || r.Targets[0].Path != "README.md" || r.Targets[0].Touch != "read" {
		t.Fatalf("read event = %#v", tr.Events[0])
	}
	e := tr.Events[1]
	if len(e.Targets) != 1 {
		t.Fatalf("edit event = %#v, want exactly 1 target", e)
	}
	if e.Tool != "apply_patch" || e.Action != "edit" || e.Targets[0].Touch != "edit" || e.Targets[0].Path != "README.md" {
		t.Fatalf("edit event = %#v", tr.Events[1])
	}
	if v := tr.Events[2]; v.Action != "verify" || !v.IsError {
		t.Fatalf("verify event = %#v", tr.Events[2])
	}
	s := tr.Stats
	if s.Edited != 1 || s.EventsBeforeFirstEdit != 1 {
		t.Fatalf("stats = %#v", s)
	}
	if math.Abs(s.ErrorRate-1.0/3.0) > 1e-9 {
		t.Fatalf("errorRate = %v", s.ErrorRate)
	}
	if s.Observability.Reads != "estimated" || s.Observability.Errors != "estimated" {
		t.Fatalf("observability = %#v", s.Observability)
	}
}

// TestTraceCodexSubagentCompactionAndScript covers Codex-specific timeline
// signals: a spawn_agent call raises a subagent mark at the right sequence, a
// context_compacted event raises a compaction mark, and a js_repl orchestration
// call has its imported path extracted as a weak hit while staying an exec
// action.
func TestTraceCodexSubagentCompactionAndScript(t *testing.T) {
	defer failOnPanic(t)
	repo := t.TempDir()
	writeRepoFile(t, repo, "packages/db/src/index.ts", "export const db = {}\n")
	root := filepath.ToSlash(repo)
	session := filepath.Join(t.TempDir(), "rollout-codex-sub.jsonl")
	writeJSONL(t, session,
		codexSessionMeta("2026-07-14T00:00:00Z", map[string]any{"id": "codex-sub", "cwd": root, "timestamp": "2026-07-14T00:00:00Z"}),
		codexCall("2026-07-14T00:00:01Z", "fc-1", "call-1", "exec_command", map[string]any{"cmd": "true", "workdir": root}),
		codexOutput("2026-07-14T00:00:02Z", "call-1", "Process exited with code 0"),
		codexCall("2026-07-14T00:00:03Z", "fc-2", "call-2", "spawn_agent", map[string]any{"task_name": "qa", "message": "review"}),
		codexOutput("2026-07-14T00:00:04Z", "call-2", `{"agent_id":"agent-1"}`),
		codexEventMsg("2026-07-14T00:00:05Z", map[string]any{"type": "context_compacted"}),
		codexCustomCall("2026-07-14T00:00:06Z", "ctc-js", "call-js", "js_repl", `await import("./packages/db/src/index.ts")`),
		codexCustomOutput("2026-07-14T00:00:07Z", "call-js", "loaded"),
	)

	stdout, _, code := runMindwalk(t, t.TempDir(), "trace", session)
	if code != 0 {
		t.Fatalf("trace exit = %d", code)
	}
	validateSchema(t, "fixtures/schema/trace.schema.json", []byte(stdout))
	tr := decodeTrace(t, []byte(stdout))

	if len(tr.Events) != 3 {
		t.Fatalf("events = %d", len(tr.Events))
	}
	if len(tr.Marks) != 2 {
		t.Fatalf("marks = %#v", tr.Marks)
	}
	if tr.Marks[0].Type != "subagent" || tr.Marks[0].Seq != 1 || tr.Marks[0].Note != "spawn_agent" {
		t.Fatalf("subagent mark = %#v", tr.Marks[0])
	}
	if tr.Marks[1].Type != "compaction" || tr.Marks[1].Seq != 2 {
		t.Fatalf("compaction mark = %#v", tr.Marks[1])
	}
	js := tr.Events[2]
	if js.Tool != "js_repl" || js.Action != "exec" {
		t.Fatalf("js event = %#v", js)
	}
	if len(js.Targets) != 1 || js.Targets[0].Path != "packages/db/src/index.ts" || js.Targets[0].Touch != "hit" || !js.Targets[0].Weak {
		t.Fatalf("js targets = %#v", js.Targets)
	}
	if tr.Stats.Subagents != 1 || tr.Stats.Compactions != 1 {
		t.Fatalf("stats = %#v", tr.Stats)
	}
}

// ===========================================================================
// Group 4 — analyze pipeline (deterministic stub judge)
// ===========================================================================

// writeAnalyzeClaudeSession writes a 4-event Claude session (seqs 0..3) with a
// strong read at seq 0, so it earns exact/exact observability and the stub
// judge's evidence seqs 0..3 all resolve.
func writeAnalyzeClaudeSession(t *testing.T, cwd string) string {
	q := quoteJSON(t, filepath.ToSlash(cwd))
	session := filepath.Join(t.TempDir(), "analyze-claude.jsonl")
	writeJSONL(t, session,
		`{"type":"user","timestamp":"2026-07-09T00:00:00Z","cwd":`+q+`,"sessionId":"an","message":{"role":"user","content":"Investigate the parser test"}}`,
		`{"type":"assistant","timestamp":"2026-07-09T00:00:01Z","cwd":`+q+`,"sessionId":"an","message":{"role":"assistant","model":"claude-test","content":[{"type":"tool_use","id":"r1","name":"Read","input":{"file_path":`+q[:len(q)-1]+`/parser.go"}}]}}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:02Z","cwd":`+q+`,"sessionId":"an","message":{"role":"user","content":[{"tool_use_id":"r1","type":"tool_result","content":"package parser","is_error":false}]}}`,
		`{"type":"assistant","timestamp":"2026-07-09T00:00:03Z","cwd":`+q+`,"sessionId":"an","message":{"role":"assistant","content":[{"type":"tool_use","id":"r2","name":"Read","input":{"file_path":`+q[:len(q)-1]+`/util.go"}}]}}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:04Z","cwd":`+q+`,"sessionId":"an","message":{"role":"user","content":[{"tool_use_id":"r2","type":"tool_result","content":"package parser","is_error":false}]}}`,
		`{"type":"assistant","timestamp":"2026-07-09T00:00:05Z","cwd":`+q+`,"sessionId":"an","message":{"role":"assistant","content":[{"type":"tool_use","id":"e1","name":"Edit","input":{"file_path":`+q[:len(q)-1]+`/parser.go","old_string":"a","new_string":"b"}}]}}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:06Z","cwd":`+q+`,"sessionId":"an","message":{"role":"user","content":[{"tool_use_id":"e1","type":"tool_result","content":"ok","is_error":false}]}}`,
		`{"type":"assistant","timestamp":"2026-07-09T00:00:07Z","cwd":`+q+`,"sessionId":"an","message":{"role":"assistant","content":[{"type":"tool_use","id":"v1","name":"Bash","input":{"command":"go test ./..."}}]}}`,
		`{"type":"user","timestamp":"2026-07-09T00:00:08Z","cwd":`+q+`,"sessionId":"an","message":{"role":"user","content":[{"tool_use_id":"v1","type":"tool_result","content":"FAIL","is_error":true}]}}`,
	)
	return session
}

func dimByName(dims []dimension, name string) dimension {
	for _, d := range dims {
		if d.Name == name {
			return d
		}
	}
	return dimension{}
}

// TestAnalyzeReportFromStubJudge runs the full analyze pipeline against the
// baked deterministic judge stub and asserts the report end to end: session and
// judge metadata (cli, model, prompt version, sha-256 input digest), the
// canned task summary and narrative, evidence-seq validation (hallucinated seqs
// dropped, findings with no surviving evidence removed entirely), and the
// mechanical verdict rollup from finding severities across all four dimensions.
func TestAnalyzeReportFromStubJudge(t *testing.T) {
	defer failOnPanic(t)
	repo := t.TempDir()
	writeRepoFile(t, repo, "parser.go", "package parser\n")
	writeRepoFile(t, repo, "util.go", "package parser\n")
	session := writeAnalyzeClaudeSession(t, repo)

	stdout, stderr, code := runMindwalk(t, t.TempDir(), "analyze", "--judge", "claude", session)
	if code != 0 {
		t.Fatalf("analyze exit = %d (stderr: %s)", code, stderr)
	}
	validateSchema(t, "fixtures/schema/report.schema.json", []byte(stdout))
	r := decodeReport(t, []byte(stdout))

	if r.Version != 1 {
		t.Fatalf("version = %d", r.Version)
	}
	if r.Session.Harness != "claude-code" || r.Session.ID != "an" || r.Session.Model != "claude-test" || r.Session.EventCount != 4 || r.Session.UserTurns != 1 {
		t.Fatalf("session = %#v", r.Session)
	}
	if r.Judge.CLI != "claude" || r.Judge.Model != "claude-sonnet-stub" || r.Judge.PromptVersion != 2 {
		t.Fatalf("judge = %#v", r.Judge)
	}
	if len(r.Judge.InputDigest) != 64 || r.Judge.GeneratedAt == "" {
		t.Fatalf("judge freshness = %#v", r.Judge)
	}
	if r.TaskSummary != "Investigate and fix the failing parser test." {
		t.Fatalf("taskSummary = %q", r.TaskSummary)
	}
	if !strings.Contains(r.Narrative, "read the parser") {
		t.Fatalf("narrative = %q", r.Narrative)
	}

	if len(r.Dimensions) != 4 {
		t.Fatalf("dimensions = %d", len(r.Dimensions))
	}
	wantOrder := []string{"exploration", "scope", "wandering", "verification"}
	for i, name := range wantOrder {
		if r.Dimensions[i].Name != name {
			t.Fatalf("dimensions[%d] = %q, want %q", i, r.Dimensions[i].Name, name)
		}
	}
	explore := dimByName(r.Dimensions, "exploration")
	if explore.Verdict != "good" {
		t.Fatalf("exploration verdict = %q", explore.Verdict)
	}
	// The [90001,90002] finding cites only nonexistent seqs and is dropped; the
	// [0,1] info finding survives.
	if len(explore.Findings) != 1 || explore.Findings[0].Severity != "info" {
		t.Fatalf("exploration findings = %#v", explore.Findings)
	}
	if got := explore.Findings[0].EvidenceSeqs; len(got) != 2 || got[0] != 0 || got[1] != 1 {
		t.Fatalf("exploration evidence = %#v", got)
	}
	scope := dimByName(r.Dimensions, "scope")
	if scope.Verdict != "warning" || len(scope.Findings) != 1 || scope.Findings[0].Severity != "warning" {
		t.Fatalf("scope = %#v", scope)
	}
	// The invalid seq 90003 is stripped, leaving only seq 2.
	if got := scope.Findings[0].EvidenceSeqs; len(got) != 1 || got[0] != 2 {
		t.Fatalf("scope evidence = %#v", got)
	}
	if w := dimByName(r.Dimensions, "wandering"); w.Verdict != "good" || len(w.Findings) != 0 {
		t.Fatalf("wandering = %#v", w)
	}
	verify := dimByName(r.Dimensions, "verification")
	if verify.Verdict != "problem" || len(verify.Findings) != 1 || verify.Findings[0].Severity != "problem" {
		t.Fatalf("verification = %#v", verify)
	}

	// Only the valid notable moment (seq 0) survives; seq 90004 is dropped.
	if len(r.NotableMoments) != 1 || r.NotableMoments[0].Seq != 0 {
		t.Fatalf("notableMoments = %#v", r.NotableMoments)
	}
}

// TestAnalyzeObservabilityBlindSpotRollup confirms that when the trace records
// no usable read signal (a Codex session with only exec commands), the
// mechanical rollup forces exploration and wandering to insufficient-data
// regardless of the judge's findings, while scope and verification still
// reflect their finding severities.
func TestAnalyzeObservabilityBlindSpotRollup(t *testing.T) {
	defer failOnPanic(t)
	repo := t.TempDir()
	root := filepath.ToSlash(repo)
	session := filepath.Join(t.TempDir(), "rollout-codex-noreads.jsonl")
	writeJSONL(t, session,
		codexSessionMeta("2026-07-09T00:00:00Z", map[string]any{"id": "nr", "cwd": root, "timestamp": "2026-07-09T00:00:00Z"}),
		codexCall("2026-07-09T00:00:01Z", "fc-0", "call-0", "exec_command", map[string]any{"cmd": "true", "workdir": root}),
		codexOutput("2026-07-09T00:00:02Z", "call-0", "Process exited with code 0"),
		codexCall("2026-07-09T00:00:03Z", "fc-1", "call-1", "exec_command", map[string]any{"cmd": "echo done", "workdir": root}),
		codexOutput("2026-07-09T00:00:04Z", "call-1", "Process exited with code 0"),
		codexCall("2026-07-09T00:00:05Z", "fc-2", "call-2", "exec_command", map[string]any{"cmd": "printenv", "workdir": root}),
		codexOutput("2026-07-09T00:00:06Z", "call-2", "Process exited with code 0"),
		codexCall("2026-07-09T00:00:07Z", "fc-3", "call-3", "exec_command", map[string]any{"cmd": "go test ./...", "workdir": root}),
		codexOutput("2026-07-09T00:00:08Z", "call-3", "Process exited with code 0"),
	)

	stdout, stderr, code := runMindwalk(t, t.TempDir(), "analyze", "--judge", "codex", session)
	if code != 0 {
		t.Fatalf("analyze exit = %d (stderr: %s)", code, stderr)
	}
	validateSchema(t, "fixtures/schema/report.schema.json", []byte(stdout))
	r := decodeReport(t, []byte(stdout))

	if v := dimByName(r.Dimensions, "exploration").Verdict; v != "insufficient-data" {
		t.Fatalf("exploration verdict = %q, want insufficient-data", v)
	}
	if v := dimByName(r.Dimensions, "wandering").Verdict; v != "insufficient-data" {
		t.Fatalf("wandering verdict = %q, want insufficient-data", v)
	}
	if v := dimByName(r.Dimensions, "scope").Verdict; v != "warning" {
		t.Fatalf("scope verdict = %q, want warning", v)
	}
	if v := dimByName(r.Dimensions, "verification").Verdict; v != "problem" {
		t.Fatalf("verification verdict = %q, want problem", v)
	}
	if r.Judge.CLI != "codex" || r.Judge.Model != "codex-stub" {
		t.Fatalf("judge = %#v", r.Judge)
	}
}

// TestAnalyzeCacheHitAndStaleness verifies the report cache lifecycle across
// runs that share one HOME: the first run judges and stores, the second serves
// the cached report, a trace change (a new user message that alters the input
// digest without adding events) forces a re-judge, and --no-cache always
// re-judges.
func TestAnalyzeCacheHitAndStaleness(t *testing.T) {
	defer failOnPanic(t)
	repo := t.TempDir()
	writeRepoFile(t, repo, "parser.go", "package parser\n")
	writeRepoFile(t, repo, "util.go", "package parser\n")
	session := writeAnalyzeClaudeSession(t, repo)
	home := t.TempDir()

	_, stderr1, code := runMindwalk(t, home, "analyze", "--judge", "claude", session)
	if code != 0 {
		t.Fatalf("run1 exit = %d (%s)", code, stderr1)
	}
	if !strings.Contains(stderr1, "judging") {
		t.Fatalf("run1 stderr should announce a fresh judge run: %q", stderr1)
	}

	out2, stderr2, _ := runMindwalk(t, home, "analyze", "--judge", "claude", session)
	if !strings.Contains(stderr2, "cached report") {
		t.Fatalf("run2 should hit the cache: %q", stderr2)
	}
	// The cached report is a real report, not an error placeholder.
	r2 := decodeReport(t, []byte(out2))
	if r2.TaskSummary != "Investigate and fix the failing parser test." {
		t.Fatalf("cached report = %#v", r2)
	}

	// Append a new user message: no new events, but the judge input digest moves.
	extra := `{"type":"user","timestamp":"2026-07-09T00:00:09Z","cwd":"` + filepath.ToSlash(repo) + `","sessionId":"an","message":{"role":"user","content":"also check the lexer"}}`
	f, err := os.OpenFile(session, os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.WriteString(extra + "\n"); err != nil {
		t.Fatal(err)
	}
	f.Close()

	_, stderr3, _ := runMindwalk(t, home, "analyze", "--judge", "claude", session)
	if !strings.Contains(stderr3, "judging") {
		t.Fatalf("run3 should re-judge a stale report: %q", stderr3)
	}

	_, stderr4, _ := runMindwalk(t, home, "analyze", "--judge", "claude", "--no-cache", session)
	if !strings.Contains(stderr4, "judging") {
		t.Fatalf("--no-cache must re-judge: %q", stderr4)
	}
}

// TestAnalyzeJudgeSelectionAndModelMismatch checks that the cache key respects
// the requested judge: a codex report caches under codex, switching to claude
// forces a re-run recorded as claude, and requesting a specific model the
// cached report was not produced with also forces a re-run that records both
// the requested alias and the model the CLI reports.
func TestAnalyzeJudgeSelectionAndModelMismatch(t *testing.T) {
	defer failOnPanic(t)
	repo := t.TempDir()
	writeRepoFile(t, repo, "parser.go", "package parser\n")
	writeRepoFile(t, repo, "util.go", "package parser\n")
	session := writeAnalyzeClaudeSession(t, repo)
	home := t.TempDir()

	out1, stderr1, code := runMindwalk(t, home, "analyze", "--judge", "codex", session)
	if code != 0 {
		t.Fatalf("codex run exit = %d (%s)", code, stderr1)
	}
	if !strings.Contains(stderr1, "judging") {
		t.Fatalf("codex run should be fresh: %q", stderr1)
	}
	if r := decodeReport(t, []byte(out1)); r.Judge.CLI != "codex" || r.Judge.Model != "codex-stub" {
		t.Fatalf("codex judge = %#v", r.Judge)
	}

	_, stderr2, _ := runMindwalk(t, home, "analyze", "--judge", "codex", session)
	if !strings.Contains(stderr2, "cached report") {
		t.Fatalf("repeat codex run should hit the cache: %q", stderr2)
	}

	out3, stderr3, _ := runMindwalk(t, home, "analyze", "--judge", "claude", session)
	if !strings.Contains(stderr3, "judging") {
		t.Fatalf("switching CLI should re-judge: %q", stderr3)
	}
	if r := decodeReport(t, []byte(out3)); r.Judge.CLI != "claude" || r.Judge.Model != "claude-sonnet-stub" {
		t.Fatalf("claude judge = %#v", r.Judge)
	}

	out4, stderr4, _ := runMindwalk(t, home, "analyze", "--judge", "claude", "--model", "sonnet", session)
	if !strings.Contains(stderr4, "judging") {
		t.Fatalf("model mismatch should re-judge: %q", stderr4)
	}
	r4 := decodeReport(t, []byte(out4))
	if r4.Judge.CLI != "claude" || r4.Judge.RequestedModel != "sonnet" || r4.Judge.Model != "sonnet" {
		t.Fatalf("model-override judge = %#v", r4.Judge)
	}
}

// ===========================================================================
// Group 5 — CLI contract / error handling
// ===========================================================================

// TestCliUnknownCommandAndUsage checks top-level CLI contracts: an unknown
// subcommand and a missing positional argument both fail with a non-zero exit
// and a diagnostic, while --help succeeds and prints usage.
func TestCliUnknownCommandAndUsage(t *testing.T) {
	defer failOnPanic(t)
	home := t.TempDir()

	_, stderr, code := runMindwalk(t, home, "frobnicate")
	if code == 0 {
		t.Fatalf("unknown command should fail")
	}
	if !strings.Contains(stderr, "unknown command") {
		t.Fatalf("unknown command stderr = %q", stderr)
	}

	_, stderr2, code2 := runMindwalk(t, home, "build")
	if code2 == 0 {
		t.Fatalf("build with no repo should fail")
	}
	if !strings.Contains(stderr2, "usage") {
		t.Fatalf("build usage stderr = %q", stderr2)
	}

	stdout, _, code3 := runMindwalk(t, home, "--help")
	if code3 != 0 {
		t.Fatalf("--help exit = %d", code3)
	}
	if !strings.Contains(stdout, "Usage") {
		t.Fatalf("--help stdout = %q", stdout)
	}
}

// TestTraceRejectsUnrecognizedSession confirms `trace` errors (non-zero exit,
// diagnostic on stderr) when handed a JSONL file that matches neither the
// Claude Code nor the Codex session shape, rather than emitting an empty trace.
func TestTraceRejectsUnrecognizedSession(t *testing.T) {
	defer failOnPanic(t)
	session := filepath.Join(t.TempDir(), "mystery.jsonl")
	writeJSONL(t, session,
		`{"kind":"telemetry","value":42}`,
		`{"kind":"telemetry","value":43}`,
	)
	stdout, stderr, code := runMindwalk(t, t.TempDir(), "trace", session)
	if code == 0 {
		t.Fatalf("trace of an unrecognized file should fail; stdout=%q", stdout)
	}
	if !strings.Contains(strings.ToLower(stderr), "not a") {
		t.Fatalf("stderr should explain the rejection: %q", stderr)
	}
}
