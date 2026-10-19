package genesis
import("errors";"revela-genesis.local/core-one/bom";"revela-worldwide.local/libs/country";"revela-worldwide.local/libs/guardian"
	"revela-genesis.local/core-one/hardware"
	"os"
	"path/filepath"
	"encoding/json")
func ApplyWorldwideProfile(spec *ToolSpec,p country.Profile)error{if spec==nil{return errors.New("tool specification is required")};if d:=guardian.CheckText(spec.Demand);!d.Allowed{return errors.New(d.Code+": "+d.Reason)};spec.Country=p.Code;spec.CountryName=p.Name;spec.Language=p.Language;spec.Currency=p.Currency;spec.SupplierDirectory=append([]string(nil),p.Suppliers...);spec.NominalACVoltage=p.NominalACVoltage;spec.FrequencyHz=p.FrequencyHz;spec.LocalAdaptations=append([]string(nil),p.Standards...);spec.LegalFrameworks=append([]string(nil),p.LegalFrameworks...);b,err:=bom.ForCountry(p.Code,p.Language);if err!=nil{return err};spec.BOM=map[string]any{"country":b.Country,"currency":b.Currency,"suppliers":b.Suppliers,"price_status":b.PriceStatus,"note":b.Note};return nil}
func ResolveWorldwideProfile(code,language string)(country.Profile,error){return country.Resolve(code,language)}


func generatedWorldGuide(spec ToolSpec) string {
	guide, _, err := hardware.BuildWorldwideGuide(spec.Country, spec.Language)
	if err != nil { return "\n\n## Worldwide adaptation\n\nCountry-specific guide unavailable; request a reviewed local adaptation. Do not guess voltage, supplier availability or legal requirements.\n" }
	return "\n\n" + guide
}

func (e *Engine) WorldwideHardwareGuide(name, countryCode, language string) (string, country.Profile, error) {
	if !validResourceName(name) { return "", country.Profile{}, errors.New("invalid tool name") }
	profile, err := country.Resolve(countryCode, language)
	if err != nil { return "", country.Profile{}, err }
	raw, err := os.ReadFile(filepath.Join(e.CoreRoot, "inventions", name, "evidence.json"))
	if err != nil { return "", country.Profile{}, err }
	var envelope struct { Specification ToolSpec `json:"specification"` }
	if err := json.Unmarshal(raw, &envelope); err != nil { return "", country.Profile{}, errors.New("invention specification evidence is invalid") }
	if err := ApplyWorldwideProfile(&envelope.Specification, profile); err != nil { return "", country.Profile{}, err }
	return generatedHardwareGuide(envelope.Specification), profile, nil
}
