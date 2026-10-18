package genesis

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// Guardian is deliberately conservative. It blocks explicit harmful intent before research
// or artifact generation, and it screens research/model text before that text can influence an invention.
type Guardian struct {
	CoreRoot string
}

type GuardianDecision struct {
	Allowed bool   `json:"allowed"`
	Code    string `json:"code"`
	Reason  string `json:"reason"`
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

func (g Guardian) Check(text string) GuardianDecision {
	lower := strings.ToLower(strings.TrimSpace(text))
	if lower == "" {
		return GuardianDecision{Allowed: false, Code: "empty_input", Reason: "A non-empty demand or evidence item is required."}
	}
	if ok, reason := g.policyReady(); !ok {
		return GuardianDecision{Allowed: false, Code: "guardian_policy_unavailable", Reason: reason}
	}
	for _, pattern := range harmfulPatterns {
		if pattern.MatchString(lower) {
			return GuardianDecision{Allowed: false, Code: "guardian_block", Reason: "The request or source matches a prohibited harm pattern."}
		}
	}
	for _, term := range g.extraTerms() {
		quoted := regexp.QuoteMeta(term)
		pattern, err := regexp.Compile(`(?i)\b` + quoted + `\b`)
		if err == nil && pattern.MatchString(lower) {
			return GuardianDecision{Allowed: false, Code: "guardian_block", Reason: "The request or source matches a configured additional Guardian term."}
		}
	}
	return GuardianDecision{Allowed: true, Code: "allowed", Reason: "No prohibited intent pattern was detected; normal review gates still apply."}
}


func (g Guardian) policyReady() (bool, string) {
	path := filepath.Join(g.CoreRoot, "guardian", "rules.yaml")
	raw, err := os.ReadFile(path)
	if err != nil {
		return false, "Guardian policy is unavailable; fail-closed mode blocks the request."
	}
	if len(raw) == 0 || len(raw) > 64*1024 {
		return false, "Guardian policy is empty or exceeds the safe size limit; fail-closed mode blocks the request."
	}
	policy := strings.ToLower(string(raw))
	required := []string{
		"mode: fail_closed",
		"core_law:",
		"weapons",
		"warfare",
		"explosives",
		"malware_and_credential_theft",
		"privacy_violations",
	}
	for _, marker := range required {
		if !strings.Contains(policy, marker) {
			return false, "Guardian policy is missing required safety controls; fail-closed mode blocks the request."
		}
	}
	return true, ""
}

func (g Guardian) extraTerms() []string {
	f, err := os.Open(filepath.Join(g.CoreRoot, "guardian", "rules.yaml"))
	if err != nil {
		return nil
	}
	defer f.Close()
	var terms []string
	inside := false
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "extra_terms:" {
			inside = true
			continue
		}
		if inside && line != "" && !strings.HasPrefix(line, "-") {
			break
		}
		if inside && strings.HasPrefix(line, "-") {
			term := strings.TrimSpace(strings.TrimPrefix(line, "-"))
			term = strings.Trim(term, `\"'`)
			term = strings.ToLower(strings.TrimSpace(term))
			if term != "" && len(term) <= 100 {
				terms = append(terms, term)
			}
		}
	}
	return terms
}

func (g Guardian) LogBlocked(stage, input, reason string) error {
	path := filepath.Join(g.CoreRoot, "guardian", "blocked.log")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	entry := map[string]any{
		"at": time.Now().UTC(), "stage": stage,
		"input_sha256": sha256String(input), "reason": reason,
	}
	b, err := json.Marshal(entry)
	if err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer f.Close()
	if _, err = f.Write(append(b, '\n')); err != nil {
		return fmt.Errorf("write guardian audit: %w", err)
	}
	return nil
}
