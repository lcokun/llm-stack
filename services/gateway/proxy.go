package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
)

const problemContentType = "application/problem+json"

type problem struct {
	Type   string `json:"type"`
	Title  string `json:"title"`
	Status int    `json:"status"`
	Detail string `json:"detail,omitempty"`
}

func newCoreProxy(target *url.URL) *httputil.ReverseProxy {
	return &httputil.ReverseProxy{
		Rewrite: func(r *httputil.ProxyRequest) {
			r.SetURL(target)
			r.SetXForwarded()
		},
		ErrorHandler: writeCoreError,
	}
}

func writeCoreError(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, context.Canceled):
		// The client left; there is nobody to answer.
	case errors.Is(err, errConversationNotFound):
		writeProblem(w, http.StatusNotFound, "Conversation not found")
	case errors.Is(err, context.DeadlineExceeded):
		slog.Error("core timed out", "path", r.URL.Path, "err", err)
		writeProblem(w, http.StatusGatewayTimeout, "Core timed out")
	default:
		slog.Error("core request failed", "path", r.URL.Path, "err", err)
		writeProblem(w, http.StatusBadGateway, "Core unavailable")
	}
}

func writeProblem(w http.ResponseWriter, status int, title string) {
	w.Header().Set("Content-Type", problemContentType)
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(problem{
		Type:   "about:blank",
		Title:  title,
		Status: status,
	})
}

func writeValidationProblem(w http.ResponseWriter, detail string) {
	w.Header().Set("Content-Type", problemContentType)
	w.WriteHeader(http.StatusUnprocessableEntity)
	_ = json.NewEncoder(w).Encode(problem{
		Type:   "about:blank",
		Title:  "Request validation failed",
		Status: http.StatusUnprocessableEntity,
		Detail: detail,
	})
}
