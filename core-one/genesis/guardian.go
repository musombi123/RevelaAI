package genesis

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

const (
	maxGuardianPolicyBytes = 64 * 1024
	maxGuardianInputBytes  = 1024 * 1024
	maxGuardianExtraTerms  = 256
	maxGuardianTermBytes   = 100
	maxGuardianStageBytes  = 100
	maxGuardianReasonBytes = 500
)

// Guardian is deliberately conservative. It blocks prohibited harm patterns
// before research or artifact generation and fails closed when its policy
// cannot be verified.
type Guardian struct {
	CoreRoot string
}

// GuardianDecision is a machine-readable result of a Guardian review.
type GuardianDecision struct {
	Allowed bool   `json:"allowed"`
	Code    string `json:"code"`
	Reason  string `json:"reason"`
	Stage   string `json:"stage,omitempty"`
}

// guardianPolicy represents a validated, bounded policy snapshot.
// A check uses one snapshot so that policy validation and term evaluation
// cannot accidentally read different policy versions.
type guardianPolicy struct {
	ExtraTerms []string
}

var harmfulPatterns = []*regexp.Regexp{
	regexp.MustCompile(`\bweapon(s|ized|ise|ize)?\b`),
	regexp.MustCompile(`\bwar(fare|s)?\b`),
	regexp.MustCompile(`\bmunition(s)?\b`),
	regexp.MustCompile(`\bexplosive(s)?\b`),
	regexp.MustCompile(`\b(bomb|bombing|detonator|assassinat(e|ion))\b`),
	regexp.MustCompile(`\b(kill|murder|massacre)\b`),
	regexp.MustCompile(`\b(ransomware|keylogger|spyware|credential theft|steal credentials)\b`),
	regexp.MustCompile(`\b(malware|botnet|rootkit|trojan horse)\b`),
	regexp.MustCompile(`\b(stalk(ing)?|covert surveillance|hidden camera)\b`),
	regexp.MustCompile(`\b(bypass authentication|evade detection|exfiltrate data)\b`),
}

var (
	guardianAuditMu sync.Mutex

	configuredTermBoundary = regexp.MustCompile(
		`(?i)(?:^|[^a-z0-9_])%s(?:$|[^a-z0-9_])`,
	)
)

// Check screens untrusted input using the default "input" stage.
func (g Guardian) Check(input string) GuardianDecision {
	return g.CheckAtStage("input", input)
}

// CheckAtStage screens untrusted text and records the stage in the decision.
// It does not automatically write to the audit log; callers can use
// LogBlocked when their workflow needs to persist a blocked decision.
func (g Guardian) CheckAtStage(stage, input string) GuardianDecision {
	stage = normalizeGuardianStage(stage)

	if strings.TrimSpace(input) == "" {
		return guardianDenied(
			"empty_input",
			"A non-empty demand or evidence item is required.",
			stage,
		)
	}

	if len(input) > maxGuardianInputBytes {
		return guardianDenied(
			"guardian_input_too_large",
			"The input exceeds the configured Guardian size limit.",
			stage,
		)
	}

	if !utf8.ValidString(input) {
		return guardianDenied(
			"guardian_invalid_text",
			"The input is not valid UTF-8 text.",
			stage,
		)
	}

	policy, reason := g.loadPolicy()
	if reason != "" {
		return guardianDenied(
			"guardian_policy_unavailable",
			reason,
			stage,
		)
	}

	normalized := strings.ToLower(strings.TrimSpace(input))

	for _, pattern := range harmfulPatterns {
		if pattern.MatchString(normalized) {
			return guardianDenied(
				"guardian_block",
				"The request or source matches a prohibited harm pattern.",
				stage,
			)
		}
	}

	for _, term := range policy.ExtraTerms {
		if guardianTermMatches(normalized, term) {
			return guardianDenied(
				"guardian_block",
				"The request or source matches a configured additional Guardian term.",
				stage,
			)
		}
	}

	return GuardianDecision{
		Allowed: true,
		Code:    "allowed",
		Reason:  "No prohibited intent pattern was detected; normal review gates still apply.",
		Stage:   stage,
	}
}

func guardianDenied(code, reason, stage string) GuardianDecision {
	return GuardianDecision{
		Allowed: false,
		Code:    code,
		Reason:  reason,
		Stage:   stage,
	}
}

