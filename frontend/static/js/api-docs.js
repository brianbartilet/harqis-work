/* Swagger stays on the authenticated dashboard origin. Never persist tokens. */
(() => {
  document.documentElement.classList.add('dark-mode');
  const config = JSON.parse(document.getElementById('api-docs-config').textContent);
  const status = document.getElementById('api-docs-status');
  window.harqisDocsRequest = request => {
    const target = new URL(request.url, location.href);
    if (target.origin !== location.origin) throw new Error('API testing is limited to this HARQIS host.');
    request.credentials = 'same-origin';
    if (!['GET', 'HEAD', 'OPTIONS'].includes((request.method || 'GET').toUpperCase())) {
      request.headers = request.headers || {};
      request.headers['X-CSRF-Token'] = config.csrf;
      const contentType = Object.entries(request.headers).find(([key]) => key.toLowerCase() === 'content-type')?.[1] || '';
      if (request.body instanceof FormData) request.body.set('csrf', config.csrf);
      else if (contentType.includes('application/x-www-form-urlencoded')) {
        const body = new URLSearchParams(request.body || '');
        body.set('csrf', config.csrf);
        request.body = body.toString();
      }
    }
    return request;
  };
  fetch('/openapi.json', {credentials: 'same-origin'}).then(async response => {
    if (!response.ok) throw new Error(response.status === 401 ? 'Your session expired. Sign in and reload this page.' : 'The API schema could not load. Reload to retry.');
    return response.json();
  }).then(spec => {
    const methods = new Set(['get', 'post', 'put', 'patch', 'delete', 'head', 'options']);
    const count = Object.values(spec.paths).reduce((total, path) => total + Object.keys(path).filter(key => methods.has(key)).length, 0);
    status.textContent = `${count} operations across ${Object.keys(spec.paths).length} paths · ${spec.tags.length} groups`;
    window.harqisSwagger = SwaggerUIBundle({
      spec, dom_id: '#swagger-ui', deepLinking: true, filter: true,
      docExpansion: 'none', defaultModelsExpandDepth: -1, displayRequestDuration: true,
      persistAuthorization: false, tryItOutEnabled: false, validatorUrl: null,
      operationsSorter: 'alpha', requestInterceptor: window.harqisDocsRequest,
      tagsSorter: (left, right) => spec.tags.findIndex(tag => tag.name === left) - spec.tags.findIndex(tag => tag.name === right),
      presets: [SwaggerUIBundle.presets.apis], layout: 'BaseLayout',
    });
  }).catch(error => { status.textContent = error.message; status.setAttribute('role', 'alert'); });
})();
