package mind

import (
  "bufio"
  "bytes"
  "context"
  "encoding/json"
  "errors"
  "fmt"
  "io"
  "net/http"
  "net/url"
  "os"
  "path/filepath"
  "strings"
  "time"
)

const maxMirrorBytesPerSource int64 = 4 << 20
const maxMirrorEventsPerSource = 2000

type mirrorCursorStore struct {
  Sources map[string]mirrorSourceCursor `json:"sources"`
}
type mirrorSourceCursor struct {
  Offset int64 `json:"offset"`
  TotalRecords int64 `json:"total_records"`
  Counts map[string]int64 `json:"event_counts"`
  LastObservedAt time.Time `json:"last_observed_at"`
  Recent []map[string]any `json:"recent_summaries"`
}
type mirrorSourceStatus struct {
  Path string `json:"path"`
  Available bool `json:"available"`
  Bytes int64 `json:"bytes"`
  Offset int64 `json:"offset"`
  NewRecords int `json:"new_records"`
  TotalRecords int64 `json:"total_records"`
  EventCounts map[string]int64 `json:"event_counts"`
  Error string `json:"error,omitempty"`
}
type healthProbe struct {
  Service string `json:"service"`
  URL string `json:"url"`
  Reachable bool `json:"reachable"`
  StatusCode int `json:"status_code,omitempty"`
  LatencyMS float64 `json:"latency_ms,omitempty"`
  Error string `json:"error,omitempty"`
}

// observeMirror consumes append-only Core-One/Core-Zero JSONL evidence from saved byte cursors.
// It never executes source, follows external URLs except a configured HTTPS health endpoint, or returns raw log lines.
func (s *Service) observeMirror(ctx context.Context) (map[string]any, error) {
  s.mirrorMu.Lock()
  defer s.mirrorMu.Unlock()
  cursorPath := filepath.Join(s.CoreRoot, "state", "mirror-cursor.json")
  store := mirrorCursorStore{Sources: map[string]mirrorSourceCursor{}}
  if raw, err := os.ReadFile(cursorPath); err == nil {
    if json.Unmarshal(raw, &store) != nil { return nil, errors.New("saved mirror cursor is invalid JSON; refusing to overwrite") }
    if store.Sources == nil { store.Sources = map[string]mirrorSourceCursor{} }
  } else if !os.IsNotExist(err) { return nil, err }
  paths := []string{
    filepath.Join(s.ZeroRoot, "audit_log", "events.jsonl"),
    filepath.Join(s.OneRoot, "state", "events", "events.jsonl"),
    filepath.Join(s.OneRoot, "guardian", "blocked.log"),
  }
  statuses := make([]mirrorSourceStatus, 0, len(paths))
  recent := []map[string]any{}
  for _, abs := range paths {
    rel, _ := filepath.Rel(s.RepoRoot, abs)
    key := filepath.ToSlash(rel)
    cursor := store.Sources[key]
    if cursor.Counts == nil { cursor.Counts = map[string]int64{} }
    if cursor.Recent == nil { cursor.Recent = []map[string]any{} }
    status := mirrorSourceStatus{Path:key, EventCounts:cursor.Counts, TotalRecords:cursor.TotalRecords, Offset:cursor.Offset}
    info, err := os.Stat(abs)
    if os.IsNotExist(err) {
      statuses = append(statuses, status)
      store.Sources[key] = cursor
      continue
    }
    if err != nil { status.Error=err.Error(); statuses=append(statuses,status); continue }
    if !info.Mode().IsRegular() { status.Error="source is not a regular file"; statuses=append(statuses,status); continue }
    status.Available=true
    status.Bytes=info.Size()
    if cursor.Offset > info.Size() || cursor.Offset < 0 { cursor.Offset=0 }
    f, err := os.Open(abs)
    if err != nil { status.Error=err.Error();statuses=append(statuses,status);continue }
    if _, err = f.Seek(cursor.Offset, io.SeekStart); err != nil { _=f.Close();status.Error=err.Error();statuses=append(statuses,status);continue }
    chunk, readErr := io.ReadAll(io.LimitReader(f, maxMirrorBytesPerSource))
    closeErr := f.Close()
    if readErr != nil { status.Error=readErr.Error();statuses=append(statuses,status);continue }
    if closeErr != nil { status.Error=closeErr.Error();statuses=append(statuses,status);continue }
    lastNL := bytes.LastIndexByte(chunk, '\n')
    if lastNL >= 0 {
      complete := chunk[:lastNL+1]
      scanner := bufio.NewScanner(bytes.NewReader(complete))
      scanner.Buffer(make([]byte, 4096), 1<<20)
      for scanner.Scan() {
        line := strings.TrimSpace(scanner.Text())
        if line == "" { continue }
        var event map[string]any
        if json.Unmarshal([]byte(line), &event) != nil {
          cursor.Counts["unparsed_record"]++
          cursor.TotalRecords++
          continue
        }
        kind := firstString(event, "type", "event", "action", "event_type", "status")
        if kind == "" { kind = "record" }
        cursor.Counts[kind]++
        cursor.TotalRecords++
        at := firstString(event, "at", "created_at", "timestamp", "time")
        cursor.LastObservedAt = time.Now().UTC()
        summary := map[string]any{"source":key,"type":limitLabel(kind,80),"at":limitLabel(at,80),"status":limitLabel(firstString(event,"status","result"),60)}
        cursor.Recent = append(cursor.Recent, summary)
        if len(cursor.Recent) > maxMirrorEventsPerSource { cursor.Recent = append([]map[string]any(nil), cursor.Recent[len(cursor.Recent)-maxMirrorEventsPerSource:]...) }
      }
      if scanner.Err()!=nil { status.Error="a JSONL record exceeds the 1 MiB scan limit" } else {
        cursor.Offset += int64(lastNL+1)
        status.NewRecords = countParsedLines(complete)
      }
    } else if len(chunk)>0 && info.Size()-cursor.Offset > int64(len(chunk)) {
      status.Error="no newline found in capped log segment; cursor not advanced"
    }
    status.Offset=cursor.Offset
    status.TotalRecords=cursor.TotalRecords
    status.EventCounts=cursor.Counts
    cursor.LastObservedAt=time.Now().UTC()
    store.Sources[key]=cursor
    statuses=append(statuses,status)
    recent=append(recent,cursor.Recent...)
  }
  if err:=writeJSONFile(cursorPath,store,0o600);err!=nil{return nil,fmt.Errorf("persist mirror cursor: %w",err)}
  if len(recent)>40 { recent=recent[len(recent)-40:] }
  zeroBase:=envOr("USECT_ZERO_BASE_URL","http://127.0.0.1:8780")
  oneBase:=envOr("GENESIS_BASE_URL","http://127.0.0.1:8781")
  zeroHealth:=probeHealth(ctx,"Core-Zero",zeroBase,"/v1/health")
  oneHealth:=probeHealth(ctx,"Core-One",oneBase,"/v1/genesis/health")
  healingDir:=filepath.Join(s.ZeroRoot,"evidence","heal")
  healCount,lastHeal:=countRecentFiles(healingDir,1000)
  return map[string]any{
    "observed_at":time.Now().UTC(),
    "mode":"read_only_incremental_log_mirror",
    "sources":statuses,
    "recent_event_summaries":recent,
    "core_zero_health":zeroHealth,
    "core_one_health":oneHealth,
    "core_zero_heal_evidence":map[string]any{"directory":"core-zero/evidence/heal","available":directoryExists(healingDir),"file_count":healCount,"latest_modified_at":lastHeal},
    "source_code_executed":false,
    "raw_log_content_exposed":false,
    "cursor_path":"core-two/state/mirror-cursor.json",
    "notes":[]string{
      "Core-Zero and Core-One audit/event streams are tailed incrementally; an unavailable log is reported, not treated as zero events.",
      "Health probes are read-only. Non-loopback upstreams must use HTTPS.",
      "The mirror reads at most 4 MiB per source per pass and advances only through complete newline-delimited records.",
    },
  },nil
}

