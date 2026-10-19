package guardian
import "strings"
type Decision struct{Allowed bool `json:"allowed"`;Code string `json:"code"`;Reason string `json:"reason"`}
var restrictedSignals=[]string{"weapon manufacture","explosive device","ransomware","credential theft","spyware","covert surveillance","non-consensual tracking","privacy violation","disable safety controls","unauthorized physical actuation","delete audit logs"}
func CheckText(input string)Decision{text:=strings.ToLower(strings.TrimSpace(input));if text==""{return Decision{false,"empty_input","Non-empty input is required."}};for _,signal:=range restrictedSignals{if strings.Contains(text,signal){return Decision{false,"worldwide_guardian_block","A configured restricted-intent signal matched. Existing core Guardian and human-review gates remain mandatory."}}};return Decision{true,"no_configured_match","No configured signal matched; this is not proof of safety or legal compliance."}}
