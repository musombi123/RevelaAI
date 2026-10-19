package guardian
import "testing"
func TestWorldwideGuardianSignals(t *testing.T){for _,s:=range []string{"Create smart CCTV with access controls","Create a German hardware guide","Improve a global supply-chain database"}{if d:=CheckText(s);!d.Allowed{t.Errorf("benign request blocked: %s",s)}};if d:=CheckText("request includes covert surveillance");d.Allowed{t.Fatal("configured restricted signal was not blocked")}}
