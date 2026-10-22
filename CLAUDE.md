# Brazil 2026 runoff tracker (Lula × Flávio Bolsonaro)

Live: https://mmuzzi.github.io/brazil-runoff-tracker/ · Repo: github.com/mmuzzi/brazil-runoff-tracker (public, GitHub Pages from `main` /).
Runoff is **2026-10-25**. Rebuilt and simplified on 2026-10-22. The earlier claude.ai prototype had calibration panels and house effects. They were dropped; the old CSVs are in `data/archive/`.

## Layout
- `index.html`: single file, vanilla JS + hand-drawn SVG, no deps. It fetches `data/data.json`. There are two charts side by side, with toggles for range (runoff / since April), poll average (ours / Plano Político / both) and chance-for (Flávio / Lula).
- `scripts/update.py`: stdlib-only. It rebuilds `data/data.json` and fails loudly (exit 1, nothing written) if any source breaks.
- `data/polls_extra.csv`: manual runoff polls that Plano Político doesn't carry (Vox Brasil, Veritá). PP deliberately removed Vox on 2026-10-18.
- `data/model_history.json`: merged model series, so history survives if PP drops days from its chart.
- `.github/workflows/update.yml`: daily cron at 11:23 UTC, plus manual `workflow_dispatch`. It commits only when data changed.

## Sources
- Polls: the JSON embedded in https://planopolitico.com.br/agregador/ (`recent_polls.t2`, scope `BR`). PP's own average comes from `presidente_t2.national_only.trajectory` (pre) and `post_first_round.national_only.trajectory` (runoff).
- Model: https://planopolitico.com.br/modelos-eleitorais/presidencial/. There's no JSON history, so the script decodes the "Trajetória da previsão" SVG paths (y=274 is 0%, 2.4 px per point) and maps them to the `hist-readout` dates. The latest day is replaced by the exact `p_wins`. Before Oct 4 the values include first-round wins, so they don't sum to 100.
- Market: Polymarket event `brazil-presidential-election`. Flávio and Lula "Yes" tokens come from the CLOB `prices-history` (daily), plus the live `outcomePrices` for today.

## Method (our average)
Flávio two-way share = flavio / (lula + flavio). Day T = equal-weight mean of each pollster's latest poll in (T−window, T], with window = 14d in the runoff and 30d before Oct 4 (sparse polls). It needs ≥3 houses. There's a regime break at the first round on 2026-10-04.

## To do / after the election
- Election night: add the actual result as a marker and compute each pollster's final error.
- After Oct 25: disable the workflow (`gh workflow disable update.yml -R mmuzzi/brazil-runoff-tracker`).
