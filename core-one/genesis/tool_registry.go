package genesis

import (
	"crypto/ed25519"
	"crypto/subtle"
	"crypto/sha256"
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
	"time"
)

const (
	registryRootName = "tool-registry"
	maxRegistryFiles = 10000
	maxRegistryBytes int64 = 512 << 20
)

var registryVersionPattern = regexp.MustCompile(`^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$`)

type SignedToolArtifact struct {
	Name           string          `json:"name"`
	Version        string          `json:"version"`
	ArtifactHash   string          `json:"artifact_hash"`
	Manifest       ToolManifest    `json:"manifest"`
	Signature      string          `json:"signature"`
	SandboxEvidence SandboxEvidence `json:"sandbox_evidence"`
	CreatedAt      time.Time       `json:"created_at"`
}

type ActiveToolPointer struct {
	Name              string    `json:"name"`
	Version           string    `json:"version"`
	ArtifactHash      string    `json:"artifact_hash"`
	Active             bool      `json:"active"`
	OwnerApprovalHash string    `json:"owner_approval_hash,omitempty"`
	UpdatedAt          time.Time `json:"updated_at"`
}

func PublishSignedToolArtifact(coreRoot, candidateDir string, manifest ToolManifest, evidence SandboxEvidence) (SignedToolArtifact, error) {
	if err := ValidateToolManifest(manifest); err != nil {
		return SignedToolArtifact{}, err
	}
	manifestJSON, err := json.Marshal(manifest)
	if err != nil {
		return SignedToolArtifact{}, errors.New("tool manifest could not be encoded")
	}
	manifestDigest := sha256.Sum256(manifestJSON)
	if !evidence.Passed || evidence.ToolName != manifest.Name ||
		evidence.ManifestHash != hex.EncodeToString(manifestDigest[:]) {
		return SignedToolArtifact{}, errors.New("matching passing sandbox evidence is required; artifact cannot be signed")
	}
	privateKey, err := registrySigningKey()
	if err != nil {
		return SignedToolArtifact{}, err
	}
	hash, err := hashArtifactTree(candidateDir)
	if err != nil {
		return SignedToolArtifact{}, err
	}
	if evidence.CandidateHash == "" || evidence.CandidateHash != hash {
		return SignedToolArtifact{}, errors.New("passing sandbox evidence must refer to the exact artifact content hash")
	}
	record := SignedToolArtifact{
		Name: manifest.Name,
		Version: manifest.Version,
		ArtifactHash: hash,
		Manifest: manifest,
		SandboxEvidence: evidence,
		CreatedAt: time.Now().UTC(),
	}
	payload, err := signingPayload(record)
	if err != nil {
		return SignedToolArtifact{}, errors.New("artifact signing payload could not be encoded")
	}
	record.Signature = "ed25519:" + hex.EncodeToString(ed25519.Sign(privateKey, payload))

	root, err := registryRoot(coreRoot)
	if err != nil {
		return SignedToolArtifact{}, err
	}
	versionBase := filepath.Join(root, "versions", manifest.Name, manifest.Version)
	if _, err := os.Lstat(versionBase); err == nil {
		return SignedToolArtifact{}, errors.New("registry versions are append-only; this tool version already exists")
	} else if !os.IsNotExist(err) {
		return SignedToolArtifact{}, errors.New("could not inspect registry version path")
	}
	if err := os.MkdirAll(filepath.Dir(versionBase), 0o700); err != nil {
		return SignedToolArtifact{}, errors.New("could not create registry version directory")
	}
	stage, err := os.MkdirTemp(filepath.Dir(versionBase), ".candidate-*")
	if err != nil {
		return SignedToolArtifact{}, errors.New("could not create registry staging directory")
	}
	defer os.RemoveAll(stage)

	artifactDir := filepath.Join(stage, "artifact")
	if err := copyArtifactTree(candidateDir, artifactDir); err != nil {
		return SignedToolArtifact{}, err
	}
	copiedHash, err := hashArtifactTree(artifactDir)
	if err != nil || copiedHash != hash {
		return SignedToolArtifact{}, errors.New("artifact changed while it was being copied; refusing to sign")
	}
	recordRaw, err := json.MarshalIndent(record, "", "  ")
	if err != nil {
		return SignedToolArtifact{}, errors.New("could not encode signed registry record")
	}
	if err := atomicWrite(filepath.Join(stage, "record.json"), recordRaw, 0o444); err != nil {
		return SignedToolArtifact{}, errors.New("could not persist signed registry record")
	}
	if err := makeTreeReadOnly(stage); err != nil {
		return SignedToolArtifact{}, errors.New("could not mark signed artifact read-only")
	}
	if err := os.Rename(stage, versionBase); err != nil {
		return SignedToolArtifact{}, errors.New("could not publish immutable registry version")
	}

	if manifest.RiskTier == 0 {
		if err := writeActivePointer(root, ActiveToolPointer{
			Name: manifest.Name, Version: manifest.Version, ArtifactHash: hash,
			Active: true, UpdatedAt: time.Now().UTC(),
		}); err != nil {
			return SignedToolArtifact{}, err
		}
	}
	return record, nil
}

