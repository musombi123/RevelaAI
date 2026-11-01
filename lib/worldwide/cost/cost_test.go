package cost

import "testing"
func TestCrossCurrencyNeedsSuppliedRates(t *testing.T){
	_,err:=BestQuote([]Quote{{Supplier:"A",Currency:"USD",Amount:10,Verified:true},{Supplier:"B",Currency:"EUR",Amount:8,Verified:true}})
	if err==nil {t.Fatal("cross-currency comparison must not invent FX")}
}
func TestBestQuoteWithSuppliedRateChoosesLowestNormalizedAmount(t *testing.T){
	got,err:=BestQuote([]Quote{{Supplier:"A",Currency:"USD",Amount:10,Verified:true,RateToBase:1},{Supplier:"B",Currency:"EUR",Amount:8,Verified:true,RateToBase:1.2}})
	if err!=nil||got.Quote.Supplier!="B"{t.Fatalf("choice=%+v err=%v",got,err)}
	if !got.Comparable || got.Quote.Amount*got.Quote.RateToBase != 9.6 {t.Fatalf("supplied FX comparison was not applied: %+v",got)}
}
