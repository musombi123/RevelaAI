package bom

import (
	"testing"
	"revela-worldwide.local/libs/country"
)
func TestWorldwideSupplierAdaptersAreQuoteOnly(t *testing.T){
	cases:=[]struct{country,currency,want string}{{"US","USD","Mouser"},{"DE","EUR","Conrad"},{"CN","CNY","LCSC"},{"KE","KES","Kamukunji"},{"JP","JPY","Akizuki"}}
	for _,tc:=range cases{p,_:=country.Resolve(tc.country,"");b:=ForCountry(p);if b.Currency!=tc.currency||len(b.Suppliers)==0{t.Fatalf("%s: %+v",tc.country,b)};found:=false;for _,s:=range b.Suppliers{if s==tc.want {found=true}};if !found{t.Errorf("%s lacks %s",tc.country,tc.want)};if b.PriceStatus!="quote_required"{t.Errorf("must not fabricate prices: %+v",b)}}
}
