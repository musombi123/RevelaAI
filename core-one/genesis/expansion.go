package genesis

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func makeExpansionPlan(spec ToolSpec, coreRoot string) map[string]any {
	target := "core-one/expand/plans/" + spec.Name + ".json"
	if shouldUseGen2(coreRoot) {
		target = "core-one/gen2/staging/" + spec.Name + ".json"
	}
	return map[string]any{"id": newID("expand"), "created_at": time.Now().UTC(), "demand": spec.Demand, "invention": spec.Name, "industry": spec.Industry, "proposal_target": target, "verbs": []string{"create", "innovate", "transform", "change", "emerge", "move", "adopt", "evolve", "forge", "protect"}, "actions": []string{"add the reviewed tool to a model family", "extract reusable libraries only after tests pass", "publish versioned API and SDK proposals", "add integration-specific acceptance tests"}, "auto_import": false, "status": "await_merge", "reason": "The engine can propose its own expansion, but cannot silently rewrite or import its running core."}
}

func shouldUseGen2(coreRoot string) bool {
	threshold := 5000
	if raw := strings.TrimSpace(os.Getenv("GENESIS_MAX_CORE_FILES")); raw != "" {
		var n int
		if _, err := fmt.Sscanf(raw, "%d", &n); err == nil && n > 10 {
			threshold = n
		}
	}
	count := 0
	_ = filepath.WalkDir(coreRoot, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			if d.Name() == ".git" || strings.HasPrefix(d.Name(), ".staging-") {
				return filepath.SkipDir
			}
			return nil
		}
		count++
		if count >= threshold {
			return filepath.SkipAll
		}
		return nil
	})
	return count >= threshold
}

func (e *Engine) recordIndustry(spec ToolSpec) error {
	path := filepath.Join(e.CoreRoot, "industries", spec.Industry, "README.md")
	if _, err := os.Stat(path); err == nil {
		return nil
	}
	body := fmt.Sprintf("# %s invention domain\n\nThis folder was proposed by Revela Genesis when demand %s was classified into this industry. It is a taxonomy starter only; do not infer regulatory approval or market demand from this classification. Add industry standards, verified sources, threat models, and acceptance tests through review.\n", spec.Industry, spec.Name)
	return atomicWrite(path, []byte(body), 0o644)
}
