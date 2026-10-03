# llm-stack — single entry point across uv, go, cargo and npm.
# Recipes run under sh, not fish, so they also work on CI runners.

# Show available recipes.
default:
    @just --list
