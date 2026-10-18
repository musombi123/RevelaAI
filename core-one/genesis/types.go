package genesis

import (
	"context"
	"time"
)

const Version = "0.2.0-alpha"

// Demand is an untrusted request to propose a new tool. It is never executed as code.
type Demand struct {
	ID        string    `json:"id"`
	Demand    string    `json:"demand"`
	Source    string    `json:"source,omitempty"`
	CreatedAt time.Time `json:"created_at"`
	Status    string    `json:"status"`
	Error     string    `json:"error,omitempty"`
}

type ResearchSource struct {
	Name      string    `json:"name"`
	URL       string    `json:"url"`
	Status    string    `json:"status"`
	Title     string    `json:"title,omitempty"`
	Snippet   string    `json:"snippet,omitempty"`
	Retrieved time.Time `json:"retrieved_at,omitempty"`
}

type ResearchEvidence struct {
	ID          string           `json:"id"`
	Query       string           `json:"query"`
	CollectedAt time.Time        `json:"collected_at"`
	Mode        string           `json:"mode"`
	Sources     []ResearchSource `json:"sources"`
	Findings    []string         `json:"findings"`
}

type ToolSpec struct {
	Name               string   `json:"name"`
	Title              string   `json:"title"`
	Demand             string   `json:"demand"`
	Purpose            string   `json:"purpose"`
	Category           string   `json:"category"`
	Industry           string   `json:"industry"`
	Capabilities       []string `json:"capabilities"`
	Inputs             []string `json:"inputs"`
	Outputs            []string `json:"outputs"`
	Safeguards         []string `json:"safeguards"`
	NeedsHardwareGuide bool     `json:"needs_hardware_guide"`
	ModelAssisted      bool     `json:"model_assisted"`
	ModelNote          string   `json:"model_note,omitempty"`
}

type Invention struct {
	ID        string           `json:"id"`
	Name      string           `json:"name"`
	Title     string           `json:"title"`
	Status    string           `json:"status"`
	CreatedAt time.Time        `json:"created_at"`
	Directory string           `json:"directory"`
	Library   string           `json:"library"`
	Model     string           `json:"model"`
	Category  string           `json:"category"`
	Industry  string           `json:"industry"`
	Files     []string         `json:"files"`
	Evidence  ResearchEvidence `json:"evidence"`
	Summary   string           `json:"summary"`
}

type Event struct {
	ID        string    `json:"id"`
	Type      string    `json:"type"`
	At        time.Time `json:"at"`
	Message   string    `json:"message"`
	Invention string    `json:"invention,omitempty"`
	Status    string    `json:"status,omitempty"`
}

type Researcher interface {
	Research(ctx context.Context, demand string) (ResearchEvidence, error)
}

type ModelAdapter interface {
	Suggest(ctx context.Context, demand string, evidence ResearchEvidence, fallback ToolSpec) (ToolSpec, error)
}
