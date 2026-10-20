package genesis

import (
	"context"
	"errors"
	"testing"
)

type countingResearcher struct {
	calls *int
}

func (r countingResearcher) Research(context.Context, string) (ResearchEvidence, error) {
	(*r.calls)++
	return ResearchEvidence{Mode: ResearchModeOffline}, nil
}

type countingModelAdapter struct {
	calls *int
}

func (m countingModelAdapter) Suggest(_ context.Context, _ string, _ ResearchEvidence, fallback ToolSpec) (ToolSpec, error) {
	(*m.calls)++
	return fallback, nil
}

func TestGuardianBlockedDemandNeverReachesResearchOrGeneration(t *testing.T) {
	engine := newTestEngine(t)
	researchCalls := 0
	modelCalls := 0
	engine.SetResearcher(countingResearcher{calls: &researchCalls})
	engine.SetModel(countingModelAdapter{calls: &modelCalls})

	_, err := engine.Invent(context.Background(), "weapon")
	if !errors.Is(err, ErrBlocked) {
		t.Fatalf("expected Guardian to block before research/generation; got %v", err)
	}
	if researchCalls != 0 {
		t.Fatalf("Guardian-blocked demand reached research %d times", researchCalls)
	}
	if modelCalls != 0 {
		t.Fatalf("Guardian-blocked demand reached model generation %d times", modelCalls)
	}
}
