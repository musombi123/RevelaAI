package mind

import (
	"go/parser"
	"go/token"
	"strings"
	"testing"
)

func TestCompileProducesPlanNotExecution(t *testing.T) {
	result, err := Compile("scan\nheal \"src/example.py\"\nassemble esp32-sensor")
	if err != nil {
		t.Fatal(err)
	}

	if len(result.Operations) != 3 {
		t.Fatalf("expected 3 operations, got %d", len(result.Operations))
	}

	if result.Status != "plan_generated_pending_review" {
		t.Fatalf("unexpected status: %q", result.Status)
	}

	if result.Executed {
		t.Fatal("compiler must never report operations as executed")
	}

	if !result.HumanApprovalRequired {
		t.Fatal("compiled plan must require human approval")
	}

	if result.Operations[0].Verb != "scan" ||
		result.Operations[1].Verb != "heal" ||
		result.Operations[2].Verb != "assemble" {
		t.Fatalf("unexpected operation sequence: %#v", result.Operations)
	}

	if result.Operations[1].Args[0] != "src/example.py" {
		t.Fatalf("unexpected heal argument: %#v", result.Operations[1].Args)
	}

	if result.Operations[0].Line != 1 ||
		result.Operations[1].Line != 2 ||
		result.Operations[2].Line != 3 {
		t.Fatalf("source line numbers were not preserved: %#v", result.Operations)
	}

	if len(Keywords) > 20 {
		t.Fatalf("unexpected keyword count: %d", len(Keywords))
	}

	if !strings.Contains(result.GoSource, "var Plan = []Operation{") {
		t.Fatal("generated Go plan declaration is missing")
	}
}

func TestUnknownCommandRejected(t *testing.T) {
	_, err := Compile("shell rm -rf /\n")
	if err == nil {
		t.Fatal("unknown command should fail")
	}
}

func TestCommandsAreCaseInsensitive(t *testing.T) {
	result, err := Compile("SCAN\nHEAL example.py\nAsSeMbLe sensor")
	if err != nil {
		t.Fatal(err)
	}

	expected := []string{"scan", "heal", "assemble"}
	for i, want := range expected {
		if result.Operations[i].Verb != want {
			t.Fatalf(
				"operation %d: got %q, want %q",
				i,
				result.Operations[i].Verb,
				want,
			)
		}
	}
}

func TestBlankLinesAndWholeLineCommentsAreIgnored(t *testing.T) {
	source := `
# Initial inventory

scan

    # Recovery proposal
heal "src/example.py"

`

	result, err := Compile(source)
	if err != nil {
		t.Fatal(err)
	}

	if len(result.Operations) != 2 {
		t.Fatalf("expected 2 operations, got %d", len(result.Operations))
	}

	if result.Operations[0].Line != 4 || result.Operations[1].Line != 7 {
		t.Fatalf("incorrect original line numbers: %#v", result.Operations)
	}
}

func TestEmptySourceAndCommentsOnlySourceRejected(t *testing.T) {
	cases := []string{
		"",
		" \n\t\n",
		"# comment only",
		"# first comment\n\n  # second comment",
	}

	for _, source := range cases {
		t.Run("empty_or_comments", func(t *testing.T) {
			if _, err := Compile(source); err == nil {
				t.Fatalf("expected empty plan to be rejected: %q", source)
			}
		})
	}
}

func TestCommandsRequireArgumentsExceptScan(t *testing.T) {
	if _, err := Compile("heal"); err == nil {
		t.Fatal("heal without an argument should fail")
	}

	if _, err := Compile("assemble"); err == nil {
		t.Fatal("assemble without an argument should fail")
	}

	if _, err := Compile("forge"); err == nil {
		t.Fatal("forge without an argument should fail")
	}

	result, err := Compile("scan")
	if err != nil {
		t.Fatalf("scan without arguments should be supported: %v", err)
	}

	if result.Operations[0].Verb != "scan" {
		t.Fatalf("unexpected operation: %#v", result.Operations[0])
	}
}

func TestEmptyFirstArgumentRejected(t *testing.T) {
	cases := []string{
		`heal ""`,
		`assemble ''`,
		`forge ""`,
	}

	for _, source := range cases {
		t.Run(source, func(t *testing.T) {
			if _, err := Compile(source); err == nil {
				t.Fatalf("expected empty first argument to be rejected: %q", source)
			}
		})
	}
}

func TestQuotedArgumentsPreserveSpacesAndEscapes(t *testing.T) {
	source := `heal "src/my file.py"
assemble 'board version' with "sensor suite"
forge "say \"hello\"" 
bridge "C:\\temp\\file.py"`

	result, err := Compile(source)
	if err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		operation int
		arg       int
		expected  string
	}{
		{0, 0, "src/my file.py"},
		{1, 0, "board version"},
		{1, 2, "sensor suite"},
		{2, 0, `say "hello"`},
		{3, 0, `C:\temp\file.py`},
	}

	for _, test := range tests {
		actual := result.Operations[test.operation].Args[test.arg]
		if actual != test.expected {
			t.Errorf(
				"operation %d argument %d: got %q, want %q",
				test.operation,
				test.arg,
				actual,
				test.expected,
			)
		}
	}
}

