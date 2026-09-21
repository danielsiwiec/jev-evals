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

## jev types by selecting a phrase from the goal

jev answers `Choice`, `Noul` and `Score` and cannot generate text. A harness that only lets it type
values prepared in advance cannot search, and BU Bench showed the cost: with `values={}` no value
question was even built, so every type returned "no value named None is available" and four of five
trial tasks died on it. Fifty-nine of the hundred tasks name no URL, so the only way in is a search
box.

Typing now has two sources. A prepared value wins when the model picks one. Otherwise the model's own
`text` is used, which generative deciders produce directly and jev selects: `goal_phrases` offers
quoted spans first, then two-to-four word windows of the goal with stopwords dropped, as a `Choice`.
Selecting among substrings of the goal is still classification, so the interface is unchanged and
both driver families keep running the same loop.

It is a real limit, not a workaround dressed up: jev can only type words the goal already contains.
That is enough to search, and not enough to invent a plausible email address for a signup form.

`Decision.text` already existed and was already parsed by the LLM decider, but `_perform` never read
it — free text was unreachable for every driver, including gemini and luna.

## Two ways to fill a field, and jev picks which

`type` and `submit` use a prepared value or a phrase selected from the goal. `compose` calls a
generative model for a value the goal does not contain — an email address, a date, a plausible name.
jev chooses between them like any other action; the harness never decides that a field needs
composing.

The helper is deliberately narrow ([text_helper.py](../peregrine/text_helper.py)). It is told which
field, and returns one string. It never sees the action list, never picks an element, never decides
whether to type. Identical contexts are cached, so a retry after a stale page costs nothing and
returns the same answer. `TEXT_MODEL` configures it, defaulting to `gemini/gemini-3.1-flash-lite`
(measured 600ms mean, the fastest of the cheap models that reliably returns valid JSON —
`gpt-5-nano` is cheaper on paper and returned empty output twice). Setting it empty disables
composing, and `compose` then reports that no text model is configured rather than guessing.

Every call is attributed: `BrowseResult.text_model`, `.text_calls`, `.text_mean_ms`, and the cost is
added to the run's own. Without that, a two-model run cannot be told apart from a one-model run in
the results.

The two modes have to be genuinely distinguishable, not decided by a coin flip. On the signup form
the first wording left `type` at 0.49 against `compose` at 0.45, and the span it would have typed was
"a contact email address" — the goal's words, in an email field. Naming the distinction in both
action descriptions moved that to 0.07 against 0.88, while a search box still prefers `type` at 0.72.
An eval asserts both probabilities rather than just the choice, because a narrow margin regresses
without anything failing.

Eight refinance runs with composing available found the answer in six; eight with it disabled found
seven. The one four-run batch that scored 2/4 was over-continuation and a paging loop, both present
before this change. Composing is never chosen on that eval, which is the expected result: every value
it needs is in the goal.

## Known-failing evals are kept failing

`test_jev_saves_the_file_once_the_host_becomes_ready` reproduces premature done: jev clicks before an
async page is ready, gets a clean "clicked", and reports done. It fails on purpose. A red test that
describes a real weakness is worth more than a green suite that hides one.
