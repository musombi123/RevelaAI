package endpoint
import("net/http";"strings";"revela-worldwide.local/libs/country")
// ResolveWorldContext accepts ?country=&lang=, with KE as the legacy default.
func ResolveWorldContext(r *http.Request,bodyCountry,bodyLanguage string)(country.Profile,error){code:=strings.TrimSpace(r.URL.Query().Get("country"));if code==""{code=strings.TrimSpace(bodyCountry)};if code==""{code="KE"};lang:=strings.TrimSpace(r.URL.Query().Get("lang"));if lang==""{lang=strings.TrimSpace(bodyLanguage)};return country.Resolve(code,lang)}
