### Added

- contract: 👍 and 👎 on a chat message (`docs/api.md` §9.7, not built). A human participant gives a message a verdict, `agree` or `disagree` (with an optional sentence), with `PUT …/conversations/{id}/messages/{seq}/verdict` and takes it back with `DELETE`. Each change emits `chat_verdict` to the chat's participants and wakes only the message's author. The message carries `verdicts`, each human's current one.
