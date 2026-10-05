"""Command-line interface ``sb``. Thin layer: parsing and printing only."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .checks import run_checks
from .config import HomeNotFoundError, find_home
from .doctor import library_status, run_doctor
from .machines import Agent, Backend, detect_machine_name, load_profile, profile_path
from .scaffold import ScaffoldReport, init_library, init_machine

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
        console.print(f"[red]✗[/] {exc}")
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
        table.add_row(STATE_STYLE[finding.state], finding.name, finding.detail)
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
            console.print(f"{mark} {issue.path}: {issue.message}")
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
