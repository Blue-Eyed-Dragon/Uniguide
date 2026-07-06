"""python -m uniguide --student-id ID --semester N [--interests a,b] [--target-credits N]
[--seed-profile p.json] [--seed-transcript t.pdf] [--sync-calendar] [--report out.md]"""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from uniguide import runner

console = Console()


@click.command()
@click.option("--student-id", required=True, help="The student's ID.")
@click.option("--semester", "current_semester", required=True, type=int, help="Semester being planned for.")
@click.option(
    "--interests",
    default="",
    help="Comma-separated interests for this planning session, e.g. 'nlp,mlops'.",
)
@click.option(
    "--target-credits",
    "target_credits_per_semester",
    type=int,
    default=None,
    help="Override the default max ECTS per semester.",
)
@click.option(
    "--full-plan/--no-full-plan",
    "plan_full_degree",
    default=None,
    help="Plan the whole remaining degree, not just personalized picks. "
    "If omitted, you'll be asked interactively.",
)
@click.option(
    "--seed-profile",
    "seed_profile_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Onboarding only: StudentProfile JSON to seed the DB with before planning.",
)
@click.option(
    "--seed-transcript",
    "seed_transcript_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Onboarding only: transcript PDF to seed the DB's grades with before planning.",
)
@click.option(
    "--sync-calendar",
    is_flag=True,
    default=False,
    help="Also create Google Calendar events for the resulting plan.",
)
@click.option(
    "--report",
    "report_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write a Markdown report to this path.",
)
def main(
    student_id: str,
    current_semester: int,
    interests: str,
    target_credits_per_semester: int | None,
    plan_full_degree: bool | None,
    seed_profile_path: str | None,
    seed_transcript_path: str | None,
    sync_calendar: bool,
    report_path: str | None,
) -> None:
    """Run the UniGuide pipeline end-to-end for one student."""
    interest_list = [i.strip() for i in interests.split(",") if i.strip()]
    if plan_full_degree is None:
        plan_full_degree = click.confirm(
            "Plan your entire remaining degree, not just personalized picks?",
            default=False,
        )
    with console.status("Running UniGuide pipeline..."):
        try:
            result = runner.run(
                student_id,
                current_semester,
                interests=interest_list,
                target_credits_per_semester=target_credits_per_semester,
                plan_full_degree=plan_full_degree,
                seed_profile_path=seed_profile_path,
                seed_transcript_path=seed_transcript_path,
                sync_calendar=sync_calendar,
            )
        except Exception as exc:
            console.print(f"[bold red]Pipeline crashed:[/bold red] {exc}")
            sys.exit(1)

    if not result["success"]:
        console.print(f"[bold red]Pipeline failed at {result['stage']}:[/bold red] {result['error']}")
        sys.exit(1)

    _render(result)

    if report_path:
        Path(report_path).write_text(_render_markdown(result), encoding="utf-8")
        console.print(f"\nReport written to [bold]{report_path}[/bold]")


def _render(result: dict) -> None:
    analysis = result["profile_analysis"]
    total_credits = analysis["credits_completed"] + analysis["credits_remaining"]

    if result["is_fresh_student"]:
        console.print("[bold cyan]New student — here's a starter plan.[/bold cyan]")
    else:
        console.print("[bold cyan]Welcome back.[/bold cyan]")

    console.print("\n[bold]Profile Analysis[/bold]")
    console.print(f"Credits: {analysis['credits_completed']}/{total_credits}  |  GPA: {analysis['gpa']}")
    if analysis["weak_subjects"]:
        console.print(f"Weak subjects: {', '.join(analysis['weak_subjects'])}")
    if analysis["strong_subjects"]:
        console.print(f"Strong subjects: {', '.join(analysis['strong_subjects'])}")

    console.print("\n[bold]Semester Plan[/bold]")
    for block in result["semester_plan"]["semesters"]:
        table = Table(title=f"Semester {block['semester_number']} ({block['total_credits']} ECTS)")
        table.add_column("Course")
        table.add_column("Title")
        table.add_column("ECTS", justify="right")
        table.add_column("Required", justify="center")
        table.add_column("Rationale")
        table.add_column("Enroll")
        for course in block["courses"]:
            table.add_row(
                course["course_id"],
                course["title"],
                str(course["credits"]),
                "Yes" if course.get("mandatory") else "",
                course["rationale"],
                course.get("link", ""),
            )
        console.print(table)

    if result["plan_full_degree"]:
        console.print(f"\nGraduation semester: {result['semester_plan']['graduation_semester']}")
    else:
        console.print(
            "\n[dim]Last planned semester (personalized picks only — "
            f"pass --full-plan to see your whole remaining degree): "
            f"{result['semester_plan']['graduation_semester']}[/dim]"
        )

    if result["calendar_synced"]:
        console.print("[green]Calendar events created.[/green]")
    elif result["calendar_error"]:
        console.print(f"[yellow]Calendar sync skipped:[/yellow] {result['calendar_error']}")


def _render_markdown(result: dict) -> str:
    analysis = result["profile_analysis"]
    total_credits = analysis["credits_completed"] + analysis["credits_remaining"]

    lines = ["# UniGuide Semester Plan", ""]
    lines.append(
        "**New student — starter plan**  " if result["is_fresh_student"] else "**Welcome back**  "
    )
    lines.append(f"**Credits:** {analysis['credits_completed']}/{total_credits}  ")
    lines.append(f"**GPA:** {analysis['gpa']}  ")
    if analysis["weak_subjects"]:
        lines.append(f"**Weak subjects:** {', '.join(analysis['weak_subjects'])}  ")
    if analysis["strong_subjects"]:
        lines.append(f"**Strong subjects:** {', '.join(analysis['strong_subjects'])}  ")
    lines.append("")

    for block in result["semester_plan"]["semesters"]:
        lines.append(f"## Semester {block['semester_number']} ({block['total_credits']} ECTS)")
        lines.append("")
        lines.append("| Course | Title | ECTS | Required | Rationale | Enroll |")
        lines.append("|---|---|---|---|---|---|")
        for course in block["courses"]:
            required = "Yes" if course.get("mandatory") else ""
            link = course.get("link", "")
            enroll = f"[Enroll]({link})" if link else ""
            lines.append(
                f"| {course['course_id']} | {course['title']} | {course['credits']} | "
                f"{required} | {course['rationale']} | {enroll} |"
            )
        lines.append("")

    if result["plan_full_degree"]:
        lines.append(f"**Graduation semester:** {result['semester_plan']['graduation_semester']}")
    else:
        lines.append(
            "**Last planned semester** (personalized picks only — pass `--full-plan` "
            f"to see your whole remaining degree): {result['semester_plan']['graduation_semester']}"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    main()
