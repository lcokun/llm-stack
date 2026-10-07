package main

import (
	"fmt"
	"log/slog"
	"net/url"
	"os"
)

type Config struct {
	Addr     string   // host:port the gateway listens on
	CoreURL  *url.URL // base URL of the Python core service
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
	coreURL, err := parseCoreURL(envOr("CORE_URL", defaultCoreURL))
	if err != nil {
		return Config{}, err
	}
	return Config{
		Addr:     envOr("GATEWAY_ADDR", defaultAddr),
		CoreURL:  coreURL,
		LogLevel: level,
	}, nil
}

func parseCoreURL(raw string) (*url.URL, error) {
	u, err := url.Parse(raw)
	if err != nil {
		return nil, fmt.Errorf("invalid CORE_URL %q: %w", raw, err)
	}
	if (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return nil, fmt.Errorf("CORE_URL %q must be an absolute http(s) URL", raw)
	}
	return u, nil
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
