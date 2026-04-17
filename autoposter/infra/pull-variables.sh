#!/usr/bin/env bash
# Pull Azure OpenAI credentials and export them for autoposter.
# Usage: source infra/pull-variables.sh
#
# NOTE: Do NOT use "set -e" here — this file is sourced into the user's
# interactive shell, and "set -e" would cause the shell to exit on any
# non-zero return code (including tab completion).

RG="rg-autoposter"
ACCOUNT="oai-autoposter"

echo "Fetching Azure OpenAI credentials from $ACCOUNT in $RG ..."

AZURE_OPENAI_ENDPOINT=$(az cognitiveservices account show \
  --name "$ACCOUNT" \
  --resource-group "$RG" \
  --query properties.endpoint \
  --output tsv) || { echo "ERROR: failed to fetch endpoint"; return 1; }

AZURE_OPENAI_API_KEY=$(az cognitiveservices account keys list \
  --name "$ACCOUNT" \
  --resource-group "$RG" \
  --query key1 \
  --output tsv) || { echo "ERROR: failed to fetch API key"; return 1; }

export AZURE_OPENAI_ENDPOINT
export AZURE_OPENAI_API_KEY
export DEVUPDATE_LLM_PROVIDER=azure_openai

echo "AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT"
echo "AZURE_OPENAI_API_KEY=<set>"
echo "DEVUPDATE_LLM_PROVIDER=$DEVUPDATE_LLM_PROVIDER"
echo ""
echo "Done. Variables exported to current shell."
