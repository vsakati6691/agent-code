"""Shared terminal presentation. System fonts and CSS only; no remote dependencies."""

CSS = r"""
:root {
  color-scheme: light;
  --bg: #f3f5f8; --surface-1: #ffffff; --surface-2: #edf1f6; --border: #ccd5df;
  --text-primary: #1b283b; --text-secondary: #485970; --text-muted: #5e6d80;
  --series-1: #2864a6; --reference: #687b90; --link: #235d9a;
  --good: #236a4f; --bad-border: #b3444f; --bad-bg: #fcf0f1;
  --warn-bg: #fcf6e9; --warn-border: #86621c; --info-bg: #eff5fc; --info-border: #577ea9;
  --row-hover: #eaf1f9; --focus: #2864a6; --radius: 8px;
  --elevation: 0 1px 2px rgb(27 40 59 / 5%);
  --overlay: rgb(10 19 34 / 55%); --dialog-shadow: 0 20px 70px rgb(0 0 0 / 25%);
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --bg: #0e1521; --surface-1: #151f2e; --surface-2: #1c293b; --border: #354359;
    --text-primary: #e6edf7; --text-secondary: #bdcadc; --text-muted: #9aabc1;
    --series-1: #3676bc; --reference: #9aabc1; --link: #9fc6f5;
    --good: #83cba7; --bad-border: #e6a0a8; --bad-bg: #301f2a;
    --warn-bg: #2c281f; --warn-border: #d9bb7b; --info-bg: #1a2a40; --info-border: #739ac8;
    --row-hover: #203149; --focus: #9fc6f5; --elevation: 0 1px 2px rgb(0 0 0 / 18%);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #0e1521; --surface-1: #151f2e; --surface-2: #1c293b; --border: #354359;
  --text-primary: #e6edf7; --text-secondary: #bdcadc; --text-muted: #9aabc1;
  --series-1: #3676bc; --reference: #9aabc1; --link: #9fc6f5;
  --good: #83cba7; --bad-border: #e6a0a8; --bad-bg: #301f2a;
  --warn-bg: #2c281f; --warn-border: #d9bb7b; --info-bg: #1a2a40; --info-border: #739ac8;
  --row-hover: #203149; --focus: #9fc6f5; --elevation: 0 1px 2px rgb(0 0 0 / 18%);
}
html { scrollbar-gutter: stable; }
body, button, input, select, textarea, kbd { font-variant-numeric: tabular-nums lining-nums; }
button, input, select, textarea { font-family: inherit; }
body { line-height: 1.5; }
a { text-underline-offset: .2em; }
:focus-visible { outline: 2px solid var(--focus); outline-offset: 3px; }
header.site { box-shadow: var(--elevation); }
header.site .inner { gap: 12px 20px; }
header.site .brand { font-size: 16px; letter-spacing: -.25px; }
header.site nav { display: flex; flex-wrap: nowrap; overflow-x: auto; gap: 20px; padding: 2px 0 4px;
  scrollbar-width: thin; min-width: 0; }
header.site nav a { flex: none; white-space: nowrap; margin: 0; padding: 6px 0; }
header.site nav a[aria-current="page"] { text-underline-offset: 7px; }
.card, .market-tile, .scan-stats, .research-path, .context-details, .table-wrap {
  border-radius: var(--radius); box-shadow: var(--elevation);
}
.card { padding: 16px 18px; }
.scan-hero { padding: 24px 0; }
.scan-hero h1 { font-size: clamp(28px, 3vw, 40px); letter-spacing: -1.2px; }
.scan-stat { padding: 16px 20px; }
.market-value, .scan-stat strong, .stat .value { letter-spacing: 0; }
.banner { border-left-width: 3px; padding: 10px 13px; overflow-wrap: anywhere; line-height: 1.5; }
.banner strong { margin-right: .35em; }
.banner details { margin-bottom: 0; }
.banner summary { color: inherit; font-weight: 600; }
.banner ul { padding-left: 20px; margin: 8px 0; }
.banner small, .banner .small { color: inherit; }
.data-notice { font-size: 13px; }
.daily-status { font-size: 12px; }
.refresh-missing ul { max-block-size: 14rem; overflow-y: auto; }
.macro-card { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.macro-card > div { font-size: 21px; line-height: 1.4; font-weight: 600; }
.macro-card small { color: var(--text-muted); }
.controls { gap: 8px 10px; padding: 4px 0; }
.controls input, .controls select, .themebtn { min-height: 36px; }
.controls input { min-width: 0; max-width: 100%; }
.controls select { max-width: 100%; }
[data-count] { display: inline-block; min-inline-size: 8.5rem; min-block-size: 1.5em; }
.themebtn { min-inline-size: 98px; white-space: nowrap; }
#goal-storage, #cmp-hint, #bet-sizing, #bet-slip-status { min-block-size: 3em; }
#bet-contract { contain: inline-size; }
.table-wrap { overflow: auto; max-block-size: 72vh; max-block-size: 72dvh;
  overscroll-behavior-inline: contain; scrollbar-width: thin; scrollbar-color: var(--reference) var(--surface-2); }
.table-wrap:focus-visible { outline-offset: 2px; }
.table-wrap table { border-collapse: separate; border-spacing: 0; }
.table-wrap th { position: sticky; top: 0; z-index: 3; background: var(--surface-2);
  box-shadow: 0 1px 0 var(--border); color: var(--text-secondary); font-size: 12px; }
.table-wrap th, .table-wrap td { padding: 9px 10px; line-height: 1.4; }
.table-wrap th.tk,
.table-wrap > table:not(:has(th.tk)) > thead > tr > th:first-child { z-index: 5; background: var(--surface-2); }
.table-wrap tbody > tr:not(.detail):hover > td,
.table-wrap tbody > tr:not(.detail):focus-within > td { background: var(--row-hover); }
.table-wrap td.num .small, .table-wrap td.num small { white-space: normal; }
.sortbtn { min-block-size: 24px; }
th[data-sort] .sortbtn::after { display: inline-block; width: 1.1em; text-align: center; }
.lazy { block-size: min(28rem, 55vh); min-block-size: 12rem; overflow: auto; padding: 12px 2px;
  position: sticky; left: 0; width: min(1260px, calc(100vw - 72px)); }
.lazy[aria-busy="true"] { opacity: 1; color: var(--text-muted); }
.lazy .evidence, .lazy .pin { position: static; width: 100%; }
.load-error { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; padding: 12px; }
.load-error p { margin: 0; }
.symsearch { width: 240px; flex: 0 1 240px; }
.symsearch input, .command-trigger { width: 100%; height: 36px; }
.command-trigger { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 0 10px; font: inherit; font-size: 13px; color: var(--text-secondary);
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; }
kbd { font: 11px/1.5 ui-monospace, monospace; font-variant-numeric: tabular-nums;
  padding: 1px 5px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface-2);
  color: var(--text-secondary); white-space: nowrap; }
.command-dialog { width: min(600px, calc(100vw - 32px)); max-height: 80vh; max-height: 80dvh;
  margin: 10vh auto 0; padding: 0; border: 1px solid var(--border); border-radius: 12px;
  color: var(--text-primary); background: var(--surface-1); box-shadow: var(--dialog-shadow); overflow: auto; }
.command-dialog::backdrop { background: var(--overlay); }
.command-head { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 14px 18px 8px; }
.command-head h2 { font-size: 16px; margin: 0; }
.command-close { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; background: none;
  border: 0; color: var(--text-muted); cursor: pointer; }
.command-dialog input { width: calc(100% - 36px); margin: 8px 18px; padding: 12px; font: inherit; font-size: 16px;
  border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--text-primary); }
.command-results { list-style: none; margin: 0; padding: 6px 8px; block-size: min(340px, 42vh);
  block-size: min(340px, 42dvh); overflow-y: auto; overscroll-behavior: contain; }
.command-results li { display: flex; align-items: baseline; gap: 16px; padding: 11px 12px;
  border-radius: 5px; cursor: pointer; }
.command-results li[aria-selected="true"] { background: var(--row-hover); outline: 1px solid var(--focus); outline-offset: -1px; }
.command-results strong { flex: 0 0 72px; color: var(--link); }
.command-results span { color: var(--text-secondary); overflow-wrap: anywhere; min-width: 0; font-size: 13px; }
.command-footer { display: flex; flex-wrap: wrap; gap: 4px 12px; justify-content: space-between;
  border-top: 1px solid var(--border); padding: 12px 18px; font-size: 12px; color: var(--text-muted); }
.command-footer p { margin: 0; }
@media (prefers-reduced-motion: no-preference) {
  .action, .command-trigger, .themebtn, .research-path { transition: border-color 120ms ease, background-color 120ms ease; }
  .command-dialog[open] { animation: command-in 120ms ease-out; }
  @keyframes command-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
}
@media (max-width: 700px) {
  header.site .inner { gap: 10px; }
  header.site .brand { flex: 1 1 auto; }
  header.site .inner .symsearch { flex: 1 1 190px; margin-left: 0; order: 2; }
  .themebtn { order: 2; min-height: 44px; }
  .symsearch input, .command-trigger { height: 44px; }
  .symsearch input { font-size: 16px; }
  .controls input, .controls select { min-height: 44px; font-size: 16px; }
  header.site nav { order: 3; gap: 18px; }
  .table-wrap th, .table-wrap td { padding: 8px; }
  .command-close { min-height: 44px; }
  .command-dialog { margin-top: 16px; max-height: calc(100dvh - 32px); }
  .command-results strong { flex-basis: 60px; }
  .command-footer .command-help { display: none; }
}
@media (max-width: 650px) {
  /* Keep the scanner's native table semantics and headers at narrow widths. */
  #t-scan.decision-scan thead { display: table-header-group; }
  #t-scan.decision-scan tbody { display: table-row-group; }
  #t-scan.decision-scan tr { display: table-row; }
  #t-scan.decision-scan td { display: table-cell; padding: 9px 10px; border-bottom: 1px solid var(--border); }
  #t-scan.decision-scan td:before { content: none; }
  #t-scan.decision-scan td.num { text-align: right; }
  #t-scan.decision-scan td.tk { min-width: 140px; max-width: 170px; }
  #t-scan.decision-scan td.research-value { min-width: 175px; max-width: 240px; }
  #t-scan.decision-scan td.scan-risk { min-width: 200px; max-width: 280px; }
}
@media print {
  .table-wrap, .lazy, .refresh-missing ul { max-block-size: none; block-size: auto; overflow: visible; }
  .table-wrap th, .table-wrap th.tk,
  .table-wrap > table:not(:has(th.tk)) > thead > tr > th:first-child,
  .table-wrap > table:not(:has(th.tk)) > tbody > tr:not(.detail) > :first-child:not([colspan]) { position: static; }
  .command-dialog { display: none !important; }
}
"""
