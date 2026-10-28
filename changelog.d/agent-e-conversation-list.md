### Fixed

- hub: `GET /projects/{owner}/{slug}/conversations` and the resume packet's conversation list read all chats in a fixed number of statements instead of about ten per chat; the answer is unchanged. With 30 direct chats and 30 rooms (18,000 messages): 592 statements and 1.2 s before, 38 statements and 0.15 s after (tsk-ggza5m1nwtzh).
