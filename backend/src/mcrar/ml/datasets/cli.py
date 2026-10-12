"""Dataset CLI commands; heavy models load only when embedding pending audio."""

from __future__ import annotations

from contextlib import contextmanager

import typer

from mcrar.config import get_settings

app = typer.Typer(no_args_is_help=True, help="Download and embed the pinned tagging datasets.")


@contextmanager
def cli_errors():
    try:
        yield
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command("download")
def download(name: str) -> None:
    """Download/check archives and extract metadata and audio (safe to resume)."""
    with cli_errors():
        from mcrar.ml.datasets.service import download_dataset

        provenance = download_dataset(get_settings(), name)
        typer.echo(f"{name}: downloaded and verified ({provenance['data_license']})")


@app.command("embed")
def embed(
    name: str,
    delete_audio: bool = typer.Option(False, "--delete-audio"),
    batch_size: int = typer.Option(32, min=1),
    device: str = "auto",
) -> None:
    """Embed with clap@195c3a3 and checkpoint before optionally deleting decoded audio."""
    with cli_errors():
        from threadpoolctl import threadpool_limits

        from mcrar.ml.datasets.embedding import EMBEDDER, embed_dataset
        from mcrar.ml.datasets.service import dataset_root, samples_for
        from mcrar.ml.embedders import load_embedder

        settings = get_settings()
        samples = samples_for(settings, name)
        output = dataset_root(settings, name) / f"embeddings/{EMBEDDER}.npz"
        embedder = load_embedder("clap", settings=settings, batch_size=batch_size, device=device)
        try:
            # Large BLAS/OpenMP thread pools spend more time coordinating these short-window
            # feature matrices than computing them. Bound CPU work while the GPU batches audio.
            with threadpool_limits(limits=4):
                report = embed_dataset(
                    samples,
                    embedder,
                    output,
                    delete_audio=delete_audio,
                    batch_size=batch_size,
                    progress=typer.echo,
                )
            typer.echo(
                f"{name}: {report['embedded']}/{report['total']} embedded, "
                f"{report['skipped']} corrupt/missing/short files skipped"
            )
            if not report["embedded"]:
                raise ValueError(
                    f"no audio could be embedded; inspect {output.with_suffix('.report.json')}"
                )
        finally:
            close = getattr(embedder, "close", None)
            if close:
                close()