func probeHealth(ctx context.Context,name,base,path string) healthProbe {
  result:=healthProbe{Service:name}
  normalized,normalizeErr:=normalizeCoreBase(base)
  if normalizeErr!=nil { result.Error="invalid upstream URL or private-network policy";return result }
  parsed,err:=url.Parse(normalized)
  if err!=nil || parsed.Host=="" || parsed.User!=nil || parsed.RawQuery!="" || parsed.Fragment!="" { result.Error="invalid upstream URL";return result }
  parsed.Path=strings.TrimRight(parsed.Path,"/")+path
  result.URL=parsed.Scheme+"://"+parsed.Host+parsed.EscapedPath()
  request,err:=http.NewRequestWithContext(ctx,http.MethodGet,parsed.String(),nil)
  if err!=nil { result.Error="could not create health request";return result }
  client:=&http.Client{Timeout:900*time.Millisecond}
  start:=time.Now()
  response,err:=client.Do(request)
  result.LatencyMS=float64(time.Since(start).Microseconds())/1000
  if err!=nil { result.Error="upstream unreachable";return result }
  defer response.Body.Close()
  result.StatusCode=response.StatusCode
  result.Reachable=response.StatusCode>=200&&response.StatusCode<300
  if !result.Reachable { result.Error="upstream returned a non-success status" }
  return result
}
func countRecentFiles(root string,capFiles int)(int,any){count:=0;var latest time.Time;_ = filepath.WalkDir(root,func(path string,entry os.DirEntry,err error)error{if err!=nil{return nil};if entry.IsDir(){return nil};info,e:=entry.Info();if e!=nil||!info.Mode().IsRegular(){return nil};count++;if info.ModTime().After(latest){latest=info.ModTime()};if count>=capFiles{return filepath.SkipAll};return nil});if latest.IsZero(){return count,nil};return count,latest.UTC()}
func firstString(obj map[string]any,keys ...string)string{for _,key:=range keys{if value,ok:=obj[key].(string);ok&&strings.TrimSpace(value)!=""{return strings.TrimSpace(value)}};return ""}
func limitLabel(value string,n int)string{value=strings.TrimSpace(value);if len(value)>n{return value[:n]};return value}
func countParsedLines(chunk []byte)int{n:=0;scanner:=bufio.NewScanner(bytes.NewReader(chunk));scanner.Buffer(make([]byte,4096),1<<20);for scanner.Scan(){if strings.TrimSpace(scanner.Text())!=""{n++}};return n}
func envOr(key,fallback string)string{if value:=strings.TrimSpace(os.Getenv(key));value!=""{return value};return fallback}
