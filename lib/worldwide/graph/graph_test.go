package graph

import "testing"
func TestRankUsesVerifiedCrossCountryEvidence(t *testing.T){
	out:=RankWorldwide([]Evidence{{ID:"safe",Country:"KE",Success:true,Verified:true,Quality:0.8},{ID:"safe",Country:"DE",Success:true,Verified:true,Quality:0.9},{ID:"fast",Country:"US",Success:true,Verified:false,Quality:0.2}})
	if len(out)!=2||out[0].ID!="safe"||len(out[0].Countries)!=2{t.Fatalf("unexpected worldwide ranking: %+v",out)}
}
