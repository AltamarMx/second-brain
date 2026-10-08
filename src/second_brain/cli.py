"""Command-line interface ``sb``. Thin layer: parsing and printing only."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
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
from .agents import sync_agents
from .backends import BackendError, get_backend
from .checks import run_checks
from .config import HomeNotFoundError, find_home, load_config, load_env
from .doctor import library_status, run_doctor
from .fetch.download import Fetcher
from .index import Filters, Mode, SearchIndex, open_index
from .ingest.doi import DOI_RE, normalize_doi
from .ingest.metadata import MetadataClient, NetworkError
from .ingest.pipeline import IngestError, IngestOptions, Ingestor, IngestResult, LockedError
from .library import InvalidDocument, Library
from .machines import Agent, Backend, detect_machine_name, load_profile, profile_path
from .models import CITEKEY_PATTERN
from .processing import Processor, ProcessResult
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
    retractions: Annotated[
        bool, typer.Option(help="Consultar en Crossref retractaciones y correcciones (usa la red).")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")] = False,
) -> None:
    """Valida la biblioteca: esquema, vocabularios, DOIs, proyectos, tamaños y PDFs fuera de git."""
    home = _home(ctx)
    if retractions:
        _check_retractions(home, as_json)
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


def _process_keys(
    lib: Library,
    keys: list[str],
    quiet: bool,
    backend_name: str | None = None,
    **options: bool,
) -> dict[str, ProcessResult]:
    """Process papers with this machine's backend; prints progress unless ``quiet``."""
    if not keys:
        return {}
    machine = detect_machine_name()
    profile = load_profile(lib.home, machine)
    name = backend_name or (profile.process.backend if profile else None)
    if name is None:
        if not quiet:
            console.print(
                f"[yellow]![/] Sin perfil machines/{machine}.toml: no se procesó (sb machine init)."
            )
        return {}
    if name == "none":
        if not quiet:
            console.print(
                '[dim]Esta máquina no procesa artículos (backend = "none"): quedan pendientes.[/]'
            )
        return {}
    try:
        backend = get_backend(name, profile, load_env(lib.home))
    except BackendError as exc:
        if not quiet:
            console.print(f"[red]✗[/] {escape(str(exc))}")
        return {}
    processor = Processor(lib, load_config(lib.home), backend, machine)
    results: dict[str, ProcessResult] = {}
    if not quiet:
        console.print(f"\nProcesando {len(keys)} artículos con {name} (≈1 min cada uno)…")
    for number, key in enumerate(keys, start=1):
        if quiet:
            results[key] = processor.process(key, **options)
            continue
        with console.status(f"[{number}/{len(keys)}] {key}…"):
            result = processor.process(key, **options)
        results[key] = result
        mark = {"processed": "[green]✓[/]", "skipped": "[dim]=[/]", "error": "[red]✗[/]"}[
            result.outcome
        ]
        detail = "; ".join(x for x in (result.message, *result.notes) if x)
        console.print(f"{mark} {key}  [dim]{escape(detail)}[/]")
    return results


