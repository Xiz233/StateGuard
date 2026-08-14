# OSWorld deployment handoff

No source changes are required after external deployment:

1. Install OSWorld/OSWorld-Verified, Docker/VM images, and benchmark assets.
2. Set the benchmark path and start the environment provider.
3. Deploy the frozen Qwen3-VL-32B-Instruct OpenAI-compatible endpoint.
4. Export Guard and Executor endpoint/model/key environment variables.
5. Run `python scripts/check_readiness.py`.
6. Run `python scripts/prepare_osworld_poc.py --benchmark-root /path/to/OSWorld`.
7. Run `python scripts/prepare_task_graphs.py --manifest configs/poc/selected_tasks.yaml`.
8. Run `python scripts/review_task_graphs.py --manifest configs/poc/selected_tasks.yaml --reviewer NAME`.
9. Dry-run `scripts/run_poc_osworld.py` with `configs/poc/osworld_poc.yaml`.
10. Run a three-task smoke, then the full three-mode PoC.

Only `DesktopEnvBackend` may need version-specific API adaptation after installation.
