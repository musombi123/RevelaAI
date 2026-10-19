package country

import "testing"

func TestCountryProfilesAndDefault(t *testing.T) {
	cases:=[]struct{input,code,currency,language string; volts int}{
		{"","KE","KES","en",240},{"USA","US","USD","en",120},{"DE","DE","EUR","de",230},{"China","CN","CNY","zh",220},{"JP","JP","JPY","ja",100},{"FR","FR","EUR","fr",230},{"BR","BR","LOCAL","en",0},
	}
	for _,tc:=range cases {p,err:=Resolve(tc.input,"");if err!=nil{t.Fatalf("%q: %v",tc.input,err)};if p.Code!=tc.code||p.Currency!=tc.currency||p.Language!=tc.language||p.NominalACVoltage!=tc.volts{t.Errorf("%q => %+v",tc.input,p)}}
}
func TestUnknownLanguageFallsBackSafely(t *testing.T){p,err:=Resolve("DE","made-up");if err!=nil{t.Fatal(err)};if p.Language!="en"{t.Fatalf("unsupported language %q",p.Language)}}
