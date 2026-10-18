package candidate
import "errors"
const CandidateID="bounded-input-guard"
func ValidInput(s string)bool{if s==""||len(s)>4096{return false};for i:=0;i<len(s);i++{if s[i]==0{return false}};clean:=s;for i:=0;i+2<len(clean);i++{if clean[i:i+3]=="../"{return false}};if len(clean)>0&&clean[0]=='/'{return false};return true}
func Validate()error{if !ValidInput("safe input")||ValidInput("../outside")||ValidInput(string(make([]byte,4097))){return errors.New("input guard failed")};return nil}
