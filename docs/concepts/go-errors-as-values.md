# Errors are values (Go)

**Short version:** Go has no exceptions. A function that can fail returns an `error` as
its last result, and the caller checks it on the next line. Every failure path in the
gateway is therefore visible in the code that handles it, and an error nobody checks is
a bug you can point at.

## The shape

```go
level, err := parseLevel(envOr("LOG_LEVEL", defaultLevel))
if err != nil {
    return Config{}, err
}
```

`parseLevel` returns two values. If `err` is non-nil the other value is meaningless, and
`LoadConfig` hands the error up to its own caller. Python would raise inside
`parseLevel` and let the exception travel until some `except` caught it, possibly many
frames away. In Go, every frame the error passes through has a line saying so.

## Fail with the zero value

On the error path `LoadConfig` returns `Config{}`, not a half-filled config. Every Go type
has a zero value (`""`, `0`, `nil`, a struct of zeros), and returning it on failure means
a caller that ignores the error gets something obviously empty instead of something that
looks plausible.

## Only `main` exits

`run` returns errors and `main` is the only function that calls `os.Exit`. `os.Exit` ends
the process immediately and skips every `defer`, so anything that closes a pool or drains
connections has to live below `main` and return normally. This also makes `run` testable,
since a test can call it and inspect the error.

## A dropped error is silent

The first version of `main` called `http.ListenAndServe(cfg.Addr, routes())` and ignored
its return value. `ListenAndServe` only returns when the server fails to start, so a taken
port made the gateway exit with status 0 and no message. Go does not force you to use an
error result from a call, so nothing stopped it. Go does refuse an unused *variable*,
which is how `err declared and not used` caught a deleted check in `main` later.

`writeJSON` drops one on purpose, with `_ = json.NewEncoder(w).Encode(body)`. By the time
encoding fails the status line has already gone out, so there is no response left to
change. The `_` records that the drop was a decision; it gets logged once there is a
logger.

## Wrapping

`fmt.Errorf` builds a new error. With `%w` it wraps the original, so callers can still
test for it with `errors.Is` and `errors.As`; with `%v` or `%q` it only copies the text.
`parseLevel` discards the library's error and writes its own message
(`unknown log level "nonsense"`), because nothing upstream needs to inspect the original
and the user needs to see which value was rejected. `%q` quotes it, so an empty value
reads as `""` instead of looking truncated.

## Why this matters here

v1 returned bare 500s from `KeyError`s on response shapes nobody had checked. The failure
was always possible; the code just never showed where. Go's style makes every such spot
visible, and the error mapping in [ADR 0009](../decisions/0009-core-keeps-an-internal-http-api.md)
depends on that, since the gateway can only map failures it can see.
