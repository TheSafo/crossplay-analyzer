// Public browser credentials, NOT DD_API_KEY / DD_APP_KEY. Fill in both values
// from a Datadog Browser RUM application on us5.datadoghq.com to enable monitoring.
(() => {
  const applicationId = 'REPLACE_WITH_DATADOG_RUM_APPLICATION_ID';
  const clientToken = 'REPLACE_WITH_DATADOG_RUM_CLIENT_TOKEN';

  // Keep local/offline use and deployments without credentials working without
  // loading the CDN or sending telemetry with placeholder credentials.
  if (!applicationId || !clientToken ||
      applicationId.startsWith('REPLACE_WITH_') || clientToken.startsWith('REPLACE_WITH_')) return;

  window.DD_RUM = window.DD_RUM || {
    q: [],
    onReady(callback) { this.q.push(callback); }
  };
  window.DD_RUM.onReady(() => {
    window.DD_RUM.init({
      applicationId,
      clientToken,
      site: 'us5.datadoghq.com',
      service: 'crossplay-analyzer',
      env: 'production',
      sessionSampleRate: 100,
      // NYT-S is a credential: mask all content, including every form input.
      // Replay stays off; do not call startSessionReplayRecording().
      defaultPrivacyLevel: 'mask',
      sessionReplaySampleRate: 0,
      trackUserInteractions: false,
      trackResources: true,
      trackLongTasks: true,
      traceSampleRate: 100,
      allowedTracingUrls: [{
        match(url) {
          const target = new URL(url, window.location.origin);
          return target.origin === window.location.origin &&
            (target.pathname === '/api/crossplay' || target.pathname.startsWith('/api/crossplay/'));
        },
        propagatorTypes: ['datadog', 'tracecontext']
      }]
    });
  });

  const sdk = document.createElement('script');
  sdk.async = true;
  sdk.src = 'https://www.datadoghq-browser-agent.com/us5/v6/datadog-rum.js';
  document.head.appendChild(sdk);
})();
