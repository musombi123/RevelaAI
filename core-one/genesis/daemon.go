package genesis

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"revela-worldwide.local/libs/country"
	"revela-worldwide.local/libs/guardian"
)

const (
	maxQueuedDemandBytes = 3999
	maxQueuedSourceBytes = 100
	maxQueueRecordBytes  = 1 << 20 // 1 MiB
	maxQueueItemsPerCycle = 50

	defaultDaemonInterval = 60 * time.Second
)

// queueStatusRecord preserves the original queue source and records the
// resulting invention separately. Embedding Demand keeps the existing JSON
// demand fields compatible with readers that decode directly into Demand.
type queueStatusRecord struct {
	Demand
	Invention   string    `json:"invention,omitempty"`
	ProcessedAt time.Time `json:"processed_at,omitempty"`
}

// Enqueue adds a demand to the queue using the default Kenya profile.
func (e *Engine) Enqueue(demand, source string) (Demand, error) {
	return e.EnqueueWorldwide(demand, source, "KE", "")
}

// EnqueueWorldwide validates and durably queues a demand with a resolved
// country and language profile. It never creates or executes an invention.
func (e *Engine) EnqueueWorldwide(
	demand string,
	source string,
	countryCode string,
	language string,
) (Demand, error) {
	if e == nil {
		return Demand{}, errors.New("genesis queue: engine is required")
	}

	if strings.TrimSpace(e.CoreRoot) == "" {
		return Demand{}, errors.New("genesis queue: core root is not configured")
	}

	demand = strings.TrimSpace(demand)
	if demand == "" || len(demand) > maxQueuedDemandBytes {
		return Demand{}, fmt.Errorf(
			"demand must contain 1 to %d UTF-8 bytes",
			maxQueuedDemandBytes,
		)
	}

	// Normalize and bound source metadata without cutting through a UTF-8
	// character. The original source is retained after processing.
	source = boundedQueueText(source, maxQueuedSourceBytes)

	profile, err := country.Resolve(countryCode, language)
	if err != nil {
		return Demand{}, fmt.Errorf(
			"genesis queue: resolve country profile: %w",
			err,
		)
	}

	globalDecision := guardian.CheckText(demand)
	if !globalDecision.Allowed {
		_ = e.Guardian.LogBlocked(
			"queued_demand_worldwide",
			demand,
			globalDecision.Reason,
		)

		e.publish(Event{
			Type:    "blocked",
			At:      time.Now().UTC(),
			Message: "Worldwide Guardian blocked a demand before it entered the queue.",
			Status:  globalDecision.Code,
		})

		return Demand{}, ErrBlocked
	}

	decision := e.Guardian.Check(demand)
	if !decision.Allowed {
		if err := e.Guardian.LogBlocked(
			"queued_demand",
			demand,
			decision.Reason,
		); err != nil {
			e.publish(Event{
				Type:    "queue_audit_error",
				At:      time.Now().UTC(),
				Message: "Guardian blocked a demand, but its audit record could not be written.",
				Status:  "audit_failed",
			})

			return Demand{}, fmt.Errorf(
				"guardian blocked demand and audit logging failed: %w",
				err,
			)
		}

		e.publish(Event{
			Type:    "blocked",
			At:      time.Now().UTC(),
			Message: "Guardian blocked a queued demand before it entered the queue.",
			Status:  decision.Code,
		})

		return Demand{}, ErrBlocked
	}

	item := Demand{
		ID:        newID("demand"),
		Demand:    demand,
		Source:    source,
		Country:   profile.Code,
		Language:  profile.Language,
		CreatedAt: time.Now().UTC(),
		Status:    "queued",
	}

	if !validQueueID(item.ID) {
		return Demand{}, errors.New(
			"genesis queue: generated an invalid queue identifier",
		)
	}

	root, err := queueRoot(e.CoreRoot)
	if err != nil {
		return Demand{}, err
	}

	pending := filepath.Join(root, "pending")
	if err := os.MkdirAll(pending, 0o700); err != nil {
		return Demand{}, fmt.Errorf(
			"create pending queue directory: %w",
			err,
		)
	}

	target := filepath.Join(pending, item.ID+".json")

	// A generated identifier must never overwrite an existing queue entry.
	if _, err := os.Lstat(target); err == nil {
		return Demand{}, fmt.Errorf(
			"genesis queue: generated queue identifier already exists",
		)
	} else if !os.IsNotExist(err) {
		return Demand{}, fmt.Errorf(
			"inspect pending queue target: %w",
			err,
		)
	}

	if err := writeJSON(target, item); err != nil {
		return Demand{}, fmt.Errorf("persist queued demand: %w", err)
	}

	e.publish(Event{
		Type:    "demand_queued",
		At:      time.Now().UTC(),
		Message: "A Guardian-screened demand was durably queued for daemon processing.",
		Status:  "queued",
	})

	return item, nil
}

