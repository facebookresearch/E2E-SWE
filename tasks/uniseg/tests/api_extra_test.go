// Hidden grading for the previously-untested unified iterator and helpers:
// StepString (asserted for internal consistency with the independently-graded
// specialized functions — non-circular: a broken Step becomes inconsistent) and
// HasTrailingLineBreak (LB4/LB5). Public API only.
package uniseg_test

import (
	"testing"

	uniseg "github.com/rivo/uniseg"
)

func sameSet(a, b map[int]bool) bool {
	if len(a) != len(b) {
		return false
	}
	for k := range a {
		if !b[k] {
			return false
		}
	}
	return true
}

// wordOffsets / sentenceOffsets return the set of byte offsets at the end of each
// word / sentence, per the specialized First* iterators (which are graded against
// the official vectors elsewhere).
func wordOffsets(s string) map[int]bool {
	m := map[int]bool{}
	off, state := 0, -1
	for len(s) > 0 {
		var seg string
		seg, s, state = uniseg.FirstWordInString(s, state)
		off += len(seg)
		m[off] = true
	}
	return m
}

func sentenceOffsets(s string) map[int]bool {
	m := map[int]bool{}
	off, state := 0, -1
	for len(s) > 0 {
		var seg string
		seg, s, state = uniseg.FirstSentenceInString(s, state)
		off += len(seg)
		m[off] = true
	}
	return m
}

// graphemeOffsets returns the set of byte offsets at each grapheme-cluster boundary.
func graphemeOffsets(s string) map[int]bool {
	m := map[int]bool{}
	off := 0
	g := uniseg.NewGraphemes(s)
	for g.Next() {
		off += len(g.Str())
		m[off] = true
	}
	return m
}

// intersect returns the elements of a that are also in b.
func intersect(a, b map[int]bool) map[int]bool {
	m := map[int]bool{}
	for k := range a {
		if b[k] {
			m[k] = true
		}
	}
	return m
}

// TestStepStringConsistency verifies that the unified StepString iterator agrees
// with the specialized functions and with StringWidth on every input: identical
// grapheme-cluster sequence, identical word- and sentence-boundary positions, and
// identical total width. (Line breaks are intentionally excluded: FirstLineSegment
// may break within grapheme clusters, whereas Step reports at cluster boundaries.)
func TestStepStringConsistency(t *testing.T) {
	fails := 0
	for _, s := range stepInputs {
		var stepClusters [][]rune
		wordB := map[int]bool{}
		sentB := map[int]bool{}
		totalW := 0
		off := 0
		state := -1
		rest := s
		for len(rest) > 0 {
			var cl string
			var b int
			cl, rest, b, state = uniseg.StepString(rest, state)
			stepClusters = append(stepClusters, []rune(cl))
			off += len(cl)
			if b&uniseg.MaskWord != 0 {
				wordB[off] = true
			}
			if b&uniseg.MaskSentence != 0 {
				sentB[off] = true
			}
			totalW += b >> uniseg.ShiftWidth
		}
		// Step reports word/sentence boundaries only at grapheme-cluster boundaries,
		// so the expected set is the specialized boundary set intersected with the
		// grapheme boundaries.
		gOff := graphemeOffsets(s)
		bad := ""
		if !segEqual(stepClusters, segGraphemes(s)) {
			bad = "grapheme clusters"
		} else if totalW != uniseg.StringWidth(s) {
			bad = "total width"
		} else if !sameSet(wordB, intersect(wordOffsets(s), gOff)) {
			bad = "word boundaries"
		} else if !sameSet(sentB, intersect(sentenceOffsets(s), gOff)) {
			bad = "sentence boundaries"
		}
		if bad != "" {
			fails++
			if fails <= 8 {
				t.Errorf("StepString %q: inconsistent %s", s, bad)
			}
		}
	}
	if fails > 8 {
		t.Errorf("... and %d more (of %d)", fails-8, len(stepInputs))
	}
}

// TestHasTrailingLineBreak covers LB4/LB5 mandatory-break detection: true iff the
// last rune has line-break class BK, CR, LF, or NL.
func TestHasTrailingLineBreak(t *testing.T) {
	cases := []struct {
		s    string
		want bool
	}{
		{"", false},
		{"a", false},
		{"abc", false},
		{"a ", false},
		{"line1\nline2", false},
		{"a\n", true},       // LF
		{"a\r", true},       // CR
		{"a\r\n", true},    // CRLF
		{"a\v", true},       // VT (BK)
		{"a\f", true},       // FF (BK)
		{"a\u0085", true},   // NEL (NL)
		{"a\u2028", true},   // LINE SEPARATOR (BK)
		{"a\u2029", true},   // PARAGRAPH SEPARATOR (BK)
	}
	for _, c := range cases {
		if got := uniseg.HasTrailingLineBreakInString(c.s); got != c.want {
			t.Errorf("HasTrailingLineBreakInString(%q) = %v, want %v", c.s, got, c.want)
		}
		if got := uniseg.HasTrailingLineBreak([]byte(c.s)); got != c.want {
			t.Errorf("HasTrailingLineBreak(%q) = %v, want %v", c.s, got, c.want)
		}
	}
}
