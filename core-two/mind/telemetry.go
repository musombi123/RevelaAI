package mind

import (
  "encoding/json"
  "net/http"
  "os"
  "path/filepath"
  "strings"
  "time"
)

type telemetryWriter struct { http.ResponseWriter; status int; bytes int64 }
func (w *telemetryWriter) WriteHeader(status int) { if w.status!=0{return};w.status=status;w.ResponseWriter.WriteHeader(status) }
func (w *telemetryWriter) Write(p []byte)(int,error){if w.status==0{w.WriteHeader(http.StatusOK)};n,err:=w.ResponseWriter.Write(p);w.bytes+=int64(n);return n,err}
func (w *telemetryWriter) Flush(){if w.status==0{w.WriteHeader(http.StatusOK)};if f,ok:=w.ResponseWriter.(http.Flusher);ok{f.Flush()}}
func (w *telemetryWriter) Unwrap()http.ResponseWriter{return w.ResponseWriter}

// WithTelemetry records low-risk request metadata only (no headers, body, query parameters or client IP).
func (s *Service) WithTelemetry(next http.Handler) http.Handler {
 return http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
   start:=time.Now();capture:=&telemetryWriter{ResponseWriter:w}
   next.ServeHTTP(capture,r)
   status:=capture.status;if status==0{status=http.StatusOK}
   entry:=map[string]any{"at":time.Now().UTC(),"method":r.Method,"route":telemetryRoute(r.URL.Path),"tool_name":telemetryToolName(r.URL.Path),"status":status,"duration_ms":float64(time.Since(start).Microseconds())/1000,"response_bytes":capture.bytes}
   raw,err:=json.Marshal(entry);if err!=nil{return}
   path:=filepath.Join(s.CoreRoot,"state","http_metrics.jsonl")
   if os.MkdirAll(filepath.Dir(path),0o700)!=nil{return}
   f,err:=os.OpenFile(path,os.O_CREATE|os.O_APPEND|os.O_WRONLY,0o600);if err!=nil{return};_,_=f.Write(append(raw,'\n'));_=f.Close()
 })
}
func telemetryToolName(path string)string {
 parts:=strings.Split(strings.Trim(path,"/"),"/")
 if len(parts)>=5&&parts[0]=="v1"&&parts[1]=="mind"&&parts[2]=="tools" {return safeTelemetryName(parts[3])}
 if len(parts)>=4&&parts[0]=="v1"&&parts[1]=="genesis"&&parts[2]=="tools" {return safeTelemetryName(parts[3])}
 return ""
}
func safeTelemetryName(name string)string{if validName(name){return name};return ""}
func telemetryRoute(path string)string{
 parts:=strings.Split(strings.Trim(path,"/"),"/")
 if len(parts)>=4&&parts[0]=="v1"&&parts[1]=="mind"&&parts[2]=="tools"{parts[3]="{name}";return "/"+strings.Join(parts,"/")}
 if len(parts)>=4&&parts[0]=="v1"&&parts[1]=="genesis"&&parts[2]=="tools"{parts[3]="{name}";return "/"+strings.Join(parts,"/")}
 if len(parts)>=5&&parts[0]=="v1"&&parts[1]=="zero"&&parts[2]=="heal"&&parts[3]=="proposals"{parts[4]="{proposal_id}";return "/"+strings.Join(parts,"/")}
 return "/"+strings.Join(parts,"/")
}
