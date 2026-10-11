package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

const (
	knownID       = "01a12b22-5a11-7232-8321-cc276ac8adfe"
	shortDeadline = 50 * time.Millisecond
)

func gatewayWithCore(t *testing.T, core http.HandlerFunc) http.Handler {
	t.Helper()
	srv := httptest.NewServer(core)
	t.Cleanup(srv.Close)
	target := mustParseURL(t, srv.URL)
	return routes(newCoreProxy(target), newCoreClient(target))
}

func TestGetConversationReturnsWhatCoreHas(t *testing.T) {
	seenRequestID := make(chan string, 1)
	gw := gatewayWithCore(t, func(w http.ResponseWriter, r *http.Request) {
		seenRequestID <- r.Header.Get(requestIDHeader)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"` + knownID + `","title":null,"created_at":"2026-10-11T13:23:54.000481Z","messages":[]}`))
	})
	req := httptest.NewRequest(http.MethodGet, "/conversations/"+knownID, nil)
	req.Header.Set(requestIDHeader, "abc-123")
	rec := httptest.NewRecorder()

	gw.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
	var got conversation
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if got.ID.String() != knownID {
		t.Errorf("id = %s, want %s", got.ID, knownID)
	}
	if !strings.Contains(rec.Body.String(), `"messages":[]`) {
		t.Errorf("messages must be an empty array, body was %s", rec.Body.String())
	}
	if id := <-seenRequestID; id != "abc-123" {
		t.Errorf("request id at core = %q, want %q", id, "abc-123")
	}
}

func TestGetConversationRejectsAnInvalidID(t *testing.T) {
	gw := gatewayWithCore(t, func(w http.ResponseWriter, r *http.Request) {
		t.Error("an invalid id reached core")
	})
	rec := httptest.NewRecorder()

	gw.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/conversations/not-a-uuid", nil))

	if rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusUnprocessableEntity)
	}
}

func TestGetConversationMapsCoreStatuses(t *testing.T) {
	tests := []struct {
		name       string
		coreStatus int
		want       int
	}{
		{"missing conversation stays 404", http.StatusNotFound, http.StatusNotFound},
		{"core crash becomes 502", http.StatusInternalServerError, http.StatusBadGateway},
		{"core rejecting validated input becomes 502", http.StatusUnprocessableEntity, http.StatusBadGateway},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gw := gatewayWithCore(t, func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tt.coreStatus)
			})
			rec := httptest.NewRecorder()

			gw.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/conversations/"+knownID, nil))

			if rec.Code != tt.want {
				t.Errorf("status = %d, want %d", rec.Code, tt.want)
			}
			if got := rec.Header().Get("Content-Type"); got != problemContentType {
				t.Errorf("content type = %q, want %q", got, problemContentType)
			}
		})
	}
}

func TestSlowCoreIsA504(t *testing.T) {
	gw := gatewayWithCore(t, func(w http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
	})
	ctx, cancel := context.WithTimeout(context.Background(), shortDeadline)
	defer cancel()
	req := httptest.NewRequest(http.MethodGet, "/conversations/"+knownID, nil).WithContext(ctx)
	rec := httptest.NewRecorder()

	gw.ServeHTTP(rec, req)

	if rec.Code != http.StatusGatewayTimeout {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusGatewayTimeout)
	}
}
