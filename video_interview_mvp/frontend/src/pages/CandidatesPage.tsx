import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Clock3, Copy, FileText, Search, Send } from 'lucide-react'
import { PageBody, PageHeader, StatTile } from '@/components/layout/AppShell'
import { STAGE_META } from '@/components/workspace/StageStrip'
import { api } from '@/lib/api'
import type { CandidateRow, CandidatesResponse, Stage } from '@/lib/types'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

const TURN_LABEL: Record<string, { text: string; chip: string }> = {
  recruiter: { text: 'ждёт вас', chip: 'bg-bad-tint text-bad-ink' },
  manager: { text: 'ждёт менеджера', chip: 'bg-warn-tint text-warn-ink' },
  candidate: { text: 'ждём кандидата', chip: 'bg-secondary text-ink-3' },
}

const FILTERS = [
  ['all', 'Все'],
  ['recruiter', 'Требуют решения'],
  ['candidate', 'Ждём кандидата'],
  ['done', 'Завершённые'],
] as const

export function CandidatesPage() {
  const navigate = useNavigate()
  const [data, setData] = useState<CandidatesResponse | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>('all')
  const [vacancyId, setVacancyId] = useState<number | 'all'>('all')

  useEffect(() => {
    api
      .get<CandidatesResponse>('/api/workspace/candidates')
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    // Кто ждёт рекрутера — наверх: список нужен именно для того, чтобы
    // разобрать очередь своих решений.
    const priority: Record<string, number> = { recruiter: 0, manager: 1, candidate: 2 }
    const sorted = [...(data?.candidates ?? [])].sort(
      (a, b) => (priority[a.waiting_on ?? ''] ?? 3) - (priority[b.waiting_on ?? ''] ?? 3),
    )
    return sorted.filter((row) => {
      if (vacancyId !== 'all' && row.vacancy_id !== vacancyId) return false
      if (needle && !row.name.toLowerCase().includes(needle)) return false
      if (filter === 'recruiter') return row.waiting_on === 'recruiter'
      if (filter === 'candidate') return row.waiting_on === 'candidate'
      if (filter === 'done') return row.stage === 'advanced' || row.stage === 'rejected'
      return true
    })
  }, [data, query, filter, vacancyId])

  async function copyLink(row: CandidateRow) {
    await navigator.clipboard.writeText(new URL(row.interview_url, location.origin).href)
    toast.success('Ссылка скопирована')
  }

  return (
    <>
      <PageHeader
        eyebrow={<span className="text-[12.5px] font-medium text-ink-3">Рабочее место</span>}
        title="Кандидаты"
        description="Все кандидаты по всем вакансиям. Доска отвечает, что происходит по одной вакансии, этот список — где вообще все и кто ждёт вашего решения."
      />

      <PageBody>
        {error && (
          <p className="rounded-lg border border-bad/25 bg-bad-tint px-4 py-3 text-[13px] text-bad-ink">{error}</p>
        )}

        {!data && !error && (
          <>
            <div className="mb-6 grid gap-3 sm:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-24 rounded-xl" />
              ))}
            </div>
            <Skeleton className="h-80 rounded-xl" />
          </>
        )}

        {data && (
          <>
            <div className="mb-6 grid gap-3 sm:grid-cols-3">
              <StatTile
                label="Всего кандидатов"
                value={data.counts.total}
                hint={`по ${data.vacancies.length} вакансиям`}
                icon={FileText}
              />
              <StatTile
                label="Ждём кандидата"
                value={data.counts.waiting_candidate}
                hint="ссылка отправлена, интервью не пройдено"
                icon={Send}
                tone="brand"
              />
              <StatTile
                label="Требуют вашего решения"
                value={data.counts.waiting_recruiter}
                hint={data.counts.waiting_recruiter > 0 ? 'откройте и вынесите вердикт' : 'очереди нет'}
                icon={Clock3}
                tone={data.counts.waiting_recruiter > 0 ? 'bad' : 'ink'}
              />
            </div>

            <div className="mb-4 flex flex-wrap items-center gap-3">
              <div className="relative min-w-56 flex-1">
                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-3" strokeWidth={2} />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Поиск по имени"
                  className="w-full rounded-lg border border-line-2 bg-card py-2.5 pl-9 pr-3.5 text-[13.5px] outline-none transition-colors placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
                />
              </div>

              <select
                value={vacancyId}
                onChange={(event) =>
                  setVacancyId(event.target.value === 'all' ? 'all' : Number(event.target.value))
                }
                className="rounded-lg border border-line-2 bg-card px-3 py-2.5 text-[13.5px] outline-none focus:border-brand"
              >
                <option value="all">Все вакансии</option>
                {data.vacancies.map((vacancy) => (
                  <option key={vacancy.id} value={vacancy.id}>
                    {vacancy.title}
                  </option>
                ))}
              </select>

              <div className="flex gap-1 rounded-[10px] bg-secondary p-1">
                {FILTERS.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setFilter(key)}
                    className={cn(
                      'rounded-lg px-3 py-1.5 text-[12.5px] transition-all duration-200',
                      filter === key
                        ? 'bg-card font-semibold text-ink shadow-[0_1px_3px_rgba(0,0,0,0.1)]'
                        : 'font-medium text-ink-3 hover:text-ink-2',
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="overflow-hidden rounded-xl bg-card shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
              {rows.length === 0 ? (
                <p className="px-6 py-14 text-center text-[13px] text-ink-3">
                  {data.counts.total === 0 ? 'Кандидатов пока нет' : 'Ничего не нашлось по этим фильтрам'}
                </p>
              ) : (
                <ul className="divide-y divide-line">
                  {rows.map((row) => {
                    const meta = STAGE_META[row.stage as Stage]
                    const turn = row.waiting_on ? TURN_LABEL[row.waiting_on] : null
                    return (
                      <li
                        key={row.id}
                        onClick={() => {
                          if (row.has_report) navigate(`/reports/${row.id}`)
                        }}
                        className={cn(
                          'flex items-center gap-4 px-4 py-3.5 transition-colors',
                          row.has_report ? 'cursor-pointer hover:bg-secondary/60' : 'hover:bg-secondary/40',
                        )}
                      >
                        <span className="h-9 w-[3px] shrink-0 rounded-full" style={{ background: meta.strip }} />

                        <div className="min-w-0 flex-[2]">
                          <p className="truncate text-[13.5px] font-semibold text-ink">{row.name}</p>
                          <Link
                            to={`/vacancies/${row.vacancy_id}`}
                            onClick={(event) => event.stopPropagation()}
                            className="truncate text-[11.5px] text-ink-3 transition-colors hover:text-brand"
                          >
                            {row.vacancy_title}
                          </Link>
                        </div>

                        <span className={cn('pill hidden shrink-0 sm:inline-flex', meta.chip)}>{meta.full}</span>

                        {turn && <span className={cn('pill hidden shrink-0 md:inline-flex', turn.chip)}>{turn.text}</span>}

                        <span className="tnum hidden w-16 shrink-0 text-right text-[11.5px] text-ink-3 lg:block">
                          {row.days_in_stage !== null ? `${row.days_in_stage} дн.` : '—'}
                        </span>

                        <span className="tnum w-10 shrink-0 text-right text-[16px] font-bold tracking-[-0.02em]">
                          {row.overall_score !== null ? (
                            <span className={row.overall_score >= 7.5 ? 'text-ok' : row.overall_score >= 5 ? 'text-warn-ink' : 'text-bad'}>
                              {row.overall_score.toFixed(1)}
                            </span>
                          ) : (
                            <span className="text-ink-3/60">—</span>
                          )}
                        </span>

                        <div className="flex shrink-0 gap-1.5">
                          {row.has_report ? (
                            <span className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[11.5px] font-medium text-ink-2">
                              <FileText className="size-3" strokeWidth={1.9} />
                              Заключение
                            </span>
                          ) : (
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation()
                                void copyLink(row)
                              }}
                              className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[11.5px] font-medium text-ink-2 transition-colors hover:border-brand hover:text-brand"
                            >
                              <Copy className="size-3" strokeWidth={1.9} />
                              Ссылка
                            </button>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </>
        )}
      </PageBody>
    </>
  )
}
