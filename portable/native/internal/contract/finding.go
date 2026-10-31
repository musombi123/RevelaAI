// Package contract defines the versioned hand-off format shared by the
// portable Field Engine and Meta Engineer. Findings are evidence, not verdicts.
package contract

import "time"

const SchemaVersion = "1.0"

type Evidence struct {
	Kind   string `json:"kind"`
	Ref    string `json:"ref"`
	SHA256 string `json:"sha256,omitempty"`
	Bytes  int64  `json:"bytes,omitempty"`
	Note   string `json:"note,omitempty"`
}

type Technique struct {
	Framework string `json:"framework"`
	ID        string `json:"id,omitempty"`
	Name      string `json:"name"`
	Tactic    string `json:"tactic,omitempty"`
}

type Finding struct {
	SchemaVersion  string      `json:"schema_version"`
	ID             string      `json:"id"`
	Source         string      `json:"source"`
	ObservedAt     time.Time   `json:"observed_at"`
	Target         string      `json:"target"`
	Category       string      `json:"category"`
	Severity       string      `json:"severity"`
	Title          string      `json:"title"`
	Summary        string      `json:"summary"`
	Evidence       []Evidence  `json:"evidence"`
	Recommendation string      `json:"recommendation"`
	Scope          string      `json:"scope"`
	Simulated      bool        `json:"simulated"`
	Techniques     []Technique `json:"techniques,omitempty"`
}
