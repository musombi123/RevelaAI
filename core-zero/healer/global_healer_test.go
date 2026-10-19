package healer
import("path/filepath";"testing")
func TestGlobalHealerAcrossCountries(t *testing.T){root:=filepath.Join("..","..");for _,tc:=range []struct{c,l string}{{"US","en"},{"DE","de"},{"CN","zh"},{"KE","sw"}}{got,err:=Classify("x509: certificate signed by unknown authority",tc.c,tc.l,root);if err!=nil{t.Fatal(err)};if !got.Matched||got.PatternID!="certificate_validation"||got.AutomaticRepair||!got.GuardianRequired{t.Fatalf("%s: %+v",tc.c,got)}}}
func TestGlobalHealerFailsClosedWithoutDatabase(t *testing.T){if _,err:=Classify("disk full","DE","de",t.TempDir());err==nil{t.Fatal("missing database must fail closed")}}
