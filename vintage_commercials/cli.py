"""Command-line interface for the Vintage TV Commercial Downloader."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from .catalog import Catalog
from .sources import archive_org, youtube
from .downloader import download
from .utils import catalog_add_result

console = Console()


def _parse_keywords(keywords: str) -> list[str]:
    """Parse a comma-separated keyword string into a list of search terms.

    Supports:
        "coca cola, pepsi, dr pepper"
        "cereal"
        "nike, reebok, adidas"
    """
    return [k.strip() for k in keywords.split(",") if k.strip()]


def _parse_years(years_str: str) -> tuple[int | None, int | None]:
    """Parse a year or year range string.

    Supports:
        "1985"       -> (1985, 1985)
        "1985-1992"  -> (1985, 1992)
        "1980-1989"  -> (1980, 1989)
    """
    if not years_str:
        return None, None

    if "-" in years_str:
        parts = years_str.split("-", 1)
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            return None, None
    else:
        try:
            y = int(years_str.strip())
            return y, y
        except ValueError:
            return None, None


def _do_search(query: str, source: str, decade: str = None,
               year_from: int = None, year_to: int = None,
               max_results: int = 15) -> list[dict]:
    """Run a search across selected sources. Returns combined results."""
    all_results = []

    if source in ("all", "archive"):
        results = archive_org.search(query, decade=decade,
                                     year_from=year_from, year_to=year_to,
                                     max_results=max_results)
        all_results.extend(results)

    if source in ("all", "youtube"):
        results = youtube.search(query, decade=decade,
                                 year_from=year_from, year_to=year_to,
                                 max_results=max_results)
        all_results.extend(results)

    return all_results


@click.group()
@click.option("--db", default="catalog.db", help="Path to catalog database.")
@click.pass_context
def cli(ctx, db):
    """Vintage TV Commercial Downloader

    Search, download, and catalog retro TV commercials from the 1980s and 1990s.

    Most commands accept multiple keywords (comma-separated) and year ranges.
    """
    ctx.ensure_object(dict)
    ctx.obj["catalog"] = Catalog(db)


@cli.command()
@click.argument("keywords")
@click.option("--decade", type=click.Choice(["1970s", "1980s", "1990s"]), help="Filter by decade.")
@click.option("--years", help="Year or year range, e.g. '1985' or '1983-1991'.")
@click.option("--source", type=click.Choice(["all", "archive", "youtube"]), default="all",
              help="Which source to search.")
@click.option("--max-results", "-n", default=15, help="Max results per source per keyword.")
@click.pass_context
def search(ctx, keywords, decade, years, source, max_results):
    """Search for vintage TV commercials.

    KEYWORDS can be comma-separated for multiple searches:

    \b
    Examples:
        vintage-commercials search "coca cola"
        vintage-commercials search "coca cola, pepsi, dr pepper"
        vintage-commercials search "cereal" --decade 1980s
        vintage-commercials search "nike" --years 1987-1993
        vintage-commercials search "fast food, soda, candy" --years 1985-1989
    """
    catalog = ctx.obj["catalog"]
    year_from, year_to = _parse_years(years)
    terms = _parse_keywords(keywords)
    all_results = []

    with console.status("[bold green]Searching for vintage commercials..."):
        for term in terms:
            console.print(f"[dim]Searching for '{term}'...[/dim]")
            results = _do_search(term, source, decade=decade,
                                 year_from=year_from, year_to=year_to,
                                 max_results=max_results)
            all_results.extend(results)
            console.print(f"  Found {len(results)} results")

    if not all_results:
        console.print("[yellow]No results found. Try different search terms.[/yellow]")
        return

    # Deduplicate by source_url
    seen = set()
    unique_results = []
    for r in all_results:
        if r["source_url"] not in seen:
            seen.add(r["source_url"])
            unique_results.append(r)
    all_results = unique_results

    # Display results
    label = ", ".join(terms)
    table = Table(title=f"Search Results for '{label}'", show_lines=True)
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

        catalog_add_result(catalog, result)

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

    \b
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
@click.option("--decade", type=click.Choice(["1970s", "1980s", "1990s"]))
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
@click.argument("keywords")
@click.option("--decade", type=click.Choice(["1970s", "1980s", "1990s"]), default=None)
@click.option("--years", help="Year or year range, e.g. '1985' or '1983-1991'.")
@click.option("--source", type=click.Choice(["all", "archive", "youtube"]), default="all")
@click.option("--max-results", "-n", default=25)
@click.pass_context
def scan(ctx, keywords, decade, years, source, max_results):
    """Scan and catalog commercials WITHOUT downloading (catalog-only mode).

    KEYWORDS can be comma-separated for multiple searches.
    Great for building up your catalog first, then selectively downloading later.

    \b
    Examples:
        vintage-commercials scan "fast food" --decade 1980s
        vintage-commercials scan "toy, cereal, candy" --decade 1990s
        vintage-commercials scan "soda" --years 1985-1992
        vintage-commercials scan "car, truck, van" --years 1980-1999
    """
    catalog = ctx.obj["catalog"]
    year_from, year_to = _parse_years(years)
    terms = _parse_keywords(keywords)
    total_found = 0
    new_count = 0

    for term in terms:
        console.print(f"[dim]Scanning for '{term}'...[/dim]")
        results = _do_search(term, source, decade=decade,
                             year_from=year_from, year_to=year_to,
                             max_results=max_results)
        total_found += len(results)

        for r in results:
            if catalog_add_result(catalog, r) is not None:
                new_count += 1

        console.print(f"  Found {len(results)} results")

    console.print(
        f"\n[bold green]Scan complete:[/bold green] "
        f"Searched {len(terms)} keyword(s), found {total_found} results, "
        f"added {new_count} new entries to catalog."
    )


@cli.command()
@click.option("--decades", default="1980s,1990s",
              help="Comma-separated decades to search, e.g. '1980s,1990s'.")
@click.option("--years", help="Year range overriding decades, e.g. '1982-1995'.")
@click.option("--source", type=click.Choice(["all", "archive", "youtube"]), default="all")
@click.option("--max-results", "-n", default=20, help="Max results per keyword per source.")
@click.option("--no-download", is_flag=True, help="Only catalog, skip downloading.")
@click.option("--keywords-file", type=click.Path(exists=True),
              help="Load keywords from a text file (one per line).")
@click.argument("keywords", required=False)
@click.pass_context
def batch(ctx, decades, years, source, max_results, no_download, keywords_file, keywords):
    """Batch search across many keywords and/or years at once.

    Catalogs all results first, then automatically downloads them.
    Without any keywords, uses built-in categories covering common
    80s/90s commercial types.

    \b
    Examples:
        # Search built-in categories across 80s and 90s (catalog + download):
        vintage-commercials batch

        # Custom keywords across both decades:
        vintage-commercials batch "coca cola, pepsi, sprite, 7up"

        # Specific year range:
        vintage-commercials batch "nike, reebok" --years 1987-1993

        # Load keywords from a file:
        vintage-commercials batch --keywords-file my_brands.txt

        # Only catalog, don't download:
        vintage-commercials batch --decades 1980s --no-download
    """
    catalog = ctx.obj["catalog"]

    # Collect keywords from all inputs
    terms = []
    if keywords:
        terms.extend(_parse_keywords(keywords))
    if keywords_file:
        with open(keywords_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    terms.append(line)

    # Default keyword list if none provided — covers common 80s/90s commercial types
    if not terms:
        terms = [
            "TV commercial",
            "cereal commercial",
            "fast food commercial",
            "soda commercial",
            "toy commercial",
            "car commercial",
            "beer commercial",
            "sneakers commercial",
            "candy commercial",
            "video game commercial",
            "Saturday morning cartoon commercial",
            "Super Bowl commercial",
        ]
        console.print(f"[dim]Using {len(terms)} built-in search categories[/dim]")

    # Determine year ranges to iterate over
    year_from, year_to = _parse_years(years)
    if year_from and year_to:
        search_configs = [(None, year_from, year_to)]
        label = f"{year_from}-{year_to}"
    else:
        decade_list = [d.strip() for d in decades.split(",")]
        search_configs = [(d, None, None) for d in decade_list]
        label = ", ".join(decade_list)

    total_combinations = len(terms) * len(search_configs)
    console.print(f"\n[bold]Batch scan:[/bold] {len(terms)} keywords x {label}")
    console.print(f"[bold]Total searches:[/bold] {total_combinations}\n")

    grand_total = 0
    new_count = 0
    new_urls = []  # track URLs added this run for download phase

    # --- Phase 1: Catalog ---
    console.print("[bold]Phase 1:[/bold] Cataloging...\n")

    with Progress(
        SpinnerColumn("simpleDots"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning...", total=total_combinations)

        for term in terms:
            for decade, yf, yt in search_configs:
                decade_label = decade or f"{yf}-{yt}"
                progress.update(task, description=f"[cyan]{term}[/cyan] ({decade_label})")

                results = _do_search(term, source, decade=decade,
                                     year_from=yf, year_to=yt,
                                     max_results=max_results)
                grand_total += len(results)

                for r in results:
                    if catalog_add_result(catalog, r) is not None:
                        new_count += 1
                        new_urls.append(r["source_url"])

                progress.advance(task)

    console.print(f"\n[bold green]Catalog complete![/bold green]")
    console.print(f"  Searches run:    {total_combinations}")
    console.print(f"  Results found:   {grand_total}")
    console.print(f"  New cataloged:   {new_count}")

    # --- Phase 2: Download ---
    if no_download:
        console.print(f"\n  [dim]Skipping downloads (--no-download flag)[/dim]")
    elif new_urls:
        console.print(f"\n[bold]Phase 2:[/bold] Downloading {len(new_urls)} new commercials...\n")
        download_count = 0
        fail_count = 0

        with Progress(
            SpinnerColumn("simpleDots"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading...", total=len(new_urls))

            for url in new_urls:
                progress.update(task, description=f"[cyan]{url[:60]}[/cyan]")
                try:
                    filepath = download(url)
                    if filepath:
                        catalog.mark_downloaded(url, filepath)
                        download_count += 1
                    else:
                        fail_count += 1
                except Exception:
                    fail_count += 1
                progress.advance(task)

        console.print(f"\n[bold green]Downloads complete![/bold green]")
        console.print(f"  Downloaded:      {download_count}")
        if fail_count:
            console.print(f"  Failed:          {fail_count}")
    else:
        console.print(f"\n  [dim]No new items to download.[/dim]")

    # Show updated stats
    s = catalog.stats()
    console.print(f"\n  [dim]Catalog total: {s['total_cataloged']} items "
                  f"({s['total_downloaded']} downloaded)[/dim]")


@cli.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to.")
@click.option("--port", "-p", default=5000, help="Port to run on.")
@click.option("--debug", is_flag=True, help="Enable Flask debug mode.")
@click.option("--no-browser", is_flag=True, help="Don't auto-open the browser.")
def web(host, port, debug, no_browser):
    """Launch the web interface — a YouTube-like browser for your collection.

    Automatically opens your browser to the site.

    \b
    Examples:
        vintage-commercials web
        vintage-commercials web -p 8080
        vintage-commercials web --no-browser
    """
    if not no_browser:
        import threading
        import webbrowser
        url = f"http://{'localhost' if host == '0.0.0.0' else host}:{port}"
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    from .webapp import run_web
    run_web(host=host, port=port, debug=debug)


def main():
    cli()


if __name__ == "__main__":
    main()
