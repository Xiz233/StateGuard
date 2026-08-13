from __future__ import annotations

import argparse

from stateguard.models import OpenAICompatibleModelClient, load_model_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/models.yaml")
    parser.add_argument("--provider", default="stateguard_api")
    parser.add_argument("--image")
    args = parser.parse_args()
    client = OpenAICompatibleModelClient(load_model_config(args.config)[args.provider])
    response = client.generate([{"role": "user", "content": "Return {\"ok\": true}."}],
                               [args.image] if args.image else None, {"type": "object"})
    print("API reachable")
    print(f"model = {response.model}\nmultimodal = OK\nJSON parse = OK")
    print(f"latency = {response.latency_seconds:.3f}s")


if __name__ == "__main__":
    main()
