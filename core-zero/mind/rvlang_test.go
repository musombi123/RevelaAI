package mind

import "testing"

func TestCompileProducesPlanNotExecution(t *testing.T) {
	r,e:=Compile("scan\nheal \"src/example.py\"\nassemble esp32-sensor");if e!=nil{t.Fatal(e)};if len(r.Operations)!=3||r.Executed||!r.HumanApprovalRequired{t.Fatalf("unexpected result: %#v",r)};if len(Keywords)>20{t.Fatalf("too many keywords: %d",len(Keywords))}
}
func TestUnknownCommandRejected(t *testing.T){if _,e:=Compile("shell rm -rf /\n");e==nil{t.Fatal("unknown command should fail")}}
