package candidate
import "errors"
const CandidateID="cross-industry-pollination"
func Shared(a,b []string)[]string{s:=map[string]bool{};for _,x:=range a{if x!=""{s[x]=true}};out:=[]string{};seen:=map[string]bool{};for _,x:=range b{if s[x]&&!seen[x]{out=append(out,x);seen[x]=true}};return out}
func Validate()error{if len(Shared([]string{"offline","audit"},[]string{"audit","offline","agriculture"}))!=2{return errors.New("shared capability count mismatch")};return nil}
