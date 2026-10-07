package main

import (
	"fmt"
	"log/slog"
	"os"
)

type Config struct {
	Addr     string // host:port the gateway listens on
	CoreURL  string // base URL of the Python core service
	LogLevel slog.Level
}

const (
	defaultAddr    = ":8080"
	defaultCoreURL = "http://127.0.0.1:8000"
	defaultLevel   = "INFO"
)

func LoadConfig() (Config, error) {
	level, err := parseLevel(envOr("LOG_LEVEL", defaultLevel))
	if err != nil {
		return Config{}, err
	}
	return Config{
		Addr:     envOr("GATEWAY_ADDR", defaultAddr),
		CoreURL:  envOr("CORE_URL", defaultCoreURL),
		LogLevel: level,
	}, nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func parseLevel(name string) (slog.Level, error) {
	var level slog.Level
	if err := level.UnmarshalText([]byte(name)); err != nil {
		return 0, fmt.Errorf("unknown log level: %q", name)
	}
	return level, nil
}
