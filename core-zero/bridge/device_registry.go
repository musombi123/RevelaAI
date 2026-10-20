package bridge

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode"
)

const (
	maxDeviceStoreBytes = 2 << 20
	maxDeviceRecords = 1000
)

var (
	devicePortPattern = regexp.MustCompile(`^/dev/tty(USB|ACM)[0-9]+$`)
	deviceScopes = map[string]int{
		"device:read": 0,
		"device:act": 1,
	}
)

type Device struct {
	ID         string     `json:"id"`
	Name       string     `json:"name"`
	SerialPort string     `json:"serial_port"`
	Tier       int        `json:"tier"`
	Scopes     []string   `json:"scopes"`
	Status     string     `json:"status"`
	CreatedAt  time.Time  `json:"created_at"`
	ExpiresAt  time.Time  `json:"expires_at"`
	RevokedAt  *time.Time `json:"revoked_at,omitempty"`
}

type deviceRecord struct {
	Device
	TokenHash string `json:"token_hash"`
}

type deviceStore struct {
	KillSwitch bool           `json:"kill_switch"`
	Devices    []deviceRecord `json:"devices"`
}

type DeviceRegistry struct {
	root string
	mu   sync.Mutex
}

func NewDeviceRegistry(root string) *DeviceRegistry {
	return &DeviceRegistry{root: strings.TrimSpace(root)}
}

func (r *DeviceRegistry) storePath(create bool) (string, error) {
	if r == nil || r.root == "" {
		return "", errors.New("device registry is not configured")
	}
	root, err := filepath.Abs(r.root)
	if err != nil {
		return "", err
	}
	info, err := os.Lstat(root)
	if err != nil {
		return "", fmt.Errorf("inspect device registry root: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return "", errors.New("device registry root must be a physical directory")
	}
	stateDir := filepath.Join(root, "state")
	info, err = os.Lstat(stateDir)
	if errors.Is(err, os.ErrNotExist) && create {
		if err := os.Mkdir(stateDir, 0700); err != nil && !errors.Is(err, os.ErrExist) {
			return "", err
		}
		info, err = os.Lstat(stateDir)
	}
	if err != nil {
		return "", err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return "", errors.New("device state directory is unsafe")
	}
	path := filepath.Join(stateDir, "devices.json")
	info, err = os.Lstat(path)
	if err == nil && (info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular()) {
		return "", errors.New("device registry file is unsafe")
	}
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return "", err
	}
	return path, nil
}

func (r *DeviceRegistry) loadLocked() (deviceStore, error) {
	path, err := r.storePath(true)
	if err != nil {
		return deviceStore{}, err
	}
	f, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return deviceStore{Devices: []deviceRecord{}}, nil
	}
	if err != nil {
		return deviceStore{}, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return deviceStore{}, err
	}
	if !info.Mode().IsRegular() || info.Size() > maxDeviceStoreBytes {
		return deviceStore{}, errors.New("device registry exceeds its size limit or is not a regular file")
	}
	raw, err := io.ReadAll(io.LimitReader(f, maxDeviceStoreBytes+1))
	if err != nil {
		return deviceStore{}, err
	}
	if len(raw) > maxDeviceStoreBytes {
		return deviceStore{}, errors.New("device registry exceeds its size limit")
	}
	var state deviceStore
	if err := json.Unmarshal(raw, &state); err != nil {
		return deviceStore{}, errors.New("device registry is invalid JSON")
	}
	if len(state.Devices) > maxDeviceRecords {
		return deviceStore{}, errors.New("device registry exceeds the record limit")
	}
	return state, nil
}

func (r *DeviceRegistry) saveLocked(state deviceStore) error {
	path, err := r.storePath(true)
	if err != nil {
		return err
	}
	raw, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	if len(raw) > maxDeviceStoreBytes {
		return errors.New("device registry exceeds its size limit")
	}
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".devices-*.tmp")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)
	if err := tmp.Chmod(0600); err != nil {
		_ = tmp.Close()
		return err
	}
	if _, err := tmp.Write(raw); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmpPath, path); err != nil {
		return err
	}
	return nil
}

func publicDevice(record deviceRecord) Device {
	record.TokenHash = ""
	record.Scopes = append([]string(nil), record.Scopes...)
	return record.Device
}

func validDeviceName(name string) bool {
	name = strings.TrimSpace(name)
	if len(name) < 2 || len(name) > 120 {
		return false
	}
	for _, ch := range name {
		if unicode.IsControl(ch) {
			return false
		}
	}
	return true
}

func validDeviceScopes(scopes []string, tier int) ([]string, error) {
	if tier < 0 || tier > 2 || len(scopes) == 0 || len(scopes) > len(deviceScopes) {
		return nil, errors.New("tier must be 0, 1, or 2 and at least one supported scope is required")
	}
	seen := make(map[string]bool)
	result := make([]string, 0, len(scopes))
	for _, scope := range scopes {
		minTier, ok := deviceScopes[scope]
		if !ok || seen[scope] || minTier > tier {
			return nil, fmt.Errorf("scope %q is not permitted for device tier %d", scope, tier)
		}
		seen[scope] = true
		result = append(result, scope)
	}
	if !seen["device:read"] {
		return nil, errors.New("every enrolled device must include device:read scope")
	}
	sort.Strings(result)
	return result, nil
}

