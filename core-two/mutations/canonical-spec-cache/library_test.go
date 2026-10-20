package candidate

import (
	"encoding/json"
	"errors"
	"math"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

func TestProposalFixture(t *testing.T) {
	if err := Validate(); err != nil {
		t.Fatal(err)
	}
}

func TestLegacyFingerprintIsStableAcrossMapKeyOrder(t *testing.T) {
	left := map[string]string{"z": "last", "a": "first", "m": "middle"}
	right := map[string]string{"m": "middle", "z": "last", "a": "first"}

	if got, want := Fingerprint(left), Fingerprint(right); got == "" || got != want {
		t.Fatalf("Fingerprint() = %q, want stable non-empty digest %q", got, want)
	}
}

func TestCanonicalMapRejectsInvalidOrUnboundedInput(t *testing.T) {
	tests := []struct {
		name  string
		input map[string]string
	}{
		{name: "empty key", input: map[string]string{" ": "value"}},
		{name: "invalid UTF-8 key", input: map[string]string{string([]byte{0xff}): "value"}},
		{name: "invalid UTF-8 value", input: map[string]string{"key": string([]byte{0xff})}},
		{name: "oversized value", input: map[string]string{"key": strings.Repeat("x", maxDemandBytes+1)}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if _, err := CanonicalMapJSON(tt.input); err == nil {
				t.Fatal("expected invalid map to be rejected")
			}
			if Fingerprint(tt.input) != "" {
				t.Fatal("invalid map must not produce a fingerprint")
			}
		})
	}

	tooMany := make(map[string]string, MaxMapEntries+1)
	for i := 0; i < MaxMapEntries+1; i++ {
		tooMany[fmt.Sprintf("key-%03d", i)] = "value"
	}
	if _, err := CanonicalMapJSON(tooMany); err == nil {
		t.Fatal("oversized map entry count must be rejected")
	}
}

func TestCanonicalSpecJSONIsStableAndVersioned(t *testing.T) {
	spec := fixtureToolSpec()
	first, err := CanonicalSpecJSON(spec)
	if err != nil {
		t.Fatal(err)
	}
	second, err := CanonicalSpecJSON(spec)
	if err != nil {
		t.Fatal(err)
	}
	if string(first) != string(second) {
		t.Fatal("canonical JSON changed for identical tool specs")
	}

	var envelope struct {
		SchemaVersion int      `json:"schema_version"`
		Spec          ToolSpec `json:"spec"`
	}
	if err := json.Unmarshal(first, &envelope); err != nil {
		t.Fatal(err)
	}
	if envelope.SchemaVersion != CanonicalSchemaVersion {
		t.Fatalf("schema version = %d, want %d", envelope.SchemaVersion, CanonicalSchemaVersion)
	}
	if envelope.Spec.Name != spec.Name || envelope.Spec.Demand != spec.Demand {
		t.Fatalf("canonical envelope lost Core-One ToolSpec data: %+v", envelope.Spec)
	}
}

func TestNilAndEmptyListsShareCanonicalRepresentation(t *testing.T) {
	left := fixtureToolSpec()
	left.Capabilities = nil
	left.Inputs = nil
	left.Outputs = nil
	left.Safeguards = nil

	right := left
	right.Capabilities = []string{}
	right.Inputs = []string{}
	right.Outputs = []string{}
	right.Safeguards = []string{}

	leftJSON, err := CanonicalSpecJSON(left)
	if err != nil {
		t.Fatal(err)
	}
	rightJSON, err := CanonicalSpecJSON(right)
	if err != nil {
		t.Fatal(err)
	}
	if string(leftJSON) != string(rightJSON) {
		t.Fatal("nil and empty list fields should have one canonical representation")
	}
}

