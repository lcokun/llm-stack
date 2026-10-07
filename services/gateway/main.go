package main

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
)

type healthResponse struct {
	Status string `json:"status"`
}

func main() {
	cfg, err := LoadConfig()
	if err != nil {
		fmt.Fprintln(os.Stderr, "config:", err)
		os.Exit(1)
	}
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: cfg.LogLevel})))
	if err := run(cfg); err != nil {
		fmt.Fprintln(os.Stderr, "gateway:", err)
		os.Exit(1)
	}
}

func run(cfg Config) error {
	return http.ListenAndServe(cfg.Addr, routes(newCoreProxy(cfg.CoreURL)))
}

func routes(core http.Handler) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", health)
	mux.Handle("/", core)
	return mux
}

func health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, healthResponse{Status: "ok"})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
