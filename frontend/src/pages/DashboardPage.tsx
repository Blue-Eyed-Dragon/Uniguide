import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { MessageCircleQuestion, CheckCircle2, Loader2, SearchX, TriangleAlert } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Button } from '@/components/ui/button'
import { ChatOverlay } from '@/components/ChatOverlay'

function monthYear(isoDate: string | null): string {
  if (!isoDate) return '—'
  return new Date(isoDate).toLocaleDateString(undefined, { month: 'short', year: 'numeric', timeZone: 'UTC' })
}

export function DashboardPage() {
  const { studentId } = useParams<{ studentId: string }>()

  const studentQuery = useQuery({
    queryKey: ['student', studentId],
    queryFn: () => api.getStudent(studentId!),
    enabled: !!studentId,
    retry: (failureCount, error) => !(error instanceof ApiError && error.status === 404) && failureCount < 2,
  })
  const planQuery = useQuery({
    queryKey: ['plan', studentId],
    queryFn: () => api.getPlan(studentId!),
    enabled: !!studentId,
  })

  const [chatOpen, setChatOpen] = useState(false)

  if (studentQuery.isLoading) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" />
        <p className="text-sm">Loading student…</p>
      </div>
    )
  }
  if (studentQuery.isError) {
    const notFound = studentQuery.error instanceof ApiError && studentQuery.error.status === 404
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-2 py-16 text-center text-muted-foreground">
          {notFound ? <SearchX className="size-8" /> : <TriangleAlert className="size-8 text-destructive" />}
          <p>{notFound ? `No student found for ID "${studentId}".` : 'Something went wrong loading this student.'}</p>
        </CardContent>
      </Card>
    )
  }

  const { profile, analysis, current_semester, current_semester_start_date } = studentQuery.data!
  const plan = planQuery.data?.plan ?? null

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle className="text-xl">{profile.name}</CardTitle>
            <p className="text-sm text-muted-foreground">
              {profile.program} · {profile.student_id} · Semester {current_semester} (
              {new Date(current_semester_start_date).toLocaleDateString(undefined, {
                year: 'numeric',
                timeZone: 'UTC',
              })}
              )
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {profile.interests.map((interest) => (
                <Badge key={interest} variant="accent">
                  {interest}
                </Badge>
              ))}
            </div>
          </div>
          <Button variant="accent" onClick={() => setChatOpen((v) => !v)}>
            <MessageCircleQuestion />
            Student Guide
          </Button>
        </CardHeader>
      </Card>

      <ChatOverlay
        studentId={studentId!}
        weakSubjects={analysis.weak_subjects}
        open={chatOpen}
        onOpenChange={setChatOpen}
      />

      <div className="grid gap-6 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Degree progress</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Progress value={analysis.credits_completed} max={analysis.credits_completed + analysis.credits_remaining} />
            <div className="flex justify-between text-sm text-muted-foreground">
              <span>
                {analysis.credits_completed} / {analysis.credits_completed + analysis.credits_remaining} ECTS
              </span>
              <span>{analysis.credits_remaining} remaining</span>
            </div>
            <p className="text-sm text-muted-foreground">GPA: {analysis.gpa ?? '—'}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Strengths &amp; weak subjects</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-1.5">
              {analysis.strong_subjects.map((tag) => (
                <Badge key={tag} variant="success">
                  {tag}
                </Badge>
              ))}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {analysis.weak_subjects.map((tag) => (
                <Badge key={tag} variant="warning">
                  {tag}
                </Badge>
              ))}
            </div>
            {analysis.strong_subjects.length === 0 && analysis.weak_subjects.length === 0 && (
              <p className="text-sm text-muted-foreground">Not enough graded courses yet to compute this.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Grades</CardTitle>
        </CardHeader>
        <CardContent>
          {profile.grades.length === 0 ? (
            <p className="text-sm text-muted-foreground">No grades on record yet.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-1.5 font-medium">Course</th>
                  <th className="py-1.5 font-medium">Title</th>
                  <th className="py-1.5 text-right font-medium">ECTS</th>
                  <th className="py-1.5 text-right font-medium">Grade</th>
                  <th className="py-1.5 text-right font-medium">Semester</th>
                </tr>
              </thead>
              <tbody>
                {profile.grades.map((g) => (
                  <tr key={g.course_id} className="border-b border-border last:border-0">
                    <td className="py-1.5">{g.course_id}</td>
                    <td className="py-1.5">{g.course_title}</td>
                    <td className="py-1.5 text-right">{g.ects}</td>
                    <td className={`py-1.5 text-right ${g.grade > 2.7 ? 'text-warning' : ''}`}>{g.grade}</td>
                    <td className="py-1.5 text-right">{g.semester ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Latest semester plan</CardTitle>
        </CardHeader>
        <CardContent>
          {!plan ? (
            <p className="text-sm text-muted-foreground">No plan yet — talk to your Student Guide to get started.</p>
          ) : (
            <div className="flex flex-col gap-4">
              {plan.semesters.map((block) => (
                <div key={block.semester_number} className="rounded-md border border-border p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h4 className="font-semibold">
                      Semester {block.semester_number} · {monthYear(block.start_date)}–{monthYear(block.end_date)} ·{' '}
                      {block.total_credits} ECTS
                    </h4>
                    {block.calendar_event_ids.length > 0 ? (
                      <Badge variant="success">
                        <CheckCircle2 className="mr-1 size-3" /> Synced
                      </Badge>
                    ) : (
                      <Badge variant="outline">Not synced</Badge>
                    )}
                  </div>
                  <div className="flex flex-col gap-2">
                    {block.courses.map((c) => (
                      <div key={c.course_id} className="flex flex-col gap-0.5 border-b border-border pb-2 last:border-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">
                            {c.course_id}: {c.title}
                          </span>
                          <span className="text-xs text-muted-foreground">{c.credits} ECTS</span>
                          {c.day_of_week && c.start_time && c.end_time && (
                            <span className="text-xs text-muted-foreground">
                              · {c.day_of_week} {c.start_time}–{c.end_time}
                            </span>
                          )}
                          {c.mandatory && <Badge variant="accent">Required</Badge>}
                          {!c.prerequisites_met && <Badge variant="destructive">Prereqs not met</Badge>}
                        </div>
                        <p className="text-xs text-muted-foreground">{c.rationale}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              <p className="text-sm text-muted-foreground">Total planned: {plan.total_planned_credits} ECTS</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
