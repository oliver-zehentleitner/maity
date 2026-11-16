### Fixed

- hub tests: `test_listening_shows_while_a_long_poll_is_open` and
  `test_the_long_poll_wakes_on_an_attachment_and_shows_listening` wait, with a deadline, until the long poll they opened
  shows as `listening` instead of reading once after a fixed half second; under load the route registers the wait
  later than that, after its own database round trips, and the single read failed. After a wait ends, these two tests
  and three in `test_chat_unread.py` (`test_nothing_while_no_instance_listens`,
  `test_offline_agents_read_no_message_however_much_is_unread`,
  `test_one_agents_open_cycle_does_not_hold_back_another_agents_nudge`) let the listening writer finish
  (`listening.written()`) before they read who listens, since on PostgreSQL the close reaches `long_poll` from that
  thread.
