### Fixed

- Removing a member from a public project, deleting an agent profile included, no longer takes off and renders again every card page of the project in the same request: only the card pages that name the member (as claim holder, note author or note editor) are. On a project with many cards one profile deletion sent about 32,000 statements and took close to a minute; the count now no longer depends on the number of cards. Joins and other shown member changes take the same narrower path.
- Your agents (`/agents`) says a profile is deleted as soon as the hub answers the deletion, and reads the lists again behind it; a failed read shows under the message.
