# HubSpot Workflows v4 — field notes

A practical reference for working with the HubSpot Workflows (Automation) **v4**
API: the endpoints worth knowing, how a flow definition is shaped, and the
gotchas that cost real time. Distilled from production marketing-ops work; all
ids below are illustrative.

---

## Endpoints

| Purpose | Request |
|---|---|
| Workflow ("flow") definition | `GET /automation/v4/flows/{flowId}` |
| List definition | `GET /crm/v3/lists/{listId}?includeFilters=true` |
| List definition (legacy id) | `GET /contacts/v1/lists/{listId}` *(fallback when v3 404s)* |
| Marketing email | `GET /marketing/v3/emails/{emailId}` |
| Per-email statistics (windowed) | `GET /marketing/v3/emails/statistics/list?startTimestamp=<ISO>&endTimestamp=<ISO>&emailIds=<id>` |

**Auth:** a private-app token (`pat-na1-…`) as `Authorization: Bearer <token>`.
Scopes needed for the above: automation, marketing email, and CRM lists.

A send action's `fields.content_id` **is** the marketing email id — join it
straight to `/marketing/v3/emails/{id}` to turn an action graph into named
emails.

## Anatomy of a flow definition

Top-level keys worth reading:

- `startActionId` — entry point of the graph.
- `actions[]` — the steps (see below).
- `enrollmentCriteria` — `type` (e.g. `LIST_BASED`), `shouldReEnroll`,
  `unEnrollObjectsNotMeetingCriteria`. This is the **real** audience; resolve it,
  don't trust the workflow's name.
- `goalFilterBranch` — goal/exit criteria. A met goal **ejects the contact
  immediately** and skips all remaining actions (a common source of "the last
  step never ran" bugs).
- `suppressionListIds` — `[]` means none.
- `timeWindows`, `blockedDates` — when sends are allowed; long delays maturing
  outside the window queue up for the next opening.

### Actions

Most actions carry an `actionTypeId`; branch actions carry `type` instead.

| `actionTypeId` / `type` | Meaning | Key fields |
|---|---|---|
| `0-1` | DELAY | `fields.delta` in **minutes**; `days = delta / 1440` (`4320` = 3 days, `43200` = 30 days) |
| `0-4` | SEND_EMAIL | `fields.content_id` = marketing email id |
| `0-5` | SET_PROPERTY | `fields.property_name` + `value` (a `staticValue`, or `timestampType: EXECUTION_TIME` = "stamp now") |
| `LIST_BRANCH` (`type`) | If/then branch | `listBranches[]` (each: `filterBranch` + `connection` + `branchName`) and optional `defaultBranch` / `defaultBranchName` |

> The list above covers the action types common in marketing/email workflows.
> HubSpot's full catalog is larger and can grow — treat an unknown id as unknown
> rather than guessing.

### Connections (the edges)

Every outgoing edge is a small object with a `nextActionId` and an `edgeType`:

- `STANDARD` — the normal next step.
- `GOTO` — a jump to an **existing** action. Used to **merge** several paths into
  one and to build **loops**. Follow these when graphing and confirm any loop can
  terminate.

A standard action has one `connection`. A `LIST_BRANCH` has a `connection` inside
each `listBranches[]` entry plus one on its `defaultBranch`. Collecting every
`nextActionId` reachable inside an action yields all of its outgoing edges
regardless of nesting — which is exactly what the analyzer does.

## The action graph

Action ids are internal and **never shown in the editor**, so graph-level
breakage is invisible in the UI. Two checks catch most of it:

- **Dangling link** — a `nextActionId` with no matching action = broken edge.
- **Orphan / unreachable** — a defined action that can't be reached from
  `startActionId`. (The only legitimately "unreferenced" action is the start
  itself.)

`hsflow analyze` computes both, plus terminals (actions with no outgoing edge —
the exits you must audit), the GOTO edges, and per-branch default coverage.

## Reading a branch correctly

A `LIST_BRANCH` takes the **first** matching branch only, so branch **order is
priority** — later overlapping branches never fire.

The highest-yield defect is **fallback coverage**: a branch with no
`defaultBranch` whose conditions don't cover everyone **silently drops** the
unmatched contacts (no action, they exit).

- `IN_LIST` + `NOT_IN_LIST` on the **same** list = a full partition → safe with
  no default.
- Two **positive** conditions (e.g. "in list A" / "in list B") do **not**
  partition — a contact in neither falls through. Needs a default.

Branch *names* are author labels; verify them against the actual list/filter
definition before trusting what a branch targets.

## Gotchas (the expensive ones)

- **`delta` is minutes, not milliseconds.** Divide by `1440` for days.
- **Statistics timestamps must be ISO-8601** (`2026-03-04T00:00:00Z`). Epoch
  milliseconds return **HTTP 400**. (`hsflow` coerces `datetime`/strings for you.)
- **Lists: try v3 first, then legacy v1.** A modern list id and its legacy id can
  differ; `/crm/v3/lists/{id}` 404s on a legacy-only id, so fall back to
  `/contacts/v1/lists/{id}`.
- **The runtime action-error / "review automation issues" history is _not_ in the
  public API.** Those are internal endpoints requiring cookie auth; the public
  `/automation/v4/flows/{id}/…` log paths return 404. Reconstruct send outcomes
  from `/marketing/v3/emails/statistics/list` (sent / suppressed / bounced /
  notsent) plus email events instead.
- **`defaultBranchName` exists even when `defaultBranch` doesn't** — a naive text
  search for "defaultBranch" over-counts. Check the actual `defaultBranch` key.
- **PowerShell writes UTF-8 _with BOM_.** If you pull flows with `ConvertTo-Json`
  and read them back elsewhere, open with a BOM-tolerant decoder (`utf-8-sig`).

## A repeatable audit, end to end

1. **Pull** the flow JSON (and every list it references). Audit the JSON, not the
   UI. QA on a **clone**, never the live asset — and prove the clone is identical
   to the original (diff the JSON; only metadata like `id`/`name`/`uuid` should
   differ).
2. **Decode** the building blocks (action types, delays, branch conditions).
3. **Build the graph** — defined vs referenced ids; flag orphans and dangling
   links; follow GOTO merges/loops; list every terminal.
4. **Translate ids to labels** — `content_id` → email name; `listId` → list name
   **and its real filter**; action id → branch name. Now every statement reads in
   plain terms.
5. **Walk the flow** and check the recurring failure patterns: branch fallback
   coverage, branch order, property set/reset symmetry on every exit (goal exits
   skip terminal resets), send→stamp consistency, enrollment-audience truth, and
   suppression/marketing guards.
6. **Verify your own findings** — re-derive counts, separate certain defects from
   inferences, and confirm impact (a stale flag nothing reads is hygiene, not a
   live bug) before rating severity.

`hsflow` automates steps 2–3 and the structural half of step 5; the rest is
judgment applied to what it surfaces.
