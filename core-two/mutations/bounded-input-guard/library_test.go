package candidate

import (
	"strings"
	"testing"
)

func TestProposalFixture(t *testing.T) {
	if err := Validate(); err != nil {
		t.Fatal(err)
	}
}

func TestValidateInput(t *testing.T) {
	tests := []struct {
		name  string
		input string
		valid bool
	}{
		{name: "ordinary text", input: "safe input", valid: true},
		{name: "relative POSIX path", input: "docs/report.txt", valid: true},
		{name: "relative Windows path", input: `docs\report.txt`, valid: true},
		{name: "maximum byte length", input: strings.Repeat("x", MaxInputBytes), valid: true},
		{name: "empty", input: "", valid: false},
		{name: "oversized", input: strings.Repeat("x", MaxInputBytes+1), valid: false},
		{name: "NUL byte", input: "safe\x00unsafe", valid: false},
		{name: "POSIX absolute", input: "/etc/passwd", valid: false},
		{name: "Windows rooted", input: `\rooted\path`, valid: false},
		{name: "UNC path", input: `\\server\share`, valid: false},
		{name: "Windows drive absolute", input: `C:\Windows\system.ini`, valid: false},
		{name: "Windows drive relative", input: "C:relative", valid: false},
		{name: "parent segment only", input: "..", valid: false},
		{name: "leading traversal", input: "../outside", valid: false},
		{name: "nested POSIX traversal", input: "folder/../outside", valid: false},
		{name: "nested Windows traversal", input: `folder\..\outside`, valid: false},
		{name: "mixed separator traversal", input: "folder/..\\outside", valid: false},
		{name: "trailing traversal segment", input: "folder/..", valid: false},
		{name: "similar but not parent segment", input: "folder/.../report", valid: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := ValidateInput(tt.input)
			if got := err == nil; got != tt.valid {
				t.Fatalf("ValidateInput(%q) valid = %v, want %v (err: %v)", tt.input, got, tt.valid, err)
			}
			if got := ValidInput(tt.input); got != tt.valid {
				t.Fatalf("ValidInput(%q) = %v, want %v", tt.input, got, tt.valid)
			}
		})
	}
}

func FuzzValidInputRejectsParentTraversal(f *testing.F) {
	for _, seed := range []string{
		"..",
		"../outside",
		`..\outside`,
		"folder/../outside",
		`folder\..\outside`,
		"folder/..\\outside",
		"folder/..",
	} {
		f.Add(seed)
	}

	f.Fuzz(func(t *testing.T, input string) {
		if len(input) > MaxInputBytes || strings.IndexByte(input, 0) >= 0 {
			return
		}
		if containsParentTraversalSegment(input) && ValidInput(input) {
			t.Fatalf("parent-directory path segment was accepted: %q", input)
		}
	})
}

func containsParentTraversalSegment(input string) bool {
	normalized := strings.ReplaceAll(input, `\`, "/")
	for _, segment := range strings.Split(normalized, "/") {
		if segment == ".." {
			return true
		}
	}
	return false
}
