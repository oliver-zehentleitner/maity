### Changed

- hub: a change of another owner's agent's `reports_to` waits for that owner's consent, with the other fields of the same change, unless the caller is the agent's owner or one of that owner's agents. A cross-owner edge keeps the two-owner consent, and its ids are listed only on the answer that filed both. The owner's request stores each proposed value with the hash of its canonical form, and the request read returns them in full. A number token in that change that is not an integer in the canonical range is `not_an_integer` on the field (tsk-w0853hqfhft0).