// RunDaemon scans immediately on startup, then runs at the configured interval.
// Every non-cancellation subsystem error generates an event for operators.
func (e *Engine) RunDaemon(ctx context.Context, interval time.Duration) {
	if e == nil {
		return
	}

	if ctx == nil {
		ctx = context.Background()
	}

	if interval <= 0 {
		interval = defaultDaemonInterval
	}

	e.runCycle(ctx)

	if ctx.Err() != nil {
		return
	}

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			e.publish(Event{
				Type:    "daemon_stopped",
				At:      time.Now().UTC(),
				Message: "Genesis daemon stopped after its context was cancelled.",
				Status:  "stopped",
			})
			return

		case <-ticker.C:
			e.runCycle(ctx)
		}
	}
}

func (e *Engine) runCycle(ctx context.Context) {
	if e == nil {
		return
	}

	if ctx == nil {
		ctx = context.Background()
	}

	if err := ctx.Err(); err != nil {
		return
	}

	if err := e.EyeScan(ctx); err != nil &&
		!errors.Is(err, ErrBlocked) &&
		!errors.Is(err, context.Canceled) &&
		!errors.Is(err, context.DeadlineExceeded) {
		e.publish(Event{
			Type:    "eye_scan_error",
			At:      time.Now().UTC(),
			Message: limitText(err.Error(), 240),
			Status:  "retry_next_cycle",
		})
	}

	if ctx.Err() != nil {
		return
	}

	if err := e.ProcessQueue(ctx); err != nil &&
		!errors.Is(err, context.Canceled) &&
		!errors.Is(err, context.DeadlineExceeded) {
		e.publish(Event{
			Type:    "queue_error",
			At:      time.Now().UTC(),
			Message: limitText(err.Error(), 240),
			Status:  "retry_next_cycle",
		})
	}
}

