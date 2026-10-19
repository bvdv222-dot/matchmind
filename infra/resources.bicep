// All MatchMind resources in one resource group. Access is identity-based throughout: local auth is off on every
// data service, and the app's user-assigned identity gets only the data roles it needs.

param environmentName string
param location string
param tags object
param principalId string
param appExists bool
param deployFoundry bool
param fastModelName string
param fastModelVersion string
param fastModelCapacity int
param strongDeploymentName string
param eventHubsSku string

var token = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var eventHubName = 'match-feed'
var cosmosDatabase = 'matchmind'

// Built-in role ids
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  eventHubsSender: '2b629674-e913-4c01-ae53-ef4638d8f975'
  eventHubsReceiver: 'a638d3c7-ab3a-418d-83e6-5f17a39d4fde'
  webPubSubOwner: '12cf5a90-567b-43ae-8102-96cf46c7d9b4'
  azureAiUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
}

// ------------------------------------------------------------------ monitoring
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${token}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${token}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// ------------------------------------------------------------------ identity and registry
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${token}'
  location: location
  tags: tags
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cr${token}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, roles.acrPull)
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

// ------------------------------------------------------------------ Event Hubs: the live match feed
resource eventHubs 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: 'evhns-${token}'
  location: location
  tags: tags
  sku: { name: eventHubsSku, tier: eventHubsSku, capacity: 1 }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
  }
}

resource feed 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: eventHubs
  name: eventHubName
  properties: {
    partitionCount: 2
    messageRetentionInDays: 1
  }
}

resource ehSenderApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(eventHubs.id, identity.id, roles.eventHubsSender)
  scope: eventHubs
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.eventHubsSender)
  }
}

resource ehReceiverApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(eventHubs.id, identity.id, roles.eventHubsReceiver)
  scope: eventHubs
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.eventHubsReceiver)
  }
}

resource ehReceiverUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(eventHubs.id, principalId, roles.eventHubsReceiver)
  scope: eventHubs
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.eventHubsReceiver)
  }
}

// ------------------------------------------------------------------ Cosmos DB (serverless): notes, traces, questions
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: 'cosmos-${token}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    disableLocalAuth: true
    capabilities: [ { name: 'EnableServerless' } ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [ { locationName: location, failoverPriority: 0, isZoneRedundant: false } ]
    minimalTlsVersion: 'Tls12'
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: cosmosDatabase
  properties: {
    resource: { id: cosmosDatabase }
  }
}

resource cosmosContainers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [for c in [ 'notes', 'asks', 'matches' ]: {
  parent: cosmosDb
  name: c
  properties: {
    resource: {
      id: c
      partitionKey: { paths: [ '/match_id' ], kind: 'Hash' }
    }
  }
}]

// Cosmos data-plane RBAC: built-in Data Contributor
var cosmosContributor = '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'

resource cosmosApp 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, 'data-contributor')
  properties: {
    principalId: identity.properties.principalId
    roleDefinitionId: cosmosContributor
    scope: cosmos.id
  }
}

resource cosmosUser 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = if (!empty(principalId)) {
  parent: cosmos
  name: guid(cosmos.id, principalId, 'data-contributor')
  properties: {
    principalId: principalId
    roleDefinitionId: cosmosContributor
    scope: cosmos.id
  }
}

// ------------------------------------------------------------------ Web PubSub (for fan-out beyond one replica)
resource webPubSub 'Microsoft.SignalRService/webPubSub@2024-03-01' = {
  name: 'wps-${token}'
  location: location
  tags: tags
  sku: { name: 'Free_F1', capacity: 1 }
  properties: {
    disableLocalAuth: true
  }
}

resource wpsHub 'Microsoft.SignalRService/webPubSub/hubs@2024-03-01' = {
  parent: webPubSub
  name: 'matchmind'
  properties: {
    anonymousConnectPolicy: 'deny'
  }
}

resource wpsOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(webPubSub.id, identity.id, roles.webPubSubOwner)
  scope: webPubSub
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.webPubSubOwner)
  }
}

