# Model API configuration

Copy `configs/models.example.yaml` to `configs/models.yaml`. Endpoints and model IDs
may be selected in YAML, but credentials are read only from the named environment
variables. The client calls `{base_url}/chat/completions`, converts screenshot paths
to data URLs only for requests, retries with exponential backoff, and raises explicit
exceptions for HTTP, empty, or malformed JSON responses.