func TestFingerprintToolSpecIncludesFullSpecification(t *testing.T) {
	base := fixtureToolSpec()
	baseFingerprint, err := FingerprintToolSpec(base)
	if err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name   string
		change func(*ToolSpec)
	}{
		{name: "purpose", change: func(s *ToolSpec) { s.Purpose += " Updated." }},
		{name: "capabilities", change: func(s *ToolSpec) { s.Capabilities = append(s.Capabilities, "review evidence") }},
		{name: "inputs", change: func(s *ToolSpec) { s.Inputs = append(s.Inputs, "requested_by") }},
		{name: "outputs", change: func(s *ToolSpec) { s.Outputs = append(s.Outputs, "review_state") }},
		{name: "safeguards", change: func(s *ToolSpec) { s.Safeguards = append(s.Safeguards, "offline by default") }},
		{name: "hardware boundary", change: func(s *ToolSpec) { s.NeedsHardwareGuide = true; s.Safeguards = append(s.Safeguards, "qualified review required") }},
		{name: "country metadata", change: func(s *ToolSpec) { s.Country = "KE"; s.CountryName = "Kenya"; s.Language = "en-KE"; s.Currency = "KES" }},
		{name: "voltage metadata", change: func(s *ToolSpec) { s.NominalACVoltage = 240 }},
		{name: "BOM", change: func(s *ToolSpec) { s.BOM = map[string]any{"status": "quoted"} }},
		{name: "model assistance", change: func(s *ToolSpec) { s.ModelAssisted = true; s.ModelNote = "Bounded metadata suggestion only." }},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			changed := base
			changed.BOM = cloneBOM(base.BOM)
			changed.Capabilities = append([]string(nil), base.Capabilities...)
			changed.Inputs = append([]string(nil), base.Inputs...)
			changed.Outputs = append([]string(nil), base.Outputs...)
			changed.Safeguards = append([]string(nil), base.Safeguards...)
			tt.change(&changed)

			got, err := FingerprintToolSpec(changed)
			if err != nil {
				t.Fatal(err)
			}
			if got == baseFingerprint {
				t.Fatal("changing a meaningful tool-spec field must change the fingerprint")
			}
		})
	}
}

func TestFingerprintToolSpecCanonicalizesNestedMapKeyOrder(t *testing.T) {
	left := fixtureToolSpec()
	left.BOM = map[string]any{
		"z": "last",
		"a": map[string]any{"y": 2, "b": 1},
	}
	right := fixtureToolSpec()
	right.BOM = map[string]any{
		"a": map[string]any{"b": 1, "y": 2},
		"z": "last",
	}

	a, err := FingerprintToolSpec(left)
	if err != nil {
		t.Fatal(err)
	}
	b, err := FingerprintToolSpec(right)
	if err != nil {
		t.Fatal(err)
	}
	if a != b {
		t.Fatalf("nested map key order affected fingerprint: %q != %q", a, b)
	}
}

func TestValidateToolSpecRejectsMalformedSpecs(t *testing.T) {
	tests := []struct {
		name   string
		change func(*ToolSpec)
	}{
		{name: "missing name", change: func(s *ToolSpec) { s.Name = "" }},
		{name: "unsafe name", change: func(s *ToolSpec) { s.Name = "../tool" }},
		{name: "missing title", change: func(s *ToolSpec) { s.Title = "  " }},
		{name: "invalid UTF-8", change: func(s *ToolSpec) { s.Title = string([]byte{0xff}) }},
		{name: "oversized demand", change: func(s *ToolSpec) { s.Demand = strings.Repeat("x", maxDemandBytes+1) }},
		{name: "invalid country", change: func(s *ToolSpec) { s.Country = "USA1" }},
		{name: "invalid language", change: func(s *ToolSpec) { s.Language = "en--US" }},
		{name: "invalid currency", change: func(s *ToolSpec) { s.Currency = "US" }},
		{name: "negative voltage", change: func(s *ToolSpec) { s.NominalACVoltage = -1 }},
		{name: "hardware without safeguards", change: func(s *ToolSpec) { s.NeedsHardwareGuide = true; s.Safeguards = nil }},
		{name: "unexplained model assistance", change: func(s *ToolSpec) { s.ModelAssisted = true }},
		{name: "oversized list", change: func(s *ToolSpec) { s.Capabilities = make([]string, MaxListItems+1) }},
		{name: "non-finite BOM number", change: func(s *ToolSpec) { s.BOM = map[string]any{"cost": math.NaN()} }},
		{name: "unsupported BOM type", change: func(s *ToolSpec) { s.BOM = map[string]any{"bad": func() {}} }},
		{name: "invalid UTF-8 BOM value", change: func(s *ToolSpec) { s.BOM = map[string]any{"bad": string([]byte{0xff})} }},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			spec := fixtureToolSpec()
			tt.change(&spec)
			if err := ValidateToolSpec(spec); err == nil {
				t.Fatal("expected malformed tool spec to be rejected")
			}
		})
	}
}

