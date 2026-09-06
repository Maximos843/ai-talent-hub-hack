import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Archive, Plus } from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/AppShell'
import { VacancyCard } from '@/components/workspace/VacancyCard'
import { api } from '@/lib/api'
import type { VacancyCardData } from '@/lib/types'
import { Skeleton } from '@/components/ui/skeleton'

function Section({
  label,
  count,
  note,
  children,
}: {
  label: string
  count: number
  note?: string
  children: React.ReactNode
}) {
  if (count === 0) return null
  return (
    <section className="mb-12">
      <div className="mb-5 flex items-baseline gap-3">
        <h2 className="eyebrow !text-[10.5px] text-ink-2">{label}</h2>
        <span className="tnum text-[11px] text-ink-3">{count}</span>
        <span className="h-px flex-1 bg-line" />
        {note && <span className="text-[11.5px] text-ink-3">{note}</span>}
      </div>
      <div className="stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{children}</div>
    </section>
  )
}

export function VacanciesPage() {
  const [vacancies, setVacancies] = useState<VacancyCardData[] | null>(null)
  const [error, setError] = useState('')
  const [showArchive, setShowArchive] = useState(false)

  useEffect(() => {
    api
      .get<VacancyCardData[]>('/api/workspace/vacancies')
      .then(setVacancies)
      .catch((e) => setError(e.message))
  }, [])

  const active = vacancies?.filter((v) => v.status === 'active') ?? []
  const drafts = vacancies?.filter((v) => v.status === 'draft') ?? []
  const closed = vacancies?.filter((v) => v.status === 'closed') ?? []
  const inFunnel = active.reduce((sum, v) => sum + v.candidates_total, 0)

  return (
    <>
      <PageHeader
        eyebrow="Рабочее место"
        title="Вакансии"
        description={
          vacancies
            ? `${active.length} в работе · ${inFunnel} кандидатов в воронке`
            : 'Загружаем вакансии…'
        }
        actions={
          <Link
            to="/vacancies/new"
            className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2.5 text-[13px] font-semibold text-white transition-colors hover:bg-brand-press"
          >
            <Plus className="size-4" strokeWidth={2.25} />
            Создать вакансию
          </Link>
        }
      />

      <PageBody>
        {error && (
          <p className="rounded-lg border border-bad/25 bg-bad-tint px-4 py-3 text-[13px] text-bad">{error}</p>
        )}

        {!vacancies && !error && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-56 rounded-xl" />
            ))}
          </div>
        )}

        {vacancies && vacancies.length === 0 && (
          <div className="rounded-xl border border-dashed border-line-2 px-8 py-16 text-center">
            <h3 className="text-[21px] font-semibold">Пока ни одной вакансии</h3>
            <p className="mx-auto mt-2 max-w-md text-[13.5px] leading-relaxed text-ink-2">
              Загрузите описание вакансии файлом или текстом&nbsp;— система разберёт требования и предложит
              вопросы под них.
            </p>
            <Link
              to="/vacancies/new"
              className="mt-6 inline-flex items-center gap-2 rounded-lg bg-ink px-4 py-2.5 text-[13px] font-semibold text-white"
            >
              <Plus className="size-4" strokeWidth={2.25} />
              Создать первую
            </Link>
          </div>
        )}

        <Section label="В работе" count={active.length}>
          {active.map((v) => (
            <VacancyCard key={v.id} vacancy={v} />
          ))}
        </Section>

        <Section label="Черновики" count={drafts.length} note="Ждут утверждения вопросов">
          {drafts.map((v) => (
            <VacancyCard key={v.id} vacancy={v} />
          ))}
        </Section>

        {closed.length > 0 && (
          <section>
            <button
              type="button"
              onClick={() => setShowArchive((value) => !value)}
              className="flex w-full items-center gap-3 py-3 text-left"
            >
              <Archive className="size-3.5 text-ink-3" strokeWidth={1.75} />
              <span className="eyebrow !text-[10.5px] text-ink-3">Архив закрытых</span>
              <span className="tnum text-[11px] text-ink-3">{closed.length}</span>
              <span className="h-px flex-1 bg-line" />
              <span className="text-[11.5px] text-ink-3">{showArchive ? 'Свернуть' : 'Показать'}</span>
            </button>
            {showArchive && (
              <div className="stagger mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {closed.map((v) => (
                  <VacancyCard key={v.id} vacancy={v} />
                ))}
              </div>
            )}
          </section>
        )}
      </PageBody>
    </>
  )
}
