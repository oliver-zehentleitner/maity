### Added

- docs/api.md §8.4: the client checks a `review_result`'s text against `review.head` before sending:
  a file and line, a name in a code span (at the head or on the default branch), an object hash;
  everything under a heading `Ran` is left out; a text that names something not there is not sent.
- docs/api.md §6.9: the review line in the rules text for a reviewer: a fresh context per review,
  the checked text sent unchanged, the commands run listed under `Ran`.
