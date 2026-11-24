import argparse
import asyncio

from .runner import run


def main():
    parser = argparse.ArgumentParser(
        description="Run independent two-turn A2A agent evaluations and publish to Phoenix"
    )
    parser.add_argument(
        "--suite",
        choices=["all", "smoke", "inventory", "distribution", "coordinator"],
        default="all",
    )
    parser.add_argument("--only", help="Comma-separated scenario IDs or role/scenario-ID selectors")
    parser.add_argument("--max-cost-usd", type=float, default=15)
    parser.add_argument("--deadline-seconds", type=float, default=7200)
    parser.add_argument("--backend", choices=["fixture", "bigquery"], default="fixture")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--phoenix-url", default="http://127.0.0.1:6006")
    parser.add_argument("--publish-only", action="store_true")
    parser.add_argument("--agent-budget-usd", type=float, default=2.0)
    args = parser.parse_args()
    _, code = asyncio.run(run(**vars(args)))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
