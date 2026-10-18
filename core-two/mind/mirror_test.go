package mind

import (
 "context"
 "encoding/json"
 "net/http"
 "net/http/httptest"
 "os"
 "path/filepath"
 "strings"
 "testing"
)

func TestMirrorConsumesZeroAndOneLogsIncrementallyWithoutExposingRawRecords(t *testing.T) {
 root,s:=newTestRepository(t)
 zeroLog:=filepath.Join(root,"core-zero","audit_log","events.jsonl")
 oneLog:=filepath.Join(root,"core-one","state","events","events.jsonl")
 for path,body:=range map[string]string{
  zeroLog:"{\"event\":\"healing_proposal_created\",\"at\":\"2026-10-19T00:00:00Z\",\"message\":\"private-zero-log-content\"}\n",
  oneLog:"{\"type\":\"invention_created\",\"at\":\"2026-10-19T00:00:01Z\",\"status\":\"await_merge\",\"message\":\"private-one-log-content\"}\n",
 } {if err:=os.MkdirAll(filepath.Dir(path),0700);err!=nil{t.Fatal(err)};if err:=os.WriteFile(path,[]byte(body),0600);err!=nil{t.Fatal(err)}}
 server:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){w.WriteHeader(http.StatusOK)}));defer server.Close()
 t.Setenv("USECT_ZERO_BASE_URL",server.URL);t.Setenv("GENESIS_BASE_URL",server.URL)
 snapshot,err:=s.observeMirror(context.Background());if err!=nil{t.Fatal(err)}
 sources,ok:=snapshot["sources"].([]mirrorSourceStatus);if !ok{t.Fatalf("unexpected sources type: %T",snapshot["sources"])}
 if len(sources)!=3||sources[0].NewRecords!=1||sources[1].NewRecords!=1{t.Fatalf("did not read ZERO and ONE evidence: %+v",sources)}
 second,err:=s.observeMirror(context.Background());if err!=nil{t.Fatal(err)}
 secondSources:=second["sources"].([]mirrorSourceStatus)
 if secondSources[0].NewRecords!=0||secondSources[1].NewRecords!=0{t.Fatalf("duplicate replay on second poll: %+v",secondSources)}
 raw,_:=json.Marshal(second);if strings.Contains(string(raw),"private-zero-log-content")||strings.Contains(string(raw),"private-one-log-content"){t.Fatal("raw source messages leaked through the mirror summary")}
 cursor,err:=os.ReadFile(filepath.Join(root,"core-two","state","mirror-cursor.json"));if err!=nil{t.Fatal(err)};if !json.Valid(cursor){t.Fatal("incremental cursor is not valid JSON")}
}

func TestRequestTelemetryCountsToolUseWithoutSecrets(t *testing.T) {
 root,s:=newTestRepository(t)
 h:=s.WithTelemetry(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){w.WriteHeader(http.StatusOK);_,_=w.Write([]byte("ok"))}))
 req:=httptest.NewRequest(http.MethodGet,"/v1/genesis/tools/offline_vault_fixture/hardware_guide?query-secret=not-to-log",nil)
 req.Header.Set("Authorization","Bearer header-secret-never-log")
 response:=httptest.NewRecorder();h.ServeHTTP(response,req)
 if response.Code!=http.StatusOK{t.Fatalf("unexpected response: %d",response.Code)}
 path:=filepath.Join(root,"core-two","state","http_metrics.jsonl");raw,err:=os.ReadFile(path);if err!=nil{t.Fatal(err)}
 if strings.Contains(string(raw),"query-secret")||strings.Contains(string(raw),"header-secret-never-log"){t.Fatalf("request secret leaked to telemetry: %s",raw)}
 count,observed:=countToolEndpointUsage(path,"offline_vault_fixture");if !observed||count!=1{t.Fatalf("wrong tool usage count: %d observed=%v",count,observed)}
}
