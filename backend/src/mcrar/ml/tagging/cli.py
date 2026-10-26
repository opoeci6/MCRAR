"""Tagging CLI registrations; catalog tagging never loads audio or model frameworks."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from mcrar.config import get_settings
from mcrar.console import echo
from mcrar.ml.datasets.cli import cli_errors

app = typer.Typer(no_args_is_help=True, help="Train, evaluate and select portable taggers.")


@app.command("train")
def train(
    label_set: str, variant: str = "mlp", seed: int = 0, epochs: int = typer.Option(100, min=1)
) -> None:
    """Train and evaluate a head or zero-shot variant on the prescribed dataset split."""
    from threadpoolctl import threadpool_limits

    from mcrar.ml.tagging.service import train_entry

    with cli_errors():
        typer.echo(f"Training {label_set}/{variant} (seed {seed})")
        with threadpool_limits(limits=4):
            entry = train_entry(get_settings(), label_set, variant, seed=seed, epochs=epochs)
        typer.echo(entry["id"])
        typer.echo(json.dumps(entry["metrics"], indent=2))


@app.command("evaluate")
def evaluate(label_sets: Annotated[list[str] | None, typer.Argument()] = None) -> None:
    """Evaluate every registered entry on its test split, with 1,000 bootstrap resamples."""
    from mcrar.ml.tagging.service import evaluate_entries

    with cli_errors():
        result, output = evaluate_entries(get_settings(), label_sets)
        typer.echo(json.dumps(result, indent=2))
        typer.echo(f"Wrote {output}")


@app.command("select")
def select() -> None:
    """Record and print the entry with the highest test primary metric for each label set."""
    from mcrar.ml.tagging.service import selected_entries

    with cli_errors():
        for name, identity in selected_entries(get_settings()).items():
            typer.echo(f"{name}: {identity or 'no entry'}")


def tag(
    label_sets: str | None = typer.Option(None, "--label-sets"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Tag the catalog from stored embeddings, with no network or audio downloads."""
    from mcrar.catalog import open_catalog
    from mcrar.ingest import reprocess_catalog
    from mcrar.ml.tagging import tagging_stages
    from mcrar.recommend.vocab import LABEL_SETS

    with cli_errors():
        settings = get_settings()
        stages = tagging_stages(settings)
        if label_sets:
            wanted = set(label_sets.replace(",", " ").split())
            # the trained sets, the vocabulary's (genre, moodtheme, scene) and any in the registry
            known = {"valence", "arousal", *LABEL_SETS, *(s.tagger.label_set for s in stages)}
            unknown = wanted - known
            if unknown:
                raise ValueError(f"unknown label sets: {', '.join(sorted(unknown))}")
            stages = [s for s in stages if s.tagger.label_set in wanted]
        if not stages:
            typer.echo("No tagging entries are available for the selected label sets.")
            return

        def progress(event) -> None:
            echo(f"[{event.index}/{event.total}] {event.kind}: {event.title}")

        with open_catalog(settings) as repo:
            report = reprocess_catalog(repo, stages=stages, force=force, on_progress=progress)
            typer.echo(
                f"Tagged {report.processed}; skipped {report.skipped}; failed {report.failed}"
            )
            for failure in report.failures:
                echo(f"error: {failure.message}", err=True)
            if report.failed or report.aborted:
                raise ValueError(report.aborted or "some catalog tracks could not be tagged")
