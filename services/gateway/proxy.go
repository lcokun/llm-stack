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
}

func newCoreProxy(target *url.URL) *httputil.ReverseProxy {
	return &httputil.ReverseProxy{
		Rewrite: func(r *httputil.ProxyRequest) {
			r.SetURL(target)
			r.SetXForwarded()
		},
		ErrorHandler: coreUnavailable,
	}
}

func coreUnavailable(w http.ResponseWriter, r *http.Request, err error) {
	if errors.Is(err, context.Canceled) {
		return
	}
	slog.Error("core unreachable", "path", r.URL.Path, "err", err)
	writeProblem(w, http.StatusBadGateway, "Core unavailable")
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
