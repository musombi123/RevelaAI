package graph

import (
	"sort"
	"strings"
)

type Evidence struct {
	ID string `json:"id"`
	Country string `json:"country"`
	Success bool `json:"success"`
	Verified bool `json:"verified"`
	Quality float64 `json:"quality"`
	Note string `json:"note,omitempty"`
}
type Rank struct { ID string `json:"id"`; Score float64 `json:"score"`; EvidenceCount int `json:"evidence_count"`; Countries []string `json:"countries"` }
func RankWorldwide(items []Evidence) []Rank {
	stats:=map[string]*Rank{}; countries:=map[string]map[string]bool{}; seen:=map[string]map[string]bool{}
	for _,e:=range items {
		id:=strings.TrimSpace(e.ID); country:=strings.ToUpper(strings.TrimSpace(e.Country)); if id=="" {continue}
		if stats[id]==nil {stats[id]=&Rank{ID:id};countries[id]=map[string]bool{};seen[id]=map[string]bool{}}
		if e.Verified {key:=country+"|"+id;if !seen[id][key] {stats[id].EvidenceCount++;seen[id][key]=true}}
		if country!="" {countries[id][country]=true}
		if e.Success {stats[id].Score+=1}
		if e.Verified {stats[id].Score+=2}
		if e.Quality>0 {q:=e.Quality;if q>1{q=1};stats[id].Score+=q}
	}
	out:=make([]Rank,0,len(stats));for id,s:=range stats {for c:=range countries[id]{s.Countries=append(s.Countries,c)};sort.Strings(s.Countries);if len(s.Countries)>1{s.Score+=float64(len(s.Countries)-1)*0.25};out=append(out,*s)}
	sort.Slice(out,func(i,j int)bool{if out[i].Score==out[j].Score{return out[i].ID<out[j].ID};return out[i].Score>out[j].Score});return out
}
