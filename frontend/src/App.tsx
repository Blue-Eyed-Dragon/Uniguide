import { Route, Routes } from 'react-router-dom'

import { Header } from '@/components/Header'
import { StudentSearchPage } from '@/pages/StudentSearchPage'
import { DashboardPage } from '@/pages/DashboardPage'

function App() {
  return (
    <div className="min-h-svh bg-background text-foreground">
      <Header />
      <main className="mx-auto max-w-5xl px-4 py-8">
        <Routes>
          <Route path="/" element={<StudentSearchPage />} />
          <Route path="/students/:studentId" element={<DashboardPage />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
