// Azure OpenAI account + model deployment
//
// Deployed as a module from main.bicep, scoped to the target resource group.

@description('Azure region.')
param location string

@description('Name of the Cognitive Services account.')
param accountName string

@description('Name of the model deployment.')
param deploymentName string

@description('Model to deploy (e.g. gpt-4o).')
param modelName string

@description('Model version.')
param modelVersion string

@description('Tokens-per-minute capacity in thousands.')
param capacityK int

// ---------------------------------------------------------------------------
// Azure OpenAI account (Cognitive Services kind: OpenAI)
// ---------------------------------------------------------------------------

resource openAi 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' = {
  name: accountName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
  }
}

// ---------------------------------------------------------------------------
// Model deployment
// ---------------------------------------------------------------------------

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2024-04-01-preview' = {
  parent: openAi
  name: deploymentName
  sku: {
    name: 'Standard'
    capacity: capacityK
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output endpoint string = openAi.properties.endpoint
output accountName string = openAi.name