func TestUnterminatedQuotesAndEscapesRejected(t *testing.T) {
	cases := []struct {
		name   string
		source string
	}{
		{
			name:   "unclosed double quote",
			source: `heal "src/example.py`,
		},
		{
			name:   "unclosed single quote",
			source: `heal 'src/example.py`,
		},
		{
			name:   "trailing escape in quoted string",
			source: `heal "src/example.py\`,
		},
	}

	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			if _, err := Compile(test.source); err == nil {
				t.Fatalf("invalid quoted source should fail: %q", test.source)
			}
		})
	}
}

func TestGeneratedGoSourceIsSyntacticallyValid(t *testing.T) {
	source := `scan
heal "src/example.py"
assemble "sensor board"
forge "say \"hello\""`

	result, err := Compile(source)
	if err != nil {
		t.Fatal(err)
	}

	_, err = parser.ParseFile(
		token.NewFileSet(),
		"generated_plan.go",
		result.GoSource,
		parser.AllErrors,
	)
	if err != nil {
		t.Fatalf("generated Go source is invalid: %v\n%s", err, result.GoSource)
	}
}

func TestArgumentCannotInjectGoStatementsIntoGeneratedSource(t *testing.T) {
	source := `heal "x\"}, os.Exit(1) //"`

	result, err := Compile(source)
	if err != nil {
		t.Fatal(err)
	}

	if len(result.Operations) != 1 || len(result.Operations[0].Args) != 1 {
		t.Fatalf("unexpected parsed plan: %#v", result.Operations)
	}

	if result.Operations[0].Args[0] != `x"}, os.Exit(1) //` {
		t.Fatalf("argument was not preserved: %q", result.Operations[0].Args[0])
	}

	_, err = parser.ParseFile(
		token.NewFileSet(),
		"generated_plan.go",
		result.GoSource,
		parser.AllErrors,
	)
	if err != nil {
		t.Fatalf("injection-shaped argument broke generated Go syntax: %v", err)
	}

	if strings.Contains(result.GoSource, "func main()") ||
		strings.Contains(result.GoSource, "exec.Command") {
		t.Fatal("generated plan must not introduce an executable entry point or command runner")
	}

	if result.Executed {
		t.Fatal("compilation must never execute input")
	}
}

func TestMaximumSourceBytesEnforced(t *testing.T) {
	source := strings.Repeat(" ", maxSourceBytes+1)

	if _, err := Compile(source); err == nil {
		t.Fatal("source exceeding maximum byte size should fail")
	}
}

func TestMaximumSourceLinesEnforced(t *testing.T) {
	source := strings.Repeat("\n", maxSourceLines)

	if _, err := Compile(source); err == nil {
		t.Fatal("source exceeding maximum line count should fail")
	}
}

func TestMaximumLineBytesEnforced(t *testing.T) {
	source := strings.Repeat("x", maxLineBytes+1)

	if _, err := Compile(source); err == nil {
		t.Fatal("line exceeding maximum byte size should fail")
	}
}

func TestMaximumArgumentBytesEnforced(t *testing.T) {
	argument := strings.Repeat("a", maxArgumentBytes+1)
	source := `heal "` + argument + `"`

	if _, err := Compile(source); err == nil {
		t.Fatal("argument exceeding maximum byte size should fail")
	}
}

func TestMaximumOperationsEnforced(t *testing.T) {
	source := strings.Repeat("scan\n", maxOperations+1)

	if _, err := Compile(source); err == nil {
		t.Fatal("source exceeding maximum operation count should fail")
	}
}

func TestMaximumArgumentsEnforced(t *testing.T) {
	tokens := []string{"forge"}
	for i := 0; i <= maxArguments; i++ {
		tokens = append(tokens, "arg")
	}

	if _, err := Compile(strings.Join(tokens, " ")); err == nil {
		t.Fatal("command exceeding maximum argument count should fail")
	}
}

func TestInvalidUTF8Rejected(t *testing.T) {
	source := string([]byte{'s', 'c', 'a', 'n', '\n', 0xff})

	if _, err := Compile(source); err == nil {
		t.Fatal("invalid UTF-8 must be rejected")
	}
}

func TestUnsupportedControlCharactersRejected(t *testing.T) {
	source := "scan\x00"

	if _, err := Compile(source); err == nil {
		t.Fatal("NUL control character should be rejected")
	}
}

func TestErrorReportsSourceLine(t *testing.T) {
	_, err := Compile("scan\n\nunknown_command argument")
	if err == nil {
		t.Fatal("expected unknown command to fail")
	}

	if !strings.Contains(err.Error(), "line 3") {
		t.Fatalf("expected line number in error, got %q", err.Error())
	}
}

func TestCompilationResultAlwaysRequiresReview(t *testing.T) {
	sources := []string{
		"scan",
		"heal src/example.py",
		"assemble sensor",
		"forge module",
		"approve proposal-1",
		"audit event-1",
	}

	for _, source := range sources {
		t.Run(source, func(t *testing.T) {
			result, err := Compile(source)
			if err != nil {
				t.Fatal(err)
			}

			if result.Executed {
				t.Fatal("compiled plan incorrectly claims execution")
			}

			if !result.HumanApprovalRequired {
				t.Fatal("compiled plan must require human approval")
			}

			if result.Status != "plan_generated_pending_review" {
				t.Fatalf("unexpected status: %q", result.Status)
			}
		})
	}
}
