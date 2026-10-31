package inventory

import "errors"

// boundedBuffer prevents subprocess stdout/stderr from growing without limit.
type boundedBuffer struct {
	data []byte
	max int
}

func (b *boundedBuffer) Write(p []byte) (int, error) {
	if b.max < 0 || len(p) > b.max-len(b.data) {
		return 0, errors.New("command output exceeded the configured size limit")
	}
	b.data = append(b.data, p...)
	return len(p), nil
}
