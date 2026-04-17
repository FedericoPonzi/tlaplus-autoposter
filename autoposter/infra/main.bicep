// Autoposter — Azure OpenAI infrastructure
//
// Deploys a resource group with an Azure OpenAI account and a GPT-4o deployment.
// Usage:
//   az deployment sub create --location eastus --template-file main.bicep

targetScope = 'subscription'

@description('Name of the resource group to create.')
param resourceGroupName string = 'rg-autoposter'

@description('Azure region for all resources.')
param location string = 'eastus'

@description('Name of the Azure OpenAI account.')
param openAiAccountName string = 'oai-autoposter'

@description('Name of the model deployment.')
param deploymentName string = 'gpt-5-1'

@description('OpenAI model to deploy.')
param modelName string = 'gpt-5.1'

@description('Model version.')
param modelVersion string = '2025-11-13'

@description('Tokens-per-minute capacity (in thousands). 1 = 1K TPM.')
param capacityK int = 10

// ---------------------------------------------------------------------------
// Resource Group
// ---------------------------------------------------------------------------

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
}

// ---------------------------------------------------------------------------
// Azure OpenAI (module scoped to the resource group)
// ---------------------------------------------------------------------------

module openai 'openai.bicep' = {
  name: 'openai-deployment'
  scope: rg
  params: {
    location: location
    accountName: openAiAccountName
    deploymentName: deploymentName
    modelName: modelName
    modelVersion: modelVersion
    capacityK: capacityK
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output resourceGroupName string = rg.name
output openAiEndpoint string = openai.outputs.endpoint
output openAiAccountName string = openai.outputs.accountName
