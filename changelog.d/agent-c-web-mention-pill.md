### Fixed

- web: a project whose pill counts unread mentions now shows a link beside its tabs ("1 unread mention") to `/notifications` filtered to that project's mentions. Before, the pill showed a number that no tab and nothing in the project led to. `/notifications` reads `kind` and `project` from its address, names the filter in its heading, links back to all notifications, and its Mark all read marks only that kind and project.
