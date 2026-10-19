// MatchMind on Azure: one resource group with the app and its services, plus a subscription budget alert.
// Deployed by `azd up`; every service is reached with the app's managed identity (no keys).
targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd environment name; used to name the resource group and resources')
param environmentName string

@minLength(1)
@description('Azure region for all resources')
param location string

@description('Object id of the person running azd (gets data access for local development); empty to skip')
param principalId string = ''

@description('Set by azd: true once the app has been deployed, so re-provisioning keeps the current image')
param appExists bool = false

@description('Create a Microsoft Foundry account and project with a model deployment for the agents')
param deployFoundry bool = true

@description('Foundry model for the fast agent tier (Narrator, Personaliser, Translator)')
param fastModelName string = 'gpt-4.1-mini'
param fastModelVersion string = '2025-04-14'
@description('Tokens-per-minute capacity in thousands for the fast model')
param fastModelCapacity int = 50

@description('Deployment name of the strong-tier model (e.g. a Claude deployment added through the Marketplace); empty = use the fast model')
param strongDeploymentName string = ''

@allowed([ 'Basic', 'Standard' ])
@description('Event Hubs tier: Basic is enough for the app; Standard if Fabric Real-Time Intelligence will read the feed')
param eventHubsSku string = 'Basic'

@description('Monthly budget for the subscription in the billing currency; 0 skips the budget')
param budgetAmount int = 100
@description('Email for budget alerts; empty skips the budget')
param budgetEmail string = ''
param budgetStartDate string = utcNow('yyyy-MM-01')

var tags = { 'azd-env-name': environmentName, project: 'matchmind' }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'resources'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    tags: tags
    principalId: principalId
    appExists: appExists
    deployFoundry: deployFoundry
    fastModelName: fastModelName
    fastModelVersion: fastModelVersion
    fastModelCapacity: fastModelCapacity
    strongDeploymentName: strongDeploymentName
    eventHubsSku: eventHubsSku
  }
}

// Alert at 50%, 80% and 100% of the monthly budget (actual spend) and at 100% forecast.
resource budget 'Microsoft.Consumption/budgets@2023-11-01' = if (budgetAmount > 0 && !empty(budgetEmail)) {
  name: 'budget-${environmentName}'
  properties: {
    category: 'Cost'
    amount: budgetAmount
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStartDate }
    notifications: {
      actual50: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 50, contactEmails: [ budgetEmail ], thresholdType: 'Actual' }
      actual80: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 80, contactEmails: [ budgetEmail ], thresholdType: 'Actual' }
      actual100: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, contactEmails: [ budgetEmail ], thresholdType: 'Actual' }
      forecast100: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, contactEmails: [ budgetEmail ], thresholdType: 'Forecasted' }
    }
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.registryLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = resources.outputs.registryName
output SERVICE_APP_NAME string = resources.outputs.appName
output SERVICE_APP_URI string = resources.outputs.appUri
output APPLICATIONINSIGHTS_CONNECTION_STRING string = resources.outputs.appInsightsConnectionString
output COSMOS_ENDPOINT string = resources.outputs.cosmosEndpoint
output EVENTHUBS_FQDN string = resources.outputs.eventHubsFqdn
output EVENTHUB_NAME string = resources.outputs.eventHubName
output WEBPUBSUB_ENDPOINT string = resources.outputs.webPubSubEndpoint
output FOUNDRY_PROJECT_ENDPOINT string = resources.outputs.foundryProjectEndpoint
output FOUNDRY_FAST_DEPLOYMENT string = resources.outputs.foundryFastDeployment
output MM_MCP_URL string = '${resources.outputs.appUri}/intel/mcp'
