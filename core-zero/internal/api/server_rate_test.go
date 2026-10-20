package api

import "testing"

func TestScopeRateLimitIsPerKeyAndPerScope(t *testing.T) {
	s := &Server{}
	for i := 0; i < scopeRateLimit; i++ {
		if !s.allowScopeRate("key-a", "scan:read") {
			t.Fatalf("request %d unexpectedly denied", i+1)
		}
	}
	if s.allowScopeRate("key-a", "scan:read") {
		t.Fatal("request beyond the per-scope limit was allowed")
	}
	if !s.allowScopeRate("key-a", "radar:compare") {
		t.Fatal("a different scope should have an independent limit")
	}
	if !s.allowScopeRate("key-b", "scan:read") {
		t.Fatal("a different key should have an independent limit")
	}
}