def _run_ingest(
    ingestor: Ingestor,
    paths: list[Path],
    dois: list[str],
    as_json: bool,
    dry_run: bool,
    process: bool = False,
) -> None:
    try:
        results = ingestor.run(paths, dois)
    except (IngestError, LockedError) as exc:
        console.print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(2) from exc
    if not as_json:
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
    processed: dict[str, ProcessResult] = {}
    if process and not dry_run:
        keys = [
            r.citekey
            for r in results
            if r.citekey and r.outcome in ("ingested", "review", "attached")
        ]
        processed = _process_keys(ingestor.lib, keys, quiet=as_json)
    if as_json:
        rows = [
            {
                **dataclasses.asdict(r),
                "processing": dataclasses.asdict(processed[r.citekey])
                if r.citekey in processed
                else None,
            }
            for r in results
        ]
        print(json.dumps(rows, ensure_ascii=False, indent=2))
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
    key: Annotated[
        str | None, typer.Option("--key", help="Asociar el PDF a este artículo (solo con un PDF).")
    ] = None,
    project: Annotated[
        str | None, typer.Option(help="Asignar lo ingerido a un proyecto existente.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option(help="Mostrar qué pasaría sin escribir, mover ni descargar.")
    ] = False,
    limit: Annotated[
        int | None, typer.Option(min=1, help="Procesar como máximo N elementos.")
    ] = None,
    no_process: Annotated[
        bool, typer.Option("--no-process", help="No resumir ni describir figuras ahora.")
    ] = False,
    all_: Annotated[
        bool,
        typer.Option(
            "--all", help="Todo seguido: ingerir, procesar lo pendiente, validar y hacer commit."
        ),
    ] = False,
    push: Annotated[bool, typer.Option(help="Con --all: además, git push.")] = False,
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
    options = IngestOptions(dry_run=dry_run, forced_doi=doi, key=key, project=project)
    ingestor = _ingestor(lib, options, interactive=sys.stdin.isatty() and not as_json)
    if retry:
        wanted += ingestor.pending_dois()
    if not items and dois is None and not retry:
        paths = lib.inbox_pdfs()
    if limit:
        paths = paths[:limit]
        wanted = wanted[: max(0, limit - len(paths))]
    if not all_:
        _run_ingest(ingestor, paths, wanted, as_json, dry_run, process=not no_process)
        return
    if dry_run or as_json:
        console.print("[red]✗[/] --all no se combina con --dry-run ni --json")
        raise typer.Exit(2)
    _ingest_all(lib, ingestor, paths, wanted, push)


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
    if "retracted" in paper.flags or "expression_of_concern" in paper.flags:
        notice = (
            "RETRACTADO"
            if "retracted" in paper.flags
            else "con nota de preocupación (expression of concern)"
        )
        console.print(f"[bold red]⚠ Este artículo está {notice}[/]")
    for update in paper.updates:
        console.print(
            f"[dim]Nota de Crossref: {update.type} {update.date or ''} {update.doi or ''}[/]"
        )
    if paper.reading or paper.rating:
        stars = "★" * (paper.rating or 0)
        console.print(f"Lectura: {paper.reading or '-'} {stars}")
    if paper.suggested:
        console.print("[yellow]Metadatos sugeridos (leídos del PDF por el LLM; sin confirmar):[/]")
        suggestion = paper.suggested.model_dump(exclude_defaults=True)
        if paper.suggested.authors:
            suggestion["authors"] = "; ".join(
                f"{a.family}, {a.given}" if a.given else a.family for a in paper.suggested.authors
            )
        for name, value in suggestion.items():
            console.print(f"  {name}: {escape(str(value))}")
        console.print(f"  [dim]Para aplicarlos: sb edit {citekey} --accept --rekey[/]")
    extra = {k: v for k, v in paper.classification.extra.items() if v}
    if extra:
        console.print(
            "Clasificación: "
            + "; ".join(
                f"{k}: {v if isinstance(v, str) else ', '.join(v)}" for k, v in extra.items()
            )
        )
    for supplement in paper.supplements:
        console.print(
            f"Suplemento {supplement.id}: {escape(supplement.label or supplement.original_filename or '')} ({supplement.pages} pp.)"
        )
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
    supplement: Annotated[
        str | None, typer.Option(help="Texto de un suplemento (s1, s2…).")
    ] = None,
) -> None:
    """Texto completo de un artículo (o de un suplemento), o solo algunas páginas o una sección."""
    lib = Library(_home(ctx))
    _read_paper(lib, citekey)
    if supplement:
        if not lib.supplement_path(citekey, supplement).is_file():
            console.print(
                f"[red]✗[/] {escape(citekey)} no tiene el suplemento {escape(supplement)}"
            )
            raise typer.Exit(1)
        body = lib.read_supplement(citekey, supplement).body
    elif not lib.fulltext_path(citekey).is_file():
        console.print(f"[red]✗[/] {escape(citekey)} no tiene texto completo (¿falta su PDF?)")
        raise typer.Exit(1)
    else:
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
    all_: Annotated[
        bool, typer.Option("--all", help="Todos los artículos de la biblioteca.")
    ] = False,
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
    if not (project or keys or from_tex or all_):
        console.print(ctx.get_help())
        raise typer.Exit(0)
    lib = Library(_home(ctx))
    papers = {
        d.meta.citekey: d.meta for d in lib.iter_papers() if not isinstance(d, InvalidDocument)
    }
    by_alias = {alias: p for p in papers.values() for alias in p.aliases}
    selected: list[tuple[str, object]] = []
    missing: list[str] = []
    for slug in project or []:
        try:
            proj.require_project(lib, slug)
        except proj.ProjectError as exc:
            err_console.print(f"[red]✗[/] {escape(str(exc))}")
            raise typer.Exit(1) from exc
        for paper in proj.members(lib, slug):
            selected += [(k, paper) for k in (paper.citekey, *paper.aliases)]
    if all_:
        selected += [(k, p) for p in papers.values() for k in (p.citekey, *p.aliases)]
    wanted = [k.strip() for k in (keys or "").split(",") if k.strip()]
    tex_keys: list[str] = []
    if from_tex:
        if not from_tex.expanduser().is_file():
            err_console.print(f"[red]✗[/] no existe {escape(str(from_tex))}")
            raise typer.Exit(2)
        tex_keys = cited_keys(from_tex.expanduser())
    for key in wanted + tex_keys:
        paper = papers.get(key) or by_alias.get(key)
        if paper is None:
            if key not in missing:
                missing.append(key)
        elif key in tex_keys:
            selected.append((key, paper))  # exactly the key the document cites
        else:
            selected += [(k, paper) for k in (paper.citekey, *paper.aliases)]
    text = bibmod.render([], fmt, keys=selected)
    changed = _write_bib(text, output)
    if output is not None:
        state = "escrito" if changed else "sin cambios"
        count = len({k for k, _ in selected})
        err_console.print(f"[green]✓[/] {count} entradas → {escape(str(output))} ({state})")
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
        changed = _write_bib(bibmod.render(papers, fmt), path)  # citekeys and their aliases
        mark, state = ("[green]✓[/]", "actualizado") if changed else ("[dim]=[/]", "sin cambios")
        console.print(f"{mark} {slug}: {len(papers)} entradas → {escape(str(path))} ({state})")
    if failed:
        raise typer.Exit(1)


# --- processing -----------------------------------------------------------------