// ProcessQueue atomically claims pending entries before processing. It
// validates queue records again at processing time, recovers interrupted
// claims, and persists terminal status before removing a completed claim.
func (e *Engine) ProcessQueue(ctx context.Context) error {
	if e == nil {
		return errors.New("genesis queue: engine is required")
	}

	if strings.TrimSpace(e.CoreRoot) == "" {
		return errors.New("genesis queue: core root is not configured")
	}

	if ctx == nil {
		ctx = context.Background()
	}

	e.queueMu.Lock()
	defer e.queueMu.Unlock()

	if err := ctx.Err(); err != nil {
		return err
	}

	root, err := queueRoot(e.CoreRoot)
	if err != nil {
		return err
	}

	pending := filepath.Join(root, "pending")
	processing := filepath.Join(root, "processing")
	failed := filepath.Join(root, "failed")
	blocked := filepath.Join(root, "blocked")
	awaitMerge := filepath.Join(root, "await_merge")

	for _, dir := range []string{
		pending,
		processing,
		failed,
		blocked,
		awaitMerge,
	} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return fmt.Errorf("prepare queue directory: %w", err)
		}
	}

	firstErr := e.recoverProcessing(root, pending, processing)

	entries, err := os.ReadDir(pending)
	if err != nil {
		return err
	}

	sort.Slice(entries, func(i, j int) bool {
		return entries[i].Name() < entries[j].Name()
	})

	processedThisCycle := 0

	for _, entry := range entries {
		if processedThisCycle >= maxQueueItemsPerCycle {
			break
		}

		if err := ctx.Err(); err != nil {
			return err
		}

		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}

		if !validQueueFileName(entry.Name()) {
			if moveErr := quarantineQueueEntry(
				pending,
				failed,
				entry.Name(),
				"invalid-name",
			); moveErr != nil && firstErr == nil {
				firstErr = fmt.Errorf(
					"quarantine invalid queue filename: %w",
					moveErr,
				)
			}
			continue
		}

		src := filepath.Join(pending, entry.Name())
		info, statErr := os.Lstat(src)

		if statErr != nil {
			if !os.IsNotExist(statErr) && firstErr == nil {
				firstErr = statErr
			}
			continue
		}

		if !info.Mode().IsRegular() {
			if moveErr := quarantineQueueEntry(
				pending,
				failed,
				entry.Name(),
				"unsafe-entry",
			); moveErr != nil && firstErr == nil {
				firstErr = fmt.Errorf(
					"quarantine non-regular queue entry: %w",
					moveErr,
				)
			}
			continue
		}

		if info.Size() > maxQueueRecordBytes {
			if moveErr := quarantineQueueEntry(
				pending,
				failed,
				entry.Name(),
				"oversized-entry",
			); moveErr != nil {
				if firstErr == nil {
					firstErr = fmt.Errorf(
						"quarantine oversized queue entry: %w",
						moveErr,
					)
				}
			} else if firstErr == nil {
				firstErr = fmt.Errorf("oversized queue entry %s was quarantined", entry.Name())
			}
			continue
		}

		claim := filepath.Join(processing, entry.Name())

		if err := os.Rename(src, claim); err != nil {
			if !os.IsNotExist(err) && firstErr == nil {
				firstErr = fmt.Errorf("claim queued demand: %w", err)
			}
			continue
		}

		processedThisCycle++

		item, readErr := readQueueDemand(claim, entry.Name())
		if readErr != nil {
			if moveErr := quarantineQueueEntry(
				processing,
				failed,
				entry.Name(),
				"invalid-record",
			); moveErr != nil && firstErr == nil {
				firstErr = fmt.Errorf(
					"invalid queue record (%v); quarantine failed: %w",
					readErr,
					moveErr,
				)
			} else if firstErr == nil {
				firstErr = fmt.Errorf(
					"invalid queue record %s: %w",
					entry.Name(),
					readErr,
				)
			}
			continue
		}

		// Revalidate stored fields because queue files may have been edited
		// outside the Enqueue API after they were originally created.
		profile, validationErr := validateQueuedDemand(e, &item)
		if validationErr != nil {
			if errors.Is(validationErr, ErrBlocked) {
				item.Status = "blocked"
				item.Error = "Guardian blocked the demand during queue processing; no invention was generated."

				if err := e.finalizeQueueRecord(
					root,
					claim,
					entry.Name(),
					item,
					"",
				); err != nil && firstErr == nil {
					firstErr = err
				}
				continue
			}

			item.Status = "failed"
			item.Error = limitText(validationErr.Error(), 500)

			if err := e.finalizeQueueRecord(
				root,
				claim,
				entry.Name(),
				item,
				"",
			); err != nil && firstErr == nil {
				firstErr = err
			}

			continue
		}

		// Persist canonical country and language data before beginning work.
		item.Country = profile.Code
		item.Language = profile.Language
		item.Status = "processing"
		item.Error = ""

		if err := writeJSON(claim, item); err != nil {
			if firstErr == nil {
				firstErr = fmt.Errorf(
					"persist processing state: %w",
					err,
				)
			}

			// Leave the claim in processing/. Recovery can safely reclaim it.
			continue
		}

		if err := ctx.Err(); err != nil {
			if requeueErr := requeueInterruptedClaim(
				claim,
				src,
				item,
			); requeueErr != nil && firstErr == nil {
				firstErr = requeueErr
			}
			return err
		}

		invention, inventErr := e.InventWorldwide(
			ctx,
			item.Demand,
			profile.Code,
			profile.Language,
		)

		if errors.Is(inventErr, context.Canceled) ||
			errors.Is(inventErr, context.DeadlineExceeded) {
			if requeueErr := requeueInterruptedClaim(
				claim,
				src,
				item,
			); requeueErr != nil && firstErr == nil {
				firstErr = requeueErr
			}
			return inventErr
		}

		inventionName := ""

		switch {
		case inventErr == nil:
			item.Status = "await_merge"
			inventionName = invention.Name

		case errors.Is(inventErr, ErrAlreadyExists):
			if existingName, sameDemand := e.findExistingInvention(item.Demand); sameDemand {
				item.Status = "await_merge"
				inventionName = existingName
			} else {
				item.Status = "failed"
				item.Error = "An invention with the derived name already exists for a different demand; inspect it manually."
			}

		case errors.Is(inventErr, ErrBlocked):
			item.Status = "blocked"
			item.Error = "Guardian blocked the demand; no new invention was generated."

		default:
			item.Status = "failed"
			item.Error = limitText(inventErr.Error(), 500)

			if firstErr == nil {
				firstErr = fmt.Errorf(
					"process queued demand %s: %w",
					item.ID,
					inventErr,
				)
			}
		}

		if err := e.finalizeQueueRecord(
			root,
			claim,
			entry.Name(),
			item,
			inventionName,
		); err != nil && firstErr == nil {
			firstErr = err
		}
	}

	return firstErr
}

