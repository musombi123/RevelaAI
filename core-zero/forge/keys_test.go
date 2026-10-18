package forge

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestRequestWaitsForHumanApprovalAndPersistsOnlyHash(t *testing.T) {
	root:=t.TempDir();m:=New(root);r,e:=m.Request("Example Developer","dev@example.invalid","https://github.com/example/project","Need to run deterministic repository scans",[]string{"scan:read"});if e!=nil{t.Fatal(e)}
	if r.Status!="pending_approval"{t.Fatalf("status=%q",r.Status)};issued:=filepath.Join(root,"state","keys","issued");_ = os.MkdirAll(issued,0700);raw,e:=os.ReadFile(filepath.Join(root,"state","keys","requests",r.ID+".json"));if e!=nil{t.Fatal(e)};if strings.Contains(string(raw),"api_key"){t.Fatal("request unexpectedly contains a key")}
	approved,secret,e:=m.Approve(r.ID,"test-human",24*time.Hour);if e!=nil{t.Fatal(e)};if approved.Status!="approved"||secret==""{t.Fatal("approval did not issue a key")};if ok,_:=m.Validate(secret,"scan:read");!ok{t.Fatal("issued key should validate for granted scope")};if ok,_:=m.Validate(secret,"heal:propose");ok{t.Fatal("key must not gain an ungranted scope")}
	entries,e:=os.ReadDir(issued);if e!=nil||len(entries)!=1{t.Fatalf("issued files=%d err=%v",len(entries),e)};saved,e:=os.ReadFile(filepath.Join(issued,entries[0].Name()));if e!=nil{t.Fatal(e)};if strings.Contains(string(saved),secret){t.Fatal("raw secret was persisted")};keyID:=strings.TrimSuffix(entries[0].Name(),".json");if _,e:=m.Revoke(keyID,"test-human");e!=nil{t.Fatal(e)};if ok,_:=m.Validate(secret,"scan:read");ok{t.Fatal("revoked key must no longer validate")}
}
func TestPrivilegedScopeCannotBeRequested(t *testing.T) { m:=New(t.TempDir());if _,e:=m.Request("Example Developer","dev@example.invalid","","Need administrative access to approve production changes",[]string{"admin:*"});e==nil{t.Fatal("privileged scope must be rejected")} }
