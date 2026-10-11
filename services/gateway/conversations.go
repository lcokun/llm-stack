package main

import (
	"net/http"
	"uuid"
)

func getConversationHandler(core *coreClient) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := uuid.Parse(r.PathValue("id"))
		if err != nil {
			writeProblem(w, http.StatusUnprocessableEntity, "Request validation failed")
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