// validateQueuedDemand performs processing-time validation and policy screening.
// The country resolver supplies a canonical profile for both current and
// legacy queue records that omitted a country or language.
func validateQueuedDemand(
	e *Engine,
	item *Demand,
) (country.Profile, error) {
	if e == nil || item == nil {
		return country.Profile{}, errors.New("engine and queued demand are required")
	}

	item.Demand = strings.TrimSpace(item.Demand)

	if item.Demand == "" || len(item.Demand) > maxQueuedDemandBytes {
		return country.Profile{}, errors.New(
			"queued demand must contain 1 to 3999 UTF-8 bytes",
		)
	}

	if len(item.Source) > maxQueuedSourceBytes {
		item.Source = boundedQueueText(item.Source, maxQueuedSourceBytes)
	}

	globalDecision := guardian.CheckText(item.Demand)
	if !globalDecision.Allowed {
		_ = e.Guardian.LogBlocked(
			"queued_demand_worldwide",
			item.Demand,
			globalDecision.Reason,
		)
		return country.Profile{}, ErrBlocked
	}

	decision := e.Guardian.Check(item.Demand)
	if !decision.Allowed {
		if err := e.Guardian.LogBlocked(
			"queued_demand",
			item.Demand,
			decision.Reason,
		); err != nil {
			return country.Profile{}, fmt.Errorf(
				"Guardian blocked queued demand and audit logging failed: %w",
				err,
			)
		}
		return country.Profile{}, ErrBlocked
	}

	code := strings.TrimSpace(item.Country)
	if code == "" {
		code = "KE"
	}

	language := strings.TrimSpace(item.Language)

	profile, err := country.Resolve(code, language)
	if err != nil {
		return country.Profile{}, fmt.Errorf(
			"resolve queued demand country profile: %w",
			err,
		)
	}

	return profile, nil
}

