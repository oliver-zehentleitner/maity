### Security

- hub: `opentelemetry-api` 1.45.2 in the runtime and dev locks (was 1.45.1,
  which fastapi pulls in), for CVE-2026-126360: a ReDoS in
  `TraceContextTextMapPropagator.extract()` on a crafted `traceparent` value.
