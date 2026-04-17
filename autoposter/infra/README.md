# Azure Infrastructure for Autoposter

Minimal Bicep templates that deploy everything needed to run `devupdate` with Azure OpenAI.

## What gets created

| Resource | Purpose |
|----------|---------|
| Resource Group (`rg-autoposter`) | Container for all resources |
| Azure OpenAI account (`oai-autoposter`) | Hosts the LLM endpoint |
| GPT-5 deployment (`gpt-5`) | Model used for summarization |

## Prerequisites

- An Azure subscription
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) (`az`) installed
- Bicep support (bundled with Azure CLI ≥ 2.20)

## Deploy

```bash
# 1. Log in
az login

# 2. Set your subscription (if you have multiple)
az account set --subscription "My Subscription"

# 3. Deploy (takes ~2 minutes)
az deployment sub create \
  --location eastus \
  --template-file infra/main.bicep
```

You can customize parameters inline:

```bash
az deployment sub create \
  --location eastus \
  --template-file infra/main.bicep \
  --parameters \
    resourceGroupName=rg-autoposter \
    location=eastus \
    openAiAccountName=oai-autoposter \
    deploymentName=gpt-5 \
    modelName=gpt-5 \
    capacityK=10
```

## Get your keys

After deployment, retrieve the endpoint and API key:

```bash
# Endpoint
az cognitiveservices account show \
  --name oai-autoposter \
  --resource-group rg-autoposter \
  --query properties.endpoint \
  --output tsv

# API key
az cognitiveservices account keys list \
  --name oai-autoposter \
  --resource-group rg-autoposter \
  --query key1 \
  --output tsv
```

## Configure autoposter

Set the environment variables for `devupdate`:

```bash
export AZURE_OPENAI_ENDPOINT=$(az cognitiveservices account show \
  --name oai-autoposter \
  --resource-group rg-autoposter \
  --query properties.endpoint --output tsv)

export AZURE_OPENAI_API_KEY=$(az cognitiveservices account keys list \
  --name oai-autoposter \
  --resource-group rg-autoposter \
  --query key1 --output tsv)

export DEVUPDATE_LLM_PROVIDER=azure_openai
```

Verify your `config.yaml` matches:

```yaml
llm:
  provider: azure_openai
  model: gpt-5
  azure_deployment: gpt-5          # must match deploymentName above
  azure_api_version: "2025-06-01"
```

Then run:

```bash
devupdate run --month 3 --year 2025
```

## One-liner setup

Copy-paste after deploy:

```bash
export AZURE_OPENAI_ENDPOINT=$(az cognitiveservices account show --name oai-autoposter --resource-group rg-autoposter --query properties.endpoint -o tsv)
export AZURE_OPENAI_API_KEY=$(az cognitiveservices account keys list --name oai-autoposter --resource-group rg-autoposter --query key1 -o tsv)
export DEVUPDATE_LLM_PROVIDER=azure_openai
```

## Tear down

```bash
az group delete --name rg-autoposter --yes --no-wait
```

## Costs

Azure OpenAI S0 tier has no base cost — you pay per token consumed. At 10K TPM capacity with occasional blog post generation, expect **< $1/month**.
