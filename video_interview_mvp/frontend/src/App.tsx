import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { VacanciesPage } from '@/pages/VacanciesPage'
import { VacancyBoardPage } from '@/pages/VacancyBoardPage'
import { VacancyQuestionsPage } from '@/pages/VacancyQuestionsPage'
import { NewVacancyPage } from '@/pages/NewVacancyPage'
import { CandidatesPage } from '@/pages/CandidatesPage'
import { QuestionBankPage } from '@/pages/QuestionBankPage'
import { ReportPage } from '@/pages/ReportPage'
import { ManagerQueuePage } from '@/pages/ManagerQueuePage'
import { Toaster } from '@/components/ui/sonner'
import type { CurrentUser } from '@/lib/types'

declare global {
  interface Window {
    __USER__?: CurrentUser
  }
}

const user: CurrentUser = window.__USER__ ?? { username: '—', role: 'hr', full_name: null }

export default function App() {
  // Менеджеру разделы рекрутера всё равно закрыты на бэкенде — не водим его туда.
  const home = user.role === 'hr' ? '/vacancies' : '/review'

  return (
    <BrowserRouter basename="/app">
      <AppShell user={user}>
        <Routes>
          <Route path="/" element={<Navigate to={home} replace />} />
          <Route path="/review" element={<ManagerQueuePage />} />
          <Route path="/vacancies" element={<VacanciesPage />} />
          <Route path="/vacancies/new" element={<NewVacancyPage />} />
          <Route path="/vacancies/:id" element={<VacancyBoardPage />} />
          <Route path="/vacancies/:id/questions" element={<VacancyQuestionsPage />} />
          <Route path="/candidates" element={<CandidatesPage />} />
          <Route path="/questions" element={<QuestionBankPage />} />
          <Route path="/reports/:id" element={<ReportPage />} />
          <Route path="*" element={<Navigate to={home} replace />} />
        </Routes>
      </AppShell>
      <Toaster position="bottom-right" />
    </BrowserRouter>
  )
}
