# Decisions

Choices that are easy to undo by accident, with the evidence behind them. If you are about to reverse
one of these, the evidence is here to argue with.

## Element ranking has no semantic term

Ranking orders elements as: in a blocking dialog first, then on screen. Both are facts about the page.

An earlier version also scored goal-word overlap — words shared between the goal text and an element's
name. Measured against the refinance objective it was close to noise: `Open more filters` and the
zero-point radio `0` both scored zero ("filters" does not match "filter", and "0" is too short to
tokenise), while `Reject All` scored only through the stopword "all". It also rewarded objectives that
named a site's controls, which is the opposite of what a goal should do. Ten runs after removing it:
eight found the answer. See `ranked_elements` in [jev_evals/actions.py](../jev_evals/actions.py).

## Pagination instead of truncation

jev sees a page of elements, page text and history, and is told what is being held back
(`not_shown`) and that `show_more` reveals it. Nothing is silently dropped. Ranking runs before
pagination, so a blocking dialog is always on the first page — a regression where this was not true
dropped `Reject All` to position 81 of 108 and cost 3 runs out of 3.

## Goals state intent only

Objectives say what the user wants, never how the site works. The refinance objective used to name
the cookie gate, the points filter and its alternate label; it now does not, and jev passes without
the hints. An objective that explains the mechanics marks its own exam.

## One Chrome per run, thrown away after

Consent and ad gates are per-profile. A shared browser lets whichever driver runs first clear the gate
for everyone behind it, so each run launches its own Chrome on a free port with a temporary profile
and deletes it afterwards. `EVAL_FRESH_PROFILE=0` opts out.

## Window size, not headless

Bankrate renders no rate form at Chrome's default 800x600 — 76 observed elements against 110 at
1440x900. This was once misattributed to headless detection. Every launch sets `--window-size`
(`EVAL_WINDOW`), and everything runs headless.

## close_tab is one action

A tab opened by a link has no history, so `back` cannot leave it. `close_tab` closes the tab and
returns to the one it was opened from, tracked at adoption. One action rather than two, because
closing a tab is one thing a person does and it lands them where they came from.

## Known-failing evals are kept failing

`test_jev_saves_the_file_once_the_host_becomes_ready` reproduces premature done: jev clicks before an
async page is ready, gets a clean "clicked", and reports done. It fails on purpose. A red test that
describes a real weakness is worth more than a green suite that hides one.
