package main

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"unicode/utf8"
	"uuid"
)

const (
	maxTitleLength      = 200
	maxRequestBodyBytes = 1 << 20
	invalidBodyDetail   = "body: must be a JSON object with an optional string title"
)

type createConversationRequest struct {
	Title *string `json:"title"`
}

func (req createConversationRequest) validate() error {
	if req.Title != nil && utf8.RuneCountInString(*req.Title) > maxTitleLength {
		return fmt.Errorf("title: must be at most %d characters", maxTitleLength)
	}
	return nil
}

func getConversationHandler(core *coreClient) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := uuid.Parse(r.PathValue("id"))
		if err != nil {
			writeValidationProblem(w, "id: must be a UUID")
			return
		}
		conv, err := core.getConversation(r.Context(), id, r.Header.Get(requestIDHeader))
		if err != nil {
			writeCoreError(w, r, err)
			return
		}
		writeJSON(w, http.StatusOK, conv)
	}
}

func createConversationHandler(core *coreClient) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		r.Body = http.MaxBytesReader(w, r.Body, maxRequestBodyBytes)
		var req createConversationRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			slog.Debug("rejected request body", "path", r.URL.Path, "err", err)
			writeValidationProblem(w, invalidBodyDetail)
			return
		}
		if err := req.validate(); err != nil {
			writeValidationProblem(w, err.Error())
			return
		}
		conv, err := core.createConversation(r.Context(), req.Title, r.Header.Get(requestIDHeader))
		if err != nil {
			writeCoreError(w, r, err)
			return
		}
		writeJSON(w, http.StatusCreated, conv)
	}
}
