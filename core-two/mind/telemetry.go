package mind

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const (
	telemetryLogName       = "http_metrics.jsonl"
	telemetryMaxLineBytes  = 8 * 1024
	telemetryMaxFileBytes  = 16 * 1024 * 1024
	telemetryFileMode      = 0o600
	telemetryDirectoryMode = 0o700
)

var telemetryFileMu sync.Mutex

type telemetryWriter struct {
	http.ResponseWriter
	status int
	bytes  int64
}

func (w *telemetryWriter) WriteHeader(status int) {
	if w.status != 0 {
		return
	}

	// Informational responses may precede the final HTTP status.
	// Record only the final response status, except 101 which is final.
	if status >= 100 && status <= 199 && status != http.StatusSwitchingProtocols {
		w.ResponseWriter.WriteHeader(status)
		return
	}

	w.status = status
	w.ResponseWriter.WriteHeader(status)
}

func (w *telemetryWriter) Write(p []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(http.StatusOK)
	}

	n, err := w.ResponseWriter.Write(p)
	if n > 0 {
		w.bytes += int64(n)
	}

	return n, err
}

func (w *telemetryWriter) Flush() {
	if w.status == 0 {
		w.WriteHeader(http.StatusOK)
	}

	if f, ok := w.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

// Unwrap supports http.ResponseController operations on the underlying writer.
func (w *telemetryWriter) Unwrap() http.ResponseWriter {
	return w.ResponseWriter
}

// WithTelemetry records bounded, low-risk request metadata.
//
// It deliberately does not record request bodies, headers, query parameters,
// client IP addresses, arbitrary unknown URL paths, or panic details.
// Telemetry write failures never change the HTTP response.
func (s *Service) WithTelemetry(next http.Handler) http.Handler {
	if next == nil {
		next = http.NotFoundHandler()
	}

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		capture := &telemetryWriter{
			ResponseWriter: w,
		}

		defer func() {
			recovered := recover()
			panicked := recovered != nil

			status := capture.status
			if status == 0 {
				if panicked {
					status = http.StatusInternalServerError
				} else {
					status = http.StatusOK
				}
			}

			requestPath := ""
			method := ""

			if r != nil {
				method = safeTelemetryMethod(r.Method)

				if r.URL != nil {
					requestPath = r.URL.Path
				}
			}

			entry := map[string]any{
				"at":           time.Now().UTC(),
				"method":       method,
				"route":        telemetryRoute(requestPath),
				"tool_name":    telemetryToolName(requestPath),
				"status":       status,
				"duration_ms":  float64(time.Since(start).Microseconds()) / 1000,
				"response_bytes": capture.bytes,
				"panicked":     panicked,
			}

			s.writeTelemetry(entry)

			// Preserve normal net/http panic handling. The panic value itself
			// is deliberately not written to the telemetry log.
			if panicked {
				panic(recovered)
			}
		}()

		next.ServeHTTP(capture, r)
	})
}

func (s *Service) writeTelemetry(entry map[string]any) {
	if s == nil || strings.TrimSpace(s.CoreRoot) == "" {
		return
	}

	raw, err := json.Marshal(entry)
	if err != nil || len(raw)+1 > telemetryMaxLineBytes {
		return
	}

	raw = append(raw, '\n')

	// Best-effort telemetry must never become a request failure.
	_ = appendTelemetryLine(s.CoreRoot, raw)
}

func appendTelemetryLine(root string, line []byte) error {
	if strings.TrimSpace(root) == "" ||
		len(line) == 0 ||
		len(line) > telemetryMaxLineBytes {
		return os.ErrInvalid
	}

	telemetryFileMu.Lock()
	defer telemetryFileMu.Unlock()

	root = filepath.Clean(root)

	// Require an existing, ordinary repository root. Do not accidentally
	// create a new repository when CoreRoot is empty or misconfigured.
	rootInfo, err := os.Lstat(root)
	if err != nil {
		return err
	}
	if rootInfo.Mode()&os.ModeSymlink != 0 || !rootInfo.IsDir() {
		return os.ErrInvalid
	}

	stateDir := filepath.Join(root, "state")

	if err := os.MkdirAll(stateDir, telemetryDirectoryMode); err != nil {
		return err
	}

	stateInfo, err := os.Lstat(stateDir)
	if err != nil {
		return err
	}
	if stateInfo.Mode()&os.ModeSymlink != 0 || !stateInfo.IsDir() {
		return os.ErrInvalid
	}

	if err := os.Chmod(stateDir, telemetryDirectoryMode); err != nil {
		return err
	}

	path := filepath.Join(stateDir, telemetryLogName)

	info, err := os.Lstat(path)
	switch {
	case err == nil:
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return os.ErrInvalid
		}

		if info.Size()+int64(len(line)) > telemetryMaxFileBytes {
			if err := rotateTelemetryFile(path); err != nil {
				return err
			}
		}

	case os.IsNotExist(err):
		// The file will be created below with restrictive permissions.

	default:
		return err
	}

	file, err := os.OpenFile(
		path,
		os.O_CREATE|os.O_APPEND|os.O_WRONLY,
		telemetryFileMode,
	)
	if err != nil {
		return err
	}
	defer file.Close()

	// Confirm that the opened descriptor and the current path refer to the
	// same regular file. This also rejects a symlink substituted at open time.
	openedInfo, err := file.Stat()
	if err != nil {
		return err
	}
	if !openedInfo.Mode().IsRegular() {
		return os.ErrInvalid
	}

	pathInfo, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if pathInfo.Mode()&os.ModeSymlink != 0 ||
		!pathInfo.Mode().IsRegular() ||
		!os.SameFile(openedInfo, pathInfo) {
		return os.ErrInvalid
	}

	if err := file.Chmod(telemetryFileMode); err != nil {
		return err
	}

	n, err := file.Write(line)
	if err != nil {
		return err
	}
	if n != len(line) {
		return os.ErrInvalid
	}

	return nil
}

