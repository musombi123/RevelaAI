package api

import (
	"net/http"
	"testing"
	"time"

	"usect-zero.local/core-zero/bridge"
)

func TestDeviceEnrollmentAndImmediateRevocation(t *testing.T) {
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", testAdminToken)
	_, h := newTestServer(t)

	body := `{"name":"ESP32 test board","serial_port":"/dev/ttyUSB0","scopes":["device:read","device:act"],"tier":1,"ttl_hours":24,"confirmation":"ENROLL_DEVICE"}`
	code, response := call(t, h, http.MethodPost, "/v1/devices/enroll", body, map[string]string{
		"X-Admin-Token": testAdminToken,
		"Content-Type": "application/json",
	})
	if code != http.StatusCreated {
		t.Fatalf("device enrollment failed: status=%d body=%v", code, response)
	}
	device, ok := response["device"].(map[string]any)
	if !ok {
		t.Fatalf("enrollment response missing device metadata: %v", response)
	}
	id, _ := device["id"].(string)
	token, _ := response["device_token"].(string)
	if id == "" || token == "" || response["shown_once"] != true {
		t.Fatalf("enrollment response missing one-time token metadata: %v", response)
	}
	if _, err := h.Devices.Authorize(id, token, "device:read", 0); err != nil {
		t.Fatalf("new device should be authorized: %v", err)
	}

	code, response = call(t, h, http.MethodPost, "/v1/devices/"+id+"/revoke", `{"confirmation":"REVOKE_DEVICE"}`, map[string]string{
		"X-Admin-Token": testAdminToken,
		"Content-Type": "application/json",
	})
	if code != http.StatusOK {
		t.Fatalf("device revoke failed: status=%d body=%v", code, response)
	}
	if _, err := h.Devices.Authorize(id, token, "device:read", 0); err == nil {
		t.Fatal("revoked device token must fail on the next authorization call")
	}
}

func TestGlobalKillSwitchEndpointRevokesTierOneAndTwo(t *testing.T) {
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", testAdminToken)
	_, h := newTestServer(t)
	tier1, token1 := enrollTestAPIRegistryDevice(t, h, "ESP32 tier one", "/dev/ttyUSB1", 1)
	tier2, token2 := enrollTestAPIRegistryDevice(t, h, "ESP32 tier two", "/dev/ttyUSB2", 2)

	code, response := call(t, h, http.MethodPost, "/v1/supervisor/kill-switch", `{"enabled":true,"confirmation":"ACTIVATE_GLOBAL_KILL_SWITCH"}`, map[string]string{
		"X-Admin-Token": testAdminToken,
		"Content-Type": "application/json",
	})
	if code != http.StatusOK || response["kill_switch_active"] != true {
		t.Fatalf("kill switch did not activate: status=%d body=%v", code, response)
	}
	if _, err := h.Devices.Authorize(tier1.ID, token1, "device:act", 1); err == nil {
		t.Fatal("Tier 1 device should be revoked by kill switch")
	}
	if _, err := h.Devices.Authorize(tier2.ID, token2, "device:act", 1); err == nil {
		t.Fatal("Tier 2 device should be revoked by kill switch")
	}
}

func enrollTestAPIRegistryDevice(t *testing.T, h *Server, name, port string, tier int) (bridge.Device, string) {
	t.Helper()
	scopes := []string{"device:read"}
	if tier >= 1 {
		scopes = append(scopes, "device:act")
	}
	device, token, err := h.Devices.Enroll(name, port, scopes, tier, 24*time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	return device, token
}
