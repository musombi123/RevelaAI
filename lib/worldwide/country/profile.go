package country

import (
	"errors"
	"strings"
	"unicode"
)

type Profile struct {
	Code string `json:"country"`
	Name string `json:"country_name"`
	Language string `json:"language"`
	LanguageName string `json:"language_name"`
	Currency string `json:"currency"`
	CurrencySymbol string `json:"currency_symbol"`
	NominalACVoltage int `json:"nominal_ac_voltage_v,omitempty"`
	FrequencyHz string `json:"frequency_hz,omitempty"`
	Suppliers []string `json:"supplier_directory"`
	Standards []string `json:"local_adaptations"`
	LegalFrameworks []string `json:"legal_framework_awareness"`
	LegalDisclaimer string `json:"legal_disclaimer"`
}

func Normalize(code string) (string, error) {
	v := strings.ToUpper(strings.TrimSpace(code))
	switch v {
	case "", "KE", "KENYA", "KEN":
		return "KE", nil
	case "US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA":
		return "US", nil
	case "DE", "GERMANY", "DEU", "DEUTSCHLAND":
		return "DE", nil
	case "CN", "CHINA", "CHN":
		return "CN", nil
	case "JP", "JAPAN", "JPN":
		return "JP", nil
	case "FR", "FRANCE", "FRA":
		return "FR", nil
	case "ES", "SPAIN", "ESP":
		return "ES", nil
	case "GB", "UK", "UNITED KINGDOM", "GBR":
		return "GB", nil
	case "IN", "INDIA", "IND":
		return "IN", nil
	case "CA", "CANADA", "CAN":
		return "CA", nil
	case "AU", "AUSTRALIA", "AUS":
		return "AU", nil
	}
	if len(v) == 2 && unicode.IsLetter(rune(v[0])) && unicode.IsLetter(rune(v[1])) {
		return v, nil
	}
	return "", errors.New("country must be a supported country name or a two-letter ISO-style code")
}

