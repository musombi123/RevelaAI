package mind

import "revela-mind.local/core-two/rvx"

type RVXEnvelope = rvx.Envelope

func SealRVX(masterKey string, plaintext []byte) (RVXEnvelope,error) { return rvx.Seal(masterKey,plaintext) }
func OpenRVX(masterKey string, envelope RVXEnvelope) ([]byte,error) { return rvx.Open(masterKey,envelope) }
