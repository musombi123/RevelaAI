package mind

import (
	"errors"
	"fmt"
	"go/ast"
	"go/importer"
	"go/parser"
	"go/token"
	"go/types"
	"strconv"
	"strings"
	"unicode/utf8"
)

const (
	maxCandidateSourceBytes = 256 * 1024
	maxCandidateCount       = 100
	maxCandidateIDBytes     = 64
)

type candidateSpec struct {
	ID       string
	Category string
	Purpose  string
	Source   string
}

type CandidateEvaluation struct {
	ID               string         `json:"id"`
	Category         string         `json:"category"`
	ImprovementType  string         `json:"improvement_type"`
	BaselineValue    float64        `json:"baseline_value"`
	CandidateValue   float64        `json:"candidate_value"`
	ImprovementPct   float64        `json:"improvement_percent"`
	Passed           bool           `json:"passed"`
	MeasurementSource string        `json:"measurement_source"`
	Evidence         map[string]any `json:"evidence,omitempty"`
	Note             string         `json:"note,omitempty"`
}

const sharedCandidateTest = `package candidate

import "testing"

func TestProposalFixture(t *testing.T) {
	if err := Validate(); err != nil {
		t.Fatal(err)
	}
}
`

var candidateCatalog = []candidateSpec{
	{
		ID:       "graph-indexed",
		Category: "graph_traversal",
		Purpose: "Provide a reusable, validated graph index with deterministic traversal, reverse-edge lookup, and shortest-path discovery. The synthetic benchmark does not establish a production speedup.",
		Source: `package candidate

import (
	"errors"
	"sort"
	"strings"
)

const CandidateID = "graph-indexed"

const (
	MaxGraphNodes = 100000
	MaxGraphEdges = 1000000
	MaxNodeIDBytes = 512
)

type Graph map[string][]string

type Index struct {
	adjacency map[string][]string
	reverse   map[string][]string
	nodes     []string
	edges     int
}

func validNodeID(node string) bool {
	if node == "" || len(node) > MaxNodeIDBytes || strings.TrimSpace(node) != node {
		return false
	}
	for _, r := range node {
		if r < 32 || r == 127 {
			return false
		}
	}
	return true
}

func BuildIndex(graph Graph) (*Index, error) {
	if len(graph) > MaxGraphNodes {
		return nil, errors.New("graph exceeds node limit")
	}

	idx := &Index{
		adjacency: make(map[string][]string, len(graph)),
		reverse:   make(map[string][]string, len(graph)),
	}

	keys := make([]string, 0, len(graph))
	for node := range graph {
		if !validNodeID(node) {
			return nil, errors.New("invalid graph node")
		}
		keys = append(keys, node)
	}
	sort.Strings(keys)

	ensureNode := func(node string) error {
		if _, exists := idx.adjacency[node]; exists {
			return nil
		}
		if len(idx.adjacency) >= MaxGraphNodes {
			return errors.New("graph exceeds unique-node limit")
		}
		idx.adjacency[node] = nil
		idx.reverse[node] = nil
		return nil
	}

	for _, node := range keys {
		if err := ensureNode(node); err != nil {
			return nil, err
		}
	}

	inputEdges := 0
	for _, source := range keys {
		seen := make(map[string]struct{})

		for _, target := range graph[source] {
			inputEdges++
			if inputEdges > MaxGraphEdges {
				return nil, errors.New("graph exceeds input-edge limit")
			}

			if target == "" {
				continue
			}
			if !validNodeID(target) {
				return nil, errors.New("invalid edge target")
			}
			if _, exists := seen[target]; exists {
				continue
			}
			seen[target] = struct{}{}

			if err := ensureNode(target); err != nil {
				return nil, err
			}

			idx.adjacency[source] = append(idx.adjacency[source], target)
			idx.reverse[target] = append(idx.reverse[target], source)
			idx.edges++
		}
	}

	for node := range idx.adjacency {
		idx.nodes = append(idx.nodes, node)
	}
	sort.Strings(idx.nodes)

	return idx, nil
}

func (idx *Index) Reachable(start string) []string {
	if idx == nil || !validNodeID(start) {
		return nil
	}

	queue := []string{start}
	seen := map[string]struct{}{start: {}}
	out := make([]string, 0, len(idx.nodes))

	for head := 0; head < len(queue); head++ {
		node := queue[head]
		out = append(out, node)

		for _, next := range idx.adjacency[node] {
			if _, exists := seen[next]; exists {
				continue
			}
			seen[next] = struct{}{}
			queue = append(queue, next)
		}
	}

	return out
}

func (idx *Index) Predecessors(node string) []string {
	if idx == nil {
		return nil
	}
	return append([]string(nil), idx.reverse[node]...)
}

func (idx *Index) Nodes() []string {
	if idx == nil {
		return nil
	}
	return append([]string(nil), idx.nodes...)
}

func (idx *Index) NodeCount() int {
	if idx == nil {
		return 0
	}
	return len(idx.nodes)
}

func (idx *Index) EdgeCount() int {
	if idx == nil {
		return 0
	}
	return idx.edges
}

func (idx *Index) ShortestPath(source, target string) []string {
	if idx == nil || !validNodeID(source) || !validNodeID(target) {
		return nil
	}
	if _, exists := idx.adjacency[source]; !exists {
		return nil
	}
	if _, exists := idx.adjacency[target]; !exists {
		return nil
	}
	if source == target {
		return []string{source}
	}

	queue := []string{source}
	seen := map[string]struct{}{source: {}}
	parent := make(map[string]string)
	found := false

	for head := 0; head < len(queue) && !found; head++ {
		current := queue[head]
		for _, next := range idx.adjacency[current] {
			if _, exists := seen[next]; exists {
				continue
			}

			seen[next] = struct{}{}
			parent[next] = current

			if next == target {
				found = true
				break
			}

			queue = append(queue, next)
		}
	}

	if !found {
		return nil
	}

	path := []string{target}
	for current := target; current != source; {
		previous, exists := parent[current]
		if !exists {
			return nil
		}
		path = append(path, previous)
		current = previous
	}

	for left, right := 0, len(path)-1; left < right; left, right = left+1, right-1 {
		path[left], path[right] = path[right], path[left]
	}

	return path
}

// Reachable preserves the simple functional entry point for callers.
func Reachable(graph Graph, start string) []string {
	if start == "" {
		return nil
	}
	idx, err := BuildIndex(graph)
	if err != nil {
		return nil
	}
	return idx.Reachable(start)
}

func Validate() error {
	graph := Graph{
		"a": {"b", "c", "b"},
		"b": {"c", "d"},
		"c": {"d"},
		"d": {},
	}

	idx, err := BuildIndex(graph)
	if err != nil {
		return err
	}

	got := idx.Reachable("a")
	want := []string{"a", "b", "c", "d"}

	if len(got) != len(want) {
		return errors.New("reachability count mismatch")
	}
	for i := range want {
		if got[i] != want[i] {
			return errors.New("reachability order mismatch")
		}
	}

	if idx.NodeCount() != 4 || idx.EdgeCount() != 5 {
		return errors.New("graph index count mismatch")
	}

	path := idx.ShortestPath("a", "d")
	if len(path) != 3 || path[0] != "a" || path[2] != "d" {
		return errors.New("shortest-path result mismatch")
	}

	if len(idx.Predecessors("d")) != 2 {
		return errors.New("reverse-edge index mismatch")
	}

	if _, err := BuildIndex(Graph{"bad\nnode": {}}); err == nil {
		return errors.New("invalid node was accepted")
	}

	return nil
}
`,
	},
	{
		ID:       "bom-cost-ranked",
		Category: "bom_search",
		Purpose: "Rank supplied BOM quotations by availability and total quoted cost while detecting integer overflow. No live prices are fetched.",
		Source: `package candidate

import "errors"

const CandidateID = "bom-cost-ranked"

const maxInt64 = int64(9223372036854775807)

type Quote struct {
	Supplier      string
	UnitCost      int64
	TransportCost int64
	InStock       bool
}

func totalCost(q Quote) (int64, bool) {
	if q.UnitCost < 0 || q.TransportCost < 0 {
		return 0, false
	}
	if q.UnitCost > maxInt64-q.TransportCost {
		return 0, false
	}
	return q.UnitCost + q.TransportCost, true
}

func BestQuote(quotes []Quote) (Quote, bool) {
	var best Quote
	var bestCost int64
	found := false

	for _, quote := range quotes {
		if quote.Supplier == "" || !quote.InStock {
			continue
		}

		cost, ok := totalCost(quote)
		if !ok {
			continue
		}
		if !found || cost < bestCost {
			best = quote
			bestCost = cost
			found = true
		}
	}

	return best, found
}

func Validate() error {
	quotes := []Quote{
		{Supplier: "fixture-a", UnitCost: 1000, TransportCost: 250, InStock: true},
		{Supplier: "fixture-b", UnitCost: 900, TransportCost: 100, InStock: true},
		{Supplier: "fixture-unavailable", UnitCost: 1, TransportCost: 1, InStock: false},
		{Supplier: "fixture-overflow", UnitCost: maxInt64, TransportCost: 1, InStock: true},
	}

	got, ok := BestQuote(quotes)
	if !ok || got.Supplier != "fixture-b" {
		return errors.New("quote ranking mismatch")
	}
	return nil
}
`,
	},
	{
		ID:       "hardware-guide-structured",
		Category: "hardware_guide",
		Purpose: "Produce bounded, structured hardware guides with prerequisites, parts, steps, verification, and stop conditions.",
		Source: `package candidate

import (
	"errors"
	"strconv"
	"strings"
)

const CandidateID = "hardware-guide-structured"

const (
	MaxGuideItems = 100
	MaxGuideLine  = 240
)

func cleanLine(value string) string {
	replacer := strings.NewReplacer(
		"\r", " ",
		"\n", " ",
		"\x00", " ",
		"\t", " ",
	)
	value = strings.TrimSpace(replacer.Replace(value))
	if len(value) > MaxGuideLine {
		value = strings.ToValidUTF8(value[:MaxGuideLine], "")
	}
	return strings.TrimSpace(value)
}

func appendSection(b *strings.Builder, heading string, values []string, numbered bool) {
	b.WriteString(heading)
	b.WriteByte('\n')

	limit := len(values)
	if limit > MaxGuideItems {
		limit = MaxGuideItems
	}

	for i := 0; i < limit; i++ {
		value := cleanLine(values[i])
		if value == "" {
			continue
		}
		if numbered {
			b.WriteString(strconv.Itoa(i + 1))
			b.WriteString(". ")
		} else {
			b.WriteString("- ")
		}
		b.WriteString(value)
		b.WriteByte('\n')
	}
}

func BuildGuide(prerequisites, parts, steps, checks, stop []string) string {
	var b strings.Builder
	appendSection(&b, "Prerequisites", prerequisites, false)
	appendSection(&b, "Parts", parts, false)
	appendSection(&b, "Steps", steps, true)
	appendSection(&b, "Verification", checks, false)
	appendSection(&b, "Stop conditions", stop, false)
	return b.String()
}

func Validate() error {
	out := BuildGuide(
		[]string{"Disconnect the power source"},
		[]string{"Approved component"},
		[]string{"Inspect", "Test"},
		[]string{"Verify expected output"},
		[]string{"Stop if the setup is unsafe"},
	)

	for _, section := range []string{
		"Prerequisites",
		"Parts",
		"Steps",
		"Verification",
		"Stop conditions",
	} {
		if !strings.Contains(out, section) {
			return errors.New("required guide section missing")
		}
	}
	if !strings.Contains(out, "1. Inspect") || !strings.Contains(out, "2. Test") {
		return errors.New("guide step numbering mismatch")
	}
	return nil
}
`,
	},
	{
		ID:       "rvx-aead-envelope",
		Category: "rvx_protection",
		Purpose: "Stage authenticated AES-GCM artifact protection with domain-separated key derivation, explicit size bounds, and an externally managed key. Never claim absolute uncopyability.",
		Source: `package candidate

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"errors"
	"io"
)

const CandidateID = "rvx-aead-envelope"
const MaxPlaintext = 16 << 20
const rvxAAD = "revela-rvx-envelope-v2"

func deriveKey(master string) []byte {
	mac := hmac.New(sha256.New, []byte(master))
	_, _ = mac.Write([]byte("revela-rvx-envelope-v2/aes-256-gcm"))
	return mac.Sum(nil)
}

func Seal(key string, plain []byte) ([]byte, error) {
	if len(key) < 32 {
		return nil, errors.New("external key must be at least 32 bytes")
	}
	if len(plain) > MaxPlaintext {
		return nil, errors.New("plaintext exceeds RVX size limit")
	}

	block, err := aes.NewCipher(deriveKey(key))
	if err != nil {
		return nil, errors.New("cipher initialization failed")
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, errors.New("authenticated cipher initialization failed")
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, errors.New("nonce generation failed")
	}

	sealed := gcm.Seal(nil, nonce, plain, []byte(rvxAAD))
	out := make([]byte, 0, len(nonce)+len(sealed))
	out = append(out, nonce...)
	out = append(out, sealed...)
	return out, nil
}

func Open(key string, box []byte) ([]byte, error) {
	if len(key) < 32 {
		return nil, errors.New("invalid RVX key or envelope")
	}

	block, err := aes.NewCipher(deriveKey(key))
	if err != nil {
		return nil, errors.New("invalid RVX key or envelope")
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, errors.New("invalid RVX key or envelope")
	}

	if len(box) < gcm.NonceSize()+gcm.Overhead() ||
		len(box) > gcm.NonceSize()+MaxPlaintext+gcm.Overhead() {
		return nil, errors.New("invalid RVX key or envelope")
	}

	nonce := box[:gcm.NonceSize()]
	ciphertext := box[gcm.NonceSize():]

	plain, err := gcm.Open(nil, nonce, ciphertext, []byte(rvxAAD))
	if err != nil {
		return nil, errors.New("RVX authentication failed")
	}
	if len(plain) > MaxPlaintext {
		return nil, errors.New("decrypted content exceeds RVX size limit")
	}

	return plain, nil
}

func Validate() error {
	// This value is test-only and must never be used in production.
	key := "fixture-only-key-not-a-production-secret-012345"

	box, err := Seal(key, []byte("sample"))
	if err != nil {
		return err
	}

	plain, err := Open(key, box)
	if err != nil || string(plain) != "sample" {
		return errors.New("authenticated encryption round trip failed")
	}

	box[len(box)-1] ^= 1
	if _, err := Open(key, box); err == nil {
		return errors.New("tampering was not detected")
	}

	return nil
}
`,
	},
	{
		ID:       "cross-industry-pollination",
		Category: "pollination",
		Purpose: "Find shared capabilities across explicitly supplied domain lists without performing automatic integration.",
		Source: `package candidate

import (
	"errors"
	"sort"
	"strings"
)

const CandidateID = "cross-industry-pollination"
const MaxCapabilityCount = 10000
const MaxCapabilityLength = 256

func Shared(a, b []string) []string {
	if len(a) > MaxCapabilityCount || len(b) > MaxCapabilityCount {
		return nil
	}

	set := make(map[string]struct{}, len(a))
	for _, value := range a {
		value = strings.TrimSpace(value)
		if value == "" || len(value) > MaxCapabilityLength {
			continue
		}
		set[value] = struct{}{}
	}

	seen := make(map[string]struct{})
	out := make([]string, 0)

	for _, value := range b {
		value = strings.TrimSpace(value)
		if value == "" || len(value) > MaxCapabilityLength {
			continue
		}

		if _, exists := set[value]; !exists {
			continue
		}
		if _, exists := seen[value]; exists {
			continue
		}

		seen[value] = struct{}{}
		out = append(out, value)
	}

	sort.Strings(out)
	return out
}

func Validate() error {
	got := Shared(
		[]string{"offline", "audit", "offline"},
		[]string{"audit", "offline", "audit"},
	)
	if len(got) != 2 || got[0] != "audit" || got[1] != "offline" {
		return errors.New("cross-domain capability matching failed")
	}
	return nil
}
`,
	},
	{
		ID:       "evidence-hash-dedup",
		Category: "evidence",
		Purpose: "Deduplicate supplied research evidence using stable content fingerprints while preserving first-seen order.",
		Source: `package candidate

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
)

const CandidateID = "evidence-hash-dedup"
const MaxEvidenceRows = 100000
const MaxEvidenceBytes = 1 << 20

func Deduplicate(items []string) []string {
	if len(items) > MaxEvidenceRows {
		return nil
	}

	seen := make(map[string]struct{}, len(items))
	out := make([]string, 0, len(items))

	for _, item := range items {
		item = strings.TrimSpace(item)
		if item == "" || len(item) > MaxEvidenceBytes {
			continue
		}

		sum := sha256.Sum256([]byte(item))
		fingerprint := hex.EncodeToString(sum[:])

		if _, exists := seen[fingerprint]; exists {
			continue
		}

		seen[fingerprint] = struct{}{}
		out = append(out, item)
	}

	return out
}

func Validate() error {
	got := Deduplicate([]string{"alpha", "alpha", " beta ", ""})
	if len(got) != 2 || got[0] != "alpha" || got[1] != "beta" {
		return errors.New("evidence deduplication failed")
	}
	return nil
}
`,
	},
	{
		ID:       "canonical-spec-cache",
		Category: "spec_cache",
		Purpose: "Create deterministic fingerprints for bounded immutable specification maps so equivalent maps share the same fingerprint.",
		Source: `package candidate

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
)

const CandidateID = "canonical-spec-cache"
const MaxSpecFields = 10000
const MaxSpecFieldBytes = 4096

func Fingerprint(spec map[string]string) string {
	if len(spec) > MaxSpecFields {
		return ""
	}
	for key, value := range spec {
		if key == "" || len(key) > MaxSpecFieldBytes || len(value) > MaxSpecFieldBytes {
			return ""
		}
	}

	// encoding/json sorts map keys for deterministic serialization.
	raw, err := json.Marshal(spec)
	if err != nil {
		return ""
	}

	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func Validate() error {
	a := Fingerprint(map[string]string{"b": "2", "a": "1"})
	b := Fingerprint(map[string]string{"a": "1", "b": "2"})
	if a == "" || a != b {
		return errors.New("canonical fingerprint is not deterministic")
	}
	return nil
}
`,
	},
	{
		ID:       "repository-path-index",
		Category: "path_index",
		Purpose: "Build a deterministic read-only index of normalized relative repository paths without accessing or executing repository files.",
		Source: `package candidate

import (
	"errors"
	"strings"
)

const CandidateID = "repository-path-index"
const MaxIndexedPaths = 100000
const MaxIndexedPathBytes = 4096

func safeRelativePath(value string) bool {
	if value == "" || len(value) > MaxIndexedPathBytes {
		return false
	}

	value = strings.ReplaceAll(value, "\\", "/")
	if strings.HasPrefix(value, "/") ||
		(len(value) >= 2 && value[1] == ':') {
		return false
	}

	for _, part := range strings.Split(value, "/") {
		if part == ".." || part == "." {
			return false
		}
	}

	for _, r := range value {
		if r < 32 || r == 127 {
			return false
		}
	}

	return true
}

func BuildIndex(paths []string) map[string]int {
	if len(paths) > MaxIndexedPaths {
		return map[string]int{}
	}

	out := make(map[string]int, len(paths))
	for i, path := range paths {
		path = strings.ReplaceAll(strings.TrimSpace(path), "\\", "/")
		if !safeRelativePath(path) {
			continue
		}
		if _, exists := out[path]; !exists {
			out[path] = i
		}
	}
	return out
}

func Validate() error {
	index := BuildIndex([]string{
		"module/a.go",
		"module/b.go",
		"module/a.go",
		"../outside",
		"module/../../outside",
	})

	if len(index) != 2 || index["module/a.go"] != 0 || index["module/b.go"] != 1 {
		return errors.New("path index mismatch")
	}
	return nil
}
`,
	},
	{
		ID:       "tamper-evident-audit-chain",
		Category: "audit_integrity",
		Purpose: "Link audit-event hashes so changes to retained event sequences are detectable; this does not prevent deletion or compromise of the whole chain.",
		Source: `package candidate

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
)

const CandidateID = "tamper-evident-audit-chain"
const MaxAuditEvents = 100000
const MaxAuditEventBytes = 1 << 20

func Chain(events []string) []string {
	if len(events) > MaxAuditEvents {
		return nil
	}

	out := make([]string, 0, len(events))
	previous := ""

	for _, event := range events {
		if len(event) > MaxAuditEventBytes {
			return nil
		}
		sum := sha256.Sum256([]byte(previous + "\n" + event))
		previous = hex.EncodeToString(sum[:])
		out = append(out, previous)
	}

	return out
}

func Verify(events, hashes []string) bool {
	if len(events) != len(hashes) || len(events) > MaxAuditEvents {
		return false
	}

	want := Chain(events)
	if len(want) != len(hashes) {
		return false
	}

	for i := range want {
		if want[i] != hashes[i] {
			return false
		}
	}

	return true
}

func Validate() error {
	original := []string{"created", "checked"}
	hashes := Chain(original)
	if !Verify(original, hashes) {
		return errors.New("valid audit chain was rejected")
	}

	modified := []string{"altered", "checked"}
	if Verify(modified, hashes) {
		return errors.New("audit modification was not detected")
	}

	return nil
}
`,
	},
	{
		ID:       "bounded-input-guard",
		Category: "input_safety",
		Purpose: "Reject oversized, malformed, absolute, or path-traversal inputs before proposal generation.",
		Source: `package candidate

import (
	"errors"
	"net/url"
	"strings"
	"unicode/utf8"
)

const CandidateID = "bounded-input-guard"
const MaxInputBytes = 4096

func ValidInput(value string) bool {
	if value == "" ||
		len(value) > MaxInputBytes ||
		!utf8.ValidString(value) {
		return false
	}

	clean := strings.ReplaceAll(value, "\\", "/")

	// Detect common single- and double-encoded traversal strings.
	for i := 0; i < 2; i++ {
		decoded, err := url.PathUnescape(clean)
		if err != nil {
			return false
		}
		if decoded == clean {
			break
		}
		clean = strings.ReplaceAll(decoded, "\\", "/")
		if len(clean) > MaxInputBytes {
			return false
		}
	}

	if strings.HasPrefix(clean, "/") ||
		(len(clean) >= 2 && clean[1] == ':') {
		return false
	}

	for _, part := range strings.Split(clean, "/") {
		if part == "." || part == ".." {
			return false
		}
	}

	for _, r := range clean {
		if r < 32 || r == 127 {
			return false
		}
	}

	return true
}

func Validate() error {
	if !ValidInput("safe input") {
		return errors.New("valid input was rejected")
	}

	for _, value := range []string{
		"",
		"../outside",
		"a/../outside",
		"..\\outside",
		"%2e%2e%2foutside",
		"%252e%252e%252foutside",
		strings.Repeat("x", MaxInputBytes+1),
		string([]byte{0, 1}),
	} {
		if ValidInput(value) {
			return errors.New("unsafe input was accepted")
		}
	}
	return nil
}
`,
	},
}

