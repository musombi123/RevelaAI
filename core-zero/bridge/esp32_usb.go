package bridge

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"sync"
	"time"
)

const (
	deviceConfirmation = "CONFIRM_DEVICE_ACTION"
	maxDeviceFrameBytes = 4096
)

type DeviceAction struct {
	Name         string `json:"name"`
	Pin          int    `json:"pin"`
	Value        int    `json:"value"`
	Confirmation string `json:"confirmation,omitempty"`
}

// DeviceAdapter is the only runtime boundary for enrolled devices. Each method
// receives the device token again so authorization is rechecked per operation.
type DeviceAdapter interface {
	Connect(deviceID, token string) error
	Read(deviceID, token string) ([]byte, error)
	Act(deviceID, token string, action DeviceAction) error
	Disconnect(deviceID, token string) error
}

// ESP32USBAdapter speaks a bounded newline-delimited JSON protocol over one
// owner-enrolled Linux USB serial port. Firmware must implement {"op":"status"}
// and {"op":"gpio","pin":N,"value":0|1}; this is not a generic ESP32 firmware
// flasher and never discovers ports.
type ESP32USBAdapter struct {
	registry *DeviceRegistry
	mu       sync.Mutex
	device   Device
	port     *os.File
	reader   *bufio.Reader
}

func NewESP32USBAdapter(registry *DeviceRegistry) *ESP32USBAdapter {
	return &ESP32USBAdapter{registry: registry}
}

