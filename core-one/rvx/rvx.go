// Package rvx provides a deliberately small, non-executing RVX parser/compiler.
// It compiles declarative verbs into a bounded JSON intermediate representation,
// not native code, WebAssembly, shell commands, or executable instructions.
package rvx

import (
	"errors"
	"fmt"
	"strings"
	"unicode"
	"unicode/utf8"
)

const (
	LanguageName    = "RVX"
	LanguageVersion = "0.1"
	CompileMode     = "declarative_ir_only"

	MaxSourceBytes      = 16 * 1024
	MaxSourceLines      = 128
	MaxInstructions     = 128
	MaxArgumentRunes    = 1000
	MaxArgumentBytes    = 4096
	MaxInstructionCount = MaxInstructions
)

const compileNotice = "Compiled to a bounded JSON intermediate representation only. No instruction was executed; this is not encrypted WASM."

// Keywords is the public RVX keyword catalogue.
//
// Compile deliberately uses its own private allowlist so another package
// cannot enable new compiler operations by mutating this exported slice.
var Keywords = []string{
	"create",
	"innovate",
	"transform",
	"change",
	"emerge",
	"move",
	"adopt",
	"protect",
	"block",
	"evolve",
	"forge",
	"research",
	"compose",
	"validate",
	"test",
	"explain",
	"expose",
	"guide",
	"await",
	"merge",
}

var supportedKeywords = map[string]struct{}{
	"create":    {},
	"innovate":  {},
	"transform": {},
	"change":    {},
	"emerge":    {},
	"move":      {},
	"adopt":     {},
	"protect":   {},
	"block":     {},
	"evolve":    {},
	"forge":     {},
	"research":  {},
	"compose":   {},
	"validate":  {},
	"test":      {},
	"explain":   {},
	"expose":    {},
	"guide":     {},
	"await":     {},
	"merge":     {},
}

var argumentRequired = map[string]struct{}{
	"block":    {},
	"protect":  {},
	"await":    {},
	"create":   {},
	"forge":    {},
	"research": {},
	"compose":  {},
	"expose":   {},
	"guide":    {},
}

// Instruction represents one declarative instruction.
//
// Argument is data only. This package never executes it or interprets it
// as Go, shell, SQL, JavaScript, native code, or another executable language.
type Instruction struct {
	Op       string `json:"op"`
	Argument string `json:"argument,omitempty"`
	Line     int    `json:"line"`
}

// Program is the bounded JSON intermediate representation returned by Compile.
type Program struct {
	Language string        `json:"language"`
	Version  string        `json:"version"`
	Mode     string        `json:"mode"`
	Count    int           `json:"count"`
	Code     []Instruction `json:"code"`
	Notice   string        `json:"notice"`
}

// Compile parses RVX source into a declarative intermediate representation.
//
// Supported syntax:
//   - One instruction per line.
//   - The first whitespace-delimited token is the keyword.
//   - Remaining text is a single bounded argument.
//   - Lines beginning with # after whitespace are comments.
//   - Statement separators and code-block delimiters are not supported.
//
// The compiler never executes instructions.
func Compile(source string) (Program, error) {
	if !utf8.ValidString(source) {
		return Program{}, errors.New("RVX source is not valid UTF-8")
	}

	// Allow a UTF-8 BOM at the beginning of a source file.
	source = strings.TrimPrefix(source, "\uFEFF")

	if strings.TrimSpace(source) == "" {
		return Program{}, errors.New("RVX source is empty")
	}

	if len(source) > MaxSourceBytes {
		return Program{}, fmt.Errorf(
			"RVX source exceeds %d bytes",
			MaxSourceBytes,
		)
	}

	if err := validateSourceCharacters(source); err != nil {
		return Program{}, err
	}

	// Accept normal Windows line endings while rejecting stray carriage
	// returns, which can otherwise make line parsing inconsistent.
	source = strings.ReplaceAll(source, "\r\n", "\n")
	if strings.ContainsRune(source, '\r') {
		return Program{}, errors.New("RVX source contains an unsupported carriage return")
	}

	lines := strings.Split(source, "\n")
	lineCount := len(lines)

	// A single trailing newline terminates the previous line and should not
	// count as an additional source line.
	if strings.HasSuffix(source, "\n") {
		lineCount--
	}

	if lineCount > MaxSourceLines {
		return Program{}, fmt.Errorf(
			"RVX source exceeds %d lines",
			MaxSourceLines,
		)
	}

	code := make([]Instruction, 0, minRVXInt(lineCount, MaxInstructions))

	for index, originalLine := range lines {
		lineNumber := index + 1
		line := strings.TrimSpace(originalLine)

		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		if strings.ContainsAny(line, ";{}") {
			return Program{}, fmt.Errorf(
				"line %d: statement separators and code blocks are not supported",
				lineNumber,
			)
		}

		op, argument := splitInstruction(line)
		op = strings.ToLower(op)

		if _, ok := supportedKeywords[op]; !ok {
			return Program{}, fmt.Errorf(
				"line %d: unsupported RVX keyword %q",
				lineNumber,
				op,
			)
		}

		argument, err := normalizeArgument(argument)
		if err != nil {
			return Program{}, fmt.Errorf("line %d: %w", lineNumber, err)
		}

		if err := validateInstruction(op, argument); err != nil {
			return Program{}, fmt.Errorf("line %d: %w", lineNumber, err)
		}

		if len(code) >= MaxInstructions {
			return Program{}, fmt.Errorf(
				"line %d: RVX source exceeds %d instructions",
				lineNumber,
				MaxInstructions,
			)
		}

		code = append(code, Instruction{
			Op:       op,
			Argument: argument,
			Line:     lineNumber,
		})
	}

	if len(code) == 0 {
		return Program{}, errors.New("RVX source contains no instructions")
	}

	program := Program{
		Language: LanguageName,
		Version:  LanguageVersion,
		Mode:     CompileMode,
		Count:    len(code),
		Code:     code,
		Notice:   compileNotice,
	}

	// Treat the compiler's own output as data that must satisfy the same
	// invariants expected of an externally supplied program.
	if err := ValidateProgram(program); err != nil {
		return Program{}, fmt.Errorf("internal RVX validation failed: %w", err)
	}

	return program, nil
}