@app.command()
def process(
    ctx: typer.Context,
    citekeys: Annotated[list[str] | None, typer.Argument(help="Artículos a procesar.")] = None,
    pending: Annotated[bool, typer.Option(help="Todos los que falten por procesar.")] = False,
    stale: Annotated[
        bool, typer.Option(help="Rehacer lo hecho con una versión anterior del prompt.")
    ] = False,
    force: Annotated[
        bool, typer.Option(help="Rehacer aunque ya esté hecho (incluso si lo editaste).")
    ] = False,
    figures: Annotated[bool, typer.Option(help="Describir las figuras.")] = True,
    backend: Annotated[str | None, typer.Option(help="Forzar un backend (claude, none…).")] = None,
    reclassify: Annotated[
        bool,
        typer.Option(help="Solo volver a clasificar (p. ej., tras agregar campos en config.toml)."),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")] = False,
) -> None:
    """Resumen, clasificación y descripción de figuras con el LLM del perfil de la máquina."""
    lib = Library(_home(ctx))
    config = load_config(lib.home)
    keys = list(citekeys or [])
    if reclassify:
        _reclassify(lib, keys, as_json, backend)
        return
    if pending or stale:
        keys += [k for k in _pending_keys(lib, config, stale, figures) if k not in keys]
    for key in keys:
        _read_paper(lib, key)
    if not keys:
        console.print("Nada que procesar.") if not as_json else print("[]")
        return
    results = _process_keys(
        lib, keys, quiet=as_json, backend_name=backend, force=force, stale=stale, figures=figures
    )
    if as_json:
        print(
            json.dumps(
                [dataclasses.asdict(r) for r in results.values()], ensure_ascii=False, indent=2
            )
        )
    if any(r.outcome == "error" for r in results.values()):
        raise typer.Exit(1)


@app.command()
def figures(
    ctx: typer.Context,
    citekey: Annotated[str, typer.Argument(help="Artículo.")],
) -> None:
    """Vuelve a describir las figuras de un artículo."""
    lib = Library(_home(ctx))
    _read_paper(lib, citekey)
    results = _process_keys(lib, [citekey], quiet=False, force=True, summary=False, figures=True)
    if any(r.outcome == "error" for r in results.values()):
        raise typer.Exit(1)


# --- search ---------------------------------------------------------------------

ProjectOpt = Annotated[str | None, typer.Option("--project", "-p", help="Solo de este proyecto.")]
StudyOpt = Annotated[
    str | None, typer.Option("--study", help="Tipo de estudio (experimental, numerico, ambos…).")
]
CountryOpt = Annotated[str | None, typer.Option(help="País (código ISO, p. ej. MX).")]
RegionOpt = Annotated[str | None, typer.Option(help="Estado o provincia.")]
LocalityOpt = Annotated[str | None, typer.Option(help="Ciudad o sitio.")]
YearOpt = Annotated[str | None, typer.Option("--year", help="2019, 2015..2024, 2015.. o ..2020.")]
StatusOpt = Annotated[
    str | None, typer.Option(help="Estado del registro (needs_review, processed…).")
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")]
ModeOpt = Annotated[Mode, typer.Option(help="hybrid (significado + palabras), semantic o lexical.")]


def _index(lib: Library, mode: str) -> SearchIndex:
    return open_index(lib, semantic=mode != "lexical")


def _index_warning(index: SearchIndex, as_json: bool) -> None:
    if index.warning and not as_json:
        err_console.print(f"[yellow]![/] {escape(index.warning)}")


ReadingOpt = Annotated[
    str | None, typer.Option(help="Estado de lectura: por-leer, leyendo, leido.")
]
FieldOpt = Annotated[
    list[str] | None,
    typer.Option("--field", help="Campo de clasificación extra: nombre=valor (repetible)."),
]


def _filters(
    project, study, country, region, locality, year, status=None, reading=None, fields=None
) -> Filters:
    try:
        start, end = Filters.parse_years(year)
    except ValueError as exc:
        console.print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(2) from exc
    pairs = tuple(f.replace(" ", "_") for f in fields or [])
    if any("=" not in p for p in pairs):
        console.print("[red]✗[/] --field se escribe nombre=valor (p. ej., --field clima=Aw)")
        raise typer.Exit(2)
    return Filters(project, study, country, region, locality, start, end, status, reading, pairs)


def _print_hits(hits, show_passages: bool) -> None:
    if not hits:
        console.print("Sin resultados.")
        return
    for hit in hits:
        meta = " · ".join(str(x) for x in (hit.year, hit.study_type, hit.places) if x)
        console.print(f"[bold]{hit.citekey}[/]  {escape(hit.title)}  [dim]{escape(meta)}[/]")
        if hit.one_sentence:
            console.print(f"   {escape(hit.one_sentence)}")
        if show_passages:
            for passage in hit.passages:
                snippet = " ".join(passage.text.split())[:220]
                console.print(f"   [dim]p. {passage.page_start} · {escape(snippet)}…[/]")


@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Qué buscar (palabras sueltas o una frase).")],
    project: ProjectOpt = None, study: StudyOpt = None, country: CountryOpt = None,
    region: RegionOpt = None, locality: LocalityOpt = None, year: YearOpt = None,
    limit: Annotated[int, typer.Option(min=1, help="Máximo de artículos.")] = 10,
    mode: ModeOpt = "hybrid",
    reading: ReadingOpt = None, field: FieldOpt = None,
    as_json: JsonOpt = False,
) -> None:  # fmt: skip
    """Busca artículos por tema (por significado y por palabras) en metadatos, resúmenes, texto y figuras."""
    lib = Library(_home(ctx))
    index = _index(lib, mode)
    filters = _filters(project, study, country, region, locality, year, None, reading, field)
    hits = index.search(query, filters, limit, mode)
    _index_warning(index, as_json)
    if as_json:
        print(json.dumps([dataclasses.asdict(h) for h in hits], ensure_ascii=False, indent=2))
    else:
        _print_hits(hits, show_passages=True)


@app.command("list")
def list_papers(
    ctx: typer.Context,
    project: ProjectOpt = None, study: StudyOpt = None, country: CountryOpt = None,
    region: RegionOpt = None, locality: LocalityOpt = None, year: YearOpt = None,
    status: StatusOpt = None, reading: ReadingOpt = None, field: FieldOpt = None,
    as_json: JsonOpt = False,
) -> None:  # fmt: skip
    """Lista artículos con filtros (sin tema). Con --json, útil para contar."""
    lib = Library(_home(ctx))
    hits = open_index(lib, semantic=False).list(
        _filters(project, study, country, region, locality, year, status, reading, field)
    )
    if as_json:
        print(json.dumps([dataclasses.asdict(h) for h in hits], ensure_ascii=False, indent=2))
        return
    _print_hits(hits, show_passages=False)
    console.print(f"\n{len(hits)} artículos")


@app.command()
def passages(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Qué buscar.")],
    paper: Annotated[str | None, typer.Option(help="Solo en este artículo.")] = None,
    limit: Annotated[int, typer.Option(min=1, help="Máximo de pasajes.")] = 8,
    refs: Annotated[bool, typer.Option(help="Incluir la lista de referencias.")] = False,
    project: ProjectOpt = None, study: StudyOpt = None, country: CountryOpt = None,
    mode: ModeOpt = "hybrid",
    as_json: JsonOpt = False,
) -> None:  # fmt: skip
    """Pasajes del texto completo (y figuras) que responden a una consulta, con página y sección."""
    lib = Library(_home(ctx))
    index = _index(lib, mode)
    found = index.passages(
        query,
        _filters(project, study, country, None, None, None),
        paper=paper,
        limit=limit,
        include_refs=refs,
        mode=mode,
    )
    _index_warning(index, as_json)
    if as_json:
        print(json.dumps([dataclasses.asdict(p) for p in found], ensure_ascii=False, indent=2))
        return
    if not found:
        console.print("Sin resultados.")
    for passage in found:
        pages = f"p. {passage.page_start}" + (
            f"–{passage.page_end}" if passage.page_end != passage.page_start else ""
        )
        kind = " · figura" if passage.kind == "figure" else ""
        console.print(
            f"[bold]{passage.citekey}[/] [dim]{pages} · {escape(passage.section)}{kind}[/]"
        )
        console.print(escape(passage.text.strip()) + "\n")


index_app = typer.Typer(
    help="Índice de búsqueda (.cache/index.sqlite, derivado).", no_args_is_help=True
)
app.add_typer(index_app, name="index")


@index_app.command("update")
def index_update(ctx: typer.Context) -> None:
    """Actualiza el índice con lo que cambió."""
    index = open_index(Library(_home(ctx)))
    changed = index.update()
    _index_warning(index, False)
    console.print(f"[green]✓[/] {changed} artículos reindexados")


@index_app.command("rebuild")
def index_rebuild(ctx: typer.Context) -> None:
    """Reconstruye el índice desde cero."""
    index = open_index(Library(_home(ctx)))
    count = index.rebuild()
    _index_warning(index, False)
    console.print(f"[green]✓[/] índice reconstruido: {count} artículos")


# --- agents ---------------------------------------------------------------------

agents_app = typer.Typer(help="Reglas y skills para Claude Code y OpenCode.", no_args_is_help=True)
app.add_typer(agents_app, name="agents")


@agents_app.command("sync")
def agents_sync(ctx: typer.Context) -> None:
    """Instala o actualiza AGENTS.md, CLAUDE.md, las skills sb-* y .claude/settings.json."""
    home = _home(ctx)
    changed = sync_agents(home)
    for path in changed:
        console.print(f"[green]+[/] {path.relative_to(home)}")
    if not changed:
        console.print("[dim]Todo al día.[/]")


@app.command()
def chat(
    ctx: typer.Context,
    agent: Annotated[
        str | None, typer.Argument(help="claude u opencode (por defecto, el del perfil).")
    ] = None,
) -> None:
    """Abre Claude Code (u OpenCode) en la biblioteca, con sus reglas y skills."""
    home = _home(ctx)
    profile = load_profile(home, detect_machine_name())
    agent = agent or (profile.chat.agent if profile else "claude")
    if agent == "opencode":
        _chat_opencode(home, profile)
        return
    if agent != "claude":
        console.print(f"[red]✗[/] agente desconocido: {escape(agent)}")
        raise typer.Exit(2)
    if shutil.which("claude") is None:
        console.print("[red]✗[/] no encontré Claude Code (`claude`)")
        raise typer.Exit(1)
    sync_agents(home)  # keep rules and skills in step with the installed version
    os.chdir(home)
    os.execvp("claude", ["claude"])


# --- import / migrate -------------------------------------------------------------

import_app = typer.Typer(help="Traer una biblioteca existente.", no_args_is_help=True)
app.add_typer(import_app, name="import")

IMPORT_LABEL = {
    "imported": ("[green]+[/]", "importados"),
    "alias": ("[blue]≈[/]", "ya existían (alias agregado)"),
    "duplicate": ("[dim]=[/]", "ya existían"),
    "conflict": ("[yellow]![/]", "citekey en conflicto"),
    "error": ("[red]✗[/]", "errores"),
}


@import_app.command("bib")
def import_bib_command(
    ctx: typer.Context,
    path: Annotated[
        Path, typer.Argument(help="Archivo .bib (de Zotero, JabRef, Mendeley o a mano).")
    ],
    project: Annotated[
        str | None, typer.Option(help="Asignar todo a un proyecto existente.")
    ] = None,
    prefer_bib: Annotated[
        bool,
        typer.Option(
            "--prefer-bib",
            help="Con DOI, ganan los campos del .bib; Crossref/DataCite solo llenan lo que falte.",
        ),
    ] = False,
    dry_run: Annotated[bool, typer.Option(help="Mostrar qué pasaría sin escribir nada.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Salida en JSON para agentes.")] = False,
) -> None:
    """Registra las entradas de un .bib conservando sus citekeys; luego suelta los PDFs en inbox/."""
    from .import_bib import import_bib

    lib = Library(_home(ctx))
    if not path.expanduser().is_file():
        console.print(f"[red]✗[/] no existe {escape(str(path))}")
        raise typer.Exit(2)
    if project:
        try:
            proj.require_project(lib, project)
        except proj.ProjectError as exc:
            raise _project_error(exc) from exc
    config = load_config(lib.home)
    client = MetadataClient(lib.cache_dir, email=config.user.email)
    results = import_bib(
        lib, client, path.expanduser(), project=project, prefer_bib=prefer_bib, dry_run=dry_run
    )
    if as_json:
        print(json.dumps([dataclasses.asdict(r) for r in results], ensure_ascii=False, indent=2))
    else:
        for r in results:
            mark, _ = IMPORT_LABEL[r.outcome]
            target = f" → [bold]{r.citekey}[/]" if r.citekey and r.citekey != r.key else ""
            note = f"  [dim]{escape(r.message)}[/]" if r.message else ""
            console.print(f"{mark} {escape(r.key)}{target}{note}")
            if r.pdf and dry_run:
                console.print(f"    [dim]PDF: {escape(r.pdf)}[/]")
            elif r.pdf_outcome in ("attached", "relinked"):
                console.print(f"    [green]PDF copiado[/] [dim]{escape(r.pdf or '')}[/]")
            elif r.pdf_outcome == "error":
                console.print(f"    [yellow]PDF no asociado[/] [dim]{escape(r.pdf or '')}[/]")
        counts = {o: sum(1 for r in results if r.outcome == o) for o in IMPORT_LABEL}
        summary = " · ".join(f"{n} {IMPORT_LABEL[o][1]}" for o, n in counts.items() if n)
        console.print(
            f"\n{'(simulación) ' if dry_run else ''}{summary or 'el .bib no tiene entradas'}"
        )
        attached = sum(1 for r in results if r.pdf_outcome in ("attached", "relinked"))
        if attached:
            console.print(
                f"{attached} PDFs copiados del .bib; procésalos con sb process --pending."
            )
        waiting = sum(
            1
            for r in results
            if r.outcome == "imported" and r.pdf_outcome not in ("attached", "relinked")
        )
        if waiting and not dry_run:
            console.print(
                "[dim]Para los que no traían PDF: suéltalos en inbox/ y ejecuta sb ingest; cada uno se asocia a su registro.[/]"
            )
    if any(r.outcome == "error" for r in results):
        raise typer.Exit(1)


@app.command()
def migrate(ctx: typer.Context) -> None:
    """Reescribe artículos y proyectos con la versión actual del esquema de datos."""
    changed = Library(_home(ctx)).migrate()
    console.print(f"[green]✓[/] {changed} archivos actualizados al esquema actual")


def _chat_opencode(home: Path, profile) -> None:
    """OpenCode with this machine's Ollama model (context window enlarged) and the MCP server."""
    from .backends.ollama import OllamaBackend

    if shutil.which("opencode") is None:
        console.print(
            "[red]✗[/] no encontré OpenCode (`opencode`). Instálalo: brew install opencode"
        )
        raise typer.Exit(1)
    llm = profile.llm if profile else None
    if llm is None or not llm.model:
        console.print(
            "[red]✗[/] falta [bold]\\[llm].model[/] en el perfil de esta máquina (p. ej., gemma4)"
        )
        raise typer.Exit(1)
    ollama = OllamaBackend(llm.model, llm.base_url, llm.num_ctx)
    if not ollama.running():
        console.print("[red]✗[/] Ollama no está abierto: ábrelo (o `ollama serve`) y reintenta")
        raise typer.Exit(1)
    variant = f"{llm.model.replace(':', '-')}-sb{llm.num_ctx // 1024}k"
    created = ollama.client.post(
        f"{ollama.base_url}/api/create",
        json={
            "model": variant,
            "from": llm.model,
            "parameters": {"num_ctx": llm.num_ctx},
            "stream": False,
        },
    )
    if created.status_code != 200:
        console.print(f"[red]✗[/] no pude preparar {variant}: {escape(created.text[:200])}")
        raise typer.Exit(1)
    sync_agents(home)
    machine_config = home / ".cache" / "opencode.machine.json"
    machine_config.parent.mkdir(parents=True, exist_ok=True)
    machine_config.write_text(
        json.dumps(
            {
                "model": f"ollama/{variant}",
                "default_agent": "bibliotecario",
                "provider": {
                    "ollama": {
                        "models": {variant: {"name": f"{llm.model} ({llm.num_ctx // 1024}k)"}}
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    console.print(f"Abriendo OpenCode con [bold]{variant}[/] y las herramientas de la biblioteca…")
    os.chdir(home)
    os.environ["OPENCODE_CONFIG"] = str(machine_config)
    os.execvp("opencode", ["opencode"])


@app.command()
def ask(
    ctx: typer.Context,
    question: Annotated[str, typer.Argument(help="La pregunta.")],
    paper: Annotated[str | None, typer.Option(help="Solo sobre este artículo.")] = None,
    backend: Annotated[str | None, typer.Option(help="ollama, claude o anthropic (por defecto, del perfil).")] = None,
    project: ProjectOpt = None, study: StudyOpt = None, country: CountryOpt = None,
    as_json: JsonOpt = False,
) -> None:  # fmt: skip
    """Pregunta suelta respondida con la biblioteca (sin abrir chat), con citas de página."""
    from .ask import ask as ask_library

    lib = Library(_home(ctx))
    profile = load_profile(lib.home, detect_machine_name())
    if backend is None:
        uses_local = profile is not None and profile.llm.provider == "ollama" and profile.llm.model
        backend = "ollama" if uses_local else (profile.process.backend if profile else "claude")
    try:
        llm = get_backend(backend, profile, load_env(lib.home))
    except BackendError as exc:
        console.print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(1) from exc
    config = load_config(lib.home)
    language = {"es": "español", "en": "inglés"}.get(config.library.summary_language, "español")
    filters = _filters(project, study, country, None, None, None)
    try:
        if as_json:
            answer = ask_library(lib, llm, question, filters, paper, language)
        else:
            with console.status(f"Buscando y preguntando a {llm.name}…"):
                answer = ask_library(lib, llm, question, filters, paper, language)
    except BackendError as exc:
        console.print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(1) from exc
    if as_json:
        print(json.dumps(dataclasses.asdict(answer), ensure_ascii=False, indent=2))
        return
    console.print(escape(answer.answer))
    cited = ", ".join(answer.citekeys) or "ninguno"
    console.print(f"\n[dim]Artículos citados: {escape(cited)} · modelo: {escape(answer.model)}[/]")


eval_app = typer.Typer(help="Evaluaciones de la búsqueda.", no_args_is_help=True)
app.add_typer(eval_app, name="eval")


@eval_app.command("search")
def eval_search(
    ctx: typer.Context,
    path: Annotated[
        Path, typer.Argument(help='JSONL: {"q": "pregunta", "expected": "citekey"} por línea.')
    ],
    k: Annotated[int, typer.Option(help="Corte para recall@k.")] = 5,
    as_json: JsonOpt = False,
) -> None:
    """Mide recall@1, recall@k y MRR de la búsqueda en modo lexical, semantic y hybrid."""
    lib = Library(_home(ctx))
    cases = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    index = open_index(lib)
    modes = ["lexical"] + (["semantic", "hybrid"] if index.semantic else [])
    report = {}
    for mode in modes:
        ranks = []
        for case in cases:
            keys = [h.citekey for h in index.search(case["q"], Filters(), limit=20, mode=mode)]
            ranks.append(keys.index(case["expected"]) + 1 if case["expected"] in keys else None)
        found = [r for r in ranks if r]
        report[mode] = {
            "recall@1": sum(1 for r in found if r == 1) / len(cases),
            f"recall@{k}": sum(1 for r in found if r <= k) / len(cases),
            "mrr": sum(1 / r for r in found) / len(cases),
            "misses": [c["q"] for c, r in zip(cases, ranks, strict=True) if not r or r > k],
        }
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    _index_warning(index, False)
    console.print(f"{len(cases)} preguntas")
    for mode, row in report.items():
        console.print(
            f"[bold]{mode:9}[/] recall@1 {row['recall@1']:.2f} · recall@{k} {row[f'recall@{k}']:.2f} · MRR {row['mrr']:.2f}"
        )


# --- phase 8 extras ----------------------------------------------------------------


def _check_retractions(home: Path, as_json: bool) -> None:
    from .retractions import check_updates

    lib = Library(home)
    config = load_config(home)
    client = MetadataClient(lib.cache_dir, email=config.user.email)
    with console.status("Consultando Crossref (retractaciones y correcciones)…"):
        notices = check_updates(lib, client)
    if as_json:
        err_console.print(
            json.dumps([dataclasses.asdict(n) for n in notices], ensure_ascii=False, default=str)
        )
        return
    if not notices:
        console.print(
            "[green]✓[/] Ningún artículo tiene retractaciones, correcciones ni notas de Crossref."
        )
    for notice in notices:
        mark = "[bold red]⚠ RETRACTADO[/]" if notice.retracted else "[yellow]![/]"
        kinds = ", ".join(f"{u.type} ({u.date})" if u.date else u.type for u in notice.updates)
        new = " [bold](nuevo)[/]" if notice.new else ""
        console.print(f"{mark} [bold]{notice.citekey}[/]{new}: {escape(kinds)}")


def _reclassify(lib: Library, keys: list[str], as_json: bool, backend_name: str | None) -> None:
    if not keys:
        keys = [
            d.meta.citekey
            for d in lib.iter_papers()
            if not isinstance(d, InvalidDocument) and lib.fulltext_path(d.meta.citekey).is_file()
        ]
    machine = detect_machine_name()
    profile = load_profile(lib.home, machine)
    name = backend_name or (profile.process.backend if profile else "claude")
    try:
        backend = get_backend(name, profile, load_env(lib.home))
    except BackendError as exc:
        console.print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(1) from exc
    processor = Processor(lib, load_config(lib.home), backend, machine)
    results = []
    for number, key in enumerate(keys, start=1):
        if as_json:
            results.append(processor.reclassify(key))
            continue
        with console.status(f"[{number}/{len(keys)}] clasificando {key}…"):
            result = processor.reclassify(key)
        results.append(result)
        mark = "[green]✓[/]" if result.outcome == "processed" else "[red]✗[/]"
        console.print(f"{mark} {key}  [dim]{escape(result.message)}[/]")
    if as_json:
        print(json.dumps([dataclasses.asdict(r) for r in results], ensure_ascii=False, indent=2))
    if any(r.outcome == "error" for r in results):
        raise typer.Exit(1)


@app.command()
def read(
    ctx: typer.Context,
    citekey: Annotated[str, typer.Argument(help="Artículo.")],
    status: Annotated[str | None, typer.Option(help="por-leer, leyendo o leido.")] = None,
    rating: Annotated[int | None, typer.Option(min=1, max=5, help="Calificación de 1 a 5.")] = None,
    clear: Annotated[bool, typer.Option(help="Quitar estado y calificación.")] = False,
) -> None:
    """Estado de lectura y calificación de un artículo."""
    lib = Library(_home(ctx))
    doc = _read_paper(lib, citekey)
    if status is not None and status not in ("por-leer", "leyendo", "leido"):
        console.print("[red]✗[/] --status debe ser por-leer, leyendo o leido")
        raise typer.Exit(2)
    update = {"reading": None, "rating": None} if clear else {}
    if status is not None:
        update["reading"] = status
    if rating is not None:
        update["rating"] = rating
    paper = doc.meta.model_copy(update=update)
    if update:
        lib.write_paper(paper, doc.body)
    console.print(f"{citekey}: {paper.reading or 'sin estado'} {'★' * (paper.rating or 0)}")


@app.command()
def edit(
    ctx: typer.Context,
    citekey: Annotated[str, typer.Argument(help="Artículo.")],
    title: Annotated[str | None, typer.Option(help="Título.")] = None,
    author: Annotated[
        list[str] | None,
        typer.Option(help="'Apellido, Nombre'; repetible, sustituye la lista. Sin coma: organización."),
    ] = None,
    year: Annotated[int | None, typer.Option(min=1000, max=2100, help="Año.")] = None,
    type_: Annotated[str | None, typer.Option("--type", help="article-journal, thesis, report…")] = None,
    container: Annotated[str | None, typer.Option(help="Revista, libro o serie.")] = None,
    publisher: Annotated[str | None, typer.Option(help="Editorial o institución (en tesis, la universidad).")] = None,
    volume: Annotated[str | None, typer.Option(help="Volumen.")] = None,
    issue: Annotated[str | None, typer.Option(help="Número.")] = None,
    pages: Annotated[str | None, typer.Option(help="Páginas.")] = None,
    doi: Annotated[str | None, typer.Option(help="DOI ('' lo quita). No consulta Crossref.")] = None,
    from_doi: Annotated[str | None, typer.Option("--from-doi", help="Traer los metadatos de este DOI (Crossref/DataCite).")] = None,
    rekey: Annotated[bool, typer.Option("--rekey", help="Nuevo citekey según los metadatos; el anterior queda como alias.")] = False,
    key: Annotated[str | None, typer.Option("--key", help="Nuevo citekey elegido (implica --rekey).")] = None,
    accept: Annotated[bool, typer.Option("--accept", help="Aplicar los metadatos sugeridos por sb process.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Mostrar qué cambiaría sin escribir.")] = False,
    as_json: JsonOpt = False,
) -> None:  # fmt: skip
    """Corrige los metadatos de un artículo (y, si quieres, su citekey) sin tocar texto, resumen ni proyectos."""
    from .edit import EditError, edit_paper, lookup_doi, parse_author

    lib = Library(_home(ctx))
    _read_paper(lib, citekey)
    options = {"title": title, "year": year, "type": type_, "container_title": container,
               "publisher": publisher, "volume": volume, "issue": issue, "pages": pages, "doi": doi}  # fmt: skip
    changes = {k: v for k, v in options.items() if v is not None}
    try:
        if author:
            changes["authors"] = [parse_author(a) for a in author]
        doi_fields, source = None, "manual"
        if from_doi:
            client = MetadataClient(lib.cache_dir, email=load_config(lib.home).user.email)
            doi_fields, source = lookup_doi(client, normalize_doi(from_doi))
            doi_fields["doi"] = normalize_doi(from_doi)
        result = edit_paper(
            lib, citekey, changes, doi_fields=doi_fields, source=source,
            rekey=rekey, new_key=key, accept=accept, dry_run=dry_run,
        )  # fmt: skip
    except (EditError, NetworkError) as exc:
        console.print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(1) from exc
    if as_json:
        print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
        return
    prefix = "(simulación) " if dry_run else ""
    if not (result.changed or result.reviewed or result.old_citekey):
        console.print(f"{citekey}: nada que cambiar.")
        return
    if result.changed:
        console.print(f"[green]✓[/] {prefix}{citekey}: {', '.join(result.changed)}")
    if result.reviewed:
        console.print(f"[green]✓[/] {prefix}{citekey}: revisado, deja needs_review")
    if result.old_citekey:
        console.print(
            f"[green]✓[/] {prefix}citekey {result.old_citekey} → [bold]{result.citekey}[/] "
            f"({result.old_citekey} queda como alias; sb bib lo sigue exportando)"
        )
        for src, dest in result.renamed:
            console.print(f"    [dim]{src} → {dest}[/]")
        console.print(
            f"[dim]En tus otras computadoras el PDF local sigue como pdfs/{result.old_citekey}.pdf: "
            f"renómbralo a pdfs/{result.citekey}.pdf.[/]"
        )


@app.command()
def attach(
    ctx: typer.Context,
    citekey: Annotated[str, typer.Argument(help="Artículo.")],
    pdf: Annotated[Path, typer.Argument(help="PDF del material suplementario.")],
    label: Annotated[
        str | None, typer.Option(help="Descripción, p. ej. 'Datos de monitoreo'.")
    ] = None,
) -> None:
    """Agrega material suplementario a un artículo: su texto se vuelve buscable."""
    from .ingest.extract import ExtractionError
    from .supplements import SupplementError
    from .supplements import attach as attach_supplement

    lib = Library(_home(ctx))
    if not pdf.expanduser().is_file():
        console.print(f"[red]✗[/] no existe {escape(str(pdf))}")
        raise typer.Exit(2)
    try:
        supplement = attach_supplement(
            lib, load_config(lib.home), citekey, pdf.expanduser().resolve(), label
        )
    except (SupplementError, ExtractionError) as exc:
        console.print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(1) from exc
    console.print(
        f"[green]✓[/] {citekey}: suplemento {supplement.id} ({supplement.pages} pp.) → "
        f"{lib.supplement_pdf(citekey, supplement.id).relative_to(lib.home)}"
    )


@app.command()
def refs(
    ctx: typer.Context,
    citekey: Annotated[str | None, typer.Argument(help="Artículo (si no, el resumen de la biblioteca).")] = None,
    missing: Annotated[bool, typer.Option(help="Obras citadas por varios de tus artículos que no tienes.")] = False,
    min_count: Annotated[int, typer.Option("--min", min=1, help="Mínimo de artículos que la citan.")] = 2,
    limit: Annotated[int, typer.Option(min=1, help="Máximo de resultados.")] = 20,
    html: Annotated[bool, typer.Option("--html", help="Grafo interactivo en el navegador (.cache/grafo.html).")] = False,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Con --html: dónde guardar la página.")] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open", help="Con --html: abrirla en el navegador.")] = True,
    as_json: JsonOpt = False,
) -> None:  # fmt: skip
    """Citas dentro de la biblioteca (según Crossref): a quién cita un artículo y quién lo cita."""
    from .citations import build_graph, graph_html, missing_works

    lib = Library(_home(ctx))
    config = load_config(lib.home)
    if citekey:
        _read_paper(lib, citekey)
    with console.status("Leyendo las referencias de Crossref…"):
        graph = build_graph(lib, MetadataClient(lib.cache_dir, email=config.user.email))
    if html:
        papers = {
            d.meta.citekey: d.meta for d in lib.iter_papers() if not isinstance(d, InvalidDocument)
        }
        out = output.expanduser() if output else lib.cache_dir / "grafo.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(graph_html(graph, papers, min_count), encoding="utf-8")
        console.print(f"[green]✓[/] Grafo guardado en {escape(str(out))}")
        undated = sorted(k for k, p in papers.items() if p.year is None)
        if undated:
            shown = ", ".join(undated[:10]) + (" …" if len(undated) > 10 else "")
            console.print(
                f"[yellow]![/] {len(undated)} sin año (fijos en la animación, marcados como "
                f"pendientes): {shown}\n    [dim]Complétalo con: sb edit KEY --year AAAA[/]"
            )
        if open_browser:
            webbrowser.open(out.resolve().as_uri())
        return
    if missing:
        works = missing_works(graph, min_count, limit)
        if as_json:
            print(json.dumps([dataclasses.asdict(w) for w in works], ensure_ascii=False, indent=2))
            return
        if not works:
            console.print(
                f"Ninguna obra fuera de la biblioteca la citan {min_count} o más de tus artículos."
            )
        for work in works:
            desc = " · ".join(x for x in (work.author, work.year, work.container) if x)
            console.print(
                f"[bold]{len(work.cited_by)}×[/] {escape(work.title or work.doi)}  [dim]{escape(desc)}[/]"
            )
            console.print(f"    [dim]DOI {work.doi} · citado por {', '.join(work.cited_by)}[/]")
        console.print("\n[dim]Para registrarlas: sb ingest DOI (quedan esperando PDF).[/]")
        return
    if citekey:
        data = {
            "citekey": citekey,
            "cites": graph.cites.get(citekey, []),
            "cited_by": graph.cited_by.get(citekey, []),
            "references": graph.references.get(citekey),
        }
        if as_json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return
        if data["references"] is None:
            console.print(
                "[yellow]![/] Crossref no publica las referencias de este artículo (o no tiene DOI)."
            )
        else:
            console.print(f"{citekey} tiene {data['references']} referencias en Crossref.")
        console.print(f"Cita a (en tu biblioteca): {', '.join(data['cites']) or 'ninguno'}")
        console.print(f"Lo citan (en tu biblioteca): {', '.join(data['cited_by']) or 'ninguno'}")
        return
    rows = sorted(graph.cited_by.items(), key=lambda kv: -len(kv[1]))
    if as_json:
        print(
            json.dumps(
                {
                    "cited_by": graph.cited_by,
                    "cites": graph.cites,
                    "without_data": graph.without_data,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    console.print("Artículos más citados dentro de tu biblioteca:")
    for key, citing in rows[:limit]:
        if citing:
            console.print(f"  [bold]{len(citing)}[/] {key}  [dim]← {', '.join(citing)}[/]")
    if not any(citing for _, citing in rows):
        console.print("  (ninguno se cita entre sí todavía)")
    if graph.without_data:
        console.print(f"[dim]Sin referencias en Crossref: {', '.join(graph.without_data)}[/]")


def _pending_keys(lib: Library, config, stale: bool = False, figures: bool = True) -> list[str]:
    """Papers with full text whose summary, figures or metadata suggestion are still missing
    (or outdated with stale)."""
    checker = Processor(lib, config, backend=None, machine="")  # type: ignore[arg-type]
    keys = []
    for doc in lib.iter_papers():
        if isinstance(doc, InvalidDocument) or not lib.fulltext_path(doc.meta.citekey).is_file():
            continue
        if (
            checker.needs_summary(doc.meta, doc.body, stale)
            or (figures and checker.needs_figures(doc.meta, stale))
            or checker.needs_metadata(doc.meta)
        ):
            keys.append(doc.meta.citekey)
    return keys


def _git(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=home, capture_output=True, text=True)


def _ingest_all(
    lib: Library, ingestor: Ingestor, paths: list[Path], dois: list[str], push: bool
) -> None:
    """sb ingest --all: ingest → process everything pending → check → commit (→ push)."""
    console.rule("1/4 Ingesta")
    exit_code = 0
    try:
        _run_ingest(ingestor, paths, dois, as_json=False, dry_run=False, process=False)
    except typer.Exit as exc:  # some PDFs failed: they are in inbox/_errores, keep going
        exit_code = exc.exit_code or 0
        if exit_code == 2:
            raise

    console.rule("2/4 Procesamiento")
    keys = _pending_keys(lib, load_config(lib.home))
    if keys:
        results = _process_keys(lib, keys, quiet=False)
        if any(r.outcome == "error" for r in results.values()):
            exit_code = 1
    else:
        console.print("Nada pendiente.")

    console.rule("3/4 Validación")
    report = run_checks(lib.home)
    for issue in report.issues:
        mark = "[red]✗[/]" if issue.level == "error" else "[yellow]![/]"
        console.print(f"{mark} {escape(issue.path)}: {escape(issue.message)}")
    if not report.ok:
        console.print(
            f"[red]✗[/] {len(report.errors)} errores: no hago commit. Corrígelos y repite."
        )
        raise typer.Exit(1)
    console.print(
        f"[green]✓[/] Biblioteca válida ({report.papers} artículos, {report.projects} proyectos)."
    )

    console.rule("4/4 Git")
    if not (lib.home / ".git").exists():
        console.print("La biblioteca no es un repositorio git: no hay nada que guardar.")
        raise typer.Exit(exit_code)
    _git(lib.home, "add", "library")
    if _git(lib.home, "diff", "--cached", "--quiet").returncode == 0:
        console.print("Sin cambios que guardar.")
    else:
        changed = _git(lib.home, "diff", "--cached", "--name-only").stdout.split()
        papers = len({Path(p).stem for p in changed if p.startswith("library/papers/")})
        message = f"ingest/process: {papers} artículos actualizados (sb ingest --all)"
        committed = _git(lib.home, "commit", "-q", "-m", message)
        if committed.returncode != 0:
            console.print(
                f"[red]✗[/] git commit falló: {escape((committed.stderr or committed.stdout).strip())}"
            )
            raise typer.Exit(1)
        console.print(f"[green]✓[/] Commit: {escape(message)}")
    if push:
        pushed = _git(lib.home, "push", "-q")
        if pushed.returncode != 0:
            console.print(f"[red]✗[/] git push falló: {escape(pushed.stderr.strip())}")
            raise typer.Exit(1)
        console.print("[green]✓[/] Subido a GitHub.")
    else:
        console.print(
            "[dim]Para subirlo a GitHub: git push (o la próxima vez, sb ingest --all --push).[/]"
        )
    raise typer.Exit(exit_code)