func normalizeGuardianStage(stage string) string {
	stage = strings.TrimSpace(stage)
	if stage == "" {
		stage = "unspecified"
	}

	return truncateGuardianText(stage, maxGuardianStageBytes)
}

// ValidatePolicy exposes a policy readiness check to startup checks,
// diagnostics, and operational status endpoints.
func (g Guardian) ValidatePolicy() error {
	_, reason := g.loadPolicy()
	if reason != "" {
		return errors.New(reason)
	}
	return nil
}

// policyReady is retained for compatibility with existing package code.
func (g Guardian) policyReady() (bool, string) {
	_, reason := g.loadPolicy()
	if reason != "" {
		return false, reason
	}
	return true, ""
}

// loadPolicy validates the policy file and extracts configured extra terms.
func (g Guardian) loadPolicy() (guardianPolicy, string) {
	if strings.TrimSpace(g.CoreRoot) == "" {
		return guardianPolicy{}, "Guardian core root is not configured; fail-closed mode blocks the request."
	}

	path := filepath.Join(g.CoreRoot, "guardian", "rules.yaml")

	info, err := os.Lstat(path)
	if err != nil {
		return guardianPolicy{}, "Guardian policy is unavailable; fail-closed mode blocks the request."
	}

	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return guardianPolicy{}, "Guardian policy must be a regular, non-symlink file; fail-closed mode blocks the request."
	}

	if info.Size() <= 0 || info.Size() > maxGuardianPolicyBytes {
		return guardianPolicy{}, "Guardian policy is empty or exceeds the safe size limit; fail-closed mode blocks the request."
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		return guardianPolicy{}, "Guardian policy could not be read; fail-closed mode blocks the request."
	}

	if len(raw) == 0 || len(raw) > maxGuardianPolicyBytes {
		return guardianPolicy{}, "Guardian policy is empty or exceeds the safe size limit; fail-closed mode blocks the request."
	}

	// Reject a policy file that changed identity while it was being read.
	currentInfo, err := os.Lstat(path)
	if err != nil ||
		currentInfo.Mode()&os.ModeSymlink != 0 ||
		!currentInfo.Mode().IsRegular() ||
		!os.SameFile(info, currentInfo) {
		return guardianPolicy{}, "Guardian policy changed during validation; fail-closed mode blocks the request."
	}

	activeLines := activeGuardianPolicyLines(string(raw))
	if len(activeLines) == 0 {
		return guardianPolicy{}, "Guardian policy contains no active controls; fail-closed mode blocks the request."
	}

	if !guardianHasFailClosedMode(activeLines) {
		return guardianPolicy{}, "Guardian policy must explicitly configure mode: fail_closed; fail-closed mode blocks the request."
	}

	activeText := strings.Join(activeLines, "\n")

	requiredControls := []string{
		"core_law:",
		"weapons",
		"warfare",
		"explosives",
		"malware_and_credential_theft",
		"privacy_violations",
	}

	for _, marker := range requiredControls {
		if !strings.Contains(activeText, marker) {
			return guardianPolicy{}, "Guardian policy is missing required safety controls; fail-closed mode blocks the request."
		}
	}

	return guardianPolicy{
		ExtraTerms: parseGuardianExtraTerms(string(raw)),
	}, ""
}

// activeGuardianPolicyLines removes blank lines and YAML comments before
// checking required controls. Commented-out examples cannot satisfy checks.
func activeGuardianPolicyLines(raw string) []string {
	lines := strings.Split(raw, "\n")
	active := make([]string, 0, len(lines))

	for _, original := range lines {
		line := stripGuardianComment(original)
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}

		active = append(active, strings.ToLower(line))
	}

	return active
}

func stripGuardianComment(line string) string {
	// The rules file is a restricted configuration file. The policy validator
	// deliberately treats '#' as the start of a comment.
	if index := strings.IndexByte(line, '#'); index >= 0 {
		return line[:index]
	}

	return line
}

func guardianHasFailClosedMode(lines []string) bool {
	for _, line := range lines {
		key, value, ok := strings.Cut(line, ":")
		if !ok || strings.TrimSpace(key) != "mode" {
			continue
		}

		value = strings.TrimSpace(value)
		value = strings.Trim(value, `"'`)

		if value == "fail_closed" {
			return true
		}
	}

	return false
}

// extraTerms is retained for compatibility with existing package code.
// It returns no terms when the complete policy cannot be validated.
func (g Guardian) extraTerms() []string {
	policy, reason := g.loadPolicy()
	if reason != "" {
		return nil
	}

	return append([]string(nil), policy.ExtraTerms...)
}

