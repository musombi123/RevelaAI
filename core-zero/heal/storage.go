package heal

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"

	"usect-zero.local/core-zero/internal/kernel"
)

func newID() (string, error) { b := make([]byte, 12); if _, e := rand.Read(b); e != nil { return "", e }; return hex.EncodeToString(b), nil }
func gitOutput(root string, args ...string) ([]byte, error) { return runGit(root, args...) }
func kWriteProposal(k *kernel.Kernel, p Proposal) error { return writeJSON(k.CoreRoot, filepath.Join("state", "proposals", "heal-"+p.ID+".json"), p) }
func kReadProposal(k *kernel.Kernel, id string, p *Proposal) error {
	if strings.ContainsAny(id, "/\\\x00") || id == "" { return os.ErrNotExist }
	return readJSON(k.CoreRoot, filepath.Join("state", "proposals", "heal-"+id+".json"), p)
}
func writeJSON(root, rel string, v any) error {
	path := filepath.Join(root, rel)
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil { return err }
	b, err := json.MarshalIndent(v, "", "  "); if err != nil { return err }; b = append(b, '\n')
	tmp := path + ".tmp"; if err = os.WriteFile(tmp, b, 0600); err != nil { return err }; return os.Rename(tmp, path)
}
func readJSON(root, rel string, v any) error { b, err := os.ReadFile(filepath.Join(root, rel)); if err != nil { return err }; return json.Unmarshal(b, v) }
