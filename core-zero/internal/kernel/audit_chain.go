package kernel

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
)

const maxAuditLogBytes int64 = 64 << 20

// AuditVerification distinguishes a valid new hash chain from an older audit
// prefix written before hash chaining existed. Legacy records are never
// described as fully verified.
type AuditVerification struct {
	Status        string `json:"status"`
	Verified      bool   `json:"verified"`
	ChainValid    bool   `json:"chain_valid"`
	Entries       int    `json:"entries"`
	LegacyEntries int    `json:"legacy_entries"`
	HeadHash      string `json:"head_hash,omitempty"`
	Error         string `json:"error,omitempty"`
}

func auditEventHash(event AuditEvent) string {
	event.Hash = ""
	raw, _ := json.Marshal(event)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func verifyAuditBytes(data []byte) AuditVerification {
	result := AuditVerification{Status: "verified", Verified: true, ChainValid: true}
	if len(data) > 0 && data[len(data)-1] != '\n' {
		result.ChainValid = false
		result.Verified = false
		result.Status = "invalid"
		result.Error = "audit log ends with an incomplete record"
		return result
	}
	scanner := bufio.NewScanner(bytes.NewReader(data))
	scanner.Buffer(make([]byte, 64*1024), maxAuditRecordBytes)
	previousHash := ""
	seenChained := false
	lineNumber := 0

	for scanner.Scan() {
		line := bytes.TrimSpace(scanner.Bytes())
		lineNumber++
		if len(line) == 0 {
			continue
		}
		var event AuditEvent
		if err := json.Unmarshal(line, &event); err != nil {
			result.ChainValid = false
			result.Verified = false
			result.Status = "invalid"
			result.Error = fmt.Sprintf("audit record %d is not valid JSON", lineNumber)
			return result
		}
		result.Entries++

		if event.Hash == "" {
			if seenChained {
				result.ChainValid = false
				result.Verified = false
				result.Status = "invalid"
				result.Error = fmt.Sprintf("legacy record appears after chained record at line %d", lineNumber)
				return result
			}
			result.LegacyEntries++
			sum := sha256.Sum256(line)
			previousHash = hex.EncodeToString(sum[:])
			result.HeadHash = previousHash
			continue
		}

		if event.PreviousHash != previousHash {
			result.ChainValid = false
			result.Verified = false
			result.Status = "invalid"
			result.Error = fmt.Sprintf("previous-hash mismatch at audit record %d", lineNumber)
			return result
		}
		expected := auditEventHash(event)
		if event.Hash != expected {
			result.ChainValid = false
			result.Verified = false
			result.Status = "invalid"
			result.Error = fmt.Sprintf("event-hash mismatch at audit record %d", lineNumber)
			return result
		}
		seenChained = true
		previousHash = event.Hash
		result.HeadHash = event.Hash
	}
	if err := scanner.Err(); err != nil {
		result.ChainValid = false
		result.Verified = false
		result.Status = "invalid"
		result.Error = "audit log exceeds the supported record or size limit"
		return result
	}
	if result.LegacyEntries > 0 {
		result.Verified = false
		result.Status = "legacy_prefix_unverified"
		result.Error = "The hash chain is valid, but legacy records written before chaining are not tamper-evident."
	}
	if result.Entries == 0 {
		result.Status = "empty"
	}
	return result
}

// auditChainHeadLocked must be called while Kernel.mu is held. It validates
// existing records before allowing another record to be appended.
func (k *Kernel) auditChainHeadLocked() (string, error) {
	path, err := k.coreFilePath("audit_log/events.jsonl", true)
	if err != nil {
		return "", err
	}
	f, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("open audit log: %w", err)
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return "", fmt.Errorf("inspect audit log: %w", err)
	}
	if !info.Mode().IsRegular() || info.Size() > maxAuditLogBytes {
		return "", errors.New("audit log is not a regular file or exceeds the 64 MiB verification limit")
	}
	data, err := io.ReadAll(io.LimitReader(f, maxAuditLogBytes+1))
	if err != nil {
		return "", fmt.Errorf("read audit log: %w", err)
	}
	if int64(len(data)) > maxAuditLogBytes {
		return "", errors.New("audit log exceeds the 64 MiB verification limit")
	}
	result := verifyAuditBytes(data)
	if !result.ChainValid {
		return "", errors.New(result.Error)
	}
	return result.HeadHash, nil
}

// VerifyAudit verifies the append-only event hash chain without changing it.
func (k *Kernel) VerifyAudit() (AuditVerification, error) {
	if k == nil {
		return AuditVerification{}, errors.New("kernel is not initialized")
	}
	k.mu.Lock()
	defer k.mu.Unlock()

	path, err := k.coreFilePath("audit_log/events.jsonl", true)
	if err != nil {
		return AuditVerification{}, err
	}
	f, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return AuditVerification{Status: "empty", Verified: true, ChainValid: true}, nil
	}
	if err != nil {
		return AuditVerification{}, fmt.Errorf("open audit log: %w", err)
	}
	defer f.Close()

	info, err := f.Stat()
	if err != nil {
		return AuditVerification{}, err
	}
	if !info.Mode().IsRegular() || info.Size() > maxAuditLogBytes {
		return AuditVerification{}, errors.New("audit log is not a regular file or exceeds the verification limit")
	}
	data, err := io.ReadAll(io.LimitReader(f, maxAuditLogBytes+1))
	if err != nil {
		return AuditVerification{}, err
	}
	if int64(len(data)) > maxAuditLogBytes {
		return AuditVerification{}, errors.New("audit log exceeds the verification limit")
	}
	return verifyAuditBytes(data), nil
}
