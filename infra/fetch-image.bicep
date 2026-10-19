// The image the existing container app runs, so `azd provision` after a deploy doesn't roll it back.
param name string

resource app 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: name
}

output image string = app.properties.template.containers[0].image
