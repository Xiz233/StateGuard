# Model providers

Both Guard and Executor use `MultimodalModelClient`. Copy `configs/models.example.yaml`
to `configs/models.yaml`; keep keys only in `OPENCODE_GO_API_KEY` and
`EXECUTOR_API_KEY`. The OpenCode Guard endpoint and model are fixed in YAML; Executor
endpoint and model come from the corresponding environment variables.

The OpenAI-compatible client posts to `/chat/completions`. The Anthropic-compatible
client posts to `/messages`; it is used by OpenCode Go Qwen3.7 Plus. Both encode local
images only at request time, apply timeout/retry/backoff, and raise explicit errors
for HTTP, timeout, empty, malformed transport JSON, or malformed model JSON.
