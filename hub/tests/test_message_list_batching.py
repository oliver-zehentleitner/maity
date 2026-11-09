"""A page of a chat's messages costs the same statements for 3 messages as for 30: the
senders are read for the whole page at once (`message_views`), and the first deliveries are
written in one INSERT (`events.mark_delivered`), not one per message. Counted per row for a
list of parameters, as sqlite3 and psycopg run it (`count_executions`), so a regression to
one fails here."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.statements import count_executions

P = "/projects/maintainer/maity"


def test_a_page_of_messages_costs_the_same_for_3_and_for_30(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    chat = f"{P}/conversations/{agent.id}/messages"
    senders: list[str] = []

    def grow(n: int) -> None:
        for i in range(n):
            writer = (agent, owner)[i % 2]
            sent = writer.post(chat, {"body": f"message {len(senders)}"})
            assert sent.status_code == 201, sent.text
            senders.append(writer.id)

    def read() -> Any:
        response = owner.get(f"{chat}?limit=50")
        assert response.status_code == 200, response.text
        return response

    # The chat's first read ever writes the reader's marks once: measure two reads that
    # each find new messages, the agent's of them not yet delivered.
    grow(1)
    read()
    grow(3)
    small = count_executions(migrated, read)
    grow(27)
    large = count_executions(migrated, read)
    assert large == small
    items = read().json()["items"]
    assert len(items) == 31
    by_body = {item["body"]: item["from"] for item in items}
    assert by_body == {f"message {i}": who for i, who in enumerate(senders)}
