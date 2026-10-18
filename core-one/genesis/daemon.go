package genesis

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

func (e *Engine) Enqueue(demand, source string) (Demand, error) {
	demand = strings.TrimSpace(demand)
	if demand == "" || len(demand) > 3999 {
		return Demand{}, errors.New("demand must contain 1 to 3999 characters")
	}
	decision := e.Guardian.Check(demand)
	if !decision.Allowed {
		_ = e.Guardian.LogBlocked("queued_demand", demand, decision.Reason)
		return Demand{}, ErrBlocked
	}
	item := Demand{ID: newID("demand"), Demand: demand, Source: limitText(source, 100), CreatedAt: time.Now().UTC(), Status: "queued"}
	return item, writeJSON(filepath.Join(e.CoreRoot, "state", "queue", "pending", item.ID+".json"), item)
}

// RunDaemon scans once on startup, then at the configured interval. HTTP queue submissions
// become eligible on the next scan; POST /invent remains the synchronous on-demand route.
func (e *Engine) RunDaemon(ctx context.Context, interval time.Duration) {
	if interval <= 0 {
		interval = 60 * time.Second
	}
	_ = e.EyeScan(ctx)
	_ = e.ProcessQueue(ctx)
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			_ = e.EyeScan(ctx)
			_ = e.ProcessQueue(ctx)
		}
	}
}

func (e *Engine) ProcessQueue(ctx context.Context) error {
	queueRoot := filepath.Join(e.CoreRoot, "state", "queue")
	pendingDir := filepath.Join(queueRoot, "pending")
	if err := os.MkdirAll(pendingDir, 0o700); err != nil {
		return err
	}
	entries, err := os.ReadDir(pendingDir)
	if err != nil {
		return err
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].Name() < entries[j].Name() })
	var firstErr error
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		path := filepath.Join(pendingDir, entry.Name())
		raw, err := os.ReadFile(path)
		if err != nil {
			if firstErr == nil {
				firstErr = err
			}
			continue
		}
		var item Demand
		if err := json.Unmarshal(raw, &item); err != nil {
			_ = moveQueueFile(path, filepath.Join(queueRoot, "failed", entry.Name()))
			if firstErr == nil {
				firstErr = err
			}
			continue
		}
		item.Status = "processing"
		_ = writeJSON(path, item)
		inv, err := e.Invent(ctx, item.Demand)
		if err != nil {
			if errors.Is(err, ErrBlocked) {
				item.Status = "blocked"
				itemError := "Guardian blocked demand."
				_ = itemError
			} else {
				item.Status = "failed"
				if firstErr == nil {
					firstErr = err
				}
			}
		} else {
			item.Status = "await_merge"
			item.Source = inv.Name
		}
		itemPath := filepath.Join(queueRoot, item.Status, entry.Name())
		_ = writeJSON(itemPath, item)
		_ = os.Remove(path)
		e.publish(Event{Type: "queue_processed", At: time.Now().UTC(), Message: "Daemon processed one queued demand.", Invention: item.Source, Status: item.Status})
	}
	return firstErr
}

func moveQueueFile(src, dest string) error {
	raw, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	if err := atomicWrite(dest, raw, 0o600); err != nil {
		return err
	}
	return os.Remove(src)
}