// Enroll registers one explicitly named USB serial port. It never enumerates
// or probes local devices. The returned token is shown once; only its hash is stored.
func (r *DeviceRegistry) Enroll(name, serialPort string, scopes []string, tier int, ttl time.Duration) (Device, string, error) {
	name = strings.TrimSpace(name)
	serialPort = strings.TrimSpace(serialPort)
	if !validDeviceName(name) {
		return Device{}, "", errors.New("device name must be 2-120 bytes without control characters")
	}
	if !devicePortPattern.MatchString(serialPort) || filepath.Clean(serialPort) != serialPort {
		return Device{}, "", errors.New("serial_port must be an explicit /dev/ttyUSBn or /dev/ttyACMn path")
	}
	if ttl <= 0 || ttl > 90*24*time.Hour {
		return Device{}, "", errors.New("device token TTL must be positive and no more than 90 days")
	}
	cleanScopes, err := validDeviceScopes(scopes, tier)
	if err != nil {
		return Device{}, "", err
	}
	idBytes := make([]byte, 12)
	tokenBytes := make([]byte, 32)
	if _, err := rand.Read(idBytes); err != nil {
		return Device{}, "", err
	}
	if _, err := rand.Read(tokenBytes); err != nil {
		return Device{}, "", err
	}
	id := hex.EncodeToString(idBytes)
	token := "uzd_" + base64.RawURLEncoding.EncodeToString(tokenBytes)
	tokenDigest := sha256.Sum256([]byte(token))
	now := time.Now().UTC()
	record := deviceRecord{
		Device: Device{
			ID: id, Name: name, SerialPort: serialPort, Tier: tier,
			Scopes: cleanScopes, Status: "active", CreatedAt: now, ExpiresAt: now.Add(ttl),
		},
		TokenHash: hex.EncodeToString(tokenDigest[:]),
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	state, err := r.loadLocked()
	if err != nil {
		return Device{}, "", err
	}
	if state.KillSwitch && tier >= 1 {
		return Device{}, "", errors.New("global kill switch is active; Tier 1-2 enrollment is blocked")
	}
	if len(state.Devices) >= maxDeviceRecords {
		return Device{}, "", errors.New("device registry is full")
	}
	for _, existing := range state.Devices {
		if existing.SerialPort == serialPort && existing.Status == "active" {
			return Device{}, "", errors.New("serial port is already assigned to an active enrolled device")
		}
	}
	state.Devices = append(state.Devices, record)
	if err := r.saveLocked(state); err != nil {
		return Device{}, "", err
	}
	return publicDevice(record), token, nil
}

func (r *DeviceRegistry) List() ([]Device, error) {
	if r == nil {
		return nil, errors.New("device registry is not configured")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	state, err := r.loadLocked()
	if err != nil {
		return nil, err
	}
	result := make([]Device, 0, len(state.Devices))
	for _, record := range state.Devices {
		result = append(result, publicDevice(record))
	}
	sort.Slice(result, func(i, j int) bool { return result[i].ID < result[j].ID })
	return result, nil
}

func (r *DeviceRegistry) Revoke(id string) (Device, error) {
	if r == nil {
		return Device{}, errors.New("device registry is not configured")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	state, err := r.loadLocked()
	if err != nil {
		return Device{}, err
	}
	for i := range state.Devices {
		if state.Devices[i].ID != id {
			continue
		}
		if state.Devices[i].Status != "revoked" {
			now := time.Now().UTC()
			state.Devices[i].Status = "revoked"
			state.Devices[i].RevokedAt = &now
		}
		if err := r.saveLocked(state); err != nil {
			return Device{}, err
		}
		return publicDevice(state.Devices[i]), nil
	}
	return Device{}, errors.New("enrolled device not found")
}

func (r *DeviceRegistry) SetKillSwitch(enabled bool) error {
	if r == nil {
		return errors.New("device registry is not configured")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	state, err := r.loadLocked()
	if err != nil {
		return err
	}
	state.KillSwitch = enabled
	if enabled {
		now := time.Now().UTC()
		for i := range state.Devices {
			if state.Devices[i].Tier >= 1 && state.Devices[i].Status == "active" {
				state.Devices[i].Status = "revoked"
				state.Devices[i].RevokedAt = &now
			}
		}
	}
	return r.saveLocked(state)
}

func (r *DeviceRegistry) KillSwitchActive() (bool, error) {
	if r == nil {
		return false, errors.New("device registry is not configured")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	state, err := r.loadLocked()
	return state.KillSwitch, err
}

// Authorize revalidates token hash, expiry, revocation, tier, and scope on each
// adapter operation. Tier 1-2 access fails closed while the global kill switch is on.
func (r *DeviceRegistry) Authorize(id, token, scope string, minimumTier int) (Device, error) {
	if r == nil || token == "" || len(token) > 256 {
		return Device{}, errors.New("device authorization failed")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	state, err := r.loadLocked()
	if err != nil {
		return Device{}, err
	}
	tokenDigest := sha256.Sum256([]byte(token))
	for _, record := range state.Devices {
		if record.ID != id {
			continue
		}
		if record.Status != "active" || !record.ExpiresAt.After(time.Now().UTC()) {
			return Device{}, errors.New("device token is revoked or expired")
		}
		if state.KillSwitch && record.Tier >= 1 {
			return Device{}, errors.New("global kill switch blocks Tier 1-2 device access")
		}
		if record.Tier < minimumTier || !containsScope(record.Scopes, scope) {
			return Device{}, errors.New("device token lacks the required scope or tier")
		}
		expected, err := hex.DecodeString(record.TokenHash)
		if err != nil || len(expected) != sha256.Size {
			return Device{}, errors.New("stored device token hash is invalid")
		}
		if subtle.ConstantTimeCompare(expected, tokenDigest[:]) != 1 {
			return Device{}, errors.New("device authorization failed")
		}
		return publicDevice(record), nil
	}
	return Device{}, errors.New("enrolled device not found")
}

func containsScope(scopes []string, wanted string) bool {
	for _, scope := range scopes {
		if scope == wanted {
			return true
		}
	}
	return false
}
