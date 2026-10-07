package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
)

func TestHealthzIsAnsweredByTheGateway(t *testing.T) {
	core := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("healthz reached core")
	})
	rec := httptest.NewRecorder()

	routes(core).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/healthz", nil))

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
}

func TestUnmatchedRoutesReachCore(t *testing.T) {
	core := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Seen-Request-Id", r.Header.Get("X-Request-Id"))
		w.WriteHeader(http.StatusCreated)
		_, _ = io.WriteString(w, r.Method+" "+r.URL.Path)
	}))
	defer core.Close()

	req := httptest.NewRequest(http.MethodPost, "/conversations", nil)
	req.Header.Set("X-Request-Id", "abc-123")
	rec := httptest.NewRecorder()

	routes(newCoreProxy(mustParseURL(t, core.URL))).ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusCreated)
	}
	if got := rec.Body.String(); got != "POST /conversations" {
		t.Errorf("core saw %q, want %q", got, "POST /conversations")
	}
	if got := rec.Header().Get("X-Seen-Request-Id"); got != "abc-123" {
		t.Errorf("request id at core = %q, want %q", got, "abc-123")
	}
}

func TestUnreachableCoreIsA502Problem(t *testing.T) {
	core := httptest.NewServer(http.NotFoundHandler())
	target := mustParseURL(t, core.URL)
	core.Close()

	rec := httptest.NewRecorder()
	routes(newCoreProxy(target)).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/conversations/x", nil))

	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusBadGateway)
	}
	if got := rec.Header().Get("Content-Type"); got != problemContentType {
		t.Errorf("content type = %q, want %q", got, problemContentType)
	}
}

func mustParseURL(t *testing.T, raw string) *url.URL {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	return u
}
