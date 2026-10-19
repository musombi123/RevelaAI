package bom
import("revela-worldwide.local/libs/bom";"revela-worldwide.local/libs/country")
type GlobalBOM = bom.BOMAdapter
func ForCountry(countryCode,language string)(GlobalBOM,error){p,err:=country.Resolve(countryCode,language);if err!=nil{return GlobalBOM{},err};return bom.ForCountry(p),nil}