func ActivateSignedToolVersion(coreRoot, name, version, artifactHash, ownerApprovalHash string) (ActiveToolPointer, error) {
	record, err := loadSignedToolArtifact(coreRoot, name, version, artifactHash)
	if err != nil {
		return ActiveToolPointer{}, err
	}
	if record.Manifest.RiskTier > 0 && !constantTimeStringEqual(ownerApprovalHash, artifactHash) {
		return ActiveToolPointer{}, errors.New("owner approval must match the exact artifact hash")
	}
	root, err := registryRoot(coreRoot)
	if err != nil {
		return ActiveToolPointer{}, err
	}
	pointer := ActiveToolPointer{
		Name: name, Version: version, ArtifactHash: artifactHash, Active: true,
		UpdatedAt: time.Now().UTC(),
	}
	if record.Manifest.RiskTier > 0 {
		pointer.OwnerApprovalHash = ownerApprovalHash
	}
	if err := writeActivePointer(root, pointer); err != nil {
		return ActiveToolPointer{}, err
	}
	return pointer, nil
}

func DeactivateSignedTool(coreRoot, name string) (ActiveToolPointer, error) {
	root, err := registryRoot(coreRoot)
	if err != nil {
		return ActiveToolPointer{}, err
	}
	pointer, err := readActivePointer(root, name)
	if err != nil {
		return ActiveToolPointer{}, err
	}
	pointer.Active = false
	pointer.UpdatedAt = time.Now().UTC()
	if err := writeActivePointer(root, pointer); err != nil {
		return ActiveToolPointer{}, err
	}
	return pointer, nil
}

func RollbackSignedTool(coreRoot, name, version, artifactHash, ownerApprovalHash string) (ActiveToolPointer, error) {
	return ActivateSignedToolVersion(coreRoot, name, version, artifactHash, ownerApprovalHash)
}

func ListSignedToolArtifacts(coreRoot string) ([]SignedToolArtifact, error) {
	root, err := registryRoot(coreRoot)
	if err != nil {
		return nil, err
	}
	base := filepath.Join(root, "versions")
	records := make([]SignedToolArtifact, 0)
	err = filepath.WalkDir(base, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() || entry.Name() != "record.json" {
			return nil
		}
		raw, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		var record SignedToolArtifact
		if json.Unmarshal(raw, &record) != nil {
			return errors.New("registry contains an invalid record")
		}
		if _, verifyErr := loadSignedToolArtifact(coreRoot, record.Name, record.Version, record.ArtifactHash); verifyErr != nil {
			return verifyErr
		}
		records = append(records, record)
		return nil
	})
	if os.IsNotExist(err) {
		return records, nil
	}
	if err != nil {
		return nil, errors.New("could not list signed tool registry")
	}
	sort.Slice(records, func(i, j int) bool {
		if records[i].Name == records[j].Name {
			if records[i].Version == records[j].Version {
				return records[i].ArtifactHash < records[j].ArtifactHash
			}
			return records[i].Version < records[j].Version
		}
		return records[i].Name < records[j].Name
	})
	return records, nil
}