func sourceFor(id string) (candidateSpec, bool) {
	for _, spec := range candidateCatalog {
		if spec.ID == id {
			return spec, true
		}
	}
	return candidateSpec{}, false
}

// isExactAllowlistedCandidate checks the full catalog entry, not merely the ID.
func isExactAllowlistedCandidate(spec candidateSpec) bool {
	for _, allowed := range candidateCatalog {
		if allowed.ID == spec.ID {
			return allowed.Category == spec.Category &&
				allowed.Purpose == spec.Purpose &&
				allowed.Source == spec.Source
		}
	}
	return false
}

func validateCandidateSource(spec candidateSpec) error {
	if !validName(spec.ID) ||
		len(spec.ID) > maxCandidateIDBytes ||
		spec.Category == "" ||
		spec.Purpose == "" {
		return errors.New("candidate metadata is incomplete or invalid")
	}

	if !isExactAllowlistedCandidate(spec) {
		return fmt.Errorf(
			"candidate %q differs from the approved static catalog",
			spec.ID,
		)
	}

	if len(spec.Source) == 0 ||
		len(spec.Source) > maxCandidateSourceBytes ||
		!utf8.ValidString(spec.Source) {
		return fmt.Errorf(
			"candidate %q source is empty, oversized, or invalid UTF-8",
			spec.ID,
		)
	}

	if !strings.Contains(spec.Source, "const CandidateID =") ||
		!strings.Contains(spec.Source, "func Validate() error") {
		return fmt.Errorf(
			"candidate %q is missing its required identity or validation function",
			spec.ID,
		)
	}

	fset := token.NewFileSet()
	file, err := parser.ParseFile(
		fset,
		spec.ID+".go",
		spec.Source,
		parser.AllErrors,
	)
	if err != nil {
		return fmt.Errorf("candidate %q does not parse: %w", spec.ID, err)
	}

	if file.Name == nil || file.Name.Name != "candidate" {
		return fmt.Errorf("candidate %q has an unexpected package name", spec.ID)
	}

	if err := validateCandidateIdentity(file, spec.ID); err != nil {
		return fmt.Errorf("candidate %q: %w", spec.ID, err)
	}

	allowedImports := map[string]bool{
		"errors":       true,
		"strings":      true,
		"strconv":      true,
		"sort":         true,
		"io":           true,
		"net/url":      true,
		"unicode/utf8": true,
		"crypto/aes":   true,
		"crypto/cipher": true,
		"crypto/rand":  true,
		"crypto/sha256": true,
		"crypto/hmac":  true,
		"encoding/hex": true,
		"encoding/json": true,
	}

	for _, importSpec := range file.Imports {
		importPath, err := strconv.Unquote(importSpec.Path.Value)
		if err != nil {
			return fmt.Errorf("candidate %q contains a malformed import", spec.ID)
		}
		if !allowedImports[importPath] {
			return fmt.Errorf(
				"candidate %q imports disallowed package %q",
				spec.ID,
				importPath,
			)
		}
	}

	var inspectionErr error

	ast.Inspect(file, func(node ast.Node) bool {
		switch n := node.(type) {
		case *ast.FuncDecl:
			if n.Recv == nil && n.Name.Name == "init" {
				inspectionErr = errors.New("init functions are not permitted")
				return false
			}
		case *ast.GoStmt:
			inspectionErr = errors.New("goroutine creation is not permitted")
			return false
		}
		return inspectionErr == nil
	})

	if inspectionErr != nil {
		return fmt.Errorf(
			"candidate %q failed AST safety checks: %w",
			spec.ID,
			inspectionErr,
		)
	}

	config := types.Config{
		Importer: importer.Default(),
	}

	if _, err := config.Check(
		"revela-mind.local/core-two/mutations/"+spec.ID,
		fset,
		[]*ast.File{file},
		nil,
	); err != nil {
		return fmt.Errorf(
			"candidate %q failed static type checking: %w",
			spec.ID,
			err,
		)
	}

	return nil
}

