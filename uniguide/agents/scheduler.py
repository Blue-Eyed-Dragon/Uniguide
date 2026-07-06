"""Scheduler agent — turns ranked CourseRecommendations into a SemesterPlan.

Wraps `tools.scheduler_tool` (deterministic credit-cap / semester-rotation
bin-packing) behind an LlmAgent, same pattern as profile_analyst: the LLM's
job is to call the tool and return its result unchanged, not to do the
credit-counting arithmetic itself.

Unlike profile_analyst and course_recommender, this agent is built per-call
via `build_scheduler()` rather than exported as a single module-level
instance: the candidate course list is bound into the tool's closure instead
of being passed as an LLM-supplied function-call argument, so the model
never has to transcribe a large CourseRecommendation list (with long
rationale text) through a function call — it only has to call the
zero-argument tool and echo back its result.
"""

from google.adk.agents import LlmAgent

from uniguide.config import agent_model
from uniguide.models.plan import SemesterPlan
from uniguide.tools.scheduler_tool import build_semester_plan_tool

INSTRUCTION = """\
You turn this student's ranked course recommendations into a multi-semester
study plan.

Call `schedule_courses_tool` (it takes no arguments — the student's data is
already bound to it) and return its `semester_plan` fields exactly as given.
Do not recompute credit totals, add courses it didn't schedule, or change
semester numbers yourself. If it returns success=False, report that no plan
could be built and why.
"""


def build_scheduler(
    student_id: str,
    credits_remaining: int,
    completed_course_ids: list[str],
    candidate_courses: list[dict],
    current_semester: int,
    max_credits_per_semester: int | None = None,
) -> LlmAgent:
    """Build a Scheduler LlmAgent bound to one student's scheduling inputs."""

    def schedule_courses_tool() -> dict:
        """Schedule this student's ranked candidate courses into semesters.

        Returns:
            Same shape as `tools.scheduler_tool.build_semester_plan_tool`.
        """
        return build_semester_plan_tool(
            student_id=student_id,
            credits_remaining=credits_remaining,
            completed_course_ids=completed_course_ids,
            candidate_courses=candidate_courses,
            current_semester=current_semester,
            max_credits_per_semester=max_credits_per_semester,
        )

    return LlmAgent(
        name="scheduler",
        model=agent_model(),
        description="Schedules ranked course recommendations into a multi-semester plan.",
        instruction=INSTRUCTION,
        tools=[schedule_courses_tool],
        output_schema=SemesterPlan,
        output_key="semester_plan",
    )
