package candidate

import "testing"

func TestProposalFixture(t *testing.T) {
	if err := Validate(); err != nil { t.Fatal(err) }
}

func TestBestQuoteSkipsUnavailableAndInvalidQuotes(t *testing.T) {
	quotes := []Quote{
		{Supplier: "", UnitCost: 1, TransportCost: 1, InStock: true},
		{Supplier: "   ", UnitCost: 1, TransportCost: 1, InStock: true},
		{Supplier: "out-of-stock", UnitCost: 0, TransportCost: 0, InStock: false},
		{Supplier: "negative-unit", UnitCost: -1, TransportCost: 0, InStock: true},
		{Supplier: "negative-transport", UnitCost: 0, TransportCost: -1, InStock: true},
	}

	if got, ok := BestQuote(quotes); ok {
		t.Fatalf("BestQuote() = %+v, true; want no eligible quote", got)
	}
}

func TestBestQuoteAvoidsInt64Overflow(t *testing.T) {
	const maxInt64 = int64(1<<63 - 1)

	quotes := []Quote{
		{
			Supplier:      "overflowing-sum",
			UnitCost:      maxInt64,
			TransportCost: maxInt64,
			InStock:       true,
		},
		{
			Supplier:      "lower-total",
			UnitCost:      maxInt64,
			TransportCost: 0,
			InStock:       true,
		},
	}

	best, ok := BestQuote(quotes)
	if !ok || best.Supplier != "lower-total" {
		t.Fatalf("BestQuote() = %+v, %v; want lower-total", best, ok)
	}
}

func TestRankQuotesOrdersAndDoesNotMutateInput(t *testing.T) {
	quotes := []Quote{
		{Supplier: "Zulu", UnitCost: 4, TransportCost: 6, InStock: true},
		{Supplier: "beta", UnitCost: 5, TransportCost: 5, InStock: true},
		{Supplier: "Alpha", UnitCost: 3, TransportCost: 7, InStock: true},
	}

	original := append([]Quote(nil), quotes...)
	ranked := RankQuotes(quotes)

	if len(ranked) != 3 {
		t.Fatalf("RankQuotes() returned %d quotes, want 3", len(ranked))
	}

	if ranked[0].Quote.Supplier != "Alpha" {
		t.Fatalf(
			"first ranked supplier = %q, want Alpha",
			ranked[0].Quote.Supplier,
		)
	}

	for i := range quotes {
		if quotes[i] != original[i] {
			t.Fatal("RankQuotes modified its input slice")
		}
	}
}

func TestTotalCostSupportsMaximumInt64Components(t *testing.T) {
	const maxInt64 = int64(1<<63 - 1)
	const want = uint64(1<<64 - 2)

	got, ok := TotalCost(Quote{
		UnitCost:      maxInt64,
		TransportCost: maxInt64,
	})

	if !ok || got != want {
		t.Fatalf("TotalCost() = %d, %v; want %d, true", got, ok, want)
	}
}
