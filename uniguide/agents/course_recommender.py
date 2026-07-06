"""Course Recommender agent — ranked CourseRecommendation[] from a query.

`search_courses_tool` wraps `tools.rag_search_tool` and deterministically
computes `prerequisites_met` from the completed-course list, so the LLM never
has to reason about prerequisite logic itself — its job is picking the best
subset of the candidates returned and writing the `rationale` text.
"""

from google.adk.agents import LlmAgent

from uniguide.config import agent_model
from uniguide.models.course import CourseRecommendation
from uniguide.tools.rag_search_tool import rag_search_tool

INSTRUCTION = """\
You recommend courses to a student based on their academic profile and a
query describing what they need (e.g. a weak subject to reinforce, an
interest to pursue, or a general "what's next" request).

Call `search_courses_tool` with a query built from the student's weak
subjects / interests and their completed_course_ids so already-taken courses
are excluded. You may call it more than once with different queries to cover
multiple weak subjects or interests, then merge and de-duplicate results by
course_id.

For each course you decide to recommend, build a CourseRecommendation from
the tool's course dict: `credits` = the tool's `ects` value (same number,
renamed field). Then:
- Keep `relevance_score` exactly as returned by the tool — do not invent or
  adjust it.
- Keep `prerequisites_met` exactly as returned by the tool.
- Keep `link`, `mandatory`, `day_of_week`, `start_time`, and `end_time`
  exactly as returned by the tool (the latter three may be empty/null for
  courses with no fixed weekly class time, e.g. thesis entries).
- Write a one- or two-sentence `rationale` explaining why this course fits
  this specific student (tie it to their weak subjects, interests, or
  progression), not a generic course description.

Return only genuinely relevant courses, ranked by relevance_score
descending. Do not recommend a course whose prerequisites_met is false
unless no better-fitting alternative exists, and say so in the rationale.
"""


def search_courses_tool(
    query: str,
    completed_course_ids: list[str],
    top_k: int = 5,
) -> dict:
    """Search the course catalog and mark whether each result's prerequisites
    are satisfied by the student's completed courses.

    Args:
        query: what the student needs, e.g. "reinforce weak subject: statistics"
            or "interested in natural language processing".
        completed_course_ids: course_ids the student has already completed.
        top_k: maximum number of candidate courses to return.

    Returns:
        Same shape as `tools.rag_search_tool`, with each course dict also
        carrying `prerequisites_met: bool`.
    """
    result = rag_search_tool(query, top_k=top_k, completed_course_ids=completed_course_ids)
    if not result["success"]:
        return result

    completed = set(completed_course_ids)
    for course in result["courses"]:
        course["prerequisites_met"] = all(p in completed for p in course["prerequisites"])

    return result


course_recommender = LlmAgent(
    name="course_recommender",
    model=agent_model(),
    description="Recommends and ranks courses for a student from a query, with rationale.",
    instruction=INSTRUCTION,
    tools=[search_courses_tool],
    output_schema=list[CourseRecommendation],
    output_key="course_recommendations",
)