// ValidateProgram validates a compiled or deserialized program without
// executing it. Call this before passing externally supplied IR to another
// component that consumes RVX programs.
func ValidateProgram(program Program) error {
	if program.Language != LanguageName {
		return fmt.Errorf("unsupported RVX language %q", program.Language)
	}

	if program.Version != LanguageVersion {
		return fmt.Errorf("unsupported RVX version %q", program.Version)
	}

	if program.Mode != CompileMode {
		return fmt.Errorf("unsupported RVX compilation mode %q", program.Mode)
	}

	if len(program.Code) == 0 {
		return errors.New("RVX program contains no instructions")
	}

	if len(program.Code) > MaxInstructions {
		return fmt.Errorf(
			"RVX program exceeds %d instructions",
			MaxInstructions,
		)
	}

	if program.Count != len(program.Code) {
		return fmt.Errorf(
			"RVX instruction count mismatch: declared %d, actual %d",
			program.Count,
			len(program.Code),
		)
	}

	if len(program.Notice) > 1000 || !utf8.ValidString(program.Notice) {
		return errors.New("RVX program notice is invalid or too large")
	}

	previousLine := 0

	for index, instruction := range program.Code {
		prefix := fmt.Sprintf("instruction %d", index+1)

		if instruction.Line < 1 || instruction.Line > MaxSourceLines {
			return fmt.Errorf("%s has an invalid source line", prefix)
		}

		if instruction.Line <= previousLine {
			return fmt.Errorf(
				"%s has a duplicate or out-of-order source line",
				prefix,
			)
		}
		previousLine = instruction.Line

		op := strings.ToLower(strings.TrimSpace(instruction.Op))
		if op != instruction.Op {
			return fmt.Errorf("%s has a non-normalized keyword", prefix)
		}

		if _, ok := supportedKeywords[op]; !ok {
			return fmt.Errorf("%s contains unsupported keyword %q", prefix, op)
		}

		argument, err := normalizeArgument(instruction.Argument)
		if err != nil {
			return fmt.Errorf("%s: %w", prefix, err)
		}

		if argument != instruction.Argument {
			return fmt.Errorf("%s has a non-normalized argument", prefix)
		}

		if err := validateInstruction(op, argument); err != nil {
			return fmt.Errorf("%s: %w", prefix, err)
		}
	}

	return nil
}

func splitInstruction(line string) (string, string) {
	for index, r := range line {
		if unicode.IsSpace(r) {
			return line[:index], strings.TrimSpace(line[index:])
		}
	}

	return line, ""
}

func normalizeArgument(argument string) (string, error) {
	if !utf8.ValidString(argument) {
		return "", errors.New("argument is not valid UTF-8")
	}

	argument = strings.TrimSpace(argument)

	if len(argument) > MaxArgumentBytes {
		return "", fmt.Errorf(
			"argument exceeds %d bytes",
			MaxArgumentBytes,
		)
	}

	if utf8.RuneCountInString(argument) > MaxArgumentRunes {
		return "", fmt.Errorf(
			"argument exceeds %d characters",
			MaxArgumentRunes,
		)
	}

	var normalized strings.Builder
	normalized.Grow(len(argument))

	spacePending := false

	for _, r := range argument {
		if unicode.IsControl(r) {
			if unicode.IsSpace(r) {
				spacePending = normalized.Len() > 0
				continue
			}

			return "", errors.New("argument contains unsupported control characters")
		}

		if unicode.IsSpace(r) {
			spacePending = normalized.Len() > 0
			continue
		}

		if spacePending {
			normalized.WriteByte(' ')
			spacePending = false
		}

		normalized.WriteRune(r)
	}

	result := normalized.String()

	if len(result) > MaxArgumentBytes {
		return "", fmt.Errorf("normalized argument exceeds %d bytes", MaxArgumentBytes)
	}
	if utf8.RuneCountInString(result) > MaxArgumentRunes {
		return "", fmt.Errorf(
			"normalized argument exceeds %d characters",
			MaxArgumentRunes,
		)
	}

	return result, nil
}

func validateInstruction(op, argument string) error {
	if _, ok := supportedKeywords[op]; !ok {
		return fmt.Errorf("unsupported RVX keyword %q", op)
	}

	if strings.ContainsAny(argument, ";{}") {
		return errors.New("statement separators and code blocks are not supported")
	}

	if _, required := argumentRequired[op]; required && argument == "" {
		return fmt.Errorf("keyword %s requires an argument", op)
	}

	return nil
}

func validateSourceCharacters(source string) error {
	for _, r := range source {
		if unicode.IsControl(r) {
			switch r {
			case '\n', '\r', '\t':
				continue
			default:
				return errors.New("RVX source contains unsupported control characters")
			}
		}
	}

	return nil
}

func minRVXInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
