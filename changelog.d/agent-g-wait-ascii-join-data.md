### Security

- `maity wait`, `resume --json` and the other `--json` output escape control, bidi and Unicode tag characters; text output escapes tags too. A `wait` that returns a message says on stderr that a body is data.
- `maity join` warns before the exchange when this machine already holds an identity on another hub, and `docs/agents.md` and the skill say to join only on your human's word.
