// Package mind contains a small, deterministic, non-executing RV Lang
// plan compiler.
//
// RV Lang compilation produces a declarative plan. It does not execute
// operations, authorize mutations, approve repairs, or actuate hardware.
// Any future executor must enforce its own authentication, authorization,
// precondition, approval, and post-execution verification requirements.
package mind

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

const (
	maxSourceBytes = 64 * 1024
	maxSourceLines = 4096
	maxLineBytes   = 8192
	maxOperations  = 200
	maxArguments   = 64
	maxArgumentBytes = 4096
)

var Keywords = []string{
	"heal",
	"assemble",
	"evolve",
	"forge",
	"bridge",
	"scan",
	"propose",
	"approve",
	"audit",
	"target",
	"using",
	"with",
	"from",
	"to",
	"if",
	"then",
	"end",
	"let",
	"true",
	"false",
}

var commands = map[string]bool{
	"heal":    true,
	"assemble": true,
	"evolve":  true,
	"forge":   true,
	"bridge":  true,
	"scan":    true,
	"propose": true,
	"approve": true,
	"audit":   true,
}

// Operation is one parsed RV Lang operation.
//
// Args contains parsed string arguments. It is not a command execution record.
type Operation struct {
	Verb string   `json:"verb"`
	Args []string `json:"args"`
	Line int      `json:"line"`
}

// Result represents a compiled RV Lang plan.
//
// Executed is always false for this compiler. HumanApprovalRequired remains
// true because compilation is not authorization to execute the generated plan.
type Result struct {
	Status               string      `json:"status"`
	Operations           []Operation `json:"operations"`
	GoSource             string      `json:"go_source"`
	Executed             bool        `json:"executed"`
	HumanApprovalRequired bool       `json:"human_approval_required"`
}

// Compile validates and compiles a bounded RV Lang source document.
//
// Syntax currently supports one operation per line, quoted arguments using
// single or double quotes, backslash escaping inside quoted strings, and
// whole-line comments beginning with '#'. Keywords are case-insensitive.
//
// Non-scan commands require at least one non-empty argument. This compiler
// builds a declarative Go representation of the plan; it never executes it.
func Compile(source string) (Result, error) {
	if len(source) > maxSourceBytes {
		return Result{}, fmt.Errorf(
			"RV source exceeds %d-byte limit",
			maxSourceBytes,
		)
	}

	if !utf8.ValidString(source) {
		return Result{}, errors.New("RV source must contain valid UTF-8")
	}

	lines := strings.Split(source, "\n")
	if len(lines) > maxSourceLines {
		return Result{}, fmt.Errorf(
			"RV source exceeds %d-line limit",
			maxSourceLines,
		)
	}

	operations := make([]Operation, 0, min(len(lines), maxOperations))

	for index, rawLine := range lines {
		lineNumber := index + 1

		if len(rawLine) > maxLineBytes {
			return Result{}, fmt.Errorf(
				"line %d: line exceeds %d-byte limit",
				lineNumber,
				maxLineBytes,
			)
		}

		if err := validateLineCharacters(rawLine); err != nil {
			return Result{}, fmt.Errorf("line %d: %w", lineNumber, err)
		}

		line := strings.TrimSpace(rawLine)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		tokens, err := tokenize(line)
		if err != nil {
			return Result{}, fmt.Errorf("line %d: %w", lineNumber, err)
		}

		if len(tokens) == 0 {
			continue
		}

		verb := strings.ToLower(tokens[0])
		if !commands[verb] {
			return Result{}, fmt.Errorf(
				"line %d: unknown command %q",
				lineNumber,
				tokens[0],
			)
		}

		args := tokens[1:]

		if verb != "scan" && len(args) == 0 {
			return Result{}, fmt.Errorf(
				"line %d: command %s requires an argument",
				lineNumber,
				verb,
			)
		}

		if verb != "scan" && strings.TrimSpace(args[0]) == "" {
			return Result{}, fmt.Errorf(
				"line %d: command %s requires a non-empty first argument",
				lineNumber,
				verb,
			)
		}

		if len(args) > maxArguments {
			return Result{}, fmt.Errorf(
				"line %d: command exceeds the maximum of %d arguments",
				lineNumber,
				maxArguments,
			)
		}

		if len(operations) >= maxOperations {
			return Result{}, fmt.Errorf(
				"line %d: RV program exceeds %d operations",
				lineNumber,
				maxOperations,
			)
		}

		// Own the argument slice so subsequent parser changes cannot
		// accidentally share a mutable token buffer with this operation.
		ownedArgs := append([]string(nil), args...)

		operations = append(operations, Operation{
			Verb: verb,
			Args: ownedArgs,
			Line: lineNumber,
		})
	}

	if len(operations) == 0 {
		return Result{}, errors.New("RV source contains no operations")
	}

	goSource, err := renderPlan(operations)
	if err != nil {
		return Result{}, fmt.Errorf("render RV plan: %w", err)
	}

	return Result{
		Status:                "plan_generated_pending_review",
		Operations:            operations,
		GoSource:              goSource,
		Executed:              false,
		HumanApprovalRequired: true,
	}, nil
}

