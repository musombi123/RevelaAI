package candidate

import (
	"errors"
	"strings"
)

const CandidateID = "bounded-input-guard"

// MaxInputBytes bounds the raw input by its UTF-8 byte length (Go string length).
const MaxInputBytes = 4096

// ValidateInput rejects empty or oversized input, NUL bytes, absolute path
// forms on POSIX and Windows, and any path component equal to "..".
//
// This is a lexical input guard, not a filesystem sandbox. Call it after the
// input's intended decoding/normalization step, and still enforce destination
// root containment when using the value as a filesystem path.
func ValidateInput(s string) error {
	if s == "" {
		return errors.New("input is empty")
	}
	if len(s) > MaxInputBytes {
		return errors.New("input exceeds maximum byte length")
	}
	if strings.IndexByte(s, 0) >= 0 {
		return errors.New("input contains a NUL byte")
	}
	if isAbsolutePathLike(s) {
		return errors.New("absolute paths are not allowed")
	}
	if hasParentTraversalSegment(s) {
		return errors.New("parent-directory path segments are not allowed")
	}
	return nil
}

// ValidInput preserves the original boolean API for mutation fixtures and callers.
func ValidInput(s string) bool {
	return ValidateInput(s) == nil
}

func isAbsolutePathLike(s string) bool {
	// A leading slash or backslash catches POSIX-rooted, Windows-rooted,
	// UNC, and extended Windows device paths.
	if strings.HasPrefix(s, "/") || strings.HasPrefix(s, `\`) {
		return true
	}

	// Reject drive-qualified and drive-relative Windows paths (for example,
	// C:\\private and C:relative), regardless of the host operating system.
	return len(s) >= 2 &&
		isASCIIAlpha(s[0]) &&
		s[1] == ':'
}

func isASCIIAlpha(c byte) bool {
	return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
}

func hasParentTraversalSegment(s string) bool {
	// Treat both separator styles as delimiters so the guard behaves
	// consistently when fixtures are evaluated on Unix or Windows.
	start := 0
	for i := 0; i <= len(s); i++ {
		if i != len(s) && s[i] != '/' && s[i] != '\\' {
			continue
		}
		if s[start:i] == ".." {
			return true
		}
		start = i + 1
	}
	return false
}

// Validate runs deterministic, offline regression fixtures.
func Validate() error {
	valid := []string{
		"safe input",
		"relative/file.txt",
		`relative\file.txt`,
		strings.Repeat("x", MaxInputBytes),
	}
	for _, input := range valid {
		if !ValidInput(input) {
			return errors.New("valid input was rejected")
		}
	}

	invalid := []string{
		"",
		strings.Repeat("x", MaxInputBytes+1),
		"bad\x00input",
		"/etc/passwd",
		`\rooted\path`,
		`C:\Windows\system.ini`,
		"C:relative",
		"..",
		"../outside",
		"folder/../outside",
		`folder\..\outside`,
		"folder/..",
		"folder/..\\outside",
	}
	for _, input := range invalid {
		if ValidInput(input) {
			return errors.New("unsafe input was accepted")
		}
	}
	return nil
}
