package candidate
import "errors"
const CandidateID="bom-cost-ranked"
type Quote struct{Supplier string;UnitCost,TransportCost int64;InStock bool}
func BestQuote(q []Quote)(Quote,bool){var best Quote;ok:=false;for _,v:=range q{if !v.InStock||v.Supplier==""||v.UnitCost<0||v.TransportCost<0{continue};if !ok||v.UnitCost+v.TransportCost<best.UnitCost+best.TransportCost{best=v;ok=true}};return best,ok}
func Validate()error{v,ok:=BestQuote([]Quote{{"sample-a",1000,250,true},{"sample-b",900,100,true}});if !ok||v.Supplier!="sample-b"{return errors.New("quote ranking mismatch")};return nil}
