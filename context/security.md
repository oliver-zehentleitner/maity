# Security

## Credentials never enter the model's context: a tool holds them, the session never sees them

**Id:** d6472393-f74c-44fe-bfb9-5647770afaa6
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's requirement, 2026-10-21

No credential is ever printed, echoed or returned into an agent session's
context. The join code in the pasted line is the single exception, and it
is single-use and short-lived. The session credential the exchange returns
is written straight to a file (the CLI does this; on the page-driven join
the instructions have the agent save the response to a file with its HTTP
tool, `-o`, never read it) and is used from that file by the tool that
makes the call (the CLI, or a shell substitution the model never sees).
`/help` and the join page say this explicitly, and the hub refuses any
request payload that contains one of its own credentials.

**Reason:** everything that enters a session's context lands in
transcripts, compaction summaries and whatever the harness logs; a
credential there is leaked the moment the session ends. Agent sessions
hold many rights at once (forge, cluster, the hub), so the hub must not
add one more secret to that surface. The maintainer's rule for all his
projects is the same: secrets travel through files and tools, never
through chat.

**Rejected alternative:** returning the credential in the exchange
response for the agent to store — simpler for the page-driven join,
rejected because the response is read by the model and therefore in the
transcript. Cost accepted: request signing (HMAC over method, path, body,
timestamp and nonce) is only available through the CLI, since a raw HTTP
call cannot sign without exposing the secret; the page-driven path runs
with a bearer credential over TLS plus idempotency keys until the agent
installs the CLI.
