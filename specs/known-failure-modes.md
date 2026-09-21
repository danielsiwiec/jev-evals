# Known failure modes

Each of these has an offline fixture. Reproduce there before changing the harness.

- **Consent and ad gates.** LimeWire shows a Quantcast consent dialog (`#qc-cmp2-container`) and
  freemagazines an ad gate (`.fc-message-root`). Both leave the page *logically* gated: the button is
  clickable but the app refuses to act. Suppressing the overlay defeats the cover, not the gate. The
  harness reports `click blocked: <blocker> is on top of this element` and lets the model decide.
  The ad gate's only control is "View a short ad" — the harness must never press it on its own.
  Fixtures: `consent_gate.html`, `ad_gate.html`, `timed_ad_gate.html`.
- **Controls hidden behind their label.** Bankrate's points filter is four `sr-only` radios, each a 1x1
  input behind a 90x47 label that carries the visible text and takes the click. Observation falls back
  to the label's box, or the control is invisible to the model and the goal unreachable.
  Fixtures: `sr_only_radio.html`, `buried_filter.html`.
- **The form fight.** A model types a value, the page re-renders and discards it. Pressing Enter on a
  multi-field form submits it half-filled, which is what caused it. Fixture: `multi_field_form.html`.
- **Premature done.** A model claims the goal is met on arrival. External scoring catches this.
- **Download path mismatch.** The download eval watches `DOWNLOADS_DIR`; Chrome writes to its profile's
  own directory. On a fresh profile these differ and every run scores "no file".