func loadSignedToolArtifact(coreRoot, name, version, artifactHash string) (SignedToolArtifact, error) {
	if !validResourceName(name) || !registryVersionPattern.MatchString(version) ||
		len(artifactHash) != 64 || strings.Trim(artifactHash, "0123456789abcdef") != "" {
		return SignedToolArtifact{}, errors.New("invalid signed artifact reference")
	}
	root, err := registryRoot(coreRoot)
	if err != nil {
		return SignedToolArtifact{}, err
	}
	versionDir := filepath.Join(root, "versions", name, version)
	recordPath := filepath.Join(versionDir, "record.json")
	recordInfo, err := os.Lstat(recordPath)
	if err != nil || recordInfo.Mode()&os.ModeSymlink != 0 || !recordInfo.Mode().IsRegular() {
		return SignedToolArtifact{}, errors.New("signed artifact version was not found")
	}
	raw, err := readRegularFileLimited(recordPath, 2<<20)
	if err != nil {
		return SignedToolArtifact{}, errors.New("signed artifact record is invalid")
	}
	var record SignedToolArtifact
	if err := json.Unmarshal(raw, &record); err != nil {
		return SignedToolArtifact{}, errors.New("signed artifact record is invalid")
	}
	if record.Name != name || record.Version != version || record.ArtifactHash != artifactHash {
		return SignedToolArtifact{}, errors.New("signed artifact identity does not match requested version")
	}
	if err := ValidateToolManifest(record.Manifest); err != nil {
		return SignedToolArtifact{}, errors.New("signed artifact manifest is invalid")
	}
	manifestJSON, err := json.Marshal(record.Manifest)
	if err != nil {
		return SignedToolArtifact{}, errors.New("signed artifact manifest cannot be encoded")
	}
	manifestDigest := sha256.Sum256(manifestJSON)
	if !record.SandboxEvidence.Passed || record.SandboxEvidence.ToolName != name ||
		record.SandboxEvidence.CandidateHash != artifactHash ||
		record.SandboxEvidence.ManifestHash != hex.EncodeToString(manifestDigest[:]) {
		return SignedToolArtifact{}, errors.New("signed artifact does not contain matching passing sandbox evidence")
	}
	publicKey, err := registryPublicKey()
	if err != nil {
		return SignedToolArtifact{}, err
	}
	if !strings.HasPrefix(record.Signature, "ed25519:") {
		return SignedToolArtifact{}, errors.New("signed artifact signature algorithm is invalid")
	}
	signature, err := hex.DecodeString(strings.TrimPrefix(record.Signature, "ed25519:"))
	if err != nil || len(signature) != ed25519.SignatureSize {
		return SignedToolArtifact{}, errors.New("signed artifact signature is invalid")
	}
	payload, err := signingPayload(record)
	if err != nil || !ed25519.Verify(publicKey, payload, signature) {
		return SignedToolArtifact{}, errors.New("signed artifact signature verification failed")
	}
	artifactDir := filepath.Join(versionDir, "artifact")
	actualHash, err := hashArtifactTree(artifactDir)
	if err != nil || actualHash != artifactHash {
		return SignedToolArtifact{}, errors.New("immutable artifact content hash verification failed")
	}
	return record, nil
}

func registrySigningKey() (ed25519.PrivateKey, error) {
	raw := strings.TrimSpace(os.Getenv("GENESIS_SIGNING_KEY"))
	if raw == "" {
		return nil, errors.New("GENESIS_SIGNING_KEY is not configured; signing is disabled")
	}
	decoded, err := base64.RawStdEncoding.DecodeString(raw)
	if err != nil {
		decoded, err = base64.StdEncoding.DecodeString(raw)
	}
	if err != nil {
		return nil, errors.New("GENESIS_SIGNING_KEY must be base64 encoded Ed25519 key material")
	}
	switch len(decoded) {
	case ed25519.SeedSize:
		return ed25519.NewKeyFromSeed(decoded), nil
	case ed25519.PrivateKeySize:
		return ed25519.PrivateKey(decoded), nil
	default:
		return nil, errors.New("GENESIS_SIGNING_KEY must encode a 32-byte seed or 64-byte Ed25519 private key")
	}
}

func registryPublicKey() (ed25519.PublicKey, error) {
	privateKey, err := registrySigningKey()
	if err != nil {
		return nil, err
	}
	publicKey, ok := privateKey.Public().(ed25519.PublicKey)
	if !ok || len(publicKey) != ed25519.PublicKeySize {
		return nil, errors.New("Genesis signing public key is invalid")
	}
	return publicKey, nil
}

func registryRoot(coreRoot string) (string, error) {
	if strings.TrimSpace(coreRoot) == "" {
		return "", errors.New("Genesis registry root is not configured")
	}
	base, err := filepath.Abs(filepath.Clean(coreRoot))
	if err != nil {
		return "", errors.New("Genesis registry root is invalid")
	}
	info, err := os.Lstat(base)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return "", errors.New("Genesis repository root is unsafe or unavailable")
	}
	root := filepath.Join(base, registryRootName)
	if err := os.MkdirAll(root, 0o700); err != nil {
		return "", errors.New("Genesis registry storage is unavailable")
	}
	info, err = os.Lstat(root)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return "", errors.New("Genesis registry directory is unsafe")
	}
	if err := os.Chmod(root, 0o700); err != nil {
		return "", errors.New("Genesis registry permissions could not be restricted")
	}
	return root, nil
}

