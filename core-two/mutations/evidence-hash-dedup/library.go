package candidate
import("crypto/sha256";"encoding/hex";"strings")
const CandidateID="evidence-hash-dedup"
func Deduplicate(v []string)[]string{seen:=map[string]bool{};out:=[]string{};for _,s:=range v{s=strings.TrimSpace(s);if s==""{continue};h:=sha256.Sum256([]byte(s));key:=hex.EncodeToString(h[:]);if !seen[key]{seen[key]=true;out=append(out,s)}};return out}
func Validate()error{v:=Deduplicate([]string{"alpha","alpha"," beta ",""});if len(v)!=2||v[0]!="alpha"||v[1]!="beta"{return errBad};return nil}
type validationError struct{}
func(validationError)Error()string{return "evidence dedup failed"}
var errBad error=validationError{}
