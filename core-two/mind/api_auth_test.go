package mind

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestPublicMindHealthRemainsAvailableWithoutServiceToken(t *testing.T) {
	t.Setenv("MIND_ADMIN_TOKEN", "")
	req := httptest.NewRequest(http.MethodGet, "/v1/mind/health", nil)
	rec := httptest.NewRecorder()

	(&Service{}).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("health status = %d, body=%s", rec.Code, rec.Body.String())
	}
}

func TestMindReadRoutesRequireTheServerSideServiceToken(t *testing.T) {
	t.Setenv("MIND_ADMIN_TOKEN", "test-mind-secret")
	service := &Service{}

	unauthorized := httptest.NewRequest(http.MethodGet, "/v1/zero/status", nil)
	unauthorizedRec := httptest.NewRecorder()
	service.ServeHTTP(unauthorizedRec, unauthorized)
	if unauthorizedRec.Code != http.StatusUnauthorized {
		t.Fatalf("unauthenticated read status = %d, want %d", unauthorizedRec.Code, http.StatusUnauthorized)
	}

	authorized := httptest.NewRequest(http.MethodGet, "/v1/zero/status", nil)
	authorized.Header.Set("X-Mind-Token", "test-mind-secret")
	authorizedRec := httptest.NewRecorder()
	service.ServeHTTP(authorizedRec, authorized)
	if authorizedRec.Code != http.StatusOK {
		t.Fatalf("authenticated read status = %d, body=%s", authorizedRec.Code, authorizedRec.Body.String())
	}
}
