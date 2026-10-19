package mind

import (
 "bufio"
 "encoding/json"
 "errors"
 "fmt"
 "os"
 "path/filepath"
 "sort"
 "strings"
 "time"
)

type LearningFeedback struct {
 Version string "json:\"version\""
 ToolName string "json:\"tool_name\""
 Mutation string "json:\"mutation\""
 Outcome string "json:\"outcome\""
 Note string "json:\"note\""
 EvidenceRef string "json:\"evidence_ref,omitempty\""
 RecordedAt time.Time "json:\"recorded_at\""
}
type mutationLearning struct {
 Mutation string "json:\"mutation\""
 Merged int "json:\"merged\""
 Rejected int "json:\"rejected\""
 Reverted int "json:\"reverted\""
 NeedsWork int "json:\"needs_work\""
 Score float64 "json:\"score\""
 FeedbackCount int "json:\"feedback_count\""
}
type LearningSummary struct {
 Status string "json:\"status\""
 FeedbackRecords int "json:\"feedback_records\""
 Mutations []mutationLearning "json:\"mutations\""
 RankingNote string "json:\"ranking_note\""
 AutomaticMerge bool "json:\"automatic_merge\""
}

func(s *Service)RecordFeedback(feedback LearningFeedback)(LearningSummary,error){
 s.learningMu.Lock();defer s.learningMu.Unlock()
 feedback.Version=strings.TrimSpace(feedback.Version);feedback.ToolName=strings.TrimSpace(feedback.ToolName);feedback.Mutation=strings.TrimSpace(feedback.Mutation);feedback.Outcome=strings.ToLower(strings.TrimSpace(feedback.Outcome));feedback.Note=strings.TrimSpace(feedback.Note);feedback.EvidenceRef=strings.TrimSpace(feedback.EvidenceRef)
 if !validName(feedback.ToolName)||!validName(feedback.Mutation)||!validEvolutionVersion(feedback.Version){return LearningSummary{},errors.New("version, tool_name, and mutation must identify an existing staged evolution")}
 if feedback.Outcome!="merged"&&feedback.Outcome!="rejected"&&feedback.Outcome!="reverted"&&feedback.Outcome!="needs_work"{return LearningSummary{},errors.New("outcome must be merged, rejected, reverted, or needs_work")}
 if len(feedback.Note)<8||len(feedback.Note)>1200{return LearningSummary{},errors.New("feedback note must be 8–1200 characters")}
 if feedback.Outcome=="merged"&&feedback.EvidenceRef==""{return LearningSummary{},errors.New("merged feedback requires an evidence_ref for the human-reviewed merge record")}
 if len(feedback.EvidenceRef)>500{return LearningSummary{},errors.New("evidence_ref must not exceed 500 characters")}
 evidencePath:=filepath.Join(s.CoreRoot,"evolutions",feedback.Version,"evidence.json")
 raw,err:=os.ReadFile(evidencePath);if err!=nil{return LearningSummary{},errors.New("evolution version does not exist under core-two/evolutions")}
 var evidence map[string]any;if json.Unmarshal(raw,&evidence)!=nil{return LearningSummary{},errors.New("existing evolution evidence is invalid")}
 if evidence["tool_name"]!=feedback.ToolName||evidence["selected_mutation"]!=feedback.Mutation{return LearningSummary{},errors.New("feedback does not match this evolution's tool and selected mutation")}
 records,err:=s.readLearningRecords();if err!=nil{return LearningSummary{},err}
 for i:=len(records)-1;i>=0;i--{if records[i].Version!=feedback.Version{continue};if records[i].Outcome==feedback.Outcome{return LearningSummary{},errors.New("duplicate feedback outcome for this evolution is rejected")};if records[i].Outcome=="reverted"{return LearningSummary{},errors.New("a reverted evolution is terminal; submit a new evolution version for another review")};if records[i].Outcome=="merged"&&feedback.Outcome!="reverted"&&feedback.Outcome!="needs_work"{return LearningSummary{},errors.New("after merged feedback, only reverted or needs_work may update this evolution")};break}
 feedback.RecordedAt=time.Now().UTC()
 path:=filepath.Join(s.CoreRoot,"state","learning.jsonl")
 if err:=appendJSONLine(path,feedback);err!=nil{return LearningSummary{},err}
 return s.learningSummary()
}
func(s *Service)readLearningRecords()([]LearningFeedback,error){
 path:=filepath.Join(s.CoreRoot,"state","learning.jsonl")
 f,err:=os.Open(path);if os.IsNotExist(err){return []LearningFeedback{},nil};if err!=nil{return nil,err};defer f.Close()
 out:=[]LearningFeedback{};scanner:=bufio.NewScanner(f);scanner.Buffer(make([]byte,4096),1<<20)
 for scanner.Scan(){var item LearningFeedback;if json.Unmarshal(scanner.Bytes(),&item)==nil{out=append(out,item)}}
 if err:=scanner.Err();err!=nil{return nil,err};return out,nil
}
func(s *Service)learningSummary()(LearningSummary,error){
 records,err:=s.readLearningRecords();if err!=nil{return LearningSummary{},err}
 latest:=map[string]LearningFeedback{};for _,item:=range records{latest[item.Version]=item}
 stats:=map[string]*mutationLearning{}
 for _,item:=range latest{v:=stats[item.Mutation];if v==nil{v=&mutationLearning{Mutation:item.Mutation};stats[item.Mutation]=v};switch item.Outcome{case "merged":v.Merged++;case "rejected":v.Rejected++;case "reverted":v.Reverted++;case "needs_work":v.NeedsWork++}}
 out:=make([]mutationLearning,0,len(stats));for _,v:=range stats{v.FeedbackCount=v.Merged+v.Rejected+v.Reverted+v.NeedsWork;v.Score=float64(v.Merged*3-v.Rejected*2-v.Reverted*5-v.NeedsWork);out=append(out,*v)};sort.Slice(out,func(i,j int)bool{if out[i].Score==out[j].Score{return out[i].Mutation<out[j].Mutation};return out[i].Score>out[j].Score})
 status:="learning_from_human_feedback";if len(latest)==0{status="awaiting_human_feedback"}
 return LearningSummary{Status:status,FeedbackRecords:len(records),Mutations:out,RankingNote:"Scores use the latest human decision for each evolution: merged +3, rejected -2, reverted -5, needs_work -1. Scores are ranking hints only; they cannot bypass Guardian or candidate tests.",AutomaticMerge:false},nil
}
func(s *Service)learningScores()map[string]float64{summary,err:=s.learningSummary();if err!=nil{return map[string]float64{}};out:=map[string]float64{};for _,item:=range summary.Mutations{score:=item.Score;if score>15{score=15};if score< -25{score= -25};out[item.Mutation]=score};return out}
func(s *Service)selectCandidateWithLearning(objective string,evals []CandidateEvaluation)(CandidateEvaluation,string,map[string]float64,bool){
 fallback,ok:=selectCandidate(objective,evals);if !ok{return CandidateEvaluation{},"",map[string]float64{},false}
 scores:=s.learningScores();lower:=strings.ToLower(objective);best:=fallback;bestScore:=-1e9;preferred:=fallback.ID
 for _,item:=range evals{if !item.Passed{continue};score:=item.ImprovementPct;if score>200{score=200};if item.ID==preferred{score+=20};score+=scores[item.ID]*100
  if strings.Contains(lower,"cost")&&(item.ID=="bom-cost-ranked"||item.ID=="canonical-spec-cache"){score+=20}
  if strings.Contains(lower,"rvx")&&item.ID=="rvx-aead-envelope"{score+=20}
  if score>bestScore{best,bestScore=item,score}
 }
 return best,"passing candidates ranked by benchmark evidence, objective fit, and bounded human-feedback history",scores,true
}
func validEvolutionVersion(version string)bool{if !strings.HasPrefix(version,"v0.1."){return false};part:=strings.TrimPrefix(version,"v0.1.");if part==""{return false};for _,c:=range part{if c<'0'||c>'9'{return false}};return true}
func appendJSONLine(path string,v any)error{if err:=os.MkdirAll(filepath.Dir(path),0o700);err!=nil{return err};raw,err:=json.Marshal(v);if err!=nil{return err};f,err:=os.OpenFile(path,os.O_CREATE|os.O_APPEND|os.O_WRONLY,0o600);if err!=nil{return err};defer f.Close();if _,err=f.Write(append(raw,'\n'));err!=nil{return fmt.Errorf("append learning record: %w",err)};return nil}
