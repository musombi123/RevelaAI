package genesis

import (
	"bufio"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const maxToolTelemetryBytes int64 = 16 << 20

var toolTelemetryMu sync.Mutex

// ToolCallTelemetry deliberately excludes prompts, arguments, user content,
// output content, credentials and request headers.
type ToolCallTelemetry struct {
	At          time.Time `json:"at"`
	Tool        string    `json:"tool"`
	VersionHash string    `json:"version_hash"`
	Success     bool      `json:"success"`
	LatencyMS   int64     `json:"latency_ms"`
	ErrorClass  string    `json:"error_class,omitempty"`
}

func appendToolCallTelemetry(coreRoot string, event ToolCallTelemetry) error {
	if !validResourceName(event.Tool) || len(event.VersionHash) != 64 || strings.Trim(event.VersionHash, "0123456789abcdef") != "" {
		return errors.New("invalid tool telemetry identity")
	}
	raw, err := json.Marshal(event)
	if err != nil || len(raw) > 2048 {
		return errors.New("tool telemetry event is invalid or oversized")
	}
	line := append(raw, '\n')
	toolTelemetryMu.Lock()
	defer toolTelemetryMu.Unlock()

	root, err := registryRoot(coreRoot)
	if err != nil {
		return errors.New("tool telemetry registry root is unavailable")
	}
	dir := filepath.Join(root, "telemetry")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return errors.New("tool telemetry storage is unavailable")
	}
	path := filepath.Join(dir, "tool_calls.jsonl")
	info, err := os.Lstat(path)
	if err == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return errors.New("tool telemetry path is unsafe")
		}
		if info.Size()+int64(len(line)) > maxToolTelemetryBytes {
			return errors.New("tool telemetry log is full; rotation is required")
		}
	} else if !os.IsNotExist(err) {
		return errors.New("tool telemetry storage is unavailable")
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return errors.New("tool telemetry storage is unavailable")
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !opened.Mode().IsRegular() {
		return errors.New("tool telemetry file is unsafe")
	}
	if err := file.Chmod(0o600); err != nil {
		return errors.New("tool telemetry permissions could not be restricted")
	}
	n, err := file.Write(line)
	if err != nil || n != len(line) {
		return errors.New("tool telemetry event could not be persisted")
	}
	return nil
}

func listToolCallTelemetry(coreRoot string, limit int) ([]ToolCallTelemetry, error) {
	if limit < 1 || limit > 500 {
		limit = 100
	}
	root, err := registryRoot(coreRoot)
	if err != nil {
		return nil, errors.New("tool telemetry registry root is unavailable")
	}
	path := filepath.Join(root, "telemetry", "tool_calls.jsonl")
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return []ToolCallTelemetry{}, nil
	}
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Size() > maxToolTelemetryBytes {
		return nil, errors.New("tool telemetry file is unavailable or unsafe")
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, errors.New("tool telemetry file is unavailable")
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 2048), 4096)
	events := make([]ToolCallTelemetry, 0, limit)
	for scanner.Scan() {
		var event ToolCallTelemetry
		if json.Unmarshal(scanner.Bytes(), &event) != nil {
			continue
		}
		events = append(events, event)
		if len(events) > limit {
			events = events[1:]
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, errors.New("tool telemetry log could not be read")
	}
	return events, nil
}

func normalizeToolErrorClass(err error) string {
	if err == nil {
		return ""
	}
	value := strings.ToLower(err.Error())
	switch {
	case strings.Contains(value, "confirmation"):
		return "confirmation_required"
	case strings.Contains(value, "signature"), strings.Contains(value, "hash"):
		return "artifact_verification_failed"
	case strings.Contains(value, "timeout"):
		return "timeout"
	case strings.Contains(value, "docker"), strings.Contains(value, "sandbox"):
		return "sandbox_failure"
	default:
		return "tool_execution_failed"
	}
}
