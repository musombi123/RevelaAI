package rvx

import "testing"

func TestCompileKnownVerbs(t *testing.T) {
	p, err := Compile("research open sources\nforge reusable library\nprotect consent\nawait human merge")
	if err != nil { t.Fatal(err) }
	if p.Count != 4 || p.Mode != "declarative_ir_only" { t.Fatalf("unexpected program: %+v", p) }
}
func TestCompileRejectsUnknownAndCodeBlocks(t *testing.T) {
	if _, err := Compile("execute rm -rf /"); err == nil { t.Fatal("unknown keyword must be rejected") }
	if _, err := Compile("create tool; execute program"); err == nil { t.Fatal("statement separators must be rejected") }
}
func TestTwentyKeywords(t *testing.T) {
	if len(Keywords) != 20 { t.Fatalf("expected 20 language keywords, got %d", len(Keywords)) }
}
