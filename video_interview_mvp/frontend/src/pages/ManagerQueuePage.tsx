import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, ClipboardCheck, Clock3 } from 'lucide-react'
import { PageBody, PageHeader, StatTile } from '@/components/layout/AppShell'
import { api } from '@/lib/api'
import type { CandidateRow } from '@/lib/types'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

interface ManagerCandidate extends CandidateRow {
  summary: string
  hr_comment: string
  hr_reviewer: string
  decided: boolean
  manager_decision: string | null
}

interface ManagerResponse {
  candidates: ManagerCandidate[]
  counts: { pending: number; total: number }
}

function scoreTone(score: number) {
  if (score >= 7.5) return 'text-ok'
  if (score >= 5) return 'text-warn-ink'
  return 'text-bad'
}

export function ManagerQueuePage() {
  const navigate = useNavigate()
  const [data, setData] = useState<ManagerResponse | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<ManagerResponse>('/api/workspace/manager/candidates')
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  const pending = (data?.candidates ?? []).filter((item) => !item.decided)
  const decided = (data?.candidates ?? []).filter((item) => item.decided)

  return (
    <>
      <PageHeader
        eyebrow={<span className="text-[12.5px] font-medium text-ink-3">Финальный этап</span>}
        title="На решение"
        description="Кандидаты, которых рекрутер передал вам после технической оценки. Заключение открывается только после его одобрения."
      />

      <PageBody>
        {error && (
          <p className="rounded-lg border border-bad/25 bg-bad-tint px-4 py-3 text-[13px] text-bad-ink">{error}</p>
        )}

        {!data && !error && (
          <>
            <div className="mb-6 grid gap-3 sm:grid-cols-2">
              {[0, 1].map((i) => (
                <Skeleton key={i} className="h-24 rounded-xl" />
              ))}
            </div>
            <Skeleton className="h-64 rounded-xl" />
          </>
        )}

        {data && (
          <>
            <div className="mb-6 grid gap-3 sm:grid-cols-2">
              <StatTile
                label="Всего передано вам"
                value={data.counts.total}
                hint="за всё время"
                icon={ClipboardCheck}
              />
              <StatTile
                label="Ждут вашего решения"
                value={data.counts.pending}
                hint={data.counts.pending > 0 ? 'откройте заключение и решите' : 'очереди нет'}
                icon={Clock3}
                tone={data.counts.pending > 0 ? 'bad' : 'ink'}
              />
            </div>

            {pending.length === 0 && decided.length === 0 && (
              <div className="rounded-xl border border-dashed border-line-2 px-8 py-16 text-center">
                <h3 className="text-[18px] font-bold text-ink-700">Пока никого не передали</h3>
                <p className="mx-auto mt-2 max-w-md text-[13.5px] leading-relaxed text-ink-2">
                  Кандидат появится здесь, когда рекрутер посмотрит заключение и пропустит его дальше.
                </p>
              </div>
            )}

            {[
              ['Ждут решения', pending],
              ['Решение принято', decided],
            ].map(([title, items]) =>
              (items as ManagerCandidate[]).length > 0 ? (
                <section key={title as string} className="mb-8">
                  <div className="mb-4 flex items-baseline gap-3">
                    <h2 className="text-[13px] font-bold text-ink-700">{title as string}</h2>
                    <span className="tnum text-[12px] text-ink-3">{(items as ManagerCandidate[]).length}</span>
                    <span className="h-px flex-1 bg-line" />
                  </div>

                  <div className="stagger grid gap-4 lg:grid-cols-2">
                    {(items as ManagerCandidate[]).map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => navigate(`/reports/${item.id}`)}
                        className={cn(
                          'group rounded-xl bg-card p-5 text-left shadow-[0_6px_24px_rgba(19,19,19,0.06)] transition-all hover:-translate-y-0.5 hover:shadow-[0_10px_30px_rgba(19,19,19,0.09)]',
                          item.decided && 'opacity-70',
                        )}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <p className="text-[11.5px] text-ink-3">{item.vacancy_title}</p>
                            <h3 className="mt-0.5 text-[17px] font-bold tracking-[-0.02em] text-ink">{item.name}</h3>
                          </div>
                          <span className="shrink-0 text-right">
                            <span
                              className={cn(
                                'tnum text-[24px] leading-none font-bold tracking-[-0.03em]',
                                item.overall_score !== null ? scoreTone(item.overall_score) : 'text-ink-3',
                              )}
                            >
                              {item.overall_score !== null ? item.overall_score.toFixed(1) : '—'}
                            </span>
                            <span className="tnum text-[14px] font-semibold text-ink-3">&nbsp;/&nbsp;10</span>
                          </span>
                        </div>

                        {item.recommendation && (
                          <p className="mt-2.5 text-[12.5px] text-ink-2">
                            <span className="text-ink-3">Рекомендация ИИ: </span>
                            {item.recommendation}
                          </p>
                        )}

                        <div className="mt-3.5 rounded-lg bg-secondary/60 px-3.5 py-2.5">
                          <p className="text-[10.5px] font-semibold uppercase tracking-[0.05em] text-ink-3">
                            Рекрутер одобрил{item.hr_reviewer ? ` · ${item.hr_reviewer}` : ''}
                          </p>
                          <p className="mt-1 text-[12.5px] leading-snug text-ink-2">
                            {item.hr_comment || 'Без комментария'}
                          </p>
                        </div>

                        {item.decided ? (
                          <p
                            className={cn(
                              'pill mt-3.5',
                              item.manager_decision === 'approve' ? 'bg-ok-tint text-ok-ink' : 'bg-bad-tint text-bad-ink',
                            )}
                          >
                            {item.manager_decision === 'approve' ? 'Финально одобрен' : 'Отклонён'}
                          </p>
                        ) : (
                          <p className="mt-3.5 inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-brand">
                            Открыть заключение и решить
                            <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" strokeWidth={2.2} />
                          </p>
                        )}
                      </button>
                    ))}
                  </div>
                </section>
              ) : null,
            )}
          </>
        )}
      </PageBody>
    </>
  )
}
