"""`maity runner`: the service that starts and stops agents on placements (docs/api.md §15).

Needs Python 3.11 (`tomllib`); the agent-side commands keep 3.10. Never reads
`MAITY_STATE_DIR`: its state directory is `hub.state_dir` in its own configuration.
"""