func parseGuardianExtraTerms(raw string) []string {
	lines := strings.Split(raw, "\n")
	terms := make([]string, 0)

	inside := false
	sectionIndent := 0
	seen := make(map[string]struct{})

	for _, original := range lines {
		lineWithoutComment := stripGuardianComment(original)
		if strings.TrimSpace(lineWithoutComment) == "" {
			continue
		}

		indent := guardianIndent(lineWithoutComment)
		trimmed := strings.TrimSpace(lineWithoutComment)
		lower := strings.ToLower(trimmed)

		if !inside {
			if lower == "extra_terms:" {
				inside = true
				sectionIndent = indent
			}
			continue
		}

		// A sibling or parent section terminates the list.
		if indent <= sectionIndent {
			break
		}

		if !strings.HasPrefix(trimmed, "-") {
			break
		}

		term := strings.TrimSpace(strings.TrimPrefix(trimmed, "-"))
		term = strings.Trim(term, `"'`)
		term = strings.ToLower(strings.TrimSpace(term))

		if term == "" || len(term) > maxGuardianTermBytes {
			continue
		}

		if strings.ContainsAny(term, "\r\n\x00") {
			continue
		}

		if _, exists := seen[term]; exists {
			continue
		}

		seen[term] = struct{}{}
		terms = append(terms, term)

		if len(terms) >= maxGuardianExtraTerms {
			break
		}
	}

	return terms
}

func guardianIndent(line string) int {
	count := 0

	for _, r := range line {
		if r != ' ' && r != '\t' {
			break
		}
		count++
	}

	return count
}

func guardianTermMatches(input, term string) bool {
	if term == "" {
		return false
	}

	patternText := fmt.Sprintf(
		`(?i)(?:^|[^a-z0-9_])%s(?:$|[^a-z0-9_])`,
		regexp.QuoteMeta(term),
	)

	pattern, err := regexp.Compile(patternText)
	if err != nil {
		return false
	}

	return pattern.MatchString(input)
}

func truncateGuardianText(value string, maxBytes int) string {
	if maxBytes <= 0 {
		return ""
	}

	if len(value) <= maxBytes {
		return value
	}

	value = value[:maxBytes]

	// Do not return invalid UTF-8 if the cutoff lands inside a code point.
	for !utf8.ValidString(value) && len(value) > 0 {
		value = value[:len(value)-1]
	}

	return value
}

// LogBlocked writes a privacy-conscious JSON Lines audit record.
// Raw user input is never written; only its SHA-256 digest is recorded.
func (g Guardian) LogBlocked(stage, input, reason string) error {
	if strings.TrimSpace(g.CoreRoot) == "" {
		return errors.New("cannot write Guardian audit: core root is not configured")
	}

	path := filepath.Join(g.CoreRoot, "guardian", "blocked.log")
	dir := filepath.Dir(path)

	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("create Guardian audit directory: %w", err)
	}

	entry := map[string]any{
		"at":          time.Now().UTC(),
		"stage":       truncateGuardianText(normalizeGuardianStage(stage), maxGuardianStageBytes),
		"input_sha256": sha256String(input),
		"reason":      truncateGuardianText(strings.TrimSpace(reason), maxGuardianReasonBytes),
	}

	record, err := json.Marshal(entry)
	if err != nil {
		return fmt.Errorf("encode Guardian audit record: %w", err)
	}

	record = append(record, '\n')

	// Prevent records produced by concurrent Guardian checks from being
	// interleaved inside the same process.
	guardianAuditMu.Lock()
	defer guardianAuditMu.Unlock()

	file, err := os.OpenFile(
		path,
		os.O_CREATE|os.O_APPEND|os.O_WRONLY,
		0o600,
	)
	if err != nil {
		return fmt.Errorf("open Guardian audit log: %w", err)
	}

	if err := file.Chmod(0o600); err != nil {
		_ = file.Close()
		return fmt.Errorf("secure Guardian audit log permissions: %w", err)
	}

	written, writeErr := file.Write(record)
	if writeErr == nil && written != len(record) {
		writeErr = errors.New("short write")
	}

	closeErr := file.Close()

	if writeErr != nil {
		return fmt.Errorf("write Guardian audit log: %w", writeErr)
	}
	if closeErr != nil {
		return fmt.Errorf("close Guardian audit log: %w", closeErr)
	}

	return nil
}
