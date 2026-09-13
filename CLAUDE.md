# Pigeon

A local cold outreach CRM. You are running inside the Pigeon folder, either from
the Claude Code pane in the page or from a terminal. Nothing here is published.

## The data

`contacts.json` is the whole database: a JSON array, one object per person.
Edit it directly. The page reloads it after you write, so a change shows up
there within a second.

| field | meaning |
|---|---|
| `id` | slug, `first-last`. Never change one; the page keys off it. |
| `name` `company` `role` | who they are |
| `email` | address. `channel` is `email` or `linkedin`. |
| `verified` | `true` only when the user has confirmed the address is real |
| `subject` `body` | the draft that gets sent |
| `status` | `queued` `sent` `replied` `converted` `bounced` `hold` `dead` |
| `sentAt` `followUpAt` `updatedAt` | `YYYY-MM-DD`, empty string if unset |
| `applied` | the user already applied to this company |
| `reqStatus` | `live` (posting is open), `none` (not posted yet), `""` (unchecked) |
| `reqTitle` `reqUrl` | the specific job posting |
| `warning` | a caution the page shows in amber above the draft |
| `notes` | free text about the relationship |
| `sendOrder` | position in the send queue, 1 goes first. Absent means unranked |
| `sendWhen` | when to send it, and the group header the page lists it under, such as `Send now` or `Tomorrow morning` |
| `rank` | 1 is the best contact at that company, higher is worse |
| `profileUrl` `domain` `logo` | LinkedIn URL, company domain, `logos/<file>` |

Rules for writing it:

- Keep it one JSON array of objects, UTF-8, and keep the existing key order on
  rows you touch. Do not reformat rows you were not asked to change.
- Set `updatedAt` to today on every row you edit. Get today's date from the
  system or the context line, do not guess it.
- Never invent an email address, a posting URL, or a `reqStatus` of `live`. If
  you are not certain, leave the field alone and say so.
- Never set `status` to `sent` on your own. The user says when something was sent.
- `sendOrder` is a queue, so keep it dense and unique: renumber the rest when you
  insert, remove, or reorder one. Give every ranked row a `sendWhen` too, and
  reuse an existing label rather than inventing a new one.
- Never set `verified` to `true` unless the user tells you the address checked out.

Each message from the pane starts with a bracketed context line naming today's
date and the contact open on screen. It is context, not the request.

## Writing drafts

Replace this section with your own rules. Until then:

- Keep it short enough to read on a phone. One ask, stated plainly.
- Only state facts about the sender that the user gave you or that already
  appear in their other drafts.
- Match the tone of the drafts already in the file rather than inventing a new one.

## What you cannot do from here

You cannot read or send mail. Sending is manual: the user copies the draft or
opens the Gmail compose link from the page. If a request needs the inbox, say so
instead of guessing what a reply said.