// ------------------------------------------------------------------ Microsoft Foundry: account, project, model
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = if (deployFoundry) {
  name: 'aif-${token}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'aif-${token}'
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = if (deployFoundry) {
  parent: foundry
  name: 'matchmind'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'MatchMind'
    description: 'Agents for live match intelligence'
  }
}

resource fastModel 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (deployFoundry) {
  parent: foundry
  name: fastModelName
  sku: { name: 'GlobalStandard', capacity: fastModelCapacity }
  properties: {
    model: { format: 'OpenAI', name: fastModelName, version: fastModelVersion }
  }
}

resource foundryAiUserApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployFoundry) {
  name: guid(resourceGroup().id, 'aif', identity.id, roles.azureAiUser)
  scope: foundry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.azureAiUser)
  }
}

resource foundryOpenAiApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployFoundry) {
  name: guid(resourceGroup().id, 'aif', identity.id, roles.openAiUser)
  scope: foundry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openAiUser)
  }
}

resource foundryAiUserDev 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployFoundry && !empty(principalId)) {
  name: guid(resourceGroup().id, 'aif', principalId, roles.azureAiUser)
  scope: foundry
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.azureAiUser)
  }
}

var foundryEndpoint = deployFoundry ? 'https://aif-${token}.services.ai.azure.com/api/projects/matchmind' : ''

// ------------------------------------------------------------------ Container Apps
resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${token}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// keep the deployed image when re-provisioning (azd sets appExists after the first deploy)
module current 'fetch-image.bicep' = if (appExists) {
  name: 'current-app-image'
  params: { name: 'ca-app-${token}' }
}

var image = appExists ? current!.outputs.image : 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-app-${token}'
  location: location
  tags: union(tags, { 'azd-service-name': 'app' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  dependsOn: [ acrPull ]
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [ { server: registry.properties.loginServer, identity: identity.id } ]
    }
    template: {
      containers: [
        {
          name: 'app'
          image: image
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'MM_HOST', value: '0.0.0.0' }
            { name: 'MM_PORT', value: '8000' }
            { name: 'MM_SELF_MCP_URL', value: 'http://127.0.0.1:8000/intel/mcp' }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
            { name: 'MM_AGENTS', value: deployFoundry ? 'on' : 'off' }
            { name: 'MM_AI_PROVIDER', value: 'foundry' }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryEndpoint }
            { name: 'FOUNDRY_FAST_DEPLOYMENT', value: deployFoundry ? fastModelName : '' }
            { name: 'FOUNDRY_STRONG_DEPLOYMENT', value: strongDeploymentName }
            { name: 'MM_STORE', value: 'cosmos' }
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'COSMOS_DATABASE', value: cosmosDatabase }
            { name: 'MM_BUS', value: 'eventhubs' }
            { name: 'EVENTHUBS_FQDN', value: '${eventHubs.name}.servicebus.windows.net' }
            { name: 'EVENTHUB_NAME', value: eventHubName }
            { name: 'WEBPUBSUB_ENDPOINT', value: 'https://${webPubSub.properties.hostName}' }
          ]
          probes: [
            { type: 'Liveness', httpGet: { path: '/api/health', port: 8000 }, initialDelaySeconds: 15, periodSeconds: 30 }
            { type: 'Readiness', httpGet: { path: '/api/health', port: 8000 }, initialDelaySeconds: 5, periodSeconds: 10 }
          ]
        }
      ]
      // live match state is in process: one replica, always on, so judges never hit a cold start
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

output registryLoginServer string = registry.properties.loginServer
output registryName string = registry.name
output appName string = app.name
output appUri string = 'https://${app.properties.configuration.ingress.fqdn}'
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output eventHubsFqdn string = '${eventHubs.name}.servicebus.windows.net'
output eventHubName string = eventHubName
output webPubSubEndpoint string = 'https://${webPubSub.properties.hostName}'
output foundryProjectEndpoint string = foundryEndpoint
output foundryFastDeployment string = deployFoundry ? fastModelName : ''
