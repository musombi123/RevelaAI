package candidate
import "errors"
const CandidateID="graph-indexed"
type Graph map[string][]string
func Reachable(g Graph,start string)[]string{if start==""{return nil};q:=[]string{start};seen:=map[string]struct{}{start:{}};out:=[]string{};for h:=0;h<len(q);h++{n:=q[h];out=append(out,n);for _,v:=range g[n]{if _,ok:=seen[v];ok{continue};seen[v]=struct{}{};q=append(q,v)}};return out}
func Validate()error{v:=Reachable(Graph{"a":{"b","c"},"b":{"c"},"c":{}},"a");if len(v)!=3||v[0]!="a"||v[1]!="b"||v[2]!="c"{return errors.New("graph traversal mismatch")};return nil}
