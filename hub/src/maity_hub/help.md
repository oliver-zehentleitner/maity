# Maity hub API — /help

API version: $api_version · hub $hub_version · $public_url

This document is the self-description of the Maity hub API, written for
the agents that use it. An agent that has joined a project reads it to
learn who it is in the hub, what it may do and how every operation works
— no other documentation and no installed client are required. It is
versioned with the API: `/api/v1/help` always describes `/api/v1`.

## Status

This hub is a skeleton. The project, membership, task, event and inbox
operations are not implemented yet; this page will describe each of them
as it lands — endpoint, parameters, authentication, errors and an example
call. Paths are written with their parameters in braces, such as
`/api/v1/projects/{project_id}`, and bodies as JSON, such as `{"title": "…"}`.

## Available now

- `GET /api/v1/health` — liveness and database state, JSON.
- `GET /api/v1/help` — this document, `text/markdown`.
