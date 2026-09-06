import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileText,
  LayoutGrid,
  ListChecks,
  Send,
  Star,
  TriangleAlert,
  UserPlus,
} from 'lucide-react'
import { PageHeader, StatTile } from '@/components/layout/AppShell'
import { CandidateCard } from '@/components/workspace/CandidateCard'
import { STAGE_META } from '@/components/workspace/StageStrip'
import { VacancyOverview } from '@/components/workspace/VacancyOverview'
import { AddCandidateDialog } from '@/components/workspace/AddCandidateDialog'
import { api } from '@/lib/api'
import type { BoardResponse, CandidateCardData, Stage } from '@/lib/types'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'



function percent(value: number | null) {
  return value === null ? '—' : `${Math.round(value * 100)}%`
}

export function VacancyBoardPage() {
  const { id } = useParams()
  const [board, setBoard] = useState<BoardResponse | null>(null)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [dropTarget, setDropTarget] = useState<Stage | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [tab, setTab] = useState<'board' | 'overview'>('board')
  const dragged = useRef<CandidateCardData | null>(null)

  const load = useCallback(async () => {
    try {
      setBoard(await api.get<BoardResponse>(`/api/workspace/vacancies/${id}/board`))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  async function invite(candidate: CandidateCardData) {
    setBusyId(candidate.id)
    try {
      await api.post(`/api/workspace/candidates/${candidate.id}/invite`)
      await navigator.clipboard.writeText(new URL(candidate.interview_url, location.origin).href)
      toast.success('Ссылка скопирована', { description: `${candidate.name} переведён в «Приглашены»` })
      await load()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusyId(null)
    }
  }

  async function copyLink(candidate: CandidateCardData) {
    await navigator.clipboard.writeText(new URL(candidate.interview_url, location.origin).href)
    toast.success('Ссылка скопирована')
  }

  async function moveTo(stage: Stage) {
    const candidate = dragged.current
    dragged.current = null
    setDropTarget(null)
    if (!candidate || candidate.stage === stage) return
    setBusyId(candidate.id)
    try {
      await api.patch(`/api/workspace/candidates/${candidate.id}/stage`, { stage })
      toast.success(`${candidate.name} → ${STAGE_META[stage].full}`)
      await load()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusyId(null)
    }
  }

  if (error) {
    return (
      <div className="mx-auto max-w-[1240px] px-6 py-8">
        <p className="rounded-lg border border-bad/25 bg-bad-tint px-4 py-3 text-[13px] text-bad-ink">{error}</p>
      </div>
    )
  }

  if (!board) {
    return (
      <div className="mx-auto max-w-[1240px] px-6 py-8">
        <Skeleton className="mb-6 h-10 w-72" />
        <div className="grid grid-cols-5 gap-3">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-72 rounded-xl" />
          ))}
        </div>
      </div>
    )
  }

  const { vacancy, columns, stats } = board
  const TABS = [
    ['board', 'Доска кандидатов', LayoutGrid, stats.total],
    ['overview', 'Описание вакансии', FileText, vacancy.must_have.length || vacancy.detected_tags.length],
  ] as const

  return (
    <>
      <PageHeader
        eyebrow={
          <Link
            to="/vacancies"
            className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-ink-3 transition-colors hover:text-brand"
          >
            <ArrowLeft className="size-3.5" strokeWidth={2.2} />
            Все вакансии
          </Link>
        }
        title={vacancy.title}
        description={
          <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[11.5px] font-semibold uppercase text-ink-2">
              {vacancy.grade}
            </span>
            <span className="text-ink-3">·</span>
            <span className="tnum">{vacancy.approved_questions_count} вопросов в интервью</span>
            <span className="text-ink-3">·</span>
            <span className="tnum">{stats.total} кандидатов</span>
          </span>
        }
        actions={
          <>
          <Link
            to={`/vacancies/${vacancy.id}/questions`}
            className="inline-flex items-center gap-2 rounded-xl border border-line bg-card px-3.5 py-2.5 text-[13px] font-medium text-ink-2 transition-colors hover:border-brand hover:text-brand"
          >
            <ListChecks className="size-4" strokeWidth={1.9} />
            Вопросы
          </Link>
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            disabled={vacancy.approved_questions_count === 0}
            className="inline-flex items-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-[13px] font-semibold text-white shadow-[0_4px_12px_rgba(0,87,255,0.22)] transition-colors hover:bg-brand-press disabled:opacity-40 disabled:shadow-none"
          >
            <UserPlus className="size-4" strokeWidth={2} />
            Добавить кандидата
          </button>
          </>
        }
      />

      <div className="mx-auto max-w-[1240px] px-6 py-7 sm:px-9">
        <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <StatTile
            label="Приглашено"
            value={stats.invited}
            hint={`из ${stats.total} заведённых`}
            icon={Send}
            tone="violet"
          />
          <StatTile
            label="Дошли до конца"
            value={percent(stats.completion_rate)}
            hint={`${stats.completed} интервью завершено`}
            icon={CheckCircle2}
            tone="brand"
          />
          <StatTile
            label="Ждут вердикта"
            value={stats.awaiting_decision}
            hint={stats.awaiting_decision > 0 ? 'оценка готова, решения нет' : 'очереди нет'}
            icon={Clock3}
            tone={stats.awaiting_decision > 0 ? 'warn' : 'ink'}
          />
          <StatTile
            label="Прошли дальше"
            value={percent(stats.pass_rate)}
            hint={`${stats.advanced} из ${stats.decided} решений`}
            icon={CheckCircle2}
            tone="ok"
          />
          <StatTile
            label="Средний балл"
            value={stats.avg_score ?? '—'}
            hint={
              stats.median_days_to_complete !== null
                ? `медиана ${stats.median_days_to_complete} дн. до интервью`
                : 'пока нет оценок'
            }
            icon={Star}
          />
        </div>

        {vacancy.approved_questions_count === 0 && (
          <Link
            to={`/vacancies/${vacancy.id}/questions`}
            className="mb-5 flex items-center gap-4 rounded-xl border-2 border-dashed border-brand/40 bg-brand-tint px-5 py-4 transition-colors hover:border-brand hover:bg-brand-tint"
          >
            <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-brand text-white">
              <ListChecks className="size-5" strokeWidth={2} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[14px] font-bold text-ink-700">Пул вопросов не утверждён</span>
              <span className="mt-0.5 block text-[12.5px] text-ink-2">
                Система подобрала {vacancy.questions_count} вопросов под требования вакансии. Отметьте нужные —
                до этого ссылку кандидату выдать нельзя.
              </span>
            </span>
            <ArrowRight className="size-5 shrink-0 text-brand" strokeWidth={2.2} />
          </Link>
        )}

        {vacancy.approved_questions_count > 6 && (
          <div className="mb-5 flex items-start gap-3 rounded-xl border border-warn/25 bg-warn-tint px-4 py-3">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn-ink" strokeWidth={2.1} />
            <p className="text-[12.5px] leading-relaxed text-warn-ink">
              <b className="font-semibold">
                В интервью {vacancy.approved_questions_count} вопросов — это много.
              </b>{' '}
              По данным платформ асинхронного интервью каждый лишний вопрос стоит около 15% completion rate;
              сокращение с 8 вопросов до 4 поднимало долю дошедших до конца с 58% до 84%. Оптимум — 4–6.
            </p>
          </div>
        )}

        {/* Переключатель разделов, а не фильтр: крупный, с подчёркиванием
            активного и счётчиками, чтобы не терялся среди плиток. */}
        <div className="mb-6 flex gap-7 border-b border-line">
          {TABS.map(([key, label, Icon, count]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={cn(
                'relative -mb-px flex items-center gap-2 border-b-[3px] px-1 pb-3.5 pt-1 text-[15px] transition-colors duration-200',
                tab === key
                  ? 'border-brand font-bold text-ink'
                  : 'border-transparent font-medium text-ink-3 hover:text-ink-2',
              )}
            >
              <Icon className={cn('size-[18px]', tab === key ? 'text-brand' : 'text-ink-3')} strokeWidth={2} />
              {label}
              <span
                className={cn(
                  'tnum rounded-full px-2 py-0.5 text-[11.5px] font-semibold',
                  tab === key ? 'bg-brand text-white' : 'bg-secondary text-ink-3',
                )}
              >
                {count}
              </span>
            </button>
          ))}
        </div>

        {tab === 'overview' ? (
          <VacancyOverview vacancy={vacancy} />
        ) : (
          <div className="grid gap-2 overflow-x-auto pb-4 [grid-template-columns:repeat(5,minmax(212px,1fr))]">
            {columns.map((column) => {
              const meta = STAGE_META[column.key]
              const isTarget = dropTarget === column.key
              return (
                <section
                  key={column.key}
                  onDragOver={(event) => {
                    event.preventDefault()
                    setDropTarget(column.key)
                  }}
                  onDragLeave={() => setDropTarget((current) => (current === column.key ? null : current))}
                  onDrop={() => void moveTo(column.key)}
                  className={cn(
                    'flex min-h-80 flex-col rounded-xl border border-dashed border-transparent p-1.5 transition-colors duration-200',
                    isTarget && 'border-brand/50 bg-brand-tint/60',
                  )}
                >
                  <header className="mb-3 px-1 pt-2 text-center">
                    <div className="flex items-center justify-center gap-1.5">
                      <span className={cn('size-1.5 shrink-0 rounded-full', meta.dot)} />
                      <h2 className="text-[11.5px] font-bold uppercase tracking-[0.07em] text-ink">
                        {column.title}
                      </h2>
                    </div>
                    <p className="tnum mt-1 text-[11.5px] text-ink-3">{column.candidates.length}</p>
                  </header>

                  <div className="flex flex-1 flex-col gap-2">
                    {column.candidates.map((candidate) => (
                      <CandidateCard
                        key={candidate.id}
                        candidate={candidate}
                        busy={busyId === candidate.id}
                        onInvite={(item) => void invite(item)}
                        onCopyLink={(item) => void copyLink(item)}
                        onDragStart={(item) => {
                          dragged.current = item
                        }}
                      />
                    ))}
                    {column.candidates.length === 0 && (
                      <p className="px-2 py-6 text-center text-[11.5px] leading-snug text-ink-3/80">
                        {column.hint}
                      </p>
                    )}
                  </div>
                </section>
              )
            })}
          </div>
        )}
      </div>

      <AddCandidateDialog
        vacancyId={vacancy.id}
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={() => void load()}
      />
    </>
  )
}
