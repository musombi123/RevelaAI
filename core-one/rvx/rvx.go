// Package rvx provides a deliberately small, non-executing RVX parser/compiler skeleton.
// It compiles declarative verbs into a JSON intermediate representation, not native code or WASM.
package rvx

import (
	"errors"
	"fmt"
	"strings"
)

var Keywords = []string{
	"create", "innovate", "transform", "change", "emerge", "move", "adopt", "protect", "block", "evolve",
	"forge", "research", "compose", "validate", "test", "explain", "expose", "guide", "await", "merge",
}

type Instruction struct {
	Op       string `json:"op"`
	Argument string `json:"argument,omitempty"`
	Line     int    `json:"line"`
}
type Program struct {
	Language string        `json:"language"`
	Version  string        `json:"version"`
	Mode     string        `json:"mode"`
	Count    int           `json:"count"`
	Code     []Instruction `json:"code"`
	Notice   string        `json:"notice"`
}

func Compile(source string) (Program, error) {
	if strings.TrimSpace(source) == "" { return Program{}, errors.New("RVX source is empty") }
	if len(source) > 16*1024 { return Program{}, errors.New("RVX source exceeds 16 KiB") }
	valid := make(map[string]bool, len(Keywords)); for _, k := range Keywords { valid[k] = true }
	lines := strings.Split(source, "\n"); if len(lines) > 128 { return Program{}, errors.New("RVX source exceeds 128 lines") }
	code := make([]Instruction, 0, len(lines))
	for index, line := range lines {
		line = strings.TrimSpace(line); if line == "" || strings.HasPrefix(line, "#") { continue }
		if strings.ContainsAny(line, ";{}") { return Program{}, fmt.Errorf("line %d: statement separators and code blocks are not supported", index+1) }
		parts := strings.SplitN(line, " ", 2); op := strings.ToLower(strings.TrimSpace(parts[0]))
		if !valid[op] { return Program{}, fmt.Errorf("line %d: unsupported RVX keyword %q", index+1, op) }
		arg := ""; if len(parts) > 1 { arg = strings.TrimSpace(parts[1]) }
		if len(arg) > 1000 { return Program{}, fmt.Errorf("line %d: argument exceeds 1000 characters", index+1) }
		if (op == "block" || op == "protect" || op == "await" || op == "create" || op == "forge" || op == "research" || op == "compose" || op == "expose" || op == "guide") && arg == "" { return Program{}, fmt.Errorf("line %d: keyword %s requires an argument", index+1, op) }
		code = append(code, Instruction{Op: op, Argument: arg, Line: index+1})
	}
	if len(code) == 0 { return Program{}, errors.New("RVX source contains no instructions") }
	return Program{Language: "RVX", Version: "0.1", Mode: "declarative_ir_only", Count: len(code), Code: code, Notice: "Compiled to a bounded JSON intermediate representation only. No instruction was executed; this is not encrypted WASM."}, nil
}
