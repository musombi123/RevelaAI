
package candidate

import (
	"reflect"
	"strings"
	"testing"
)

func TestProposalFixture(t *testing.T) {
	if err := Validate(); err != nil {
		t.Fatal(err)
	}
}

func TestNormalizeCapabilityTag(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  string
		valid bool
	}{
		{
			name:  "trims and lowercases",
			input: " Agriculture/Water ",
			want:  "agriculture/water",
			valid: true,
		},
		{
			name:  "allows namespaced tags",
			input: "AI:Audit_v2",
			want:  "ai:audit_v2",
			valid: true,
		},
		{
			name:  "rejects empty",
			input: "   ",
			valid: false,
		},
		{
			name:  "rejects path traversal",
			input: "../unsafe",
			valid: false,
		},
		{
			name:  "rejects interior whitespace",
			input: "offline audit",
			valid: false,
		},
		{
			name:  "rejects non ASCII characters",
			input: "agriculturé",
			valid: false,
		},
		{
			name:  "rejects oversized tag",
			input: strings.Repeat("a", maxCapabilityTagLength+1),
			valid: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, valid := NormalizeCapabilityTag(tt.input)

			if valid != tt.valid {
				t.Fatalf("valid = %v, want %v", valid, tt.valid)
			}

			if valid && got != tt.want {
				t.Fatalf("normalized tag = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestSharedNormalizesDeduplicatesAndSorts(t *testing.T) {
	a := []string{
		"offline",
		" Audit ",
		"AUDIT",
		"../unsafe",
		"",
	}

	b := []string{
		"AUDIT",
		"offline",
		"audit",
		"agriculture",
		"offline",
		"../unsafe",
		"",
	}

	want := []string{"audit", "offline"}
	got := Shared(a, b)

	if !reflect.DeepEqual(got, want) {
		t.Fatalf("Shared() = %#v, want %#v", got, want)
	}
}

func TestSharedReturnsEmptyWhenThereIsNoOverlap(t *testing.T) {
	got := Shared(
		[]string{"agriculture", "water"},
		[]string{"audit", "offline"},
	)

	if len(got) != 0 {
		t.Fatalf("Shared() = %#v, want no shared capabilities", got)
	}
}

func TestSharedDoesNotMutateInputs(t *testing.T) {
	a := []string{"offline", "audit"}
	b := []string{"audit", "offline"}

	originalA := append([]string(nil), a...)
	originalB := append([]string(nil), b...)

	_ = Shared(a, b)

	if !reflect.DeepEqual(a, originalA) {
		t.Fatalf("Shared() modified first input: %#v", a)
	}

	if !reflect.DeepEqual(b, originalB) {
		t.Fatalf("Shared() modified second input: %#v", b)
	}
}
