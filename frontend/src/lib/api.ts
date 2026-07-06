export interface Grade {
  course_id: string
  course_title: string
  ects: number
  grade: number
  semester: number | null
}

export interface StudentProfile {
  student_id: string
  name: string
  program: string
  semesters_completed: number
  grades: Grade[]
  interests: string[]
}

export interface ProfileAnalysis {
  credits_completed: number
  credits_remaining: number
  completed_course_ids: string[]
  weak_subjects: string[]
  strong_subjects: string[]
  gpa: number | null
}

export interface StudentDashboard {
  profile: StudentProfile
  analysis: ProfileAnalysis
  current_semester: number
  current_semester_start_date: string
}

export interface CourseRecommendation {
  course_id: string
  title: string
  credits: number
  relevance_score: number
  rationale: string
  semester_offered: number[]
  prerequisites_met: boolean
  link: string
  mandatory: boolean
  day_of_week: string | null
  start_time: string | null
  end_time: string | null
}

export interface SemesterBlock {
  semester_number: number
  courses: CourseRecommendation[]
  total_credits: number
  calendar_event_ids: string[]
  start_date: string | null
  end_date: string | null
}

export interface SemesterPlan {
  student_id: string
  semesters: SemesterBlock[]
  total_planned_credits: number
  graduation_semester: number
}

export interface PlanResponse {
  plan: SemesterPlan | null
}

export interface CreditGap {
  student_id: string
  credits_completed: number
  credits_remaining: number
  degree_total_ects: number
}

export interface ChatContext {
  profile: StudentProfile | null
  semester_plan: SemesterPlan | null
}

export interface ChatResponse {
  reply: string
}

// One id per page load (not persisted), so a browser refresh starts a new
// conversation instead of resuming whatever was last saved for this student.
const CHAT_SESSION_TOKEN = crypto.randomUUID()

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }
  return res.json() as Promise<T>
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}))
    throw new ApiError(res.status, errBody.detail ?? res.statusText)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => getJSON<{ status: string }>('/health'),
  getStudent: (studentId: string) => getJSON<StudentDashboard>(`/students/${studentId}`),
  getPlan: (studentId: string) => getJSON<PlanResponse>(`/students/${studentId}/plan`),
  getCreditGap: (studentId: string) => getJSON<CreditGap>(`/students/${studentId}/credit-gap`),
  getChatContext: (studentId: string) => getJSON<ChatContext>(`/students/${studentId}/chat/context`),
  postChat: (studentId: string, message: string) =>
    postJSON<ChatResponse>(`/students/${studentId}/chat`, { message, session_token: CHAT_SESSION_TOKEN }),
}

export { ApiError }
