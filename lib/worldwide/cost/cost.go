package cost

import "errors"

type Quote struct {
	Supplier string `json:"supplier"`
	Country string `json:"country"`
	Currency string `json:"currency"`
	Amount float64 `json:"amount"`
	Verified bool `json:"verified"`
	RateToBase float64 `json:"rate_to_base,omitempty"` // base-currency units per one unit of Currency
}
type Choice struct { Quote Quote `json:"quote"`; Comparable bool `json:"comparable"`; Reason string `json:"reason"` }
func BestQuote(quotes []Quote) (Choice,error) {
	var best *Quote; var bestValue float64; comparableCount:=0
	for _,q:=range quotes {
		if !q.Verified || q.Amount<0 {continue}
		value:=q.Amount
		if q.RateToBase>0 {value*=q.RateToBase} else if q.Currency=="" {continue}
		comparable:=true
		for _,other:=range quotes {if other.Verified && other.Amount>=0 && other.Currency!=q.Currency && (other.RateToBase<=0||q.RateToBase<=0){comparable=false;break}}
		if !comparable && comparableCount==0 {continue}
		if best==nil || value<bestValue {copy:=q;best=&copy;bestValue=value}
		comparableCount++
	}
	if best==nil {return Choice{Comparable:false,Reason:"No comparable verified quote is available; request current country-specific supplier quotes and a timestamped FX source."},errors.New("no comparable verified supplier quote")}
	return Choice{Quote:*best,Comparable:true,Reason:"Selected from verified quote inputs and supplied FX conversion only; no currency rate was inferred."},nil
}
