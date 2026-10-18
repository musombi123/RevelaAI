package mind

import (
 "encoding/json"
 "os"
 "path/filepath"
 "testing"
)

func TestHumanFeedbackInfluencesRankingButCannotBypassGates(t *testing.T) {
 root,s:=newTestRepository(t)
 fixtures:=[]struct{version,tool,mutation,outcome,note,ref string}{
  {"v0.1.0","offline_vault_a","graph-indexed","reverted","Regression observed during owner review",""},
  {"v0.1.1","offline_vault_b","bom-cost-ranked","merged","Passed owner review with integration evidence","commit:abc123"},
 }
 for _,item:=range fixtures{
  folder:=filepath.Join(root,"core-two","evolutions",item.version);if err:=os.MkdirAll(folder,0700);err!=nil{t.Fatal(err)}
  evidence:=map[string]any{"version":item.version,"tool_name":item.tool,"selected_mutation":item.mutation}
  raw,_:=json.Marshal(evidence);if err:=os.WriteFile(filepath.Join(folder,"evidence.json"),raw,0600);err!=nil{t.Fatal(err)}
  _,err:=s.RecordFeedback(LearningFeedback{Version:item.version,ToolName:item.tool,Mutation:item.mutation,Outcome:item.outcome,Note:item.note,EvidenceRef:item.ref})
  if err!=nil{t.Fatal(err)}
 }
 summary,err:=s.learningSummary();if err!=nil{t.Fatal(err)}
 if summary.AutomaticMerge||summary.FeedbackRecords!=2{t.Fatalf("invalid learning state: %+v",summary)}
 scores:=s.learningScores();if scores["graph-indexed"]!=-5||scores["bom-cost-ranked"]!=3{t.Fatalf("wrong human feedback scores: %+v",scores)}
 candidates:=[]CandidateEvaluation{
  {ID:"graph-indexed",ImprovementPct:10,Passed:true},
  {ID:"bom-cost-ranked",ImprovementPct:90,Passed:true},
  {ID:"rvx-aead-envelope",ImprovementPct:1000,Passed:false},
 }
 selected,_,_,ok:=s.selectCandidateWithLearning("improve graph traversal",candidates)
 if !ok||selected.ID!="bom-cost-ranked"{t.Fatalf("historical review should affect ranking among passing candidates: %+v",selected)}
 if selected.ID=="rvx-aead-envelope"{t.Fatal("learning score must never select an unqualified candidate")}
}

func TestFeedbackMustMatchExistingEvolutionAndRejectDuplicateOutcome(t *testing.T) {
 root,s:=newTestRepository(t)
 folder:=filepath.Join(root,"core-two","evolutions","v0.1.0");if err:=os.MkdirAll(folder,0700);err!=nil{t.Fatal(err)}
 evidence:=map[string]any{"version":"v0.1.0","tool_name":"offline_vault_fixture","selected_mutation":"graph-indexed"};raw,_:=json.Marshal(evidence);if err:=os.WriteFile(filepath.Join(folder,"evidence.json"),raw,0600);err!=nil{t.Fatal(err)}
 f:=LearningFeedback{Version:"v0.1.0",ToolName:"offline_vault_fixture",Mutation:"graph-indexed",Outcome:"rejected",Note:"Rejected by reviewer because of regression"}
 if _,err:=s.RecordFeedback(f);err!=nil{t.Fatal(err)}
 if _,err:=s.RecordFeedback(f);err==nil{t.Fatal("duplicate feedback must be rejected")}
 wrong:=f;wrong.Mutation="bom-cost-ranked";wrong.Outcome="needs_work"
 if _,err:=s.RecordFeedback(wrong);err==nil{t.Fatal("feedback not matching the selected mutation must be rejected")}
}
