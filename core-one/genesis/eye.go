package genesis

import (
	"context"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

var workaroundMarker = regexp.MustCompile(`(?i)\b(todo|fixme|workaround|temporary|hack)\b[: -]*`)
var topicStopWords = map[string]bool{
	"about": true, "after": true, "again": true, "being": true, "build": true, "could": true, "create": true, "first": true, "from": true, "have": true, "into": true, "just": true, "make": true, "more": true, "most": true, "other": true, "over": true, "same": true, "should": true, "since": true, "some": true, "such": true, "than": true, "that": true, "their": true, "them": true, "then": true, "there": true, "these": true, "they": true, "this": true, "those": true, "through": true, "tool": true, "tools": true, "using": true, "very": true, "when": true, "where": true, "which": true, "while": true, "with": true, "work": true, "would": true, "system": true, "based": true, "data": true, "project": true, "research": true, "technology": true, "result": true, "source": true, "github": true, "software": true, "repository": true, "kenya": true, "demand": true, "emerging": true, "hardware": true, "integration": true, "standards": true, "innovation": true, "available": true, "recent": true, "search": true,
}

type gapSignal struct {
	Signature string `json:"signature"`
	Count     int    `json:"count"`
	Marker    string `json:"marker"`
}

// EyeScan performs one model-free discovery cycle: external research, repository gap fingerprinting,
// provenance persistence, and threshold-based demand triggering. Triggered work remains await-merge.
func (e *Engine) EyeScan(ctx context.Context) error {
	if ctx == nil { ctx = context.Background() }
	select { case <-ctx.Done(): return ctx.Err(); default: }
	e.mu.RLock(); researcher := e.Researcher; e.mu.RUnlock(); if researcher == nil { researcher = NewWebResearcher() }
	e.publish(Event{Type: "eye_scan_started", At: time.Now().UTC(), Message: "Eye began a scheduled source and repository-gap scan."})
	evidence, err := researcher.Research(ctx, "emerging technology demand engineering workarounds hardware integration standards Kenya")
	if err != nil { return err }
	if err := ctx.Err(); err != nil { return err }
	for _, src := range evidence.Sources {
		if src.Status != "retrieved" { continue }
		if d := e.Guardian.Check(src.Name + " " + src.Title + " " + src.Snippet); !d.Allowed {
			_ = e.Guardian.LogBlocked("eye_research_source", src.URL+" "+src.Title+" "+src.Snippet, d.Reason)
			e.publish(Event{Type: "eye_source_blocked", At: time.Now().UTC(), Message: "Guardian blocked an unsafe research record; it was not added to evidence or used to trigger invention.", Status: d.Code})
			return ErrBlocked
		}
	}
	gaps, scanErr := scanRepositoryGaps(e.RepoRoot)
	if scanErr != nil { evidence.Findings = append(evidence.Findings, "Repository gap scan incomplete: "+limitText(scanErr.Error(), 180)) }
	for _, g := range gaps { evidence.Findings = append(evidence.Findings, fmt.Sprintf("Local gap signal: marker=%s, count=%d, signature=%s.", g.Marker, g.Count, g.Signature)) }
	evidence.Findings = append(evidence.Findings, "Eye scan does not execute source code or treat search results as verified market, legal, standards, or patent conclusions.")
	if err := e.saveResearchEvidence(evidence); err != nil { return err }
	threshold := configuredThreshold("GENESIS_WORKAROUND_THRESHOLD", 6)
	for _, gap := range gaps {
		if gap.Count >= threshold {
			demand := fmt.Sprintf("Create a generic remediation tool for repeated repository workaround signature %s", gap.Signature)
			if e.triggerOnce(ctx, "workaround:"+gap.Signature, demand) { break }
		}
	}
	demandThreshold := configuredThreshold("GENESIS_DEMAND_THRESHOLD", 5)
	if topic, count := repeatedTopic(evidence.Sources); topic != "" && count >= demandThreshold {
		demand := fmt.Sprintf("Create a reusable tool for emerging cross-source demand theme %s", topic)
		_ = e.triggerOnce(ctx, "demand:"+topic, demand)
	}
	e.publish(Event{Type: "eye_scan_completed", At: time.Now().UTC(), Message: fmt.Sprintf("Eye scan completed: %d research source records and %d repeated-workaround signals.", len(evidence.Sources), len(gaps)), Status: "ok"})
	return nil
}

func (e *Engine) triggerOnce(ctx context.Context, key, demand string) bool {
	statePath := filepath.Join(e.CoreRoot, "state", "eye", "triggered.json")
	var seen map[string]string
	if raw, err := os.ReadFile(statePath); err == nil { _ = jsonUnmarshal(raw, &seen) }
	if seen == nil { seen = map[string]string{} }
	if _, ok := seen[key]; ok { return false }
	inv, err := e.Invent(ctx, demand)
	if err != nil { return false }
	seen[key] = inv.Name
	if writeJSON(statePath, seen) != nil { return false }
	e.publish(Event{Type: "eye_auto_invention", At: time.Now().UTC(), Message: "A research/repository threshold triggered a new proposal awaiting human merge.", Invention: inv.Name, Status: "await_merge"})
	return true
}

func configuredThreshold(env string, fallback int) int {
	var n int
	if raw := strings.TrimSpace(os.Getenv(env)); raw != "" { if _, err := fmt.Sscanf(raw, "%d", &n); err == nil && n > 0 && n <= 1000 { return n } }
	return fallback
}

func scanRepositoryGaps(repoRoot string) ([]gapSignal, error) {
	counts := map[string]int{}; markerBySig := map[string]string{}; fileCount := 0; var firstErr error
	err := filepath.WalkDir(repoRoot, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil { if firstErr == nil { firstErr = walkErr }; return nil }
		if d.IsDir() { base:=d.Name(); if base==".git"||base=="node_modules"||base=="vendor"||base=="dist"||base=="build"||base==".venv"||base=="venv"||base==".next"||base=="core-one"||strings.HasPrefix(base,".staging-"){return filepath.SkipDir}; return nil }
		if fileCount >= 25000 { return fs.SkipAll }; if !isTextSource(path) { return nil }; fileCount++
		info,err:=d.Info();if err!=nil||info.Size()>1<<20{return nil};raw,err:=os.ReadFile(path);if err!=nil{return nil}
		for _,line:=range strings.Split(string(raw),"\n") { match:=workaroundMarker.FindStringIndex(line);if match==nil{continue};phrase:=strings.ToLower(strings.TrimSpace(line[match[1]:]));phrase=regexp.MustCompile(`[^a-z0-9]+`).ReplaceAllString(phrase," ");phrase=strings.Join(strings.Fields(phrase)," ");if len(phrase)<12{continue};if len(phrase)>120{phrase=phrase[:120]};sig:=sha256String(phrase)[:12];counts[sig]++;markerBySig[sig]=strings.ToLower(strings.TrimSpace(line[:match[0]+1])) }
		return nil
	})
	if err!=nil&&firstErr==nil{firstErr=err};out:=[]gapSignal{};for sig,count:=range counts{if count>1{out=append(out,gapSignal{Signature:sig,Count:count,Marker:limitText(markerBySig[sig],40)})}}
	sort.Slice(out,func(i,j int)bool{return out[i].Count>out[j].Count});return out,firstErr
}
func isTextSource(path string) bool {
	ext:=strings.ToLower(filepath.Ext(path));switch ext{case ".go",".py",".js",".jsx",".ts",".tsx",".md",".json",".yaml",".yml",".toml",".rs",".java",".sh",".sql",".html",".css",".txt",".tf",".c",".h",".cpp",".xml":return true};return false
}
func repeatedTopic(sources []ResearchSource) (string, int) {
	counts:=map[string]int{};seenSource:=map[string]map[string]bool{}
	for _,src:=range sources{if src.Status!="retrieved"{continue};text:=strings.ToLower(src.Title+" "+src.Snippet);tokens:=strings.FieldsFunc(text,func(r rune)bool{return !(r>='a'&&r<='z'||r>='0'&&r<='9')});once:=map[string]bool{};for _,t:=range tokens{if len(t)<5||topicStopWords[t]||once[t]{continue};once[t]=true;if seenSource[t]==nil{seenSource[t]=map[string]bool{}};if !seenSource[t][src.URL]{seenSource[t][src.URL]=true;counts[t]++}}}
	best:="";n:=0;for topic,count:=range counts{if count>n{best=topic;n=count}};return best,n
}
