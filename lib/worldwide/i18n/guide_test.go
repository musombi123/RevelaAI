package i18n

import (
	"strings"
	"testing"
	"revela-worldwide.local/libs/country"
)
func TestGuideLocalizationAndVoltageSafety(t *testing.T){
	cases:=[]struct{code,lang,contains string}{{"US","en","120 V"},{"DE","de","Weltweiter Hardware-Leitfaden"},{"CN","zh","全球硬件指南"},{"JP","ja","世界向けハードウェアガイド"},{"KE","sw","Mwongozo wa vifaa wa kimataifa"}}
	for _,tc:=range cases{p,err:=country.Resolve(tc.code,tc.lang);if err!=nil{t.Fatal(err)};g:=WorldwideGuide(p);if !strings.Contains(g,tc.contains){t.Errorf("%s guide missing %q",tc.code,tc.contains)};if !strings.Contains(g,"reference only")&&!strings.Contains(g,"参考")&&!strings.Contains(g,"参考値"){t.Errorf("%s guide lacks verification disclaimer",tc.code)}}
}