func signingPayload(record SignedToolArtifact) ([]byte, error) {
	manifest, err := json.Marshal(record.Manifest)
	if err != nil {
		return nil, err
	}
	evidence, err := json.Marshal(record.SandboxEvidence)
	if err != nil {
		return nil, err
	}
	return []byte(record.Name + "\n" + record.Version + "\n" + record.ArtifactHash + "\n" +
		string(manifest) + "\n" + string(evidence) + "\n" + record.CreatedAt.UTC().Format(time.RFC3339Nano)), nil
}

func hashArtifactTree(root string) (string, error) {
	info, err := os.Lstat(root)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return "", errors.New("artifact root must be a non-symlink directory")
	}
	type fileEntry struct {
		path string
		content []byte
	}
	var entries []fileEntry
	var total int64
	err = filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return errors.New("artifact symlinks are forbidden")
		}
		if entry.IsDir() {
			return nil
		}
		if !entry.Type().IsRegular() {
			return errors.New("artifact contains a non-regular file")
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		total += info.Size()
		if total > maxRegistryBytes || len(entries) >= maxRegistryFiles {
			return errors.New("artifact exceeds registry size limits")
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		entries = append(entries, fileEntry{path: filepath.ToSlash(rel), content: raw})
		return nil
	})
	if err != nil {
		return "", errors.New("could not hash artifact tree")
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].path < entries[j].path })
	hash := sha256.New()
	for _, entry := range entries {
		_, _ = io.WriteString(hash, entry.path+"\x00")
		_, _ = hash.Write(entry.content)
		_, _ = io.WriteString(hash, "\x00")
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func copyArtifactTree(source, destination string) error {
	if err := os.MkdirAll(destination, 0o700); err != nil {
		return errors.New("could not create artifact copy")
	}
	return filepath.WalkDir(source, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return errors.New("artifact symlinks are forbidden")
		}
		rel, err := filepath.Rel(source, path)
		if err != nil {
			return err
		}
		target := filepath.Join(destination, rel)
		if entry.IsDir() {
			return os.MkdirAll(target, 0o700)
		}
		if !entry.Type().IsRegular() {
			return errors.New("artifact contains a non-regular file")
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return atomicWrite(target, raw, 0o400)
	})
}

func makeTreeReadOnly(root string) error {
	return filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		// Artifacts must be readable by the sandbox's non-root UID while
		// remaining non-writable to all users. Parent registry directories and
		// active pointers remain private to the Genesis process.
		if entry.IsDir() {
			return os.Chmod(path, 0o555)
		}
		return os.Chmod(path, 0o444)
	})
}

func writeActivePointer(root string, pointer ActiveToolPointer) error {
	if !validResourceName(pointer.Name) || !registryVersionPattern.MatchString(pointer.Version) ||
		len(pointer.ArtifactHash) != 64 || strings.Trim(pointer.ArtifactHash, "0123456789abcdef") != "" {
		return errors.New("refusing invalid active pointer")
	}
	raw, err := json.MarshalIndent(pointer, "", "  ")
	if err != nil {
		return errors.New("could not encode active tool pointer")
	}
	dir := filepath.Join(root, "active")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return errors.New("active tool registry is unavailable")
	}
	return atomicWrite(filepath.Join(dir, pointer.Name+".json"), raw, 0o600)
}

func readActivePointer(root, name string) (ActiveToolPointer, error) {
	if !validResourceName(name) {
		return ActiveToolPointer{}, errors.New("invalid tool name")
	}
	path := filepath.Join(root, "active", name+".json")
	info, err := os.Lstat(path)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return ActiveToolPointer{}, errors.New("tool has no active registry pointer")
	}
	raw, err := readRegularFileLimited(path, 64*1024)
	if err != nil {
		return ActiveToolPointer{}, errors.New("active tool pointer is invalid")
	}
	var pointer ActiveToolPointer
	if err := json.Unmarshal(raw, &pointer); err != nil ||
		pointer.Name != name || !registryVersionPattern.MatchString(pointer.Version) ||
		len(pointer.ArtifactHash) != 64 || strings.Trim(pointer.ArtifactHash, "0123456789abcdef") != "" {
		return ActiveToolPointer{}, errors.New("active tool pointer is invalid")
	}
	return pointer, nil
}

func constantTimeStringEqual(a, b string) bool {
	return len(a) == len(b) && subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}

func makeRegistryError(err error) string {
	if err == nil {
		return ""
	}
	return fmt.Sprintf("registry operation failed: %s", err.Error())
}
