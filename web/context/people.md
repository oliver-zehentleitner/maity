# People

## A person or an organisation at /<handle> is one read of GET /people/{handle}, shown as the hub answers it

**Id:** 63efb194-f0ff-4137-bb1f-fb4265356e3b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's report that `/wolfgang` showed nothing (seq 15767) and the card tsk-dnxgm9k0f317, 2026-10-30; the read the dashboard lacked, proposed with the card and settled by the coordinator as docs/api.md §6.27 (#738), with its later changes (`page_served`, `projects` with `shared` and `projects_total`, a placeholder for a `null` picture, `not_found` for whoever shows the reader nothing), 2026-10-30
**Revisit when:** §6.27 changes its answer, the hub serves a person's page images, or follows (`friends`) exist

`/<handle>` (one segment, not one of the dashboard's own words) is the
person or organisation view (`js/person.js`). It reads `GET
/people/{handle}` once and shows only what that answer holds for this
reader: the name, `@handle`, the picture, for a person the bio and the
links (each sent by the hub already built from the name, #764, so the
page builds none; Discord's name as text), the projects, for an
organisation its members. **View public
page** is there only while `page_served`, and opens `/<handle>?as=public`
in a new tab. A picture the answer gives no address for is a neutral
placeholder, not §6.10's generated avatar. A shared project leads to its
Overview, any other to its public page. An alias answers with the
current handle and the address follows it; `not_found` says that there
is nobody to see, as for an unknown name.

**Reason:** what a reader may see of another person (the bio only while
the page is public, the links by `links_visible`, a picture by §6.10)
is the hub's to decide per reader; one read that already answers that
keeps the view from guessing it from member lists, which would show a
bio or a link to the wrong reader or miss the public projects. The
generated avatar needs the account id, which the answer leaves out on
purpose.

**Rejected alternative:** building the view from the member views of
the shared projects: no bio, no public page, nothing for a person one
shares no project with, and no organisation for a non-member. A
generated avatar from the handle: it would differ from the one every
other view draws for the same person, and change with a rename. Hiding
the picture's place: the layout would jump from one person to the next.
