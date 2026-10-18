// Package candidate is a proposal-only Core-Two mutation; not wired into Core-One.
package candidate
import "errors"
const CandidateID = "graph-indexed"
type Graph map[string][]string
func Reachable(graph Graph,start string)[]string{if start==""{return nil};q:=[]string{start};seen:=map[string]struct{}{start:{}};out:=make([]string,0,len(graph)+1);for h:=0;h<len(q);h++{n:=q[h];out=append(out,n);for _,next:=range graph[n]{if next==""{continue};if _,ok:=seen[next];ok{continue};seen[next]=struct{}{};q=append(q,next)}};return out}
func Validate()error{got:=Reachable(Graph{"a":{"b","c"},"b":{"c"},"c":{}},"a");if len(got)!=3||got[0]!="a"||got[1]!="b"||got[2]!="c"{return errors.New("graph traversal mismatch")};return nil}
