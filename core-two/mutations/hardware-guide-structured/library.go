package candidate
import("errors";"strings";"strconv")
const CandidateID="hardware-guide-structured"
func BuildGuide(parts,steps,checks,stop []string)string{var b strings.Builder;b.WriteString("Prerequisites\n");for _,x:=range parts{b.WriteString("- "+x+"\n")};b.WriteString("Steps\n");for i,x:=range steps{b.WriteString(strconv.Itoa(i+1)+". "+x+"\n")};b.WriteString("Verification\n");for _,x:=range checks{b.WriteString("- "+x+"\n")};b.WriteString("Stop conditions\n");for _,x:=range stop{b.WriteString("- "+x+"\n")};return b.String()}
func Validate()error{s:=BuildGuide([]string{"disconnect power"},[]string{"inspect"},[]string{"verify"},[]string{"stop if unsure"});for _,v:=range []string{"Prerequisites","Steps","Verification","Stop conditions"}{if !strings.Contains(s,v){return errors.New("missing guide section")}};return nil}
