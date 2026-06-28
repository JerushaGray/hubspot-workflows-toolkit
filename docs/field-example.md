# A finding in context: what "no default" actually costs

`hsflow analyze` reports structural defects in a workflow. On their own they can
read like lint ("action 8 has no default"). This note translates one of them
into what it costs in the only terms that matter to a marketing team, contacts
and pipeline, using the bundled synthetic sample so every claim is reproducible.

## The finding

Running `hsflow analyze examples/sample_flow.json` reports:

```text
WARNING BRANCH_NO_DEFAULT [action 8]: LIST_BRANCH with 2 branch(es) and no default: contacts matching none will silently exit unless the branch conditions fully partition the audience (e.g. IN_LIST + NOT_IN_LIST on the same list). Verify coverage.
```

Action 8 routes two paths: "Has Package A" to one email, "Has Package B" to
another. There is no default branch.

## Why it costs money

A `LIST_BRANCH` sends each contact down the first path whose condition matches.
With no default, a contact who matches none of the conditions takes no path at
all: they get no email and silently exit the workflow.

Here both conditions are *positive* ("is in list A", "is in list B"). A contact
who is in neither list matches nothing and falls out. That segment:

- gets **zero touches** from this nurture,
- is **invisible in the canvas**, which shows two tidy branches and no hint that
  a third group exists,
- is **invisible in send stats**, because those contacts were never enrolled in
  a send to begin with,
- shows up only in the flow JSON, which nobody reads.

If the "neither" segment is even 10 to 20 percent of enrollees, that is 10 to 20
percent of the nurture audience receiving nothing, with no signal on any
dashboard. In an activation or onboarding flow, that is lost product activation
and lost pipeline, and it looks exactly like normal performance.

## How to confirm, and fix

Confirm whether the branches actually partition the audience:

- `IN_LIST` plus `NOT_IN_LIST` on the **same** list is a true partition. Everyone
  takes exactly one path, so no default is needed.
- Two positive "has X" / "has Y" conditions do **not** partition. A contact with
  neither falls through, and the branch needs a default.

Fix: add a default branch that routes the unmatched segment somewhere intentional
(a general email, an exit with a reason, or a holding state), so "neither" is a
decision rather than an accident.

## A related pattern: over-suppression

A second way a workflow quietly underdelivers is at send time rather than in the
graph. A behavior-triggered flow that enrolls anyone who fits, with no
marketing-contact guard and an empty suppression list, will try to send to
non-marketable contacts too. Those sends are dropped at send time as
suppressions. In a portal with a large non-marketable population, a meaningful
share of "sent" is actually "suppressed", and the open and click rates you report
are computed against a denominator that includes people who could never have
received the email.

This one is a judgment check, not a structural defect: `hsflow` does not flag it.
It comes from resolving the real enrollment audience and reading the suppression
configuration (step 5 of the audit in
[workflows-v4-reference.md](workflows-v4-reference.md)). The tool surfaces the
graph; a person still has to read the audience.

## The point

"Action 8 has no default" and "a segment of your nurture audience silently
receives nothing" are the same fact in two languages. The analyzer finds where
contacts leak; the crosswalk turns the ids into names so you can say *which*
segment and *which* emails. The value is not the lint line, it is being able to
put a number and a name on the leak before it quietly costs a quarter of
pipeline.