// recoverProcessing recovers interrupted claims. If a final state was
// already persisted before a crash, it removes the completed claim rather
// than processing the same demand a second time.
func (e *Engine) recoverProcessing(
	root string,
	pending string,
	processing string,
) error {
	entries, err := os.ReadDir(processing)
	if err != nil {
		return err
	}

	var firstErr error

	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}

		name := entry.Name()
		if !validQueueFileName(name) {
			if moveErr := quarantineQueueEntry(
				processing,
				filepath.Join(root, "failed"),
				name,
				"invalid-processing-name",
			); moveErr != nil && firstErr == nil {
				firstErr = moveErr
			}
			continue
		}

		src := filepath.Join(processing, name)

		info, err := os.Lstat(src)
		if err != nil {
			if firstErr == nil && !os.IsNotExist(err) {
				firstErr = err
			}
			continue
		}

		if !info.Mode().IsRegular() {
			if moveErr := quarantineQueueEntry(
				processing,
				filepath.Join(root, "failed"),
				name,
				"unsafe-processing-entry",
			); moveErr != nil && firstErr == nil {
				firstErr = moveErr
			}
			continue
		}

		if info.Size() > maxQueueRecordBytes {
			if moveErr := quarantineQueueEntry(
				processing,
				filepath.Join(root, "failed"),
				name,
				"oversized-processing-entry",
			); moveErr != nil && firstErr == nil {
				firstErr = moveErr
			}
			continue
		}

		item, readErr := readQueueDemand(src, name)
		if readErr != nil {
			if moveErr := quarantineQueueEntry(
				processing,
				filepath.Join(root, "failed"),
				name,
				"invalid-processing-record",
			); moveErr != nil && firstErr == nil {
				firstErr = fmt.Errorf(
					"invalid interrupted queue record (%v); quarantine failed: %w",
					readErr,
					moveErr,
				)
			}
			continue
		}

		// A crash can occur after the terminal status file is written but
		// before the claim is removed. Detect that condition before recovery.
		completed, completedErr := hasTerminalQueueRecord(root, name, item.ID)
		if completedErr != nil {
			if firstErr == nil {
				firstErr = completedErr
			}
			continue
		}

		if completed {
			if err := os.Remove(src); err != nil && firstErr == nil {
				firstErr = fmt.Errorf(
					"remove completed queue claim %s: %w",
					name,
					err,
				)
			}
			continue
		}

		dest := filepath.Join(pending, name)

		_, statErr := os.Lstat(dest)
		if statErr == nil {
			// Never overwrite a pending record. Keep the original pending
			// record and quarantine the duplicate processing claim.
			if moveErr := quarantineQueueEntry(
				processing,
				filepath.Join(root, "failed"),
				name,
				"duplicate-processing",
			); moveErr != nil && firstErr == nil {
				firstErr = fmt.Errorf(
					"duplicate pending/processing queue record %s: %w",
					name,
					moveErr,
				)
			}
			continue
		}

		if !os.IsNotExist(statErr) {
			if firstErr == nil {
				firstErr = statErr
			}
			continue
		}

		item.Status = "queued"
		item.Error = "Recovered after an interrupted processing attempt."

		if err := writeJSON(src, item); err != nil {
			if firstErr == nil {
				firstErr = fmt.Errorf(
					"persist recovered queue state: %w",
					err,
				)
			}
			continue
		}

		if err := os.Rename(src, dest); err != nil {
			if firstErr == nil {
				firstErr = fmt.Errorf(
					"return interrupted demand to pending queue: %w",
					err,
				)
			}
		}
	}

	return firstErr
}

