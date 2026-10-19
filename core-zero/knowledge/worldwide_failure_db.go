package knowledge
import("embed";"encoding/json";"errors")
//go:embed worldwide_failure_db/patterns.json
var worldwideFiles embed.FS
type FailurePattern struct{ID string `json:"id"`;Category string `json:"category"`;MatchAny []string `json:"match_any"`;Recommendation string `json:"recommendation"`;Risk string `json:"risk"`}
type failureDB struct{Patterns []FailurePattern `json:"patterns"`}
func WorldwideFailurePatterns()([]FailurePattern,error){raw,err:=worldwideFiles.ReadFile("worldwide_failure_db/patterns.json");if err!=nil{return nil,err};var db failureDB;if len(raw)==0||json.Unmarshal(raw,&db)!=nil||len(db.Patterns)==0{return nil,errors.New("worldwide failure database invalid")};return db.Patterns,nil}