func TestCacheDeduplicatesAndReturnsDefensiveCopies(t *testing.T) {
	cache, err := NewSpecCache(2)
	if err != nil {
		t.Fatal(err)
	}

	spec := fixtureToolSpec()
	fingerprint, inserted, err := cache.Put(spec)
	if err != nil || !inserted {
		t.Fatalf("first Put() = (%q, %v, %v), want inserted", fingerprint, inserted, err)
	}
	fingerprintAgain, inserted, err := cache.Put(spec)
	if err != nil || inserted || fingerprintAgain != fingerprint {
		t.Fatalf("duplicate Put() = (%q, %v, %v), want exact cache hit", fingerprintAgain, inserted, err)
	}

	raw, ok, err := cache.Lookup(fingerprint)
	if err != nil || !ok {
		t.Fatalf("Lookup() = (ok=%v, err=%v), want hit", ok, err)
	}
	raw[0] ^= 0xff
	again, ok, err := cache.Lookup(fingerprint)
	if err != nil || !ok {
		t.Fatalf("second Lookup() = (ok=%v, err=%v), want hit", ok, err)
	}
	if len(again) == 0 || again[0] == raw[0] {
		t.Fatal("caller modified the cache through a returned byte slice")
	}
	if cache.Len() != 1 {
		t.Fatalf("Len() = %d, want 1", cache.Len())
	}
}

func TestCacheIsBoundedAndRejectsMalformedKeys(t *testing.T) {
	if _, err := NewSpecCache(0); err == nil {
		t.Fatal("zero-capacity cache must be rejected")
	}
	if _, err := NewSpecCache(MaxCacheEntries + 1); err == nil {
		t.Fatal("capacity above hard limit must be rejected")
	}

	cache, err := NewSpecCache(1)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := cache.Put(fixtureToolSpec()); err != nil {
		t.Fatal(err)
	}

	second := fixtureToolSpec()
	second.Purpose += " A distinct specification."
	if _, _, err := cache.Put(second); !errors.Is(err, ErrCacheFull) {
		t.Fatalf("Put() error = %v, want ErrCacheFull", err)
	}

	for _, key := range []string{"", "not-a-digest", strings.Repeat("A", 64), strings.Repeat("z", 64)} {
		if _, _, err := cache.Lookup(key); !errors.Is(err, ErrInvalidFingerprint) {
			t.Fatalf("Lookup(%q) error = %v, want ErrInvalidFingerprint", key, err)
		}
	}
	if _, ok, err := cache.Lookup(strings.Repeat("0", 64)); err != nil || ok {
		t.Fatalf("missing key Lookup() = (ok=%v, err=%v), want miss", ok, err)
	}
}

func TestCacheConcurrentPutIsSafe(t *testing.T) {
	cache, err := NewSpecCache(8)
	if err != nil {
		t.Fatal(err)
	}
	const workers = 64
	var wg sync.WaitGroup
	var inserts atomic.Int32
	errs := make(chan error, workers)

	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			fingerprint, inserted, err := cache.Put(fixtureToolSpec())
			if err != nil {
				errs <- err
				return
			}
			if fingerprint == "" {
				errs <- errors.New("empty fingerprint")
				return
			}
			if inserted {
				inserts.Add(1)
			}
			if _, ok, err := cache.Lookup(fingerprint); err != nil || !ok {
				errs <- errors.New("concurrent lookup failed")
			}
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Error(err)
	}
	if got := inserts.Load(); got != 1 {
		t.Fatalf("number of inserts = %d, want exactly 1", got)
	}
	if cache.Len() != 1 {
		t.Fatalf("cache Len() = %d, want 1", cache.Len())
	}
}

func FuzzFingerprintIsDeterministic(f *testing.F) {
	f.Add("alpha", "one")
	f.Add("unicode", "Mombasa")
	f.Add("", "value")
	f.Fuzz(func(t *testing.T, key, value string) {
		if len(key) > maxNameBytes*4 || len(value) > maxDemandBytes {
			return
		}
		input := map[string]string{key: value}
		first, err := CanonicalMapJSON(input)
		if err != nil {
			return
		}
		second, err := CanonicalMapJSON(input)
		if err != nil {
			t.Fatal(err)
		}
		if string(first) != string(second) || Fingerprint(input) == "" {
			t.Fatal("canonical map output or fingerprint was unstable")
		}
	})
}

func cloneBOM(input map[string]any) map[string]any {
	if input == nil {
		return nil
	}
	copy := make(map[string]any, len(input))
	for key, value := range input {
		copy[key] = value
	}
	return copy
}
