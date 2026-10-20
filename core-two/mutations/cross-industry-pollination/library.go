
package candidate

import (
	"errors"
	"sort"
	"strings"
)

const CandidateID = "cross-industry-pollination"

const maxCapabilityTagLength = 128

// NormalizeCapabilityTag canonicalizes a capability tag.
// Tags are case-insensitive, trimmed, ASCII-only identifiers.
// Allowed characters are letters, digits, '.', '_', '-', ':' and '/'.
// A tag must start with a letter or digit.
func NormalizeCapabilityTag(tag string) (string, bool) {
	tag = strings.ToLower(strings.TrimSpace(tag))

	if tag == "" || len(tag) > maxCapabilityTagLength {
		return "", false
	}

	for i := 0; i < len(tag); i++ {
		c := tag[i]

		if isASCIILetter(c) || (c >= '0' && c <= '9') {
			continue
		}

		switch c {
		case '.', '_', '-', ':', '/':
			// These characters are allowed after the first character.
			if i == 0 {
				return "", false
			}
		default:
			return "", false
		}
	}

	return tag, true
}

func isASCIILetter(c byte) bool {
	return (c >= 'a' && c <= 'z') ||
		(c >= 'A' && c <= 'Z')
}

// Shared returns the unique, normalized capability tags present in both
// collections. Invalid tags are ignored. Results are sorted so callers get
// the same output regardless of input order.
//
// This function only compares tags. It does not connect services, transfer
// data, execute source code, deploy components, or grant permissions.
func Shared(a, b []string) []string {
	left := make(map[string]struct{}, len(a))

	for _, raw := range a {
		tag, ok := NormalizeCapabilityTag(raw)
		if !ok {
			continue
		}

		left[tag] = struct{}{}
	}

	matches := make(map[string]struct{})

	for _, raw := range b {
		tag, ok := NormalizeCapabilityTag(raw)
		if !ok {
			continue
		}

		if _, exists := left[tag]; exists {
			matches[tag] = struct{}{}
		}
	}

	out := make([]string, 0, len(matches))
	for tag := range matches {
		out = append(out, tag)
	}

	sort.Strings(out)
	return out
}

// Validate runs deterministic, offline regression fixtures.
func Validate() error {
	got := Shared(
		[]string{"offline", "audit"},
		[]string{"audit", "offline", "agriculture"},
	)

	if len(got) != 2 || got[0] != "audit" || got[1] != "offline" {
		return errors.New("shared capability count or ordering mismatch")
	}

	normalized := Shared(
		[]string{" Offline ", "audit", "offline", "../unsafe"},
		[]string{"AUDIT", "offline", "offline", "", "../unsafe"},
	)

	if len(normalized) != 2 ||
		normalized[0] != "audit" ||
		normalized[1] != "offline" {
		return errors.New("capability normalization or filtering mismatch")
	}

	if _, ok := NormalizeCapabilityTag(strings.Repeat(
		"a", maxCapabilityTagLength+1,
	)); ok {
		return errors.New("oversized capability tag was accepted")
	}

	if _, ok := NormalizeCapabilityTag("../unsafe"); ok {
		return errors.New("malformed capability tag was accepted")
	}

	return nil
}
