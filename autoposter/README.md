# Autoposter

Semi-automated TLA+ monthly development update blog post generator.

**Autoposter** (`devupdate`) is a Python CLI tool that semi-automates the creation of monthly TLA+ development update blog posts. It collects activity data from GitHub repositories, Google Group discussions, Metabase dashboards, and the TLA+ Foundation website, summarizes the highlights via an LLM, renders a Markdown blog post with metrics and charts, and can optionally open a draft pull request on the target repository.

## Prerequisites

- **Python 3.11+**
- **A GitHub personal access token** — required for GitHub API calls (set via `GITHUB_TOKEN`)
- **An LLM provider account** — one of:
  - [Azure OpenAI](https://azure.microsoft.com/en-us/products/ai-services/openai-service) (default)
  - [OpenAI](https://platform.openai.com/)
  - [Anthropic](https://www.anthropic.com/)
  - [Ollama](https://ollama.com/) (local, no account needed)

## Installation / Setup

```bash
# Clone the repo
git clone <repo-url>
cd autoposter

# Install in editable mode
pip install -e .
```

This installs the `devupdate` CLI command.

## Configuration

All runtime configuration lives in [`config.yaml`](config.yaml). Secrets (API keys, tokens) are **never** stored in this file — they come exclusively from environment variables.

### Structure

```yaml
# Target month/year — set to "auto" to use the previous calendar month
month: auto
year: auto

# Tracked GitHub repositories
repos:
  - name: TLC
    slug: tlaplus/tlaplus
  - name: Vscode Extension
    slug: tlaplus/vscode-tlaplus
  - name: TLAPM
    slug: tlaplus/tlapm
  - name: Apalache
    slug: apalache-mc/apalache

# LLM provider and model settings
llm:
  provider: azure_openai          # overridden by DEVUPDATE_LLM_PROVIDER env var
  model: gpt-5
  azure_deployment: gpt-5        # Azure-specific
  azure_api_version: "2025-06-01" # Azure-specific
  ollama_base_url: http://localhost:11434  # Ollama-specific

# Data sources
metabase:
  dashboard_url: https://metabase.tlapl.us/public/dashboard/...
  card_uuids: []

google_group:
  archive_url: https://discuss.tlapl.us/maillist.html

grants:
  url: https://foundation.tlapl.us/grants/index.html

# PR target repository
target_repo: tlaplus/foundation-website

# Local output directory for intermediate artifacts
output_dir: output
```

### Tracked Repositories

| Name             | GitHub Slug              |
|------------------|--------------------------|
| TLC              | `tlaplus/tlaplus`        |
| Vscode Extension | `tlaplus/vscode-tlaplus` |
| TLAPM            | `tlaplus/tlapm`          |
| Apalache         | `apalache-mc/apalache`   |

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | Yes | GitHub personal access token for API calls |
| `DEVUPDATE_LLM_PROVIDER` | No | Override LLM provider (`azure_openai`, `openai`, `anthropic`, `ollama`) |
| `OPENAI_API_KEY` | For `openai` | OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | For `azure_openai` | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_API_KEY` | For `azure_openai` | Azure OpenAI API key (falls back to `OPENAI_API_KEY` if unset) |
| `ANTHROPIC_API_KEY` | For `anthropic` | Anthropic API key |

> **Note:** When using `azure_openai`, the key lookup order is `AZURE_OPENAI_API_KEY` → `OPENAI_API_KEY`. If neither is set, a warning is logged and LLM calls will fail.

## Azure OpenAI Setup

Azure OpenAI is the default provider. Follow these steps to configure it:

1. **Create an Azure OpenAI resource** in the [Azure portal](https://portal.azure.com/).
2. **Deploy a model** (e.g., `gpt-5`) within the resource.
3. **Note the endpoint URL and API key** from the resource's "Keys and Endpoint" page.
4. **Set environment variables:**

   ```bash
   export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
   export AZURE_OPENAI_API_KEY="your-key-here"
   export DEVUPDATE_LLM_PROVIDER="azure_openai"
   ```

5. **Update `config.yaml`** with your deployment name and API version:

   ```yaml
   llm:
     provider: azure_openai
     model: gpt-5
     azure_deployment: gpt-5          # must match your Azure deployment name
     azure_api_version: "2025-06-01"   # check Azure docs for latest version
   ```

## Usage

The CLI entry point is `devupdate`. All commands accept `-v` / `--verbose` for debug logging.

```bash
# Full pipeline (collect + summarize + build)
devupdate run

# With month/year override
devupdate run --month 3 --year 2025

# Dry run (skip LLM, use placeholder text)
devupdate run --dry-run

# Collect data only
devupdate collect --month 3 --year 2025

# Build with custom output directory
devupdate build --output-dir ./my-output

# Full pipeline + open draft PR
devupdate pr --repo-dir /path/to/target-repo

# Verbose logging
devupdate -v run
```

## Project Structure

```
autoposter/
├── config.yaml                  # Runtime configuration
├── pyproject.toml               # Package metadata and dependencies
├── metrics/                     # Metric definitions / chart configs
├── prompts/                     # LLM prompt templates
├── templates/                   # Jinja2 blog post templates
└── src/
    └── autoposter/
        ├── __init__.py
        ├── cli.py               # Click CLI entry point (devupdate)
        ├── config.py            # Config loader and validation
        ├── models.py            # Shared data models
        ├── collectors/          # Data collection from GitHub, Google Group, Metabase, Grants
        ├── summarizer/          # LLM-based summarization
        ├── builder/             # Markdown post rendering with metrics and charts
        └── publisher/           # Draft PR creation
```

## Pipeline Stages

The `devupdate run` command executes four stages in sequence:

1. **Collect** — Pulls activity data for the target month from each configured source: GitHub commits/PRs/issues, Google Group threads, Metabase dashboard metrics, and the TLA+ Foundation grants page.
2. **Summarize** — Sends the collected data to the configured LLM to produce concise, human-readable summaries for each section of the blog post. Skipped in `--dry-run` mode (placeholder text is used instead).
3. **Build** — Renders the final Markdown blog post using Jinja2 templates, embedding the summaries along with metrics and SVG charts (generated via Pygal).
4. **PR** — *(Optional, via `devupdate pr`)* Commits the generated post to a branch and opens a draft pull request on the target repository (`tlaplus/foundation-website`).

## Using Other LLM Providers

### OpenAI

```bash
export OPENAI_API_KEY="sk-..."
export DEVUPDATE_LLM_PROVIDER="openai"
```

No changes to `config.yaml` are needed beyond ensuring `llm.model` is set to a model available on your OpenAI account (e.g., `gpt-5`).

### Anthropic

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export DEVUPDATE_LLM_PROVIDER="anthropic"
```

Set `llm.model` in `config.yaml` to an Anthropic model name (e.g., `claude-sonnet-4-20250514`).

### Ollama (local)

```bash
export DEVUPDATE_LLM_PROVIDER="ollama"
```

No API key is required. Make sure Ollama is running locally on the URL specified by `llm.ollama_base_url` (default: `http://localhost:11434`) and that the model in `llm.model` has been pulled.

```bash
ollama pull llama3
```

Then set `llm.model: llama3` in `config.yaml`.