func validateCandidateIdentity(file *ast.File, expected string) error {
	for _, declaration := range file.Decls {
		general, ok := declaration.(*ast.GenDecl)
		if !ok || general.Tok != token.CONST {
			continue
		}

		for _, rawSpec := range general.Specs {
			valueSpec, ok := rawSpec.(*ast.ValueSpec)
			if !ok {
				continue
			}

			for i, name := range valueSpec.Names {
				if name.Name != "CandidateID" {
					continue
				}

				if i >= len(valueSpec.Values) {
					return errors.New("CandidateID has no literal value")
				}

				literal, ok := valueSpec.Values[i].(*ast.BasicLit)
				if !ok || literal.Kind != token.STRING {
					return errors.New("CandidateID must be a string literal")
				}

				value, err := strconv.Unquote(literal.Value)
				if err != nil || value != expected {
					return errors.New("CandidateID does not match catalog identity")
				}

				return nil
			}
		}
	}

	return errors.New("CandidateID declaration is missing")
}

// validateCandidateCatalog checks the catalog itself for duplicate IDs and
// rejects entries that cannot pass the same validation required before staging.
func validateCandidateCatalog() error {
	if len(candidateCatalog) == 0 || len(candidateCatalog) > maxCandidateCount {
		return errors.New("candidate catalog is empty or exceeds its size limit")
	}

	seen := make(map[string]bool, len(candidateCatalog))

	for _, spec := range candidateCatalog {
		if seen[spec.ID] {
			return fmt.Errorf("duplicate candidate ID %q", spec.ID)
		}
		seen[spec.ID] = true

		if err := validateCandidateSource(spec); err != nil {
			return err
		}
	}

	return nil
}
