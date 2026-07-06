import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function StudentSearchPage() {
  const [studentId, setStudentId] = useState('')
  const navigate = useNavigate()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (studentId.trim()) navigate(`/students/${studentId.trim()}`)
  }

  return (
    <div className="flex justify-center pt-16">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Find your dashboard</CardTitle>
          <CardDescription>Enter your Student ID / Matrikelnummer to view your academic progress.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex gap-2">
            <input
              value={studentId}
              onChange={(e) => setStudentId(e.target.value)}
              placeholder="e.g. demo-student-001"
              autoFocus
              className="flex-1 rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
            <Button type="submit" disabled={!studentId.trim()}>
              <Search />
              Go
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
