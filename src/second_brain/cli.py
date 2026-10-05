"""Command-line interface ``sb``. Thin layer: parsing and printing only."""

from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__
from . import bibtex as bibmod
from . import projects as proj
from .checks import run_checks
from .config import HomeNotFoundError, find_home, load_config
from .doctor import library_status, run_doctor
from .fetch.download import Fetcher
from .ingest.doi import DOI_RE, normalize_doi
from .ingest.metadata import MetadataClient
from .ingest.pipeline import IngestError, IngestOptions, Ingestor, IngestResult, LockedError
from .library import InvalidDocument, Library
from .machines import Agent, Backend, detect_machine_name, load_profile, profile_path
from .models import CITEKEY_PATTERN
from .reading import select_pages, select_section
from .scaffold import ScaffoldReport, init_library, init_machine
from .texcite import cited_keys

app = typer.Typer(
    name="sb",
    help="second-brain: biblioteca de artículos científicos consultable con LLMs.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
machine_app = typer.Typer(
    help="Perfiles por máquina (machines/{nombre}.toml).", no_args_is_help=True
)
app.add_typer(machine_app, name="machine")
pdf_app = typer.Typer(help="PDFs: faltantes, descarga y apertura.", no_args_is_help=True)
app.add_typer(pdf_app, name="pdf")
project_app = typer.Typer(help="Proyectos: crear, asignar artículos, listar.", no_args_is_help=True)
app.add_typer(project_app, name="project")
bib_app = typer.Typer(help="BibTeX generado desde los registros.")
app.add_typer(bib_app, name="bib")
err_console = Console(stderr=True)

console = Console()
STATE_STYLE = {
    "ok": "[green]✓[/]",
    "warn": "[yellow]![/]",
    "fail": "[red]✗[/]",
    "info": "[dim]·[/]",
}


def _version(value: bool) -> None:
    if value:
        console.print(f"sb {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    home: Annotated[
        Path | None,
        typer.Option(
            "--home", help="Carpeta de la biblioteca (si no, SB_HOME o la carpeta actual)."
        ),
    ] = None,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Muestra la versión."),
    ] = False,
) -> None:
    ctx.obj = home


def _home(ctx: typer.Context) -> Path:
    try:
        return find_home(ctx.obj)
    except HomeNotFoundError as exc:
        console.print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(2) from exc


def _print_report(report: ScaffoldReport, base: Path) -> None:
    for path in report.created:
        console.print(f"[green]+[/] {path.relative_to(base)}")
    for path in report.skipped:
        console.print(f"[dim]= {path.relative_to(base)} (ya existía)[/]")
    for note in report.notes:
        console.print(f"[blue]i[/] {note}")


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help="Carpeta del repo de datos (se crea si no existe).")],
    email: Annotated[str | None, typer.Option(help="Correo para Crossref y Unpaywall.")] = None,
    institution: Annotated[
        str | None, typer.Option(help="Institución con acceso a editoriales.")
    ] = None,
    ip_range: Annotated[
        list[str] | None,
        typer.Option("--ip-range", help="Rango de IP institucional (CIDR); se puede repetir."),
    ] = None,
    vpn_hint: Annotated[
        str | None, typer.Option(help="Mensaje cuando una descarga pide autenticación.")
    ] = None,
    force: Annotated[bool, typer.Option(help="Sobrescribe los archivos que ya existan.")] = False,
) -> None:
    """Crea (o completa) un repo de datos: carpetas, configuración y hook de git."""
    report = init_library(
        path,
        email=email,
        institution=institution,
        ip_ranges=ip_range,
        vpn_hint=vpn_hint,
        force=force,
    )
    _print_report(report, path.expanduser().resolve())
    console.print("\nSiguiente paso: [bold]sb machine init[/] dentro de la biblioteca.")


