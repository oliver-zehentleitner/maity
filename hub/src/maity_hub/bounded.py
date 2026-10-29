"""Maps kept in the process with a bound on their size (card tsk-7865c6c2gszb).

The caches per project gain a key for every project the hub serves and lose none while
it runs: with open registration they grow with the instance. `put` writes a key as the
newest and drops the oldest written beyond the bound; what a dropped key held is read
or computed again on its next use. The caller holds the lock that guards the map.
"""

from __future__ import annotations

from collections.abc import Callable


def put[K, V](
    kept: dict[K, V], key: K, value: V, most: int, stays: Callable[[V], bool] | None = None
) -> list[K]:
    """`kept[key] = value` as the newest entry; beyond `most`, the oldest written go,
    except `key` itself and those `stays` keeps (a lock held right now). Returns the
    keys dropped."""
    kept.pop(key, None)
    kept[key] = value
    dropped: list[K] = []
    if len(kept) > most:
        for old in list(kept):
            if len(kept) <= most:
                break
            if old == key or (stays is not None and stays(kept[old])):
                continue
            del kept[old]
            dropped.append(old)
    return dropped
