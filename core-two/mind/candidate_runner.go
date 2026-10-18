package mind

import (
  "bytes"
  "context"
  "fmt"
  "os"
  "os/exec"
  "path/filepath"
  "strings"
  "time"
)

// runCandidateTest executes only a fixed, allowlisted Core-Two candidate template in a
// disposable offline Go module. Repository-sourced invention code is never run here.
func runCandidateTest(parent context.Context, spec candidateSpec) error {
  ctx,cancel:=context.WithTimeout(parent,8*time.Second)
  defer cancel()
  root,err:=os.MkdirTemp("","revela-mind-candidate-test-")
  if err!=nil{return err}
  defer os.RemoveAll(root)
  moduleRoot:=filepath.Join(root,"module")
  if err:=os.Mkdir(moduleRoot,0o700);err!=nil{return err}
  files:=map[string]string{"go.mod":"module candidate.fixture\n\ngo 1.23\n","library.go":spec.Source+"\n","library_test.go":sharedCandidateTest}
  for name,content:=range files{if err:=os.WriteFile(filepath.Join(moduleRoot,name),[]byte(content),0o600);err!=nil{return err}}
  cmd:=exec.CommandContext(ctx,"go","test","-count=1","-timeout=4s",".")
  cmd.Dir=moduleRoot
  cmd.Env=offlineGoEnvironment(root)
  var output bytes.Buffer;cmd.Stdout=&output;cmd.Stderr=&output
  if err:=cmd.Run();err!=nil{details:=strings.TrimSpace(output.String());if len(details)>1200{details=details[:1200]};if ctx.Err()!=nil{return fmt.Errorf("candidate test exceeded bounded runtime: %w",ctx.Err())};return fmt.Errorf("go test rejected %s: %v: %s",spec.ID,err,details)}
  return nil
}
func offlineGoEnvironment(tempRoot string)[]string{env:=[]string{};for _,key:=range []string{"PATH","GOROOT","GOCACHE","GOOS","GOARCH","CGO_ENABLED"}{if value:=os.Getenv(key);value!=""{env=append(env,key+"="+value)}};if os.Getenv("GOCACHE")==""{if cache,err:=os.UserCacheDir();err==nil{env=append(env,"GOCACHE="+filepath.Join(cache,"go-build"))}};return append(env,"HOME="+tempRoot,"TMPDIR="+tempRoot,"GOTOOLCHAIN=local","GOPROXY=off","GOSUMDB=off","GOWORK=off","GOENV=off")}
