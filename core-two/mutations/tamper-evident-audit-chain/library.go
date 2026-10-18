package candidate
import("crypto/sha256";"encoding/hex";"errors")
const CandidateID="tamper-evident-audit-chain"
func Chain(v []string)[]string{out:=[]string{};prev:="";for _,e:=range v{h:=sha256.Sum256([]byte(prev+"\n"+e));prev=hex.EncodeToString(h[:]);out=append(out,prev)};return out}
func Verify(v,h []string)bool{if len(v)!=len(h){return false};want:=Chain(v);for i:=range want{if want[i]!=h[i]{return false}};return true}
func Validate()error{v:=[]string{"created","reviewed"};h:=Chain(v);if !Verify(v,h)||Verify([]string{"altered","reviewed"},h){return errors.New("audit chain did not detect edit")};return nil}
