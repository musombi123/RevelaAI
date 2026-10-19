// Package candidate provides a proposal-only Core-Two graph index.
//
// This candidate is not wired into Core-One and performs no external I/O.
package candidate

import (
	"fmt"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

const CandidateID = "graph-indexed"

const (
	MaxGraphNodes   = 100_000
	MaxGraphEdges   = 1_000_000
	MaxGraphNodeID  = 512
)

// Graph represents a directed adjacency-list graph.
// Neighbors that are not explicit map keys are treated as terminal nodes.
type Graph map[string][]string

// GraphIndex is a validated, read-only-by-API graph index.
//
// Its fields are private. Methods return copies of internal slices so callers
// cannot mutate the index through returned values.
type GraphIndex struct {
	adjacency map[string][]string
	reverse   map[string][]string
	nodes     []string
	edges     int
}

// BuildGraphIndex validates and indexes a graph.
//
// It preserves neighbor order for each source node, removes duplicate edges,
// builds a reverse index, and includes nodes referenced only by edges.
//
// Empty neighbor labels are ignored for compatibility with Reachable's
// original behavior. Empty graph keys are rejected.
func BuildGraphIndex(graph Graph) (*GraphIndex, error) {
	if len(graph) > MaxGraphNodes {
		return nil, fmt.Errorf(
			"graph has %d declared nodes; maximum is %d",
			len(graph),
			MaxGraphNodes,
		)
	}

	index := &GraphIndex{
		adjacency: make(map[string][]string, len(graph)),
		reverse:   make(map[string][]string, len(graph)),
	}

	keys := make([]string, 0, len(graph))

	for node := range graph {
		if err := validateGraphNodeID(node); err != nil {
			return nil, fmt.Errorf("invalid graph key: %w", err)
		}
		keys = append(keys, node)
	}

	// Sort sources so reverse-index results are deterministic.
	sort.Strings(keys)

	ensureNode := func(node string) error {
		if _, exists := index.adjacency[node]; exists {
			return nil
		}

		if len(index.adjacency) >= MaxGraphNodes {
			return fmt.Errorf(
				"graph exceeds the maximum of %d unique nodes",
				MaxGraphNodes,
			)
		}

		index.adjacency[node] = nil
		index.reverse[node] = nil

		return nil
	}

	for _, node := range keys {
		if err := ensureNode(node); err != nil {
			return nil, err
		}
	}

	scannedEdges := 0

	for _, source := range keys {
		neighbors := graph[source]
		seenNeighbors := make(map[string]struct{}, len(neighbors))

		for _, target := range neighbors {
			scannedEdges++

			if scannedEdges > MaxGraphEdges {
				return nil, fmt.Errorf(
					"graph exceeds the maximum of %d input edges",
					MaxGraphEdges,
				)
			}

			// Preserve the original traversal behavior for blank neighbors.
			if target == "" {
				continue
			}

			if err := validateGraphNodeID(target); err != nil {
				return nil, fmt.Errorf(
					"invalid neighbor of %q: %w",
					source,
					err,
				)
			}

			if _, duplicate := seenNeighbors[target]; duplicate {
				continue
			}
			seenNeighbors[target] = struct{}{}

			if err := ensureNode(target); err != nil {
				return nil, err
			}

			index.adjacency[source] = append(
				index.adjacency[source],
				target,
			)

			index.reverse[target] = append(
				index.reverse[target],
				source,
			)

			index.edges++
		}
	}

	index.nodes = make([]string, 0, len(index.adjacency))
	for node := range index.adjacency {
		index.nodes = append(index.nodes, node)
	}
	sort.Strings(index.nodes)

	return index, nil
}

// ValidateGraph checks whether a graph can be safely indexed.
func ValidateGraph(graph Graph) error {
	_, err := BuildGraphIndex(graph)
	return err
}

// Reachable performs breadth-first traversal using the validated index.
//
// The starting node is included in the result. A valid but unknown starting
// node therefore produces a one-element result, matching the original API.
func (g *GraphIndex) Reachable(start string) []string {
	if g == nil || validateGraphNodeID(start) != nil {
		return nil
	}

	queue := []string{start}
	seen := map[string]struct{}{
		start: {},
	}
	result := make([]string, 0, 1)

	for head := 0; head < len(queue); head++ {
		node := queue[head]
		result = append(result, node)

		for _, next := range g.adjacency[node] {
			if _, exists := seen[next]; exists {
				continue
			}

			seen[next] = struct{}{}
			queue = append(queue, next)
		}
	}

	return result
}

// ReachableChecked validates the graph and returns traversal errors.
//
// Unlike Reachable, this function can report malformed or oversized graphs.
func ReachableChecked(graph Graph, start string) ([]string, error) {
	index, err := BuildGraphIndex(graph)
	if err != nil {
		return nil, err
	}

	if start == "" {
		return nil, nil
	}

	if err := validateGraphNodeID(start); err != nil {
		return nil, fmt.Errorf("invalid starting node: %w", err)
	}

	return index.Reachable(start), nil
}

// Reachable preserves the original public function signature.
//
// If the supplied graph is invalid or exceeds configured limits, it returns
// nil. Use ReachableChecked when the caller needs an explanation of failure.
func Reachable(graph Graph, start string) []string {
	result, err := ReachableChecked(graph, start)
	if err != nil {
		return nil
	}
	return result
}

// Neighbors returns a copy of a node's outgoing neighbors.
func (g *GraphIndex) Neighbors(node string) []string {
	if g == nil {
		return nil
	}

	neighbors, exists := g.adjacency[node]
	if !exists {
		return nil
	}

	return append([]string(nil), neighbors...)
}

// Predecessors returns a copy of the nodes that directly point to node.
//
// Results are deterministic because the index processes source nodes in
// sorted order. Duplicate edges do not create duplicate predecessors.
func (g *GraphIndex) Predecessors(node string) []string {
	if g == nil {
		return nil
	}

	predecessors, exists := g.reverse[node]
	if !exists {
		return nil
	}

	return append([]string(nil), predecessors...)
}

// Nodes returns all indexed node identifiers in sorted order.
func (g *GraphIndex) Nodes() []string {
	if g == nil {
		return nil
	}

	return append([]string(nil), g.nodes...)
}

// NodeCount reports the number of distinct indexed nodes.
func (g *GraphIndex) NodeCount() int {
	if g == nil {
		return 0
	}

	return len(g.nodes)
}

// EdgeCount reports the number of distinct indexed directed edges.
func (g *GraphIndex) EdgeCount() int {
	if g == nil {
		return 0
	}

	return g.edges
}

// HasPath reports whether target is reachable from source.
//
// A node has a path to itself when that node exists in the index.
func (g *GraphIndex) HasPath(source, target string) bool {
	return g.ShortestPath(source, target) != nil
}

// ShortestPath returns a shortest directed path from source to target.
//
// Breadth-first search finds the shortest path by edge count. When multiple
// shortest paths exist, adjacency order determines which one is returned.
// The path contains both endpoints. It returns nil if either endpoint does
// not exist or no path connects them.
func (g *GraphIndex) ShortestPath(source, target string) []string {
	if g == nil {
		return nil
	}

	if validateGraphNodeID(source) != nil ||
		validateGraphNodeID(target) != nil {
		return nil
	}

	if _, exists := g.adjacency[source]; !exists {
		return nil
	}
	if _, exists := g.adjacency[target]; !exists {
		return nil
	}

	if source == target {
		return []string{source}
	}

	queue := []string{source}
	visited := map[string]struct{}{
		source: {},
	}
	parent := make(map[string]string)

	found := false

	for head := 0; head < len(queue); head++ {
		current := queue[head]

		for _, next := range g.adjacency[current] {
			if _, exists := visited[next]; exists {
				continue
			}

			visited[next] = struct{}{}
			parent[next] = current

			if next == target {
				found = true
				break
			}

			queue = append(queue, next)
		}

		if found {
			break
		}
	}

	if !found {
		return nil
	}

	path := []string{target}
	for current := target; current != source; {
		previous, exists := parent[current]
		if !exists {
			// Defensive guard against an inconsistent index.
			return nil
		}

		path = append(path, previous)
		current = previous
	}

	// Reverse the target-to-source reconstruction.
	for left, right := 0, len(path)-1; left < right; left, right = left+1, right-1 {
		path[left], path[right] = path[right], path[left]
	}

	return path
}

// Validate performs deterministic self-checks for this candidate.
func Validate() error {
	graph := Graph{
		"a": {"b", "c", "b"},
		"b": {"c", "a"},
		"c": {},
	}

	index, err := BuildGraphIndex(graph)
	if err != nil {
		return fmt.Errorf("build graph index: %w", err)
	}

	got := index.Reachable("a")
	want := []string{"a", "b", "c"}

	if !sameStrings(got, want) {
		return fmt.Errorf(
			"graph traversal mismatch: got %v, want %v",
			got,
			want,
		)
	}

	if index.NodeCount() != 3 {
		return fmt.Errorf(
			"node count mismatch: got %d, want 3",
			index.NodeCount(),
		)
	}

	if index.EdgeCount() != 4 {
		return fmt.Errorf(
			"edge count mismatch: got %d, want 4",
			index.EdgeCount(),
		)
	}

	predecessors := index.Predecessors("c")
	if !sameStrings(predecessors, []string{"a", "b"}) {
		return fmt.Errorf(
			"reverse-index mismatch: got %v, want [a b]",
			predecessors,
		)
	}

	path := index.ShortestPath("a", "c")
	if !sameStrings(path, []string{"a", "c"}) {
		return fmt.Errorf(
			"shortest-path mismatch: got %v, want [a c]",
			path,
		)
	}

	if !index.HasPath("b", "a") {
		return fmt.Errorf("expected path from b to a")
	}

	if index.HasPath("c", "a") {
		return fmt.Errorf("unexpected path from c to a")
	}

	unknown := index.Reachable("unknown")
	if !sameStrings(unknown, []string{"unknown"}) {
		return fmt.Errorf(
			"unknown-start behavior mismatch: got %v",
			unknown,
		)
	}

	if err := ValidateGraph(Graph{"valid": {"bad\nnode"}}); err == nil {
		return fmt.Errorf("expected invalid node identifier to be rejected")
	}

	if _, err := ReachableChecked(Graph{"a": {"b"}}, ""); err != nil {
		return fmt.Errorf("empty start should be accepted: %w", err)
	}

	return nil
}

func validateGraphNodeID(node string) error {
	if node == "" {
		return fmt.Errorf("node identifier must not be empty")
	}

	if !utf8.ValidString(node) {
		return fmt.Errorf("node identifier is not valid UTF-8")
	}

	if len(node) > MaxGraphNodeID {
		return fmt.Errorf(
			"node identifier exceeds %d bytes",
			MaxGraphNodeID,
		)
	}

	if strings.TrimSpace(node) != node {
		return fmt.Errorf("node identifier has surrounding whitespace")
	}

	for _, r := range node {
		if unicode.IsControl(r) {
			return fmt.Errorf("node identifier contains a control character")
		}
	}

	return nil
}

func sameStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}

	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}

	return true
}