func (a *ESP32USBAdapter) Connect(deviceID, token string) error {
	if a == nil || a.registry == nil {
		return errors.New("device adapter is not configured")
	}
	device, err := a.registry.Authorize(deviceID, token, "device:read", 0)
	if err != nil {
		return err
	}
	if runtime.GOOS != "linux" {
		return errors.New("ESP32 USB serial access is supported only by the local Linux adapter host")
	}
	if !devicePortPattern.MatchString(device.SerialPort) {
		return errors.New("stored device serial path is not an allowed enrolled USB serial port")
	}
	info, err := os.Lstat(device.SerialPort)
	if err != nil {
		return fmt.Errorf("inspect enrolled serial port: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeCharDevice == 0 {
		return errors.New("enrolled serial port is not a physical device node")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	// Fixed executable and arguments; the enrolled port is validated and no
	// shell is involved. No port enumeration or probing occurs.
	cmd := exec.CommandContext(ctx, "/bin/stty", "-F", device.SerialPort, "115200", "raw", "-echo", "min", "0", "time", "10")
	if output, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("configure enrolled serial port: %w (%s)", err, strings.TrimSpace(string(output)))
	}
	port, err := os.OpenFile(device.SerialPort, os.O_RDWR, 0)
	if err != nil {
		return fmt.Errorf("open enrolled serial port: %w", err)
	}

	a.mu.Lock()
	defer a.mu.Unlock()
	if a.port != nil {
		_ = port.Close()
		return errors.New("device adapter is already connected")
	}
	a.device = device
	a.port = port
	a.reader = bufio.NewReaderSize(port, maxDeviceFrameBytes)
	return nil
}

func (a *ESP32USBAdapter) Read(deviceID, token string) ([]byte, error) {
	if a == nil || a.registry == nil {
		return nil, errors.New("device adapter is not configured")
	}
	if _, err := a.registry.Authorize(deviceID, token, "device:read", 0); err != nil {
		return nil, err
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.port == nil || a.device.ID != deviceID {
		return nil, errors.New("device is not connected")
	}
	if err := writeDeviceFrame(a.port, map[string]any{"op": "status"}); err != nil {
		return nil, err
	}
	return readDeviceFrame(a.reader)
}

func (a *ESP32USBAdapter) Act(deviceID, token string, action DeviceAction) error {
	if a == nil || a.registry == nil {
		return errors.New("device adapter is not configured")
	}
	device, err := a.registry.Authorize(deviceID, token, "device:act", 1)
	if err != nil {
		return err
	}
	if err := validateDeviceAction(device, action); err != nil {
		return err
	}

	a.mu.Lock()
	defer a.mu.Unlock()
	if a.port == nil || a.device.ID != deviceID {
		return errors.New("device is not connected")
	}
	// Revalidate immediately before the state-changing serial write.
	current, err := a.registry.Authorize(deviceID, token, "device:act", 1)
	if err != nil {
		return err
	}
	if err := validateDeviceAction(current, action); err != nil {
		return err
	}
	if err := writeDeviceFrame(a.port, map[string]any{
		"op": "gpio", "pin": action.Pin, "value": action.Value,
	}); err != nil {
		return err
	}
	response, err := readDeviceFrame(a.reader)
	if err != nil {
		return err
	}
	var ack struct {
		Status string `json:"status"`
	}
	if err := json.Unmarshal(response, &ack); err != nil || ack.Status != "ok" {
		return errors.New("ESP32 did not acknowledge the requested action")
	}
	return nil
}

func (a *ESP32USBAdapter) Disconnect(deviceID, token string) error {
	if a == nil {
		return nil
	}
	var authErr error
	if a.registry == nil {
		authErr = errors.New("device adapter is not configured")
	} else if _, err := a.registry.Authorize(deviceID, token, "device:read", 0); err != nil {
		authErr = err
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.port != nil {
		closeErr := a.port.Close()
		a.port = nil
		a.reader = nil
		a.device = Device{}
		if closeErr != nil {
			return closeErr
		}
	}
	// Closing is always performed even if authorization was revoked, so
	// revocation cannot strand an open hardware handle.
	return authErr
}

func validateDeviceAction(device Device, action DeviceAction) error {
	if device.Tier < 1 || !containsScope(device.Scopes, "device:act") {
		return errors.New("device token lacks device:act scope or tier")
	}
	if device.Tier == 2 && action.Confirmation != deviceConfirmation {
		return errors.New("Tier 2 action requires confirmation=CONFIRM_DEVICE_ACTION for this action")
	}
	if action.Name != "set_gpio" || !safeESP32OutputPin(action.Pin) || (action.Value != 0 && action.Value != 1) {
		return errors.New("unsupported ESP32 action; only set_gpio on approved output pins with value 0 or 1 is permitted")
	}
	return nil
}

func safeESP32OutputPin(pin int) bool {
	switch pin {
	case 4, 5, 13, 14, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33:
		return true
	default:
		return false
	}
}

func writeDeviceFrame(w io.Writer, value any) error {
	raw, err := json.Marshal(value)
	if err != nil {
		return err
	}
	if len(raw) > maxDeviceFrameBytes-1 {
		return errors.New("device command exceeds the frame size limit")
	}
	raw = append(raw, '\n')
	n, err := w.Write(raw)
	if err != nil {
		return err
	}
	if n != len(raw) {
		return io.ErrShortWrite
	}
	return nil
}

func readDeviceFrame(reader *bufio.Reader) ([]byte, error) {
	if reader == nil {
		return nil, errors.New("device serial reader is unavailable")
	}
	var raw []byte
	for len(raw) <= maxDeviceFrameBytes {
		part, err := reader.ReadSlice('\n')
		raw = append(raw, part...)
		if len(raw) > maxDeviceFrameBytes {
			return nil, errors.New("ESP32 response exceeds the frame size limit")
		}
		if err == nil {
			raw = bytes.TrimSpace(raw)
			if len(raw) == 0 {
				return nil, errors.New("ESP32 returned an empty response")
			}
			var payload map[string]any
			if err := json.Unmarshal(raw, &payload); err != nil {
				return nil, errors.New("ESP32 returned invalid JSON")
			}
			return append([]byte(nil), raw...), nil
		}
		if !errors.Is(err, bufio.ErrBufferFull) {
			return nil, fmt.Errorf("read ESP32 serial response: %w", err)
		}
	}
	return nil, errors.New("ESP32 response exceeds the frame size limit")
}
