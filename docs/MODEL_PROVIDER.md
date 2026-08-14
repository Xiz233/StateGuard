# Model providers

Both Guard and Executor use `MultimodalModelClient`. Copy `configs/models.example.yaml`
to `configs/models.yaml`; keep keys only in `STATEGUARD_API_KEY` and `EXECUTOR_API_KEY`.
Endpoints and models come from the corresponding `*_BASE_URL` and `*_MODEL` variables.

The OpenAI-compatible client posts to `/chat/completions`, encodes local images only at
request time, applies timeout/retry/backoff, requests JSON objects, and raises explicit
errors for HTTP, timeout, empty, malformed transport JSON, or malformed model JSON.
Executor and Guard each allow one schema-correction retry.
