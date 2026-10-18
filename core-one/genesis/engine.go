package genesis

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

var ErrBlocked = errors.New("guardian blocked the demand")
var ErrAlreadyExists = errors.New("an invention with that name already exists; review it instead of overwriting it")

// Engine is standalone: all core planning works without a model endpoint or vendor SDK.
// Network research and the optional model/provider bridges are adapters, not dependencies.
type Engine struct {
	RepoRoot   string
	CoreRoot   string
	Guardian   Guardian
	Researcher Researcher
	Model      ModelAdapter

	mu          sync.RWMutex
	inventMu    sync.Mutex
	researchMu  sync.Mutex
	queueMu     sync.Mutex
	eventMu     sync.RWMutex
	subscribers map[chan Event]struct{}
}

func NewEngine(repoRoot string) (*Engine, error) {
	if strings.TrimSpace(repoRoot) == "" {
		return nil, errors.New("repository root is required")
	}
	abs, err := filepath.Abs(repoRoot)
	if err != nil {
		return nil, err
	}
	core := filepath.Join(abs, "core-one")
	for _, dir := range []string{"inventions", "libraries/created", "models", "research", "guardian", "expand/plans", "state/queue", "state/events"} {
		if err := os.MkdirAll(filepath.Join(core, dir), 0o700); err != nil {
			return nil, err
		}
	}
	g := Guardian{CoreRoot: core}
	if _, err := os.Stat(filepath.Join(core, "guardian", "rules.yaml")); os.IsNotExist(err) {
		if err := atomicWrite(filepath.Join(core, "guardian", "rules.yaml"), []byte(defaultGuardianRules), 0o600); err != nil {
			return nil, err
		}
	}
	if _, err := os.Stat(filepath.Join(core, "models", "generic_tool.yaml")); os.IsNotExist(err) {
		if err := atomicWrite(filepath.Join(core, "models", "generic_tool.yaml"), []byte(defaultModelBlueprint), 0o644); err != nil {			return nil, err
		}
	}
	e := &Engine{RepoRoot: abs, CoreRoot: core, Guardian: g, Researcher: NewWebResearcher(), Model: NewConfiguredModelAdapter(), subscribers: make(map[chan Event]struct{})}
	return e, nil
}

func (e *Engine) SetResearcher(r Researcher) { e.mu.Lock(); defer e.mu.Unlock(); e.Researcher = r }
func (e *Engine) SetModel(m ModelAdapter)    { e.mu.Lock(); defer e.mu.Unlock(); e.Model = m }

