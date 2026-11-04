# Model API configuration

Copy `configs/models.example.yaml` to `configs/models.yaml`. Endpoints and model IDs
may be selected in YAML, but credentials are read only from the named environment
variables. OpenAI-compatible providers call `{base_url}/chat/completions` and encode
screenshots as data URLs. All clients retry with exponential backoff and raise
explicit exceptions for HTTP, empty, or malformed JSON responses.

Provider type `anthropic_compatible` calls `{base_url}/messages`, authenticates with
`x-api-key`, and sends screenshots as Anthropic base64 image blocks. The checked-in
example config uses OpenCode Go Qwen3.7 Plus as the Guard:

```text
base_url: https://opencode.ai/zen/go/v1
model: qwen3.7-plus
api_key_env: OPENCODE_GO_API_KEY
```

Only the secret value is supplied at runtime. Do not commit `configs/models.yaml`
or an API key.
