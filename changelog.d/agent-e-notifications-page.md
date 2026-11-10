### Fixed

- hub: `GET /me/notifications` no longer derives every item of the last 30 days on every call. A page reads only the chat messages it can reach, the unread-chat count and the membership scope read one query each instead of one per agent and membership, and a page reads each project and actor once; the answer is unchanged. Measured with 30,000 chat items: 1.16 s before, 0.1 s after (tsk-svhatnxrtqn8).
