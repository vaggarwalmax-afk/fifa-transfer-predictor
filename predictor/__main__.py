"""Command line: python -m predictor {fetch,train,all}."""

from __future__ import annotations

import argparse
import sys

import requests

from . import config
from .dataset import build_dataset, save_dataset
from .fetch import fetch_all
from .football_data import FootballDataError
from .model import save_model, train


def cmd_fetch(args: argparse.Namespace) -> None:
    fetch_all(
        api_key=config.api_key(),
        seasons=args.seasons,
        season_count=args.season_count,
        include_current=args.include_current,
        limit=args.limit,
        use_fpl=not args.no_fpl,
        refresh=args.refresh,
    )
    print(f"Raw data saved to {config.RAW_DIR}")


def cmd_train(args: argparse.Namespace) -> None:
    dataset = build_dataset()
    # Train before saving anything, so a failed run leaves the old dataset + model pair intact.
    model = train(dataset["players"], folds=args.folds)
    save_dataset(dataset)
    save_model(model)
    with_values = sum(1 for p in dataset["players"] if p["market_value_eur_m"])
    print(f"Dataset: {len(dataset['players'])} players, {with_values} with a market value "
          f"-> {config.PLAYERS_PATH}")
    if dataset["unmatched_market_values"]:
        print(f"  {len(dataset['unmatched_market_values'])} market-value rows had no stats match "
              f"(not in the fetched seasons' scorer lists): "
              f"{', '.join(dataset['unmatched_market_values'][:12])}"
              f"{' ...' if len(dataset['unmatched_market_values']) > 12 else ''}")

    m = model["metrics"]
    print(f"Model trained on {m['n_train']} players -> {config.MODEL_PATH}")
    print(f"  R^2 (log value): {m['r2_log_in_sample']:.2f} in-sample, {m['r2_log_cv']:.2f} "
          f"{m['folds']}-fold CV")
    print(f"  CV mean absolute error: EUR {m['mae_eur_m_cv']:.1f}m, median error "
          f"{m['median_abs_pct_error_cv']:.0%}")
    for name, why in model["dropped_features"].items():
        print(f"  ! {name} left out of the model: {why}")
    for effect in model["per_unit_effects"]:
        shown = "not used" if effect["dropped"] else f"{effect['pct']:+.1%}"
        print(f"    {effect['unit']:<28} {shown}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m predictor",
                                     description="Premier League transfer value predictor")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = argparse.ArgumentParser(add_help=False)
    fetch.add_argument("--seasons", type=int, nargs="+",
                       help="season start years, e.g. 2023 2024 2025 (default: last N completed)")
    fetch.add_argument("--season-count", type=int, default=config.DEFAULT_SEASON_COUNT,
                       help="how many recent seasons when --seasons is not given (default 3)")
    fetch.add_argument("--include-current", action="store_true",
                       help="also include the season in progress")
    fetch.add_argument("--limit", type=int, default=config.DEFAULT_SCORERS_LIMIT,
                       help="players per season from the scorers table (default 100)")
    fetch.add_argument("--no-fpl", action="store_true",
                       help="skip the FPL enrichment (minutes, availability, photos)")
    fetch.add_argument("--refresh", action="store_true", help="re-download cached FPL histories")

    trainp = argparse.ArgumentParser(add_help=False)
    trainp.add_argument("--folds", type=int, default=5, help="cross-validation folds (default 5)")

    sub.add_parser("fetch", parents=[fetch], help="download stats into data/raw/")
    sub.add_parser("train", parents=[trainp], help="build the dataset and train the model")
    sub.add_parser("all", parents=[fetch, trainp], help="fetch, then train")

    args = parser.parse_args(argv)
    try:
        if args.command in ("fetch", "all"):
            cmd_fetch(args)
        if args.command in ("train", "all"):
            cmd_train(args)
    except (FootballDataError, FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"Network error talking to football-data.org: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
