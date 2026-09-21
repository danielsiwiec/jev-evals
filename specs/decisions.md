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
eight found the answer. See `ranked_elements` in [peregrine/actions.py](../peregrine/actions.py).

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

## close_tab is verified by an eval that fails without it

`test_jev_leaves_a_dead_end_tab_and_returns_to_the_goal` opens four tabs — two unrelated, the one
holding the answer, and a noisy lead form opened from it — and lands jev on the lead form. jev closes
it on the first step and returns to the answer, three runs out of three. Removing `close_tab` from the
action space makes the same eval fail with jev calling `back` three times and getting nowhere, which
is what the action was added to fix.

## settle() waits for quiet, not for a fixed time

After every action the harness waits for the page to stop changing before observing again, because
the loop compares observations to decide whether anything happened. That wait used to be a hardcoded
400ms sleep, which was simultaneously too long for a static page and too short for a slow one.

It now polls a cheap DOM signature — readyState, url, element count, body length — every 50ms and
returns on the first unchanged reading, with the old 800ms as a ceiling. Measured: 402ms to 54ms per
call, the offline suite from 74s to 46s, and refinance runs from ~8.9s to 5.6-7.8s.

This was worth finding before any rewrite: a profile showed 87% of a click's 462ms was that sleep and
only 7% was Playwright, which is why raw CDP was not the answer to slowness. See
[performance](#performance-where-the-time-actually-goes) below.

## Performance: where the time actually goes

Measured on a real page, per operation: Playwright `page.evaluate` 1.5ms against raw CDP
`Runtime.evaluate` 0.7ms; a bare `locator.click()` 34.6ms against a raw CDP mouse dispatch 2.8ms.
Playwright's overhead is real but small next to model latency (~194ms per step) and next to anything
the harness spends waiting. Rewriting the transport in raw CDP would target roughly 4% of a run while
requiring us to rebuild tab adoption, dialog handling, downloads and navigation waits — all of which
are load-bearing for the evals. Playwright stays.

## Everything rendered is offered; there is no viewport band

`observe.js` used to emit only elements within a band from one viewport above to three below, which
silently dropped 282 of 533 candidates on Bankrate — thirteen times more than pagination withheld,
and without telling jev they existed. The band was a guess about what would be reachable.

It is gone. Anything rendered is emitted, ranking puts dialogs and on-screen elements first, and
pagination bounds what is sent per page while `not_shown` counts the rest. Eight runs after the
change found the answer and reported done eight times out of eight, against three of four before,
and used *fewer* input tokens — about 60k against 73k. Offering more and ranking it well beats
filtering early and guessing.

Raising the page-text slice from 1800 to 6000 characters was tried at the same time and reverted: it
cost about 30k more tokens per run for no gain, and the second batch was worse than baseline. jev
pages through text with `show_more` when it needs to.

## Known-failing evals are kept failing

`test_jev_saves_the_file_once_the_host_becomes_ready` reproduces premature done: jev clicks before an
async page is ready, gets a clean "clicked", and reports done. It fails on purpose. A red test that
describes a real weakness is worth more than a green suite that hides one.
