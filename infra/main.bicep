targetScope = 'resourceGroup'

param location string = resourceGroup().location

@minLength(3)
@maxLength(16)
param namePrefix string

@allowed(['staging', 'production'])
param environment string

@description('GitHub owner/repository used in the environment-scoped OIDC subject.')
param githubRepository string

@description('Immutable, public GHCR image: ghcr.io/owner/repo@sha256:<64 lowercase hex digits>.')
@minLength(80)
param image string

@description('Entra application registration client ID. Configure an application role for API callers.')
@minLength(36)
@maxLength(36)
param authClientId string

param authRequiredRole string = 'Task.ReadWrite'

@description('Leave false on first deployment. Bootstrap opens ingress only after Easy Auth is configured.')
param externalIngress bool = false

var suffix = uniqueString(resourceGroup().id)
var metricsPublisherRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
var acrPullRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-${environment}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${namePrefix}-${environment}-insights'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    DisableLocalAuth: true
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: '${namePrefix}${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

resource runtimeIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-${environment}-runtime'
  location: location
}

resource deployIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-${environment}-deploy'
  location: location
}

resource federation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: deployIdentity
  name: 'github-${environment}'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:environment:${environment}'
    audiences: ['api://AzureADTokenExchange']
  }
}

resource metricsPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(insights.id, runtimeIdentity.id, metricsPublisherRole)
  scope: insights
  properties: {
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: metricsPublisherRole
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, runtimeIdentity.id, acrPullRole)
  scope: registry
  properties: {
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRole
  }
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-${environment}-environment'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
  }
}

module app 'app.bicep' = {
  name: 'app-${environment}'
  params: {
    location: location
    name: '${namePrefix}-${environment}'
    managedEnvironmentId: managedEnvironment.id
    runtimeIdentityId: runtimeIdentity.id
    runtimeClientId: runtimeIdentity.properties.clientId
    deployPrincipalId: deployIdentity.properties.principalId
    image: image
    environment: environment
    connectionString: insights.properties.ConnectionString
    authClientId: authClientId
    authTenantId: tenant().tenantId
    authRequiredRole: authRequiredRole
    externalIngress: externalIngress
  }
}

output containerAppName string = app.outputs.name
output containerAppUrl string = app.outputs.url
output deployClientId string = deployIdentity.properties.clientId
output tenantId string = tenant().tenantId
output subscriptionId string = subscription().subscriptionId
output resourceGroupName string = resourceGroup().name
output registryLoginServer string = registry.properties.loginServer
