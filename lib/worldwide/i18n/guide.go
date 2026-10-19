package i18n

import (
	"fmt"
	"strings"

	"revela-worldwide.local/libs/country"
)

func labels(lang string) (title, intro, materials, steps, verify, safety string) {
	switch strings.ToLower(lang) {
	case "de":
		return "Weltweiter Hardware-Leitfaden", "Landesspezifische Hinweise sind Referenzwerte; Typenschild, Standort und aktuelle Normen haben Vorrang.", "Materialliste", "Arbeitsschritte", "Prüfung", "Sicherheit und Konformität"
	case "zh":
		return "全球硬件指南", "国家适配信息仅供参考；以设备铭牌、现场情况和现行标准为准。", "物料清单", "操作步骤", "验证", "安全与合规"
	case "ja":
		return "世界向けハードウェアガイド", "国別情報は参考値です。機器銘板、現場条件、現行規格を必ず確認してください。", "部品表", "作業手順", "検証", "安全と法令順守"
	case "fr":
		return "Guide matériel mondial", "Les adaptations nationales sont indicatives; vérifiez la plaque signalétique, le site et les normes en vigueur.", "Nomenclature", "Étapes techniques", "Vérification", "Sécurité et conformité"
	case "es":
		return "Guía de hardware mundial", "Las adaptaciones nacionales son orientativas; verifique la placa, el sitio y las normas vigentes.", "Lista de materiales", "Pasos técnicos", "Verificación", "Seguridad y cumplimiento"
	case "sw":
		return "Mwongozo wa vifaa wa kimataifa", "Marekebisho ya nchi ni ya marejeo; hakiki lebo ya kifaa, eneo na viwango vinavyotumika.", "Orodha ya vifaa", "Hatua za fundi", "Uhakiki", "Usalama na uzingatiaji"
	default:
		return "Worldwide hardware guide", "Country adaptations are reference guidance; equipment nameplates, site conditions and current standards take precedence.", "Bill of materials", "Technician steps", "Verification", "Safety and compliance"
	}
}

func WorldwideGuide(p country.Profile) string {
	title, intro, materials, steps, verify, safety := labels(p.Language)
	return fmt.Sprintf("\n\n---\n\n## %s — %s (%s)\n\n%s\n\n- **Country:** %s\n- **Language:** %s\n- **BOM currency:** %s\n- **Supplier directory:** %s\n- **Nominal AC reference:** %s\n- **Local adaptations:** %s\n- **Legal awareness:** %s\n\n### %s\n- Use authorized, locally available parts and confirm current availability, taxes, import rules and written supplier quotes.\n- Do not insert guessed prices or assume a supplier's stock, certification or authenticity.\n\n### %s\n1. Use a qualified local technician for mains or hazardous-energy work; isolate, lock out and verify de-energization first.\n2. Match every component to the exact datasheet, ratings, environmental conditions and reviewed schematic.\n3. Do not assume voltage, grounding, plug type, wiring colour, connector pinout, or DIN-rail suitability from country alone.\n4. Keep actuators disconnected during first power-up; test with a current-limited source and dummy load where appropriate.\n5. Verify emergency stop, protective earth, over-current protection, enclosure and safe failure behavior before acceptance.\n\n### %s\n- Record part-number evidence, test results, supplier quotes and source dates. Distinguish retrieved facts from assumptions.\n- Confirm all local certifications, permits and inspection needs with competent authorities or qualified professionals.\n\n### %s\n%s\n\n**Purposeful localization:** one reviewed tool specification can carry multiple country-specific BOMs and guides. This is a proposal scaffold, not electrical certification or legal advice.\n",
title,p.Name,p.Code,intro,p.Name,p.LanguageName,p.Currency,strings.Join(p.Suppliers,", "),voltage(p.NominalACVoltage,p.FrequencyHz),strings.Join(p.Standards,"; "),strings.Join(p.LegalFrameworks,"; "),materials,steps,verify,safety,p.LegalDisclaimer)
}

func voltage(v int, f string) string {
	if v <= 0 { return "Not specified; check local utility and equipment nameplate" }
	return fmt.Sprintf("~%d V / %s Hz (reference only; confirm the site)",v,f)
}
