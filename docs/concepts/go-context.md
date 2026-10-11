# Context: cancellation and deadlines (Go)

**Short version:** a `context.Context` travels down the call chain with every request. It
carries two signals, "stop, nobody is waiting any more" and "stop, you ran out of time",
and anything that does I/O watches it. In the gateway it is how a closed browser tab
stops the call to core, and how a slow core turns into a 504.

## Where it comes from

Every incoming request has one: `r.Context()`. The server cancels it when the client
disconnects. The handler passes it into `core.getConversation`, which builds the outbound
request with `http.NewRequestWithContext(ctx, ...)`. From then on the outbound request
belongs to the inbound one: if the browser goes, the request to core is cancelled too.

ADR 0009 requires exactly this for chat, where an abandoned stream would otherwise keep
Ollama generating on the GPU. The reverse proxy gets it for free, because it builds its
outbound request from the incoming one.

## Deadlines only get stricter

```go
ctx, cancel := context.WithTimeout(ctx, coreRequestTimeout)
defer cancel()
```

`WithTimeout` returns a child context that expires after 10 seconds or when its parent
does, whichever comes first. A child can never outlive its parent. `TestSlowCoreIsA504`
relies on this: the incoming request carries a 50 ms deadline, so the 10 s timeout inside
`getConversation` never gets a chance to matter.

`cancel` releases the timer. Forgetting it leaks the timer until it fires, and `go vet`
flags the omission.

## Why not a client-wide timeout

`http.Client` has a `Timeout` field, and it would cover every request the client makes,
including the chat stream that legitimately runs for minutes. A deadline on the context
belongs to one call, so each method picks its own: 10 seconds for fetching a
conversation, none for a stream that the client's disconnect will end anyway.

## Telling the two signals apart

When a call fails because of its context, the error wraps one of two values:

- `context.Canceled`: the client left. `writeCoreError` writes nothing, because nobody is
  there to read it.
- `context.DeadlineExceeded`: time ran out. `writeCoreError` answers 504.

`http.Client` wraps these inside its own error type (`Get "http://...": context deadline
exceeded`), and `errors.Is` digs through the layers to find them. The 504 test confirms
that.
