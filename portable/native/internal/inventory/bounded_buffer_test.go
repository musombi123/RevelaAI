package inventory

import (
	"testing"
)

func TestBoundedBufferRejectsOutputBeyondLimit(t *testing.T) {
	buffer := &boundedBuffer{max: 4}
	if n, err := buffer.Write([]byte("1234")); err != nil || n != 4 {
		t.Fatalf("first write failed: n=%d err=%v", n, err)
	}
	if _, err := buffer.Write([]byte("5")); err == nil {
		t.Fatal("buffer must reject data beyond its limit")
	}
	if string(buffer.data) != "1234" {
		t.Fatalf("buffer changed after rejected write: %q", buffer.data)
	}
}
