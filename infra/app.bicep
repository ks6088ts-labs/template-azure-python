param location string
param name string
param managedEnvironmentId string
param runtimeIdentityId string
param runtimeClientId string
param deployPrincipalId string
param image string
param environment string

@secure()
param connectionString string

param authClientId string
param authTenantId string
param authRequiredRole string
param externalIngress bool

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${runtimeIdentityId}': {} }
  }
  properties: {
    managedEnvironmentId: managedEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: externalIngress
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      secrets: [
        { name: 'insights-connection-string', value: connectionString }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'PROJECT_NAME', value: name }
            { name: 'APP_ENVIRONMENT', value: environment }
            { name: 'AUTH_MODE', value: 'easyauth' }
            { name: 'AUTH_REQUIRED_ROLE', value: authRequiredRole }
            { name: 'AZURE_CLIENT_ID', value: runtimeClientId }
            { name: 'TELEMETRY_ENABLED', value: 'true' }
            { name: 'TELEMETRY_USE_MANAGED_IDENTITY', value: 'true' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'insights-connection-string' }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/healthz', port: 8000 }
              initialDelaySeconds: 3
              periodSeconds: 5
              failureThreshold: 30
            }
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8000 }
              periodSeconds: 10
            }
            {
              type: 'Readiness'
              httpGet: { path: '/readyz', port: 8000 }
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
        }
      ]
      // The demo repository is process-local; use durable storage before scaling out.
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

resource auth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = {
  parent: app
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: {
      unauthenticatedClientAction: 'Return401'
      excludedPaths: ['/healthz', '/readyz']
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: authClientId
          openIdIssuer: '${az.environment().authentication.loginEndpoint}${authTenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [authClientId, 'api://${authClientId}']
        }
      }
    }
    httpSettings: { requireHttps: true }
  }
}

resource deployRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(app.id, deployPrincipalId, 'container-app-contributor')
  scope: app
  properties: {
    principalId: deployPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '358470bc-b998-42bd-ab17-a7e34c199c0f')
  }
}

output name string = app.name
output url string = 'https://${app.properties.configuration.ingress.fqdn}'
