package candidate
import("crypto/sha256";"encoding/hex";"encoding/json")
const CandidateID="canonical-spec-cache"
func Fingerprint(v map[string]string)string{b,_:=json.Marshal(v);h:=sha256.Sum256(b);return hex.EncodeToString(h[:])}
func Validate()error{a:=Fingerprint(map[string]string{"b":"2","a":"1"});b:=Fingerprint(map[string]string{"a":"1","b":"2"});if a==""||a!=b{return errBad};return nil}
type validationError struct{}
func(validationError)Error()string{return "unstable canonical fingerprint"}
var errBad error=validationError{}