// readQueueDemand refuses symlinked/non-regular files, oversized payloads,
// invalid JSON, missing IDs, unsafe IDs, and filename/ID mismatches.
func readQueueDemand(path, filename string) (Demand, error) {
	var item Demand

	info, err := os.Lstat(path)
	if err != nil {
		return item, err
	}

	if !info.Mode().IsRegular() {
		return item, errors.New("queue record must be a regular file")
	}

	if info.Size() > maxQueueRecordBytes {
		return item, errors.New("queue record exceeds the size limit")
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		return item, err
	}

	if err := json.Unmarshal(raw, &item); err != nil {
		return item, fmt.Errorf("decode queue JSON: %w", err)
	}

	if !validQueueID(item.ID) {
		return item, errors.New("queue record has a missing or invalid ID")
	}

	if filename != item.ID+".json" {
		return item, errors.New("queue filename does not match record ID")
	}

	if strings.TrimSpace(item.Demand) == "" {
		return item, errors.New("queue record has no demand")
	}

	if len(item.Demand) > maxQueuedDemandBytes {
		return item, errors.New("queue demand exceeds the configured size limit")
	}

	return item, nil
}

// finalizeQueueRecord writes a durable status record before removing the
// processing claim. The original Source value remains available for provenance.
func (e *Engine) finalizeQueueRecord(
	root string,
	claim string,
	filename string,
	item Demand,
	inventionName string,
) error {
	if !validQueueOutcome(item.Status) {
		return fmt.Errorf(
			"genesis queue: refusing invalid terminal status %q",
			item.Status,
		)
	}

	statusDir := filepath.Join(root, item.Status)

	if err := os.MkdirAll(statusDir, 0o700); err != nil {
		return fmt.Errorf("create queue status directory: %w", err)
	}

	record := queueStatusRecord{
		Demand:      item,
		Invention:   inventionName,
		ProcessedAt: time.Now().UTC(),
	}

	dest := filepath.Join(statusDir, filename)
	if err := writeJSON(dest, record); err != nil {
		return fmt.Errorf(
			"persist final queue status %q: %w",
			item.Status,
			err,
		)
	}

	if err := os.Remove(claim); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove completed queue claim: %w", err)
	}

	// Event metadata includes the invention separately from the source that
	// originally introduced the demand.
	message := "Daemon processed a queued demand. Generated inventions remain subject to human review."

	e.publishQueueOutcome(item, inventionName, message)

	return nil
}

// publishQueueOutcome is separated so queue events retain a consistent
// message and do not replace demand provenance with the generated invention.
func (e *Engine) publishQueueOutcome(
	item Demand,
	inventionName string,
	message string,
) {
	if e == nil {
		return
	}

	e.publish(Event{
		Type:      "queue_processed",
		At:        time.Now().UTC(),
		Message:   message,
		Invention: inventionName,
		Status:    item.Status,
	})
}

func (e *Engine) findExistingInvention(demand string) (string, bool) {
	if e == nil || strings.TrimSpace(e.CoreRoot) == "" {
		return "", false
	}

	name := deriveSpec(demand).Name
	if !validResourceName(name) {
		return "", false
	}

	path := filepath.Join(
		e.CoreRoot,
		"inventions",
		name,
		"evidence.json",
	)

	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() > maxQueueRecordBytes {
		return "", false
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		return "", false
	}

	var envelope struct {
		Specification ToolSpec `json:"specification"`
	}

	if json.Unmarshal(raw, &envelope) != nil {
		return "", false
	}

	if strings.TrimSpace(envelope.Specification.Demand) != strings.TrimSpace(demand) {
		return "", false
	}

	return name, true
}

// moveQueueFile safely moves a regular queue file without following a symlink.
func moveQueueFile(src, dest string) error {
	info, err := os.Lstat(src)
	if err != nil {
		return err
	}

	if !info.Mode().IsRegular() {
		return errors.New("source queue entry is not a regular file")
	}

	if info.Size() > maxQueueRecordBytes {
		return errors.New("source queue entry exceeds the configured size limit")
	}

	if _, err := os.Lstat(dest); err == nil {
		return errors.New("destination queue entry already exists")
	} else if !os.IsNotExist(err) {
		return err
	}

	raw, err := os.ReadFile(src)
	if err != nil {
		return err
	}

	if err := atomicWrite(dest, raw, 0o600); err != nil {
		return err
	}

	return os.Remove(src)
}

