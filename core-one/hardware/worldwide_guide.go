package hardware
import("revela-worldwide.local/libs/country";"revela-worldwide.local/libs/i18n")
func BuildWorldwideGuide(countryCode,language string)(string,country.Profile,error){p,err:=country.Resolve(countryCode,language);if err!=nil{return "",country.Profile{},err};return i18n.WorldwideGuide(p),p,nil}