// rotateTelemetryFile retains one previous log file. Callers must hold
// telemetryFileMu while using this function.
func rotateTelemetryFile(path string) error {
	backup := path + ".1"

	backupInfo, err := os.Lstat(backup)
	switch {
	case err == nil:
		if backupInfo.Mode()&os.ModeSymlink != 0 ||
			!backupInfo.Mode().IsRegular() {
			return os.ErrInvalid
		}

		if err := os.Remove(backup); err != nil {
			return err
		}

	case os.IsNotExist(err):
		// No previous backup exists.

	default:
		return err
	}

	return os.Rename(path, backup)
}

func safeTelemetryMethod(method string) string {
	switch method {
	case http.MethodGet,
		http.MethodHead,
		http.MethodPost,
		http.MethodPut,
		http.MethodPatch,
		http.MethodDelete,
		http.MethodOptions,
		http.MethodTrace,
		http.MethodConnect:
		return method
	default:
		return "OTHER"
	}
}

func telemetryToolName(path string) string {
	parts := telemetryPathParts(path)
	if len(parts) < 4 {
		return ""
	}

	if parts[0] != "v1" {
		return ""
	}

	switch {
	case parts[1] == "mind" && parts[2] == "tools":
		return safeTelemetryName(parts[3])

	case parts[1] == "genesis" && parts[2] == "tools":
		return safeTelemetryName(parts[3])

	default:
		return ""
	}
}

func safeTelemetryName(name string) string {
	if name == "" || name == "." || name == ".." || len(name) > 80 {
		return ""
	}

	// Restrict telemetry identifiers to printable ASCII identifier
	// characters, even if validName accepts a broader range.
	for _, r := range name {
		if !((r >= 'a' && r <= 'z') ||
			(r >= 'A' && r <= 'Z') ||
			(r >= '0' && r <= '9') ||
			r == '_' || r == '-' || r == '.') {
			return ""
		}
	}

	if !validName(name) {
		return ""
	}

	return name
}

func telemetryRoute(path string) string {
	parts := telemetryPathParts(path)
	if len(parts) == 0 {
		return "/"
	}

	// Allow only known static routes. Unknown routes are deliberately
	// collapsed so arbitrary IDs, filenames, or secrets in paths are not logged.
	staticRoutes := map[string]bool{
		"health":      true,
		"healthz":     true,
		"ready":       true,
		"readyz":      true,
		"live":        true,
		"metrics":     true,
		"v1/health":   true,
		"v1/ready":    true,
		"v1/mind":     true,
		"v1/genesis":  true,
		"v1/mind/status":    true,
		"v1/genesis/status": true,
	}

	staticPath := strings.Join(parts, "/")
	if staticRoutes[staticPath] {
		return "/" + staticPath
	}

	if len(parts) >= 3 &&
		parts[0] == "v1" &&
		(parts[1] == "mind" || parts[1] == "genesis") &&
		parts[2] == "tools" {
		base := "/v1/" + parts[1] + "/tools/{name}"

		if len(parts) == 4 {
			return base
		}

		if len(parts) == 5 && isSafeTelemetryToolAction(parts[4]) {
			return base + "/" + parts[4]
		}

		return base + "/other"
	}

	if len(parts) >= 4 &&
		parts[0] == "v1" &&
		parts[1] == "zero" &&
		parts[2] == "heal" &&
		parts[3] == "proposals" {
		base := "/v1/zero/heal/proposals"

		if len(parts) == 4 {
			return base
		}

		if len(parts) == 5 {
			return base + "/{proposal_id}"
		}

		if len(parts) == 6 && isSafeTelemetryProposalAction(parts[5]) {
			return base + "/{proposal_id}/" + parts[5]
		}

		return base + "/{proposal_id}/other"
	}

	return "/unmatched"
}

func telemetryPathParts(path string) []string {
	path = strings.Trim(path, "/")
	if path == "" {
		return nil
	}

	return strings.Split(path, "/")
}

func isSafeTelemetryToolAction(action string) bool {
	switch action {
	case "run", "invoke", "status", "schema":
		return true
	default:
		return false
	}
}

func isSafeTelemetryProposalAction(action string) bool {
	switch action {
	case "approve", "reject", "status", "cancel":
		return true
	default:
		return false
	}
}