// validateLineCharacters rejects unsafe control characters that can make
// source text or diagnostic output ambiguous. Tabs and carriage returns are
// allowed as whitespace. Newlines have already been separated by Compile.
func validateLineCharacters(line string) error {
	for _, r := range line {
		if r == '\t' || r == '\r' {
			continue
		}

		if unicode.IsControl(r) {
			return fmt.Errorf(
				"unsupported control character U+%04X",
				r,
			)
		}
	}

	return nil
}

// renderPlan serializes operations as Go string literals.
//
// strconv.Quote safely escapes argument contents, preventing an argument from
// injecting additional Go syntax into the generated declaration.
func renderPlan(operations []Operation) (string, error) {
	var builder strings.Builder

	builder.WriteString(
		"// Code generated by USECT-ZERO RV compiler; review required.\n" +
			"// This file describes a plan; it does not authorize execution.\n" +
			"package main\n\n" +
			"type Operation struct {\n" +
			"\tVerb string\n" +
			"\tArgs []string\n" +
			"\tLine int\n" +
			"}\n\n" +
			"var Plan = []Operation{\n",
	)

	for _, operation := range operations {
		if !commands[operation.Verb] {
			return "", fmt.Errorf(
				"refusing to render unknown operation verb %q",
				operation.Verb,
			)
		}

		quotedArgs := make([]string, len(operation.Args))
		for index, argument := range operation.Args {
			quotedArgs[index] = strconv.Quote(argument)
		}

		builder.WriteString("\t{Verb: ")
		builder.WriteString(strconv.Quote(operation.Verb))
		builder.WriteString(", Args: []string{")
		builder.WriteString(strings.Join(quotedArgs, ", "))
		builder.WriteString("}, Line: ")
		builder.WriteString(strconv.Itoa(operation.Line))
		builder.WriteString("},\n")
	}

	builder.WriteString("}\n")

	return builder.String(), nil
}

// tokenize parses a single RV Lang line.
//
// Quoted segments can contain whitespace. Both single and double quotes are
// supported. Within a quoted segment, a backslash escapes the following rune.
// A trailing backslash or unclosed quote is rejected.
//
// Example:
//
//	assemble "esp32 sensor" using "template 1.0.0"
//
// becomes:
//
//	["assemble", "esp32 sensor", "using", "template 1.0.0"]
func tokenize(source string) ([]string, error) {
	if !utf8.ValidString(source) {
		return nil, errors.New("line must contain valid UTF-8")
	}

	if len(source) > maxLineBytes {
		return nil, fmt.Errorf("line exceeds %d-byte limit", maxLineBytes)
	}

	var output []string
	var token strings.Builder

	var quote rune
	escaped := false
	active := false

	flush := func() error {
		if !active {
			return nil
		}

		if len(output) >= maxArguments+1 {
			return fmt.Errorf(
				"line exceeds maximum of %d tokens",
				maxArguments+1,
			)
		}

		output = append(output, token.String())
		token.Reset()
		active = false

		return nil
	}

	for _, r := range source {
		if unicode.IsControl(r) && r != '\t' && r != '\r' {
			return nil, fmt.Errorf(
				"unsupported control character U+%04X",
				r,
			)
		}

		if escaped {
			token.WriteRune(r)
			escaped = false
			active = true

			if token.Len() > maxArgumentBytes {
				return nil, fmt.Errorf(
					"argument exceeds %d-byte limit",
					maxArgumentBytes,
				)
			}

			continue
		}

		if quote != 0 {
			switch r {
			case '\\':
				escaped = true

			case quote:
				quote = 0
				active = true

			default:
				token.WriteRune(r)
			}

			if token.Len() > maxArgumentBytes {
				return nil, fmt.Errorf(
					"argument exceeds %d-byte limit",
					maxArgumentBytes,
				)
			}

			continue
		}

		switch {
		case r == '\'' || r == '"':
			quote = r
			active = true

		case r == ' ' || r == '\t' || r == '\r':
			if err := flush(); err != nil {
				return nil, err
			}

		default:
			token.WriteRune(r)
			active = true

			if token.Len() > maxArgumentBytes {
				return nil, fmt.Errorf(
					"argument exceeds %d-byte limit",
					maxArgumentBytes,
				)
			}
		}
	}

	if escaped {
		return nil, errors.New("unterminated escape sequence in quoted string")
	}

	if quote != 0 {
		return nil, errors.New("unterminated quoted string")
	}

	if err := flush(); err != nil {
		return nil, err
	}

	return output, nil
}
