"""Command-line interface for the Vintage TV Commercial Downloader."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

from .catalog import Catalog
from .sources import archive_org, youtube
from .downloader import download

console = Console()


@click.group()
@click.option("--db", default="catalog.db", help="Path to catalog database.")
@click.pass_context
def cli(ctx, db):
    """Vintage TV Commercial Downloader

    Search, download, and catalog retro TV commercials from the 1980s and 1990s.
    """
    ctx.ensure_object(dict)
    ctx.obj["catalog"] = Catalog(db)


@cli.command()
@click.argument("query")
@click.option("--decade", type=click.Choice(["1980s", "1990s", "1970s"]), help="Filter by decade.")
@click.option("--source", type=click.Choice(["all", "archive", "youtube"]), default="all",
              help="Which source to search.")
@click.option("--max-results", "-n", default=15, help="Max results per source.")
@click.pass_context
def search(ctx, query, decade, source, max_results):
    """Search for vintage TV commercials.

    Examples:
        vintage-commercials search "coca cola"
        vintage-commercials search "cereal" --decade 1980s
        vintage-commercials search "nike" --source youtube
    """
    catalog = ctx.obj["catalog"]
    all_results = []

    with console.status("[bold green]Searching for vintage commercials..."):
        if source in ("all", "archive"):
            console.print("[dim]Searching Internet Archive...[/dim]")
            results = archive_org.search(query, decade=decade, max_results=max_results)
            all_results.extend(results)
            console.print(f"  Found {len(results)} results on archive.org")

        if source in ("all", "youtube"):
            console.print("[dim]Searching YouTube...[/dim]")
            results = youtube.search(query, decade=decade, max_results=max_results)
            all_results.extend(results)
            console.print(f"  Found {len(results)} results on YouTube")

    if not all_results:
        console.print("[yellow]No results found. Try different search terms.[/yellow]")
        return

    # Display results
    table = Table(title=f"Search Results for '{query}'", show_lines=True)
    table.add_column("#", style="bold", width=4)
    table.add_column("Source", width=10)
    table.add_column("Title", max_width=50)
    table.add_column("Year", width=6)
    table.add_column("In Catalog", width=10)

    for i, r in enumerate(all_results, 1):
        in_catalog = "Yes" if catalog.exists(r["source_url"]) else ""
        table.add_row(
            str(i),
            r["source"],
            r["title"][:50],
            r.get("year_estimate") or "?",
            in_catalog,
        )

    console.print(table)

    # Offer to catalog/download
    console.print(f"\n[bold]Enter numbers to download (e.g. 1,3,5) or 'all' or 'q' to quit:[/bold]")
    selection = click.prompt("Selection", default="q")

    if selection.lower() == "q":
        return

    if selection.lower() == "all":
        indices = list(range(len(all_results)))
    else:
        try:
            indices = [int(x.strip()) - 1 for x in selection.split(",")]
        except ValueError:
            console.print("[red]Invalid selection.[/red]")
            return

    for idx in indices:
        if idx < 0 or idx >= len(all_results):
            console.print(f"[yellow]Skipping invalid index {idx + 1}[/yellow]")
            continue

        result = all_results[idx]
        console.print(f"\n[bold]Downloading:[/bold] {result['title']}")

        # Add to catalog first
        catalog.add(
            title=result["title"],
            source=result["source"],
            source_url=result["source_url"],
            year_estimate=result.get("year_estimate"),
            decade=result.get("decade"),
            description=result.get("description"),
            duration_seconds=result.get("duration_seconds"),
            thumbnail_url=result.get("thumbnail_url"),
            metadata=result,
        )

        # Download
        filepath = download(result["source_url"])
        if filepath:
            catalog.mark_downloaded(result["source_url"], filepath)
            console.print(f"  [green]Saved:[/green] {filepath}")
        else:
            console.print(f"  [red]Download failed[/red]")

    console.print("\n[bold green]Done![/bold green]")


@cli.command()
@click.argument("url")
@click.option("--title", help="Override the title in the catalog.")
@click.option("--decade", help="Decade tag (e.g. 1980s).")
@click.option("--brand", help="Brand name.")
@click.pass_context
def grab(ctx, url, title, decade, brand):
    """Download a specific commercial by URL and add it to the catalog.

    Examples:
        vintage-commercials grab "https://www.youtube.com/watch?v=abc123"
        vintage-commercials grab "https://archive.org/details/some-commercial" --brand "Pepsi" --decade 1980s
    """
    catalog = ctx.obj["catalog"]

    if catalog.exists(url):
        console.print("[yellow]Already in catalog. Downloading anyway...[/yellow]")

    console.print(f"[bold]Downloading:[/bold] {url}")
    filepath = download(url)

    if filepath:
        catalog.add(
            title=title or url.split("/")[-1],
            source="youtube" if "youtube" in url or "youtu.be" in url else "archive.org" if "archive.org" in url else "other",
            source_url=url,
            file_path=filepath,
            decade=decade,
            brand=brand,
        )
        console.print(f"[green]Saved and cataloged:[/green] {filepath}")
    else:
        console.print("[red]Download failed.[/red]")


@cli.command("list")
@click.option("--decade", type=click.Choice(["1980s", "1990s", "1970s"]))
@click.option("--brand", help="Filter by brand name.")
@click.option("--downloaded", is_flag=True, help="Only show downloaded items.")
@click.option("--query", "-q", help="Search within catalog.")
@click.pass_context
def list_catalog(ctx, decade, brand, downloaded, query):
    """List commercials in the catalog."""
    catalog = ctx.obj["catalog"]
    results = catalog.search(query=query, decade=decade, brand=brand, downloaded_only=downloaded)

    if not results:
        console.print("[yellow]No items found in catalog.[/yellow]")
        return

    table = Table(title="Catalog", show_lines=True)
    table.add_column("ID", width=4)
    table.add_column("Title", max_width=45)
    table.add_column("Source", width=10)
    table.add_column("Year", width=6)
    table.add_column("Decade", width=8)
    table.add_column("Brand", width=12)
    table.add_column("Downloaded", width=10)

    for r in results:
        table.add_row(
            str(r["id"]),
            (r["title"] or "")[:45],
            r["source"],
            r.get("year_estimate") or "?",
            r.get("decade") or "?",
            r.get("brand") or "",
            "Yes" if r.get("file_path") else "No",
        )

    console.print(table)


@cli.command()
@click.pass_context
def stats(ctx):
    """Show catalog statistics."""
    catalog = ctx.obj["catalog"]
    s = catalog.stats()

    panel_text = f"""
