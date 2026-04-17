# TLA+ Monthly Dev Update: Semi-Automated Blog Post

Produce a monthly Markdown post summarizing TLA+ ecosystem activity, in the
style of the [TLA+ Foundation dev updates](https://foundation.tlapl.us/blog/2025-02-dev-update/).
A bot drafts the post and opens a pull request. A maintainer reviews and
merges. Nothing is published automatically.

## Post Format
Sample post format. Short intro, a few major updates (if any) written by hand, and 
automated sections that include: full changes across different repos, numbers info,
notable community emails, 

```markdown
---
title: "{Month Year} Development Update"
layout: post
---

# {Month Year} Development Update

{2 to 3 sentence intro about the month's focus.}

## New debugger support

## TLA+ formatter now available into tlatools
TLA+ has an official formatter and it is now available in the tlatools release.

## Development Updates

Summaries of merged pull requests (and significant issues or releases) for
each project this month. One paragraph per each feature

- TLC: Graal native-image support for SANY was improved so TLA+ modules
  embedded in the image load correctly
  ([#1116](https://github.com/tlaplus/tlaplus/pull/1116))
- TLC: New feature flag.
- Vscode Extension: Syntax highlighting no longer treats operator definitions inside
  comments as operators
  ([#362](https://github.com/tlaplus/vscode-tlaplus/pull/362)).
- Vscode extension: Added support for unicode operators autocompletion.
- TLAPM: Fixed a race condition in the language server when multiple backend
  provers run concurrently
  ([#194](https://github.com/tlaplus/tlapm/pull/194)).

### By the Numbers

| Metric                        | {Month Year} |
| ----------------------------- | -----------: |
| Open issues                   |          {n} |
| Merged pull requests          |          {n} |
| Commits                       |          {n} |
| Releases                      |          {n} |
| Active contributors           |          {n} |
| New contributors              |          {n} |
| Google Group messages         |          {n} |
| Tool runs (TLC / Apalache)    |  {n} / {n}  |

![Pull requests per month](./assets/2025-04/prs_per_month.svg)
![Commits per month](./assets/2025-04/commits_per_month.svg)
![Active contributors per month](./assets/2025-04/active_contributors_per_month.svg)

> Tool usage stats are opt-in and anonymized; actual usage is likely higher.
> Source: [metabase.tlapl.us](https://metabase.tlapl.us/public/dashboard/cf7e1a79-19b6-4be1-88bf-0a3fd5aa0dec).

### Community & Events

- Notable mailing list threads, upcoming workshops, recorded talks, grants,
  and new community specs.

```

## How Each Section is Populated

The post mixes hand-written highlights at the top with automated sections
below. The bot generates only the automated parts; the maintainer adds
any hand-written feature sections during PR review.

### Intro

Written by the LLM last, given the other sections as context. 2 to 3
sentences naming the month's focus.

### Hand-written feature sections

Optional. Top-level (`H2`) sections written by the maintainer for major
features that deserve more than a one-line bullet (for example
"New debugger support" or "TLA+ formatter now available into tlatools").
The bot does not generate or modify these. It does emit a placeholder
comment in the post (`<!-- add hand-written highlights here -->`)
between the intro and `Development Updates` to make the insertion point
obvious during review.

### Development Updates

A single flat bulleted list. One bullet per merged PR (or significant
issue or release) across all tracked projects. Each bullet is prefixed
with the project name and is one short paragraph describing what changed,
with PR numbers linked inline. Bullets do not lead with contributor
names. When an item carries a ```changelog``` fence, the fence's
contents are used verbatim as the bullet body (see below).

Project name prefixes and source repos:

- `TLC`: [`tlaplus/tlaplus`](https://github.com/tlaplus/tlaplus)
- `Vscode Extension`: [`tlaplus/vscode-tlaplus`](https://github.com/tlaplus/vscode-tlaplus)
- `TLAPM`: [`tlaplus/tlapm`](https://github.com/tlaplus/tlapm)
- `Apalache`: [`apalache-mc/apalache`](https://github.com/apalache-mc/apalache)

Bullets are grouped by project in the order above and otherwise sorted
by merge date.

### By the Numbers

I'm still not fully sure about the content of this section, but it might be interesting to see. Across `tlaplus/tlaplus`,
`tlaplus/vscode-tlaplus`, `tlaplus/tlapm`, and `apalache-mc/apalache`, the builder counts merged PRs,
commits, releases, active contributors, and first-time contributors in the
month. `Open issues` is a snapshot taken at run time. `Google Group
messages` comes from the public mailing list archive at
<https://discuss.tlapl.us/maillist.html>. Tool-run counts and
the associated charts come from the public Metabase dashboard (https://metabase.tlapl.us/) that serves
opt-in TLA+ Tools telemetry, queried via stable public-card UUIDs
hard-coded in config. 

Each run appends the month's row to a checked-in `metrics/history.json`,
and the builder renders per-month line charts as SVGs next to the post.
No cross-month deltas are computed in text; the charts show history.

### Community & Events

The place for notable community discussions, workshops, grants, conferences, and community specs. Grants can be extracted automatically from https://foundation.tlapl.us/grants/index.html. Conferences, workshops and new grants can also be extracted from the google group archive.

The google group archive will also be used for the notable discussion (if a thread has more than 2 answers it will be considered notable).

- Source: [TLA+ Google Group archive](https://discuss.tlapl.us/maillist.html)

## Contributor-Authored Entries

If a PR description or commit message contains a fenced `changelog` block,
the block's contents are used verbatim as the bullet body in
`Development Updates`, preserving Markdown formatting and paragraph breaks.
The builder still adds the project prefix and a trailing link to the
source PR or commit.

Source (in a PR body or commit message on `vscode-tlaplus`):

````markdown
```changelog
This is a longer,

multiline

changelog entry. Most entries should be one short paragraph, but a new
feature might justify two or three.
```
````

Renders as a bullet under `Development Updates`:

> - **Vscode Extension**: This is a longer,
>
>   multiline
>
>   changelog entry. Most entries should be one short paragraph, but a
>   new feature might justify two or three.
>   ([vscode-tlaplus#362](https://github.com/tlaplus/vscode-tlaplus/pull/362))

Items with a `changelog` fence skip the LLM summarizer entirely. Multiple
fences in one item are concatenated in order. Items without a fence go
through normal LLM summarization.

## Architecture Overview

This is just an idea, the implementation might be different. Four stages, each a small module with a file-based handoff so stages can be rerun independently.

1. **Collect** normalizes items from every data source into a single list:
   GitHub REST API for repos and orgs, RSS for the Foundation blog, an HTML
   scraper for `discuss.tlapl.us`, and the public Metabase JSON endpoints
   for telemetry. One adapter per source type.
2. **Summarize** feeds each section's items to an LLM, using a checked-in
   reference post as the style exemplar and a versioned prompt template.
   Items carrying a ```changelog``` fence bypass the LLM.
3. **Build** renders the post from a Jinja template, computes the metrics
   table and charts, and runs deterministic validation (no em dashes /
   en dashes / horizontal bars, well-formed frontmatter, every linked URL
   came from the collected items, every referenced chart file exists).
4. **PR** commits the post and assets on a branch and opens a draft PR
   with a generated description that @-mentions the month's contributors.

All behavior that varies month-to-month (data sources, filters, prompt,
LLM provider, target repo, schedule) lives in a single `config.yaml`.

## Workflow

Two supported modes:

- **Local CLI**. A maintainer runs `devupdate run` on their machine. The
  LLM is whichever one they already use, selected via an environment
  variable (OpenAI, Anthropic, Ollama, or Azure OpenAI). This is the
  primary path for ad-hoc or corrective runs.
- **GitHub Actions**. A monthly cron (`0 9 1 * *` UTC) plus
  `workflow_dispatch` runs the same CLI inside Actions. The LLM is Azure
  OpenAI, configured via repo secrets.

The Action uses the built-in `GITHUB_TOKEN` (`contents: write`,
`pull-requests: write`) to push the branch and open the PR. The PR is
authored by `github-actions[bot]`. No App or PAT is needed. All input
data is public, so the token is only used for writing back to its own
repo.

Review workflow in both modes: the bot opens a draft PR; contributors and
maintainers review and can push fixes or leave comments; the maintainer
addresses comments and merges manually. The bot never merges.