func (e *Engine) Invent(ctx context.Context, demand string) (Invention, error) {
	if ctx == nil { ctx = context.Background() }
	demand = limitText(demand, 4000)
	if demand == "" {
		return Invention{}, errors.New("demand is required")
	}
	if len(demand) >= 4000 {
		return Invention{}, errors.New("demand exceeds the 3999-character limit")
	}
	select {
	case <-ctx.Done():
		return Invention{}, ctx.Err()
	default:
	}
	e.inventMu.Lock()
	defer e.inventMu.Unlock()
	e.mu.RLock()
	researcher, model := e.Researcher, e.Model
	e.mu.RUnlock()
	if researcher == nil { researcher = NewWebResearcher() }
	decision := e.Guardian.Check(demand)
	if !decision.Allowed {
		_ = e.Guardian.LogBlocked("demand", demand, decision.Reason)
		e.publish(Event{Type: "blocked", At: time.Now().UTC(), Message: "Guardian blocked a demand before research or file generation.", Status: decision.Code})
		return Invention{}, ErrBlocked
	}
	e.publish(Event{Type: "research_started", At: time.Now().UTC(), Message: "Eye started research for an approved demand."})
	evidence, err := researcher.Research(ctx, demand)
	if err != nil {
		return Invention{}, fmt.Errorf("research failed: %w", err)
	}
	if err := ctx.Err(); err != nil { return Invention{}, err }
	if len(evidence.Sources) > 200 || len(evidence.Findings) > 100 {
		return Invention{}, errors.New("research evidence exceeded configured item limits; invention refused")
	}
	for _, finding := range evidence.Findings {
		if len(finding) > 4000 { return Invention{}, errors.New("research finding exceeded the 4000-character limit; invention refused") }
		if d := e.Guardian.Check(finding); !d.Allowed {
			_ = e.Guardian.LogBlocked("research_finding", finding, d.Reason)
			e.publish(Event{Type: "blocked", At: time.Now().UTC(), Message: "Guardian blocked the complete invention because a research finding matched a prohibited pattern.", Status: d.Code})
			return Invention{}, ErrBlocked
		}
	}
	for _, source := range evidence.Sources {
		if len(source.Name) > 200 || len(source.URL) > 2048 || len(source.Title) > 500 || len(source.Snippet) > 4000 {
			return Invention{}, errors.New("research source exceeded configured field limits; invention refused")
		}
		checkText := source.Name + " " + source.Title + " " + source.Snippet + " " + source.URL
		if d := e.Guardian.Check(checkText); !d.Allowed {
			_ = e.Guardian.LogBlocked("research_source", source.URL+" "+checkText, d.Reason)
			e.publish(Event{Type: "blocked", At: time.Now().UTC(), Message: "Guardian blocked the complete invention because a research source matched a prohibited pattern.", Status: d.Code})
			return Invention{}, ErrBlocked
		}
	}
	if err := e.saveResearchEvidence(evidence); err != nil {
		return Invention{}, fmt.Errorf("save research evidence: %w", err)
	}

	baseSpec := deriveSpec(demand)
	spec := baseSpec
	if model != nil {
		modelSpec, modelErr := model.Suggest(ctx, demand, evidence, baseSpec)
		if modelErr == nil {
			candidate, _ := json.Marshal(modelSpec)
			if d := e.Guardian.Check(string(candidate)); !d.Allowed {
				_ = e.Guardian.LogBlocked("model_specification", string(candidate), d.Reason)
				e.publish(Event{Type: "blocked", At: time.Now().UTC(), Message: "Guardian blocked the complete invention because a model-generated specification violated policy.", Status: d.Code})
				return Invention{}, ErrBlocked
			}
			// Model content is untrusted metadata only. Identity, classification, and hardware safety
			// boundaries remain anchored to the deterministic demand parser.
			spec = overlayModelMetadata(baseSpec, modelSpec)
		} else {
			spec.ModelNote = "Configured model adapter was unavailable; deterministic model-free specification used: " + limitText(modelErr.Error(), 160)
		}
	}
	if err := ctx.Err(); err != nil { return Invention{}, err }
	if d := e.Guardian.Check(spec.Title + " " + spec.Purpose + " " + strings.Join(spec.Capabilities, " ") + " " + strings.Join(spec.Safeguards, " ")); !d.Allowed {
		_ = e.Guardian.LogBlocked("final_specification", demand, d.Reason)
		return Invention{}, ErrBlocked
	}
	plan, err := BuildCapabilityPlan(spec, evidence, e.CoreRoot)
	if err != nil {
		return Invention{}, fmt.Errorf("build capability/requirement plan: %w", err)
	}
	planBytes, err := json.Marshal(plan)
	if err != nil { return Invention{}, fmt.Errorf("encode capability plan: %w", err) }
	if d := e.Guardian.Check(string(planBytes)); !d.Allowed {
		_ = e.Guardian.LogBlocked("capability_plan", string(planBytes), d.Reason)
		e.publish(Event{Type: "blocked", At: time.Now().UTC(), Message: "Guardian blocked the invention because its capability plan violated policy.", Status: d.Code})
		return Invention{}, ErrBlocked
	}
	invention, err := e.forge(spec, evidence, plan)
	if err != nil {
		e.publish(Event{Type: "forge_error", At: time.Now().UTC(), Message: limitText(err.Error(), 300), Status: "error"})
		return Invention{}, err
	}
	e.publish(Event{Type: "invention_created", At: time.Now().UTC(), Message: "Genesis generated a reviewable invention package; it was not merged or executed.", Invention: invention.Name, Status: "await_merge"})
	return invention, nil
}

