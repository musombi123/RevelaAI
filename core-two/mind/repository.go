package mind

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const maxRepositoryEntries = 500000
const maxReportedPaths = 500

type repositoryInventory struct {
	RepositoryRoot string `json:"repository_root"`; ObservedAt time.Time `json:"observed_at"`; Complete bool `json:"complete"`; DirectoriesScanned int `json:"directories_scanned"`; FilesScanned int `json:"files_scanned"`; TotalRegularFileBytes int64 `json:"total_regular_file_bytes"`; LanguageCounts map[string]int `json:"language_counts"`; CorePathCounts map[string]int `json:"core_path_counts"`; HubPathCounts map[string]int `json:"hub_path_counts"`; PriorityPaths []string `json:"priority_paths,omitempty"`; HubPaths []string `json:"hub_paths,omitempty"`; OpenAPIPaths []string `json:"openapi_paths,omitempty"`; ChangelogPaths []string `json:"changelog_paths,omitempty"`; AuditLogPaths []string `json:"audit_log_paths,omitempty"`; PathSizeManifestSHA256 string `json:"path_size_manifest_sha256"`; LimitsNote string `json:"limits_note"`
}

// scanRepositoryInventory indexes every repository path except Git internals. It never follows symlinks or executes source; its manifest is over paths and sizes, not file contents.
func (s *Service) scanRepositoryInventory() (repositoryInventory,error) {
	inventory:=repositoryInventory{RepositoryRoot:"configured_repository_root",ObservedAt:time.Now().UTC(),Complete:true,LanguageCounts:map[string]int{},CorePathCounts:map[string]int{"core-zero":0,"core-one-inventions":0,"core-one-libraries":0,"core-one-guardian":0,"core-two":0},HubPathCounts:map[string]int{},PriorityPaths:[]string{},HubPaths:[]string{},OpenAPIPaths:[]string{},ChangelogPaths:[]string{},AuditLogPaths:[]string{},LimitsNote:"Path/size inventory only; no source execution, symlink traversal, or content copying. .git internals are excluded. A 500,000-entry cap fails the scan rather than silently reporting a complete result."}
	hasher:=sha256.New();hubNames:=map[string]bool{"elimu":true,"shamba":true,"biashara":true,"community":true,"scripture":true,"faith":true,"theology":true,"education":true,"agriculture":true,"marketplace":true,"study":true,"study-hub":true}
	walkErr:=filepath.WalkDir(s.RepoRoot,func(path string,entry fs.DirEntry,incomingErr error)error{if incomingErr!=nil{return incomingErr};if path==s.RepoRoot{inventory.DirectoriesScanned++;return nil};rel,err:=filepath.Rel(s.RepoRoot,path);if err!=nil{return err};rel=filepath.ToSlash(rel);if entry.IsDir(){if entry.Name()==".git"{return filepath.SkipDir};inventory.DirectoriesScanned++}else{inventory.FilesScanned++;if inventory.FilesScanned+inventory.DirectoriesScanned>maxRepositoryEntries{return fmt.Errorf("repository scan exceeded the %d-entry safety cap; no complete inventory written",maxRepositoryEntries)};if entry.Type()&os.ModeSymlink==0{info,e:=entry.Info();if e!=nil{return e};if info.Mode().IsRegular(){inventory.TotalRegularFileBytes+=info.Size();_,_=fmt.Fprintf(hasher,"%s\x00%d\n",rel,info.Size())}};inventory.LanguageCounts[languageForPath(rel)]++};low:=strings.ToLower(rel)
	if strings.HasPrefix(low,"core-zero/")||low=="core-zero"{inventory.CorePathCounts["core-zero"]++};if strings.HasPrefix(low,"core-one/inventions/")||low=="core-one/inventions"{inventory.CorePathCounts["core-one-inventions"]++};if strings.HasPrefix(low,"core-one/libraries/")||low=="core-one/libraries"{inventory.CorePathCounts["core-one-libraries"]++};if strings.HasPrefix(low,"core-one/guardian/")||low=="core-one/guardian"{inventory.CorePathCounts["core-one-guardian"]++};if strings.HasPrefix(low,"core-two/")||low=="core-two"{inventory.CorePathCounts["core-two"]++}
	segments:=strings.Split(low,"/");inHub:=false;for _,segment:=range segments{if hubNames[segment]{inventory.HubPathCounts[segment]++;inHub=true}};if inHub&&len(inventory.HubPaths)<maxReportedPaths{inventory.HubPaths=append(inventory.HubPaths,rel)}
	if strings.HasSuffix(low,"/openapi.yaml")||strings.HasSuffix(low,"/openapi.yml")||low=="openapi.yaml"||low=="openapi.yml"{if len(inventory.OpenAPIPaths)<maxReportedPaths{inventory.OpenAPIPaths=append(inventory.OpenAPIPaths,rel)};inventory.PriorityPaths=appendBounded(inventory.PriorityPaths,rel)}
	base:=strings.ToLower(filepath.Base(rel));if strings.Contains(low,"changelog")||strings.HasPrefix(base,"changes-")||base=="changes.md"{inventory.ChangelogPaths=appendBounded(inventory.ChangelogPaths,rel);inventory.PriorityPaths=appendBounded(inventory.PriorityPaths,rel)};if strings.Contains(low,"audit_log"){inventory.AuditLogPaths=appendBounded(inventory.AuditLogPaths,rel);inventory.PriorityPaths=appendBounded(inventory.PriorityPaths,rel)};if strings.HasPrefix(low,"core-zero/")||strings.HasPrefix(low,"core-one/inventions/")||strings.HasPrefix(low,"core-one/libraries/")||strings.HasPrefix(low,"core-one/guardian/"){inventory.PriorityPaths=appendBounded(inventory.PriorityPaths,rel)};return nil})
	if walkErr!=nil{return repositoryInventory{},walkErr};inventory.PathSizeManifestSHA256=hex.EncodeToString(hasher.Sum(nil));inventory.PriorityPaths=sortedUnique(inventory.PriorityPaths);inventory.HubPaths=sortedUnique(inventory.HubPaths);inventory.OpenAPIPaths=sortedUnique(inventory.OpenAPIPaths);inventory.ChangelogPaths=sortedUnique(inventory.ChangelogPaths);inventory.AuditLogPaths=sortedUnique(inventory.AuditLogPaths);return inventory,nil
}
func appendBounded(paths []string,path string)[]string{if len(paths)>=maxReportedPaths{return paths};return append(paths,path)}
func languageForPath(path string)string{switch strings.ToLower(filepath.Ext(path)){case ".go":return "go";case ".py":return "python";case ".js",".mjs",".cjs":return "javascript";case ".jsx":return "jsx";case ".ts",".mts",".cts":return "typescript";case ".tsx":return "tsx";case ".json":return "json";case ".yaml",".yml":return "yaml";case ".md",".mdx":return "markdown";case ".html",".htm":return "html";case ".css":return "css";case ".rs":return "rust";case ".c",".h":return "c";case ".cpp",".cc",".hpp",".hh":return "cpp";case ".java":return "java";case ".sql":return "sql";case ".sh",".ps1",".bat":return "shell";case ".toml":return "toml";case ".xml":return "xml";default:return "other"}}
func sortedUnique(values []string)[]string{sort.Strings(values);if len(values)<2{return values};out:=values[:1];for _,value:=range values[1:]{if value!=out[len(out)-1]{out=append(out,value)}};return out}
