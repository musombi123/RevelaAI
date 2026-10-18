// Package radar is a deterministic, offline comparison engine; it never fetches remote data.
package radar

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
)

type Evidence struct {
	Name string `json:"name"`
	Version string `json:"version"`
	Benchmark float64 `json:"benchmark"`
	Source string `json:"source"`
	EvidenceID string `json:"evidence_id"`
}
type Comparison struct {
	Current Evidence `json:"current"`
	Candidate Evidence `json:"candidate"`
	VersionOrder int `json:"version_order"`
	ImprovementRatio float64 `json:"improvement_ratio"`
	ExceedsThirtyPercent bool `json:"exceeds_thirty_percent"`
	Recommendation string `json:"recommendation"`
	NetworkUsed bool `json:"network_used"`
	HumanApprovalRequired bool `json:"human_approval_required"`
}
func Compare(current,candidate Evidence)(Comparison,error){
	if current.Benchmark<=0||candidate.Benchmark<0{return Comparison{},errors.New("benchmark scores must be non-negative and current benchmark must be positive")};order,err:=CompareSemver(candidate.Version,current.Version);if err!=nil{return Comparison{},err};ratio:=candidate.Benchmark/current.Benchmark;improved:=ratio>1.30;rec:="no_upgrade_proposed"
	if order>0&&improved{rec="upgrade_candidate_for_human_review"}else if order<=0&&improved{rec="benchmark_improved_but_version_not_newer_review_metadata"}else if order>0{rec="newer_version_without_thirty_percent_benchmark_gain"}
	return Comparison{Current:current,Candidate:candidate,VersionOrder:order,ImprovementRatio:ratio,ExceedsThirtyPercent:improved,Recommendation:rec,NetworkUsed:false,HumanApprovalRequired:true},nil
}
func CompareSemver(a,b string)(int,error){pa,ea:=parse(a);pb,eb:=parse(b);if ea!=nil||eb!=nil{return 0,errors.New("versions must use strict major.minor.patch semver (optional v prefix and prerelease ignored in this MVP)")};for i:=0;i<3;i++{if pa[i]<pb[i]{return -1,nil};if pa[i]>pb[i]{return 1,nil}};return 0,nil}
func parse(s string)([3]int,error){var p [3]int;s=strings.TrimPrefix(strings.TrimSpace(s),"v");s=strings.SplitN(s,"-",2)[0];s=strings.SplitN(s,"+",2)[0];v:=strings.Split(s,".");if len(v)!=3{return p,fmt.Errorf("invalid semver")};for i:=range p{n,e:=strconv.Atoi(v[i]);if e!=nil||n<0||strings.HasPrefix(v[i],"+"){return p,fmt.Errorf("invalid semver")};p[i]=n};return p,nil}