func (e *Engine) saveResearchEvidence(ev ResearchEvidence) error {
	e.researchMu.Lock()
	defer e.researchMu.Unlock()
	path := filepath.Join(e.CoreRoot, "research", ev.CollectedAt.UTC().Format("2006-01-02")+".json")
	var entries []ResearchEvidence
	if raw, err := os.ReadFile(path); err == nil {
		if json.Unmarshal(raw, &entries) != nil {
			return errors.New("existing daily research file is not valid JSON; refusing to overwrite it")
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	entries = append(entries, ev)
	return writeJSON(path, entries)
}

func (e *Engine) publish(event Event) {
	if event.ID == "" {
		event.ID = newID("evt")
	}
	if event.At.IsZero() {
		event.At = time.Now().UTC()
	}
	path := filepath.Join(e.CoreRoot, "state", "events", "events.jsonl")
	if b, err := json.Marshal(event); err == nil {
		_ = appendLine(path, b)
	}
	e.eventMu.RLock()
	defer e.eventMu.RUnlock()
	for ch := range e.subscribers {
		select {
		case ch <- event:
		default:
		}
	}
}

func appendLine(path string, b []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.Write(append(b, '\n'))
	return err
}

func (e *Engine) Subscribe() (<-chan Event, func()) {
	ch := make(chan Event, 32)
	e.eventMu.Lock()
	e.subscribers[ch] = struct{}{}
	e.eventMu.Unlock()
	cancel := func() {
		e.eventMu.Lock()
		if _, ok := e.subscribers[ch]; ok {
			delete(e.subscribers, ch)
			close(ch)
		}
		e.eventMu.Unlock()
	}
	return ch, cancel
}

// overlayModelMetadata deliberately keeps identity/classification/safety flags from the
// deterministic demand parser. An optional model may enrich bounded descriptive metadata only.
func overlayModelMetadata(base, proposed ToolSpec) ToolSpec {
	out := base
	if v := cleanModelString(proposed.Title, 120); v != "" { out.Title = v }
	if v := cleanModelString(proposed.Purpose, 500); v != "" { out.Purpose = v }
	// Model metadata may add detail, but cannot remove deterministic baseline capabilities,
	// required request fields, outputs, or safeguards.
	out.Capabilities = mergeModelList(base.Capabilities, proposed.Capabilities, 12, 120)
	out.Inputs = mergeModelList(base.Inputs, proposed.Inputs, 12, 120)
	out.Outputs = mergeModelList(base.Outputs, proposed.Outputs, 12, 120)
	out.Safeguards = mergeModelList(base.Safeguards, proposed.Safeguards, 16, 180)
	out.Name = base.Name
	out.Demand = base.Demand
	out.Category = base.Category
	out.Industry = base.Industry
	out.NeedsHardwareGuide = base.NeedsHardwareGuide
	out.ModelAssisted = true
	out.ModelNote = cleanModelString(proposed.ModelNote, 180)
	if out.ModelNote == "" { out.ModelNote = "Model contributed bounded descriptive metadata; tool identity and safety classification remained deterministic." }
	return out
}

const defaultGuardianRules = `version: 1
mode: fail_closed
core_law: "Protect, not destroy. Human review required for generated artifacts."
block_categories:
  - weapons
  - warfare
  - explosives
  - malware_and_credential_theft
  - covert_surveillance
  - privacy_violations
  - illegal_operation
notes:
  - "Pattern screening is a safety layer, not a perfect semantic classifier."
  - "Research snippets and model-proposed metadata are untrusted and are screened before use."
  - "No generated code is executed, deployed, or merged automatically."
`

const defaultModelBlueprint = `name: generic_tool_blueprint
version: 1
purpose: "A model family specification from which safe, reviewable tool scaffolds can be derived."
inputs: [demand, research_evidence, policy_constraints]
outputs: [tool_specification, source_scaffold, tests, openapi, hardware_guide, evidence, merge_checklist]
execution: "proposal_only"
required_gates: [guardian, tests, human_review, explicit_merge]
model_optional: true
`