// requeueInterruptedClaim restores a cancelled task to pending without
// overwriting an existing item.
func requeueInterruptedClaim(
	claim string,
	pendingTarget string,
	item Demand,
) error {
	item.Status = "queued"
	item.Error = "Processing was interrupted; demand returned to the pending queue."

	if err := writeJSON(claim, item); err != nil {
		return fmt.Errorf("persist interrupted queue state: %w", err)
	}

	if _, err := os.Lstat(pendingTarget); err == nil {
		return fmt.Errorf(
			"cannot requeue interrupted demand because its pending file already exists",
		)
	} else if !os.IsNotExist(err) {
		return fmt.Errorf("inspect pending retry target: %w", err)
	}

	if err := os.Rename(claim, pendingTarget); err != nil {
		return fmt.Errorf("requeue interrupted demand: %w", err)
	}

	return nil
}

// hasTerminalQueueRecord detects a completed queue result after a crash
// between status persistence and claim removal.
func hasTerminalQueueRecord(
	root string,
	filename string,
	expectedID string,
) (bool, error) {
	for _, status := range []string{"await_merge", "blocked", "failed"} {
		path := filepath.Join(root, status, filename)

		info, err := os.Lstat(path)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return false, fmt.Errorf(
				"inspect terminal queue record: %w",
				err,
			)
		}

		if !info.Mode().IsRegular() {
			return false, errors.New(
				"terminal queue record is not a regular file",
			)
		}

		if info.Size() > maxQueueRecordBytes {
			return false, errors.New(
				"terminal queue record exceeds the size limit",
			)
		}

		raw, err := os.ReadFile(path)
		if err != nil {
			return false, err
		}

		var item Demand
		if err := json.Unmarshal(raw, &item); err != nil {
			return false, fmt.Errorf(
				"decode terminal queue record: %w",
				err,
			)
		}

		if item.ID == expectedID {
			return true, nil
		}
	}

	return false, nil
}

func quarantineQueueEntry(
	sourceDir string,
	failedDir string,
	filename string,
	reason string,
) error {
	if err := os.MkdirAll(failedDir, 0o700); err != nil {
		return err
	}

	src := filepath.Join(sourceDir, filename)
	destName := filename + "." + reason + "." + newID("quarantine")
	dest := filepath.Join(failedDir, destName)

	return os.Rename(src, dest)
}

func queueRoot(coreRoot string) (string, error) {
	if strings.TrimSpace(coreRoot) == "" {
		return "", errors.New("genesis queue: core root is required")
	}

	absRoot, err := filepath.Abs(coreRoot)
	if err != nil {
		return "", fmt.Errorf("resolve core root: %w", err)
	}

	return filepath.Join(absRoot, "state", "queue"), nil
}

func validQueueID(id string) bool {
	if len(id) < len("demand-a") || len(id) > 100 {
		return false
	}

	if !strings.HasPrefix(id, "demand-") {
		return false
	}

	for _, r := range id {
		if (r >= 'a' && r <= 'z') ||
			(r >= 'A' && r <= 'Z') ||
			(r >= '0' && r <= '9') ||
			r == '-' ||
			r == '_' {
			continue
		}

		return false
	}

	return true
}

func validQueueFileName(name string) bool {
	if !strings.HasSuffix(name, ".json") {
		return false
	}

	id := strings.TrimSuffix(name, ".json")
	return validQueueID(id) && filepath.Base(name) == name
}

func validQueueOutcome(status string) bool {
	switch status {
	case "await_merge", "blocked", "failed":
		return true
	default:
		return false
	}
}

func boundedQueueText(value string, maxBytes int) string {
	value = strings.TrimSpace(strings.Join(strings.Fields(value), " "))
	if maxBytes <= 0 {
		return ""
	}

	var out strings.Builder
	out.Grow(min(len(value), maxBytes))

	for _, r := range value {
		character := string(r)
		if out.Len()+len(character) > maxBytes {
			break
		}
		out.WriteString(character)
	}

	return out.String()
}
