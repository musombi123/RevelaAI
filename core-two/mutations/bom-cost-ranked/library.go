// Package candidate implements deterministic BOM quote validation and ranking.
package candidate

import (
	"errors"
	"sort"
	"strings"
)

type Quote struct {
	Supplier string
	UnitCost int64
	TransportCost int64
	InStock bool
}

type RankedQuote struct {
	Quote Quote
	Total uint64
}

// TotalCost returns the exact non-negative total without overflowing int64.
func TotalCost(q Quote) (uint64, bool) {
	if q.UnitCost < 0 || q.TransportCost < 0 {
		return 0, false
	}
	return uint64(q.UnitCost) + uint64(q.TransportCost), true
}

func eligible(q Quote) bool {
	if strings.TrimSpace(q.Supplier) == "" || !q.InStock {
		return false
	}
	_, ok := TotalCost(q)
	return ok
}

// BestQuote selects the lowest-cost eligible supplier with deterministic ties.
func BestQuote(quotes []Quote) (Quote, bool) {
	ranked := RankQuotes(quotes)
	if len(ranked) == 0 {
		return Quote{}, false
	}
	return ranked[0].Quote, true
}

// RankQuotes returns a new sorted slice; it never mutates the caller's input.
func RankQuotes(quotes []Quote) []RankedQuote {
	ranked := make([]RankedQuote, 0, len(quotes))
	for _, q := range quotes {
		if !eligible(q) {
			continue
		}
		total, _ := TotalCost(q)
		ranked = append(ranked, RankedQuote{Quote: q, Total: total})
	}
	sort.SliceStable(ranked, func(i, j int) bool {
		if ranked[i].Total != ranked[j].Total {
			return ranked[i].Total < ranked[j].Total
		}
		left, right := strings.ToLower(strings.TrimSpace(ranked[i].Quote.Supplier)),
			strings.ToLower(strings.TrimSpace(ranked[j].Quote.Supplier))
		if left != right {
			return left < right
		}
		return ranked[i].Quote.Supplier < ranked[j].Quote.Supplier
	})
	return ranked
}

// Validate checks the invariants required by this deterministic ranking library.
func Validate() error {
	const maxInt64 = int64(1<<63 - 1)
	total, ok := TotalCost(Quote{UnitCost: maxInt64, TransportCost: maxInt64})
	if !ok || total != uint64(1<<64-2) {
		return errors.New("BOM cost overflow invariant failed")
	}
	best, found := BestQuote([]Quote{
		{Supplier: "valid", UnitCost: 1, TransportCost: 1, InStock: true},
		{Supplier: "unavailable", UnitCost: 0, TransportCost: 0, InStock: false},
	})
	if !found || best.Supplier != "valid" {
		return errors.New("BOM quote eligibility invariant failed")
	}
	return nil
}
