package candidate
import "errors"
const CandidateID="repository-path-index"
func BuildIndex(v []string)map[string]int{out:=map[string]int{};for i,p:=range v{if _,ok:=out[p];!ok{out[p]=i}};return out}
func Validate()error{m:=BuildIndex([]string{"a","b","a"});if len(m)!=2||m["a"]!=0||m["b"]!=1{return errors.New("path index mismatch")};return nil}
