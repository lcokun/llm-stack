package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"time"
	"uuid"
)

const (
	coreRequestTimeout = 10 * time.Second
	requestIDHeader    = "X-Request-Id"
)

var errConversationNotFound = errors.New("conversation not found")

type conversation struct {
	ID        uuid.UUID `json:"id"`
	Title     *string   `json:"title"`
	CreatedAt time.Time `json:"created_at"`
	Messages  []message `json:"messages"`
}

type message struct {
	ID        uuid.UUID `json:"id"`
	Role      string    `json:"role"`
	Content   string    `json:"content"`
	CreatedAt time.Time `json:"created_at"`
}

type coreClient struct {
	base *url.URL
	http *http.Client
}

func newCoreClient(base *url.URL) *coreClient {
	return &coreClient{base: base, http: &http.Client{}}
}

func (c *coreClient) getConversation(ctx context.Context, id uuid.UUID, requestID string) (conversation, error) {
	ctx, cancel := context.WithTimeout(ctx, coreRequestTimeout)
	defer cancel()

	target := c.base.JoinPath("conversations", id.String())
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target.String(), nil)
	if err != nil {
		return conversation{}, err
	}
	if requestID != "" {
		req.Header.Set(requestIDHeader, requestID)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return conversation{}, err
	}
	defer resp.Body.Close()

	switch resp.StatusCode {
	case http.StatusOK:
	case http.StatusNotFound:
		return conversation{}, errConversationNotFound
	default:
		return conversation{}, fmt.Errorf("core answered %d", resp.StatusCode)
	}

	var conv conversation
	if err := json.NewDecoder(resp.Body).Decode(&conv); err != nil {
		return conversation{}, fmt.Errorf("decode core response: %w", err)
	}
	return conv, nil
}