@machine_app.command("init")
def machine_init(
    ctx: typer.Context,
    name: Annotated[
        str | None, typer.Option(help="Nombre del perfil (por defecto, el de esta computadora).")
    ] = None,
    backend: Annotated[
        Backend, typer.Option(help="Quién procesa los artículos al ingerir.")
    ] = "claude",
    agent: Annotated[Agent, typer.Option(help="Agente que abre `sb chat`.")] = "claude",
    force: Annotated[bool, typer.Option(help="Sobrescribe el perfil si ya existe.")] = False,
) -> None:
    """Crea el perfil de esta máquina y activa el hook de git en este clon."""
    home = _home(ctx)
    report = init_machine(
        home, name or detect_machine_name(), backend=backend, agent=agent, force=force
    )
    _print_report(report, home)


@machine_app.command("show")
def machine_show(ctx: typer.Context) -> None:
    """Muestra qué perfil está activo en esta computadora."""
    home = _home(ctx)
    name = detect_machine_name()
    profile = load_profile(home, name)
    if profile is None:
        console.print(
            f"[red]✗[/] {name}: no existe {profile_path(home, name).relative_to(home)} → sb machine init"
        )
        raise typer.Exit(1)
    console.print(f"[bold]{name}[/] ({profile_path(home, name).relative_to(home)})")
    console.print_json(profile.model_dump_json())


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Revisa que esta máquina tenga todo lo necesario."""
    findings = run_doctor(ctx.obj)
    table = Table(show_header=False, box=None, pad_edge=False)
    for finding in findings:
        table.add_row(STATE_STYLE[finding.state], finding.name, escape(finding.detail))
    console.print(table)
    if any(f.state == "fail" for f in findings):
        raise typer.Exit(1)


@app.command()
def check(
    ctx: typer.Context,
    fast: Annotated[
        bool, typer.Option(help="Omite textos completos y figuras (para el hook de git).")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")] = False,
) -> None:
    """Valida la biblioteca: esquema, vocabularios, DOIs, proyectos, tamaños y PDFs fuera de git."""
    home = _home(ctx)
    report = run_checks(home, fast=fast)
    if as_json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "papers": report.papers,
                    "projects": report.projects,
                    "issues": [dataclasses.asdict(i) for i in report.issues],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for issue in report.issues:
            mark = "[red]✗[/]" if issue.level == "error" else "[yellow]![/]"
            console.print(f"{mark} {escape(issue.path)}: {escape(issue.message)}")
        summary = f"{report.papers} artículos, {report.projects} proyectos"
        if report.ok:
            console.print(f"[green]✓[/] Biblioteca válida ({summary}).")
        else:
            console.print(f"[red]✗[/] {len(report.errors)} errores ({summary}).")
    if not report.ok:
        raise typer.Exit(1)


@app.command()
def status(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")] = False,
) -> None:
    """Qué hay pendiente: PDFs en inbox/, artículos por estado y proyectos."""
    state = library_status(_home(ctx))
    if as_json:
        data = dataclasses.asdict(state)
        data["home"] = str(state.home)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    console.print(f"[bold]Biblioteca[/] {state.home}  ·  máquina [bold]{state.machine}[/]")
    console.print(f"  inbox/: {state.inbox} PDFs por ingerir")
    detail = ", ".join(f"{k}: {v}" for k, v in sorted(state.by_status.items())) or "ninguno"
    console.print(f"  artículos: {state.papers} ({detail})")
    if state.invalid:
        console.print(f"  [red]{state.invalid} archivos inválidos → sb check[/]")
    console.print(f"  proyectos: {state.projects_active} activos de {state.projects_total}")
    console.print(f"  pdfs/ en esta máquina: {state.local_pdfs}")


OUTCOME_LABEL = {
    "ingested": ("[green]✓[/]", "ingeridos"),
    "review": ("[yellow]?[/]", "por revisar"),
    "attached": ("[green]+[/]", "PDF añadido"),
    "relinked": ("[blue]↺[/]", "re-vinculados"),
    "awaiting": ("[yellow]…[/]", "esperando PDF"),
    "duplicate": ("[dim]=[/]", "duplicados"),
    "offline": ("[yellow]![/]", "sin conexión"),
    "error": ("[red]✗[/]", "errores"),
}


def _print_ingest(results: list[IngestResult], dry_run: bool) -> None:
    for r in results:
        mark, _ = OUTCOME_LABEL[r.outcome]
        key = f" → [bold]{r.citekey}[/]" if r.citekey else ""
        doi = f" [dim]{escape(r.doi)}[/]" if r.doi else ""
        note = f"  [dim]{escape(r.message)}[/]" if r.message else ""
        console.print(f"{mark} {escape(r.source)}{key}{doi}{note}")
    counts = {o: sum(1 for r in results if r.outcome == o) for o in OUTCOME_LABEL}
    summary = " · ".join(f"{n} {OUTCOME_LABEL[o][1]}" for o, n in counts.items() if n)
    prefix = "(simulación) " if dry_run else ""
    console.print(f"\n{prefix}{summary or 'nada que ingerir'}")


def _confirm_vpn(hint: str) -> bool:
    console.print(f"[yellow]![/] No estás en la red institucional. {escape(hint)}.")
    answer = input("  Presiona Enter para reintentar, o escribe s para saltar: ")
    return answer.strip().lower() != "s"


def _ingestor(lib: Library, options: IngestOptions, interactive: bool) -> Ingestor:
    config = load_config(lib.home)
    client = MetadataClient(lib.cache_dir, email=config.user.email)
    fetcher = Fetcher(
        config.access, config.user.email, confirm_vpn=_confirm_vpn if interactive else None
    )
    return Ingestor(lib, config, client, options, fetcher=fetcher)


def _run_ingest(
    ingestor: Ingestor, paths: list[Path], dois: list[str], as_json: bool, dry_run: bool
) -> None:
    try:
        results = ingestor.run(paths, dois)
    except (IngestError, LockedError) as exc:
        console.print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(2) from exc
    if as_json:
        print(json.dumps([dataclasses.asdict(r) for r in results], ensure_ascii=False, indent=2))
    else:
        if not ingestor.config.user.email:
            console.print(
                "[yellow]![/] Sin \\[user].email en config.toml: Crossref atiende más lento "
                "y no se consulta Unpaywall (acceso abierto)."
            )
        _print_ingest(results, dry_run)
        awaiting = sum(1 for r in results if r.outcome == "awaiting")
        if awaiting and not dry_run:
            console.print(
                f"[dim]{awaiting} esperan PDF: reintenta con [bold]sb ingest --retry[/] o guarda "
                "el PDF en inbox/ (sb pdf open KEY lo abre en el navegador).[/]"
            )
    if any(r.outcome in ("error", "offline") for r in results):
        raise typer.Exit(1)


@app.command()
def ingest(
    ctx: typer.Context,
    items: Annotated[
        list[str] | None,
        typer.Argument(help="PDFs o DOIs (por defecto, todos los PDFs de inbox/)."),
    ] = None,
    dois: Annotated[
        Path | None, typer.Option("--dois", help="Archivo con un DOI por línea.")
    ] = None,
    retry: Annotated[
        bool, typer.Option(help="Reintentar la descarga de los que esperan PDF.")
    ] = False,
    doi: Annotated[str | None, typer.Option(help="Forzar el DOI (solo con un PDF).")] = None,
    project: Annotated[
        str | None, typer.Option(help="Asignar lo ingerido a un proyecto existente.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option(help="Mostrar qué pasaría sin escribir, mover ni descargar.")
    ] = False,
    limit: Annotated[
        int | None, typer.Option(min=1, help="Procesar como máximo N elementos.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")] = False,
) -> None:
    """Ingiere PDFs o DOIs: metadatos, descarga, duplicados, texto completo y pdfs/."""
    lib = Library(_home(ctx))
    paths: list[Path] = []
    wanted: list[str] = []
    for item in items or []:
        path = Path(item).expanduser()
        if path.is_file():
            paths.append(path.resolve())
        elif DOI_RE.fullmatch(normalize_doi(item)):
            wanted.append(item)
        else:
            console.print(f"[red]✗[/] {escape(item)} no es un archivo ni un DOI")
            raise typer.Exit(2)
    if dois is not None:
        lines = dois.expanduser().read_text(encoding="utf-8").splitlines()
        wanted += [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    options = IngestOptions(dry_run=dry_run, forced_doi=doi, project=project)
    ingestor = _ingestor(lib, options, interactive=sys.stdin.isatty() and not as_json)
    if retry:
        wanted += ingestor.pending_dois()
    if not items and dois is None and not retry:
        paths = lib.inbox_pdfs()
    if limit:
        paths = paths[:limit]
        wanted = wanted[: max(0, limit - len(paths))]
    _run_ingest(ingestor, paths, wanted, as_json, dry_run)


def _read_paper(lib: Library, citekey: str):
    if not re.fullmatch(CITEKEY_PATTERN, citekey) or not lib.paper_path(citekey).is_file():
        console.print(f"[red]✗[/] no existe el artículo {escape(citekey)}")
        raise typer.Exit(1)
    return lib.read_paper(citekey)


@app.command()
def show(
    ctx: typer.Context,
    citekey: Annotated[str, typer.Argument(help="Citekey del artículo.")],
    as_json: Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")] = False,
) -> None:
    """Metadatos, clasificación y resumen de un artículo."""
    lib = Library(_home(ctx))
    doc = _read_paper(lib, citekey)
    paper = doc.meta
    local_pdf = lib.pdfs_dir / f"{citekey}.pdf"
    if as_json:
        data = paper.model_dump(mode="json")
        data["summary"] = doc.body
        data["local_pdf"] = str(local_pdf) if local_pdf.exists() else None
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    authors = "; ".join(f"{a.family}, {a.given}" if a.given else a.family for a in paper.authors)
    console.print(f"[bold]{escape(paper.title)}[/]")
    console.print(escape(authors or "(sin autores)"))
    venue = ", ".join(str(x) for x in (paper.container_title, paper.year) if x)
    if venue:
        console.print(escape(venue))
    if paper.doi:
        console.print(f"DOI: {escape(paper.doi)}")
    flags = f" · {', '.join(paper.flags)}" if paper.flags else ""
    console.print(f"[dim]{citekey} · {paper.status}{flags}[/]")
    if paper.projects:
        console.print("Proyectos: " + ", ".join(paper.projects))
    console.print(f"PDF local: {local_pdf if local_pdf.exists() else 'no está en esta máquina'}")
    console.print()
    console.print(escape(doc.body) if doc.body else "[dim](sin resumen todavía)[/]")


@app.command()
def text(
    ctx: typer.Context,
    citekey: Annotated[str, typer.Argument(help="Citekey del artículo.")],
    pages: Annotated[str | None, typer.Option(help="Páginas: 5, 4-6 u 8-.")] = None,
    section: Annotated[
        str | None, typer.Option(help="Sección cuyo encabezado contiene este texto.")
    ] = None,
) -> None:
    """Texto completo de un artículo, o solo algunas páginas o una sección."""
    lib = Library(_home(ctx))
    _read_paper(lib, citekey)
    if not lib.fulltext_path(citekey).is_file():
        console.print(f"[red]✗[/] {escape(citekey)} no tiene texto completo (¿falta su PDF?)")
        raise typer.Exit(1)
    body = lib.read_fulltext(citekey).body
    if pages:
        try:
            body = select_pages(body, pages)
        except ValueError as exc:
            console.print(f"[red]✗[/] {escape(str(exc))}")
            raise typer.Exit(2) from exc
    if section:
        found = select_section(body, section)
        if found is None:
            console.print(f"[red]✗[/] no hay ninguna sección que contenga {escape(section)!r}")
            raise typer.Exit(1)
        body = found
    print(body)


@app.command()
def remove(
    ctx: typer.Context,
    citekey: Annotated[str, typer.Argument(help="Citekey del artículo a eliminar.")],
    delete_pdf: Annotated[
        bool, typer.Option(help="Borrar también el PDF (por defecto va a inbox/_eliminados/).")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="No pedir confirmación.")] = False,
) -> None:
    """Elimina un artículo: registro, texto completo y figuras. Tus notas no se tocan."""
    lib = Library(_home(ctx))
    paper = _read_paper(lib, citekey).meta
    pdf = lib.pdfs_dir / f"{citekey}.pdf"
    console.print(f"Eliminar [bold]{citekey}[/]: {escape(paper.title)}")
    if paper.projects:
        console.print(f"  está en los proyectos: {', '.join(paper.projects)}")
    if pdf.exists():
        destino = "se borra" if delete_pdf else "pasa a inbox/_eliminados/"
        console.print(f"  PDF local: {destino}")
    if not yes and not typer.confirm("¿Continuar?", default=False):
        raise typer.Exit(1)
    removed = lib.remove_paper(citekey)
    if pdf.exists():
        if delete_pdf:
            pdf.unlink()
        else:
            target = lib.inbox_dir / "_eliminados" / pdf.name
            target.parent.mkdir(parents=True, exist_ok=True)
            pdf.rename(target)
    for path in removed:
        console.print(f"[red]-[/] {path.relative_to(lib.home)}")
    notes = lib.notes_dir / f"{citekey}.md"
    if notes.exists():
        console.print(f"[blue]i[/] Se conservan tus notas: {notes.relative_to(lib.home)}")
    console.print(
        "Si te arrepientes: git restore library/ (antes del commit); después sigue en el historial de git."
    )


@pdf_app.command("status")
def pdf_status(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")] = False,
) -> None:
    """Artículos que esperan PDF o cuyo PDF no está en esta máquina."""
    lib = Library(_home(ctx))
    log_path = lib.cache_dir / "fetch.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.is_file() else {}
    rows = []
    for doc in lib.iter_papers():
        if isinstance(doc, InvalidDocument):
            continue
        paper = doc.meta
        if (lib.pdfs_dir / f"{paper.citekey}.pdf").exists():
            continue
        state = "esperando PDF" if paper.pdf is None else "no está en esta máquina"
        last = log.get(normalize_doi(paper.doi)) if paper.doi else None
        rows.append(
            {
                "citekey": paper.citekey,
                "doi": paper.doi,
                "state": state,
                "last_attempt": last,
            }
        )
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        console.print("[green]✓[/] Todos los artículos tienen su PDF en esta máquina.")
        return
    for row in rows:
        reason = (
            f"  [dim]{escape(row['last_attempt']['message'])}[/]" if row["last_attempt"] else ""
        )
        console.print(f"[yellow]…[/] [bold]{row['citekey']}[/] {row['state']}{reason}")
    console.print(f"\n{len(rows)} sin PDF local. Descárgalos con: sb pdf get --missing")


@pdf_app.command("get")
def pdf_get(
    ctx: typer.Context,
    citekeys: Annotated[list[str] | None, typer.Argument(help="Citekeys a descargar.")] = None,
    missing: Annotated[
        bool, typer.Option(help="Todos los que no tienen PDF en esta máquina.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")] = False,
) -> None:
    """Descarga a pdfs/ el PDF de artículos ya registrados."""
    lib = Library(_home(ctx))
    ingestor = _ingestor(lib, IngestOptions(), interactive=sys.stdin.isatty() and not as_json)
    wanted = ingestor.pending_dois(only_awaiting=False) if missing else []
    for citekey in citekeys or []:
        paper = _read_paper(lib, citekey).meta
        if not paper.doi:
            console.print(f"[red]✗[/] {citekey} no tiene DOI: no se puede descargar")
            raise typer.Exit(1)
        wanted.append(paper.doi)
    if not wanted:
        console.print("Nada que descargar.")
        return
    _run_ingest(ingestor, [], wanted, as_json, dry_run=False)


@pdf_app.command("open")
def pdf_open(
    ctx: typer.Context,
    citekey: Annotated[str | None, typer.Argument(help="Citekey del artículo.")] = None,
    awaiting: Annotated[
        bool, typer.Option(help="Abrir en el navegador los artículos que esperan PDF.")
    ] = False,
    limit: Annotated[int, typer.Option(min=1, help="Máximo de pestañas con --awaiting.")] = 10,
) -> None:
    """Abre el PDF local o, si no está, la página del artículo en el navegador."""
    lib = Library(_home(ctx))
    if awaiting:
        pending = [
            d.meta
            for d in lib.iter_papers()
            if not isinstance(d, InvalidDocument) and d.meta.status == "awaiting_pdf" and d.meta.doi
        ]
        for paper in pending[:limit]:
            console.print(f"[yellow]…[/] {paper.citekey}  https://doi.org/{paper.doi}")
            webbrowser.open_new_tab(f"https://doi.org/{paper.doi}")
        console.print(
            f"\nAbrí {min(limit, len(pending))} de {len(pending)}. Descarga los PDFs y luego: "
            "[bold]sb ingest ~/Downloads/*.pdf[/] (cada uno se asocia a su registro por su DOI)."
        )
        return
    if citekey is None:
        console.print("[red]✗[/] indica un citekey o usa --awaiting")
        raise typer.Exit(2)
    paper = _read_paper(lib, citekey).meta
    local = lib.pdfs_dir / f"{citekey}.pdf"
    if local.exists():
        subprocess.run(["open", str(local)], check=False)
    elif paper.doi:
        console.print("No está en esta máquina; abro la página del artículo.")
        console.print("[dim]Guarda el PDF en inbox/ y ejecuta sb ingest: se asocia solo.[/]")
        webbrowser.open(f"https://doi.org/{paper.doi}")
    else:
        console.print(f"[red]✗[/] {citekey} no tiene PDF local ni DOI")
        raise typer.Exit(1)


# --- projects -------------------------------------------------------------------


def _project_error(exc: Exception) -> typer.Exit:
    console.print(f"[red]✗[/] {escape(str(exc))}")
    return typer.Exit(1)


@project_app.command("create")
def project_create(
    ctx: typer.Context,
    slug: Annotated[str | None, typer.Argument(help="Identificador: minúsculas y guiones.")] = None,
    name: Annotated[str | None, typer.Option(help="Nombre legible.")] = None,
    kind: Annotated[str | None, typer.Option(help="Tipo (ver [vocab].project_kind).")] = None,
    desc: Annotated[
        str | None, typer.Option(help="Descripción: objetivo, preguntas, palabras clave.")
    ] = None,
) -> None:
    """Crea un proyecto. Sin argumentos, pregunta cada dato."""
    lib = Library(_home(ctx))
    config = load_config(lib.home)
    interactive = sys.stdin.isatty()
    if slug is None:
        if not interactive:
            console.print("[red]✗[/] falta el slug del proyecto")
            raise typer.Exit(2)
        slug = typer.prompt("Slug (p. ej., tesis-doctoral)")
    if name is None:
        name = typer.prompt("Nombre", default=slug) if interactive else slug
    if kind is None and interactive:
        options = ", ".join(config.vocab.project_kind)
        kind = (
            typer.prompt(f"Tipo ({options}; vacío si ninguno)", default="", show_default=False)
            or None
        )
    if desc is None and interactive:
        desc = typer.prompt("Descripción (vacía si ninguna)", default="", show_default=False)
    try:
        proj.create_project(lib, config, slug, name, kind, desc or "")
    except proj.ProjectError as exc:
        raise _project_error(exc) from exc
    console.print(
        f"[green]✓[/] Proyecto [bold]{slug}[/] creado ({lib.project_path(slug).relative_to(lib.home)})"
    )


@project_app.command("add")
def project_add(
    ctx: typer.Context,
    slug: Annotated[str, typer.Argument(help="Proyecto.")],
    citekeys: Annotated[list[str], typer.Argument(help="Artículos a agregar.")],
    note: Annotated[str | None, typer.Option(help="Para qué sirve en este proyecto.")] = None,
) -> None:
    """Agrega artículos a un proyecto."""
    lib = Library(_home(ctx))
    try:
        added, present = proj.add_papers(lib, slug, citekeys, note)
    except proj.ProjectError as exc:
        raise _project_error(exc) from exc
    for key in added:
        console.print(f"[green]+[/] {key}")
    for key in present:
        console.print(f"[dim]= {key} (ya estaba{'; nota actualizada' if note else ''})[/]")


@project_app.command("remove")
def project_remove(
    ctx: typer.Context,
    slug: Annotated[str, typer.Argument(help="Proyecto.")],
    citekeys: Annotated[list[str], typer.Argument(help="Artículos a quitar.")],
) -> None:
    """Quita artículos de un proyecto (los artículos siguen en la biblioteca)."""
    lib = Library(_home(ctx))
    try:
        removed, absent = proj.remove_papers(lib, slug, citekeys)
    except proj.ProjectError as exc:
        raise _project_error(exc) from exc
    for key in removed:
        console.print(f"[red]-[/] {key}")
    for key in absent:
        console.print(f"[dim]= {key} (no estaba en {slug})[/]")


@project_app.command("list")
def project_list(
    ctx: typer.Context,
    kind: Annotated[str | None, typer.Option(help="Solo de este tipo.")] = None,
    all_: Annotated[bool, typer.Option("--all", help="Incluir archivados.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")] = False,
) -> None:
    """Lista los proyectos con su número de artículos."""
    rows = [
        s
        for s in proj.summaries(Library(_home(ctx)))
        if (kind is None or s.project.kind == kind) and (all_ or s.project.status != "archived")
    ]
    if as_json:
        data = [
            {
                **s.project.model_dump(mode="json"),
                "description": s.description,
                "papers": len(s.members),
            }
            for s in rows
        ]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if not rows:
        console.print("No hay proyectos. Crea uno con: sb project create")
        return
    for s in rows:
        kind_text = f" · {s.project.kind}" if s.project.kind else ""
        status = "" if s.project.status == "active" else f" · {s.project.status}"
        console.print(
            f"[bold]{s.project.slug}[/]  {escape(s.project.name)}  "
            f"[dim]{len(s.members)} artículos{kind_text}{status}[/]"
        )


@project_app.command("show")
def project_show(
    ctx: typer.Context,
    slug: Annotated[str, typer.Argument(help="Proyecto.")],
    as_json: Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")] = False,
) -> None:
    """Descripción y artículos de un proyecto."""
    lib = Library(_home(ctx))
    try:
        doc = proj.require_project(lib, slug)
    except proj.ProjectError as exc:
        raise _project_error(exc) from exc
    papers = sorted(proj.members(lib, slug), key=lambda p: p.citekey)
    if as_json:
        data = {
            **doc.meta.model_dump(mode="json"),
            "description": doc.body,
            "papers": [
                {
                    "citekey": p.citekey,
                    "title": p.title,
                    "year": p.year,
                    "note": p.projects[slug].note,
                }
                for p in papers
            ],
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    kind_text = f" · {doc.meta.kind}" if doc.meta.kind else ""
    console.print(
        f"[bold]{escape(doc.meta.name)}[/] [dim]({slug}{kind_text} · {doc.meta.status})[/]"
    )
    if doc.body:
        console.print(escape(doc.body))
    console.print(f"\n{len(papers)} artículos:")
    for p in papers:
        note = p.projects[slug].note
        console.print(
            f"  {p.citekey}  {escape(p.title)}" + (f"  [dim]— {escape(note)}[/]" if note else "")
        )


@project_app.command("archive")
def project_archive(
    ctx: typer.Context,
    slug: Annotated[str, typer.Argument(help="Proyecto.")],
    restore: Annotated[bool, typer.Option(help="Volver a activarlo.")] = False,
) -> None:
    """Archiva un proyecto terminado (sus artículos conservan la membresía)."""
    try:
        project = proj.set_status(Library(_home(ctx)), slug, "active" if restore else "archived")
    except proj.ProjectError as exc:
        raise _project_error(exc) from exc
    console.print(f"[green]✓[/] {slug}: {project.status}")


# --- BibTeX -------------------------------------------------------------------


def _write_bib(text: str, output: Path | None) -> bool:
    """Write the .bib (or print it); return True if the file changed."""
    if output is None:
        print(text, end="")
        return True
    output = output.expanduser()
    if output.exists() and output.read_text(encoding="utf-8") == text:
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return True


@bib_app.callback(invoke_without_command=True)
def bib(
    ctx: typer.Context,
    project: Annotated[
        list[str] | None, typer.Option("--project", "-p", help="Artículos de este proyecto.")
    ] = None,
    keys: Annotated[str | None, typer.Option(help="Citekeys separados por comas.")] = None,
    from_tex: Annotated[
        Path | None, typer.Option(help="Los artículos citados en este .tex.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Archivo .bib (si no, a la pantalla).")
    ] = None,
    fmt: Annotated[bibmod.Format, typer.Option("--format", help="bibtex o biblatex.")] = "bibtex",
    strict: Annotated[
        bool, typer.Option(help="Terminar con error si falta algún citekey.")
    ] = False,
) -> None:
    """Genera BibTeX de un proyecto, de unos citekeys o de lo citado en un .tex."""
    if ctx.invoked_subcommand:
        return
    if not (project or keys or from_tex):
        console.print(ctx.get_help())
        raise typer.Exit(0)
    lib = Library(_home(ctx))
    selected: dict[str, object] = {}
    missing: list[str] = []
    for slug in project or []:
        try:
            proj.require_project(lib, slug)
        except proj.ProjectError as exc:
            err_console.print(f"[red]✗[/] {escape(str(exc))}")
            raise typer.Exit(1) from exc
        for paper in proj.members(lib, slug):
            selected[paper.citekey] = paper
    wanted = [k.strip() for k in (keys or "").split(",") if k.strip()]
    if from_tex:
        if not from_tex.expanduser().is_file():
            err_console.print(f"[red]✗[/] no existe {escape(str(from_tex))}")
            raise typer.Exit(2)
        wanted += cited_keys(from_tex.expanduser())
    for key in wanted:
        if key in selected:
            continue
        if re.fullmatch(CITEKEY_PATTERN, key) and lib.paper_path(key).is_file():
            selected[key] = lib.read_paper(key).meta
        elif key not in missing:
            missing.append(key)
    text = bibmod.render(list(selected.values()), fmt)
    changed = _write_bib(text, output)
    if output is not None:
        state = "escrito" if changed else "sin cambios"
        err_console.print(f"[green]✓[/] {len(selected)} entradas → {escape(str(output))} ({state})")
    if missing:
        err_console.print(
            f"[yellow]![/] {len(missing)} citekeys no están en la biblioteca: {escape(', '.join(missing))}"
        )
        if strict:
            raise typer.Exit(1)


@bib_app.command("sync")
def bib_sync(
    ctx: typer.Context,
    fmt: Annotated[bibmod.Format, typer.Option("--format", help="bibtex o biblatex.")] = "bibtex",
) -> None:
    """Reescribe los .bib de [bib_outputs] del perfil de esta máquina."""
    lib = Library(_home(ctx))
    machine = detect_machine_name()
    profile = load_profile(lib.home, machine)
    if profile is None or not profile.bib_outputs:
        console.print(f"No hay [bold]\\[bib_outputs][/] en machines/{machine}.toml. Ejemplo:")
        console.print('  [bib_outputs]\n  tesis-doctoral = "~/Documents/tesis/refs.bib"')
        return
    failed = False
    for slug, target in profile.bib_outputs.items():
        path = Path(target).expanduser()
        path = path if path.is_absolute() else lib.home / path
        try:
            proj.require_project(lib, slug)
        except proj.ProjectError as exc:
            console.print(f"[red]✗[/] {escape(str(exc))}")
            failed = True
            continue
        papers = proj.members(lib, slug)
        changed = _write_bib(bibmod.render(papers, fmt), path)
        mark, state = ("[green]✓[/]", "actualizado") if changed else ("[dim]=[/]", "sin cambios")
        console.print(f"{mark} {slug}: {len(papers)} entradas → {escape(str(path))} ({state})")
    if failed:
        raise typer.Exit(1)
