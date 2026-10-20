package bridge

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func enrollTestDevice(t *testing.T, registry *DeviceRegistry, name, port string, tier int) (Device, string) {
	t.Helper()
	scopes := []string{"device:read"}
	if tier >= 1 {
		scopes = append(scopes, "device:act")
	}
	device, token, err := registry.Enroll(name, port, scopes, tier, time.Hour)
	if err != nil {
		t.Fatalf("enroll device: %v", err)
	}
	return device, token
}

func TestRevokedDeviceIsBlockedOnNextCallAndTokenHashOnlyIsStored(t *testing.T) {
	root := t.TempDir()
	registry := NewDeviceRegistry(root)
	device, token := enrollTestDevice(t, registry, "ESP32 lab", "/dev/ttyUSB0", 1)

	if _, err := registry.Authorize(device.ID, token, "device:read", 0); err != nil {
		t.Fatalf("active device should authorize: %v", err)
	}
	raw, err := os.ReadFile(filepath.Join(root, "state", "devices.json"))
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), token) || !strings.Contains(string(raw), "token_hash") {
		t.Fatal("device token must not be persisted in plaintext")
	}
	if _, err := registry.Revoke(device.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Authorize(device.ID, token, "device:read", 0); err == nil {
		t.Fatal("revoked device was authorized on the next call")
	}
}

func TestExpiredDeviceTokenIsRejected(t *testing.T) {
	root := t.TempDir()
	registry := NewDeviceRegistry(root)
	device, token := enrollTestDevice(t, registry, "ESP32 expired", "/dev/ttyUSB1", 0)

	registry.mu.Lock()
	state, err := registry.loadLocked()
	if err != nil {
		registry.mu.Unlock()
		t.Fatal(err)
	}
	state.Devices[0].ExpiresAt = time.Now().UTC().Add(-time.Minute)
	err = registry.saveLocked(state)
	registry.mu.Unlock()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Authorize(device.ID, token, "device:read", 0); err == nil {
		t.Fatal("expired device token was authorized")
	}
}

func TestGlobalKillSwitchRevokesTierOneAndTwoButKeepsTierZero(t *testing.T) {
	registry := NewDeviceRegistry(t.TempDir())
	tier0, token0 := enrollTestDevice(t, registry, "ESP32 read-only", "/dev/ttyUSB0", 0)
	tier1, token1 := enrollTestDevice(t, registry, "ESP32 tier one", "/dev/ttyUSB1", 1)
	tier2, token2 := enrollTestDevice(t, registry, "ESP32 tier two", "/dev/ttyUSB2", 2)

	if err := registry.SetKillSwitch(true); err != nil {
		t.Fatal(err)
	}
	active, err := registry.KillSwitchActive()
	if err != nil || !active {
		t.Fatalf("kill switch should be active: active=%v err=%v", active, err)
	}
	if _, err := registry.Authorize(tier0.ID, token0, "device:read", 0); err != nil {
		t.Fatalf("Tier 0 read-only device should remain available: %v", err)
	}
	if _, err := registry.Authorize(tier1.ID, token1, "device:act", 1); err == nil {
		t.Fatal("Tier 1 device remained authorized after kill switch")
	}
	if _, err := registry.Authorize(tier2.ID, token2, "device:act", 1); err == nil {
		t.Fatal("Tier 2 device remained authorized after kill switch")
	}
}

func TestTierTwoActuatorRequiresPerActionConfirmation(t *testing.T) {
	device := Device{Tier: 2, Scopes: []string{"device:read", "device:act"}}
	action := DeviceAction{Name: "set_gpio", Pin: 23, Value: 1}
	if err := validateDeviceAction(device, action); err == nil {
		t.Fatal("Tier 2 action must require explicit confirmation")
	}
	action.Confirmation = deviceConfirmation
	if err := validateDeviceAction(device, action); err != nil {
		t.Fatalf("confirmed Tier 2 action should pass the confirmation gate: %v", err)
	}
}