[bold]Total cataloged:[/bold]  {s['total_cataloged']}
[bold]Total downloaded:[/bold] {s['total_downloaded']}

[bold]By Decade:[/bold]
"""
    for decade, count in s.get("by_decade", {}).items():
        panel_text += f"  {decade}: {count}\n"

    panel_text += "\n[bold]By Source:[/bold]\n"
    for source, count in s.get("by_source", {}).items():
        panel_text += f"  {source}: {count}\n"

    console.print(Panel(panel_text, title="Catalog Stats", expand=False))


@cli.command()
@click.argument("query")
@click.option("--decade", type=click.Choice(["1980s", "1990s", "1970s"]), default=None)
@click.option("--source", type=click.Choice(["all", "archive", "youtube"]), default="all")
@click.option("--max-results", "-n", default=25)
@click.pass_context
def scan(ctx, query, decade, source, max_results):
    """Scan and catalog commercials WITHOUT downloading (catalog-only mode).

    Great for building up your catalog first, then selectively downloading later.

    Examples:
        vintage-commercials scan "fast food" --decade 1980s
        vintage-commercials scan "toy commercial" --decade 1990s --source archive
    """
    catalog = ctx.obj["catalog"]
    all_results = []

    with console.status("[bold green]Scanning for vintage commercials..."):
        if source in ("all", "archive"):
            results = archive_org.search(query, decade=decade, max_results=max_results)
            all_results.extend(results)

        if source in ("all", "youtube"):
            results = youtube.search(query, decade=decade, max_results=max_results)
            all_results.extend(results)

    new_count = 0
    for r in all_results:
        if not catalog.exists(r["source_url"]):
            catalog.add(
                title=r["title"],
                source=r["source"],
                source_url=r["source_url"],
                year_estimate=r.get("year_estimate"),
                decade=r.get("decade"),
                description=r.get("description"),
                duration_seconds=r.get("duration_seconds"),
                thumbnail_url=r.get("thumbnail_url"),
                metadata=r,
            )
            new_count += 1

    console.print(
        f"[bold green]Scan complete:[/bold green] "
        f"Found {len(all_results)} results, added {new_count} new entries to catalog."
    )


def main():
    cli()


if __name__ == "__main__":
    main()