func Resolve(countryCode, language string) (Profile, error) {
	code, err := Normalize(countryCode)
	if err != nil { return Profile{}, err }
	lang := strings.ToLower(strings.TrimSpace(language))
	p := Profile{Code:code, Language:lang, Currency:"LOCAL", CurrencySymbol:"¤",
		Suppliers:[]string{"Local authorized distributor; request a current quote"},
		Standards:[]string{"Confirm applicable national and local standards before procurement or installation"},
		LegalFrameworks:[]string{"Applicable national law and local regulatory requirements"},
		LegalDisclaimer:"Awareness index only; not legal advice or a complete compliance determination."}
	switch code {
	case "KE":
		p.Name, p.Currency, p.CurrencySymbol, p.NominalACVoltage, p.FrequencyHz = "Kenya", "KES", "KSh", 240, "50"
		p.Suppliers = []string{"Kamukunji (verify seller and part provenance)", "Authorized local distributors; written quote required"}
		p.Standards = []string{"Kenya market and import requirements", "Mains supply nominal reference 240 V / 50 Hz; confirm site and device nameplate"}
		p.LegalFrameworks = []string{"Kenya Data Protection Act and applicable regulations", "Applicable KEBS requirements"}
	case "US":
		p.Name, p.Currency, p.CurrencySymbol, p.NominalACVoltage, p.FrequencyHz = "United States", "USD", "$", 120, "60"
		p.Suppliers = []string{"Mouser", "DigiKey", "Amazon US (seller and authenticity checks required)"}
		p.Standards = []string{"Applicable NEC/NFPA and state/local electrical rules", "Typical nominal reference 120 V / 60 Hz; verify site and equipment ratings"}
		p.LegalFrameworks = []string{"Applicable US federal, state and sector-specific privacy/security law", "Applicable FCC/UL/NFPA requirements as relevant"}
	case "DE":
		p.Name, p.Currency, p.CurrencySymbol, p.NominalACVoltage, p.FrequencyHz = "Germany", "EUR", "€", 230, "50"
		p.Suppliers = []string{"Conrad", "Reichelt", "Authorized EU distributors"}
		p.Standards = []string{"Applicable DIN/VDE and EU requirements; DIN rail only where appropriate to the reviewed design", "Typical nominal reference 230 V / 50 Hz; verify site and equipment ratings"}
		p.LegalFrameworks = []string{"GDPR", "Applicable EU and German product, electrical and privacy requirements"}
	case "CN":
		p.Name, p.Currency, p.CurrencySymbol, p.NominalACVoltage, p.FrequencyHz = "China", "CNY", "¥", 220, "50"
		p.Suppliers = []string{"LCSC", "Alibaba (seller, certification and counterfeit checks required)", "Authorized mainland distributors"}
		p.Standards = []string{"Applicable GB/GB-T and CCC requirements where applicable", "Typical nominal reference 220 V / 50 Hz; verify site and equipment ratings"}
		p.LegalFrameworks = []string{"Applicable China data, cybersecurity, product and import/export laws"}
	case "JP":
		p.Name, p.Currency, p.CurrencySymbol, p.NominalACVoltage, p.FrequencyHz = "Japan", "JPY", "¥", 100, "50/60 (regional)"
		p.Suppliers = []string{"Akizuki", "Mouser Japan", "Authorized Japanese distributors"}
		p.Standards = []string{"Applicable JIS/PSE and local utility requirements", "Typical nominal reference 100 V; frequency varies by region, verify site and equipment ratings"}
		p.LegalFrameworks = []string{"Applicable Japanese privacy, electrical and product safety requirements"}
	case "FR":
		p.Name, p.Currency, p.CurrencySymbol, p.NominalACVoltage, p.FrequencyHz = "France", "EUR", "€", 230, "50"
		p.Suppliers = []string{"Conrad", "Reichelt", "Authorized EU distributors"}
		p.Standards = []string{"Applicable NF/CENELEC and EU requirements", "Typical nominal reference 230 V / 50 Hz; verify site and equipment ratings"}
		p.LegalFrameworks = []string{"GDPR", "Applicable French and EU requirements"}
	case "ES":
		p.Name, p.Currency, p.CurrencySymbol, p.NominalACVoltage, p.FrequencyHz = "Spain", "EUR", "€", 230, "50"
		p.Suppliers = []string{"Authorized Spanish distributors", "Authorized EU distributors"}
		p.Standards = []string{"Applicable UNE/CENELEC and EU requirements", "Typical nominal reference 230 V / 50 Hz; verify site and equipment ratings"}
		p.LegalFrameworks = []string{"GDPR", "Applicable Spanish and EU requirements"}
	case "GB":
		p.Name, p.Currency, p.CurrencySymbol, p.NominalACVoltage, p.FrequencyHz = "United Kingdom", "GBP", "£", 230, "50"
		p.Suppliers = []string{"RS", "Farnell", "Authorized UK distributors"}
		p.Standards = []string{"Applicable BS 7671 and local regulations", "Typical nominal reference 230 V / 50 Hz; verify site and equipment ratings"}
		p.LegalFrameworks = []string{"UK GDPR and applicable UK data/product safety laws"}
	case "IN":
		p.Name, p.Currency, p.CurrencySymbol, p.NominalACVoltage, p.FrequencyHz = "India", "INR", "₹", 230, "50"
		p.Suppliers = []string{"Authorized Indian distributors", "Mouser India where available"}
		p.Standards = []string{"Applicable BIS and local electrical requirements", "Typical nominal reference 230 V / 50 Hz; verify site and equipment ratings"}
		p.LegalFrameworks = []string{"Applicable Indian data protection and product safety laws"}
	case "CA":
		p.Name, p.Currency, p.CurrencySymbol, p.NominalACVoltage, p.FrequencyHz = "Canada", "CAD", "C$", 120, "60"
		p.Suppliers = []string{"Mouser Canada", "DigiKey Canada", "Authorized Canadian distributors"}
		p.Standards = []string{"Applicable Canadian Electrical Code and provincial rules", "Typical nominal reference 120 V / 60 Hz; verify site and equipment ratings"}
		p.LegalFrameworks = []string{"Applicable Canadian federal/provincial privacy and product requirements"}
	case "AU":
		p.Name, p.Currency, p.CurrencySymbol, p.NominalACVoltage, p.FrequencyHz = "Australia", "AUD", "A$", 230, "50"
		p.Suppliers = []string{"RS Australia", "element14 Australia", "Authorized Australian distributors"}
		p.Standards = []string{"Applicable AS/NZS 3000 and local rules", "Typical nominal reference 230 V / 50 Hz; verify site and equipment ratings"}
		p.LegalFrameworks = []string{"Applicable Australian Privacy Act and product safety requirements"}
	default:
		p.Name = code
	}
	if lang == "" {
		switch code {case "DE":lang="de";case "CN":lang="zh";case "JP":lang="ja";case "FR":lang="fr";case "ES":lang="es";case "KE":lang="en";default:lang="en"}
	}
	switch lang {
	case "en", "de", "zh", "ja", "fr", "es", "sw":
		p.Language = lang
	default:
		p.Language = "en"
	}
	names := map[string]string{"en":"English","de":"German","zh":"Chinese","ja":"Japanese","fr":"French","es":"Spanish","sw":"Swahili"}
	p.LanguageName = names[p.Language]
	return p, nil
}
