import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  Copy,
  Check,
  CircleHelp,
  FileText,
  Loader2,
  Minus,
  Play,
  Share2,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  UserPlus,
} from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/AppShell'
import { api } from '@/lib/api'
import type { CoverageItem, ProctoringSummary, ReportAnswer, ReportResponse } from '@/lib/types'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

type Verdict = 'confirmed' | 'partial' | 'risk' | 'unknown'

const VERDICT: Record<Verdict, { label: string; icon: typeof Check; chip: string; hint: string }> = {
  confirmed: {
    label: 'Подтверждено',
    icon: Check,
    chip: 'bg-ok-tint text-ok-ink',
    hint: 'кандидат раскрыл требование, есть подтверждение в ответе',
  },
  partial: {
    label: 'Частично',
    icon: Minus,
    chip: 'bg-warn-tint text-warn-ink',
    hint: 'тема прозвучала, но без глубины или личного вклада',
  },
  risk: {
    label: 'Есть риск',
    icon: AlertTriangle,
    chip: 'bg-bad-tint text-bad-ink',
    hint: 'ответ противоречит требованию или содержит ошибку',
  },
  unknown: {
    label: 'Не проверялось',
    icon: CircleHelp,
    chip: 'bg-secondary text-ink-3',
    hint: 'вопросов по теме не было — это не значит, что навыка нет',
  },
}

/** «Не проверялось» — отдельный класс, а не отказ: отсутствие упоминания
 *  навыка не равно его отсутствию. Это снижает false positive. */
function verdictOf(item: CoverageItem): Verdict {
  const status = (item.status || '').toLowerCase()
  if (status.includes('частич')) return 'partial'
  if (status.includes('риск') || status.includes('не подтвержд') || status === 'missing') return 'risk'
  if (status.includes('подтвержд') || status === 'confirmed') return 'confirmed'
  return 'unknown'
}

const titleOf = (item: CoverageItem) => item.topic || item.requirement || item.skill || 'Без названия'
const quotesOf = (item: CoverageItem) => item.evidence_quotes ?? (item.evidence ? [item.evidence] : [])

function timecode(ms: number) {
  const total = Math.max(0, Math.round(ms / 1000))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function scoreTone(score: number) {
  if (score >= 7.5) return 'text-ok'
  if (score >= 5) return 'text-warn-ink'
  return 'text-bad'
}

const DECISION_LABEL: Record<string, string> = {
  approve: 'Пропущен дальше',
  reject: 'Не проходит',
  needs_review: 'Нужна доп. проверка',
}

// ---------------------------------------------------------------- решение

/** Передача кандидата нанимающему менеджеру.
 *
 *  Менеджер видит заключение только после одобрения рекрутера — так устроен
 *  доступ на бэкенде. Поэтому ссылку показываем ровно в этот момент, а рядом
 *  даём одноразовый инвайт: без аккаунта ссылка ему ничего не откроет. */
function HandoffBox({ sessionId }: { sessionId: number }) {
  const [invite, setInvite] = useState('')
  const [busy, setBusy] = useState(false)
  const reportUrl = new URL(`/app/reports/${sessionId}`, location.origin).href

  async function copy(value: string, message: string) {
    await navigator.clipboard.writeText(value)
    toast.success(message)
  }

  async function createInvite() {
    setBusy(true)
    try {
      const created = await api.post<{ invite_url: string; expires_in_hours: number }>(
        '/api/auth/invitations',
        { role: 'hiring_manager' },
      )
      setInvite(created.invite_url)
      await copy(created.invite_url, `Приглашение скопировано, действует ${created.expires_in_hours} ч`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 rounded-lg border border-line bg-card p-4">
      <h3 className="flex items-center gap-2 text-[13px] font-bold text-ink-700">
        <Share2 className="size-3.5 text-brand" strokeWidth={2.2} />
        Передать нанимающему менеджеру
      </h3>
      <p className="mt-1 text-[12px] leading-snug text-ink-3">
        Заключение открылось менеджеру автоматически — доступ появляется только после вашего одобрения.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-md bg-secondary px-3 py-2 font-mono text-[12px] text-ink-2">
          {reportUrl}
        </code>
        <button
          type="button"
          onClick={() => void copy(reportUrl, 'Ссылка на заключение скопирована')}
          className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-[12.5px] font-medium text-ink-2 transition-colors hover:border-brand hover:text-brand"
        >
          <Copy className="size-3.5" strokeWidth={1.9} />
          Копировать
        </button>
      </div>

      <div className="mt-3 border-t border-line pt-3">
        {invite ? (
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-md bg-brand-tint px-3 py-2 font-mono text-[12px] text-brand">
              {invite}
            </code>
            <button
              type="button"
              onClick={() => void copy(invite, 'Приглашение скопировано')}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-[12.5px] font-medium text-ink-2 transition-colors hover:border-brand hover:text-brand"
            >
              <Copy className="size-3.5" strokeWidth={1.9} />
              Копировать
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[12px] leading-snug text-ink-3">
              Если у менеджера ещё нет аккаунта — выдайте одноразовое приглашение на 48 часов.
            </p>
            <button
              type="button"
              onClick={() => void createInvite()}
              disabled={busy}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-[12.5px] font-medium text-brand transition-colors hover:bg-brand-tint disabled:opacity-40"
            >
              {busy ? <Loader2 className="size-3.5 animate-spin" strokeWidth={2.2} /> : <UserPlus className="size-3.5" strokeWidth={2} />}
              Пригласить менеджера
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

/** Вердикт ИИ и решение рекрутера в одном блоке: читаешь основания и тут же
 *  выбираешь. Итог модели — рекомендация, кадровое решение остаётся за человеком. */
function VerdictCard({
  report,
  counts,
  weakest,
  redFlags,
  onDone,
}: {
  report: ReportResponse
  counts: Record<Verdict, number>
  weakest: ReportAnswer | null
  redFlags: string[]
  onDone: () => void
}) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const canDecide = report.viewer_role === 'hr' && !report.hr_review
  // Менеджер решает последним и только после одобрения рекрутера.
  const canDecideFinal =
    report.viewer_role === 'hiring_manager' &&
    report.hr_review?.decision === 'approve' &&
    !report.manager_review

  async function decide(decision: 'approve' | 'reject') {
    setBusy(decision)
    const role = report.viewer_role === 'hiring_manager' ? 'manager' : 'hr'
    try {
      await api.post(`/api/reviews/${report.session_id}/${role}`, { decision, comment: comment.trim() })
      toast.success(DECISION_LABEL[decision])
      onDone()
    } catch (e) {
      toast.error((e as Error).message)
      setBusy(null)
    }
  }

  const facts: Array<{ text: string; tone: string }> = []
  if (counts.confirmed) facts.push({ text: `${counts.confirmed} подтверждено`, tone: 'text-ok-ink' })
  if (counts.risk) facts.push({ text: `${counts.risk} с риском`, tone: 'text-bad-ink' })
  if (counts.partial) facts.push({ text: `${counts.partial} частично`, tone: 'text-warn-ink' })
  if (counts.unknown) facts.push({ text: `${counts.unknown} не проверялось`, tone: 'text-ink-3' })

  return (
    <section className="mb-5 overflow-hidden rounded-xl bg-card shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
      <div className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0 flex-1">
            <p className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-ink-3">Рекомендация ИИ</p>
            <p className="mt-1.5 text-[22px] leading-tight font-bold tracking-[-0.02em] text-ink">
              {report.recommendation || 'Не сформулирована'}
            </p>
            {report.summary && (
              <p className="mt-3 max-w-2xl text-[13.5px] leading-relaxed text-ink-2">{report.summary}</p>
            )}
          </div>
          <div className="shrink-0 text-right">
            <p className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-ink-3">Балл</p>
            <p className="mt-1 whitespace-nowrap">
              <span
                className={cn(
                  'tnum text-[34px] leading-none font-bold tracking-[-0.03em]',
                  report.overall_score !== null ? scoreTone(report.overall_score) : 'text-ink-3',
                )}
              >
                {report.overall_score !== null ? report.overall_score.toFixed(1) : '—'}
              </span>
              <span className="tnum text-[18px] font-semibold text-ink-3">&nbsp;/&nbsp;10</span>
            </p>
            {report.score_confidence !== null && (
              <p className="tnum mt-1.5 text-[11.5px] text-ink-3">
                уверенность {Math.round(report.score_confidence * 100)}%
              </p>
            )}
          </div>
        </div>

        {(facts.length > 0 || weakest || redFlags.length > 0) && (
          <div className="mt-4 rounded-lg bg-secondary/60 px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
              {facts.map((fact) => (
                <span key={fact.text} className={cn('tnum text-[12.5px] font-medium', fact.tone)}>
                  {fact.text}
                </span>
              ))}
            </div>
            {weakest && (
              <p className="mt-2.5 text-[12.5px] leading-snug text-ink-2">
                Самый слабый ответ —{' '}
                <b className={cn('tnum font-semibold', scoreTone(weakest.score ?? 0))}>
                  {(weakest.score ?? 0).toFixed(1)}
                </b>{' '}
                за «{weakest.question.slice(0, 70)}…»
              </p>
            )}
            {redFlags.length > 0 && (
              <ul className="mt-2 space-y-1">
                {redFlags.slice(0, 3).map((flag, index) => (
                  <li key={index} className="flex items-start gap-1.5 text-[12.5px] leading-snug text-bad-ink">
                    <AlertTriangle className="mt-0.5 size-3 shrink-0" strokeWidth={2.3} />
                    {flag}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {(canDecide || canDecideFinal) && (
        <div className="border-t border-line bg-secondary/30 px-6 py-5">
          <p className="text-[13px] font-semibold text-ink-700">
            {canDecideFinal ? 'Финальное решение по кандидату' : 'Ваше решение — двигать кандидата дальше?'}
          </p>
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            rows={2}
            placeholder={
              canDecideFinal ? 'Комментарий к решению — необязательно' : 'Комментарий для нанимающего менеджера — необязательно'
            }
            className="mt-2.5 w-full resize-y rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[13px] leading-relaxed outline-none placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
          />
          {/* Отказ слева, одобрение справа — привычное направление движения. */}
          <div className="mt-3 grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => void decide('reject')}
              disabled={busy !== null}
              className="inline-flex items-center justify-center gap-2 rounded-lg border-2 border-bad bg-bad-tint px-5 py-3 text-[13.5px] font-bold text-bad-ink transition-all hover:bg-bad hover:text-white disabled:opacity-40"
            >
              {busy === 'reject' ? (
                <Loader2 className="size-4 animate-spin" strokeWidth={2.2} />
              ) : (
                <ThumbsDown className="size-4" strokeWidth={2.2} />
              )}
              {canDecideFinal ? 'Отклонить' : 'Не проходит'}
            </button>
            <button
              type="button"
              onClick={() => void decide('approve')}
              disabled={busy !== null}
              className="inline-flex items-center justify-center gap-2 rounded-lg border-2 border-ok bg-ok-tint px-5 py-3 text-[13.5px] font-bold text-ok-ink transition-all hover:bg-ok hover:text-white disabled:opacity-40"
            >
              {busy === 'approve' ? (
                <Loader2 className="size-4 animate-spin" strokeWidth={2.2} />
              ) : (
                <ThumbsUp className="size-4" strokeWidth={2.2} />
              )}
              {canDecideFinal ? 'Финально одобрить' : 'Пропустить дальше'}
            </button>
          </div>
        </div>
      )}

      {report.hr_review && (
        <div className="border-t border-line bg-secondary/30 px-6 py-4">
          <div className="flex flex-wrap items-center gap-3">
            <span
              className={cn(
                'pill',
                report.hr_review.decision === 'approve' ? 'bg-ok-tint text-ok-ink' : 'bg-bad-tint text-bad-ink',
              )}
            >
              {DECISION_LABEL[report.hr_review.decision] ?? report.hr_review.decision}
            </span>
            <span className="text-[13px] text-ink-2">Решение рекрутера принято</span>
            {report.hr_review.comment && (
              <span className="text-[12.5px] text-ink-3">«{report.hr_review.comment}»</span>
            )}
          </div>
          {report.manager_review && (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <span
                className={cn(
                  'pill',
                  report.manager_review.decision === 'approve' ? 'bg-ok-tint text-ok-ink' : 'bg-bad-tint text-bad-ink',
                )}
              >
                {report.manager_review.decision === 'approve' ? 'Финально одобрен' : 'Отклонён менеджером'}
              </span>
              <span className="text-[13px] text-ink-2">Решение нанимающего менеджера</span>
              {report.manager_review.comment && (
                <span className="text-[12.5px] text-ink-3">«{report.manager_review.comment}»</span>
              )}
            </div>
          )}
          {report.viewer_role === 'hr' && report.hr_review.decision === 'approve' && !report.manager_review && (
            <HandoffBox sessionId={report.session_id} />
          )}
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------- ответ

/** Словесная метка балла: цифру всё равно приходится переводить в «сильный
 *  или слабый», так пусть это делает интерфейс, а не читатель. */
function scoreLabel(score: number) {
  if (score >= 8) return { text: 'сильный ответ', chip: 'bg-ok-tint text-ok-ink' }
  if (score >= 6) return { text: 'средний ответ', chip: 'bg-warn-tint text-warn-ink' }
  if (score >= 4) return { text: 'слабый ответ', chip: 'bg-bad-tint text-bad-ink' }
  return { text: 'ответ не засчитан', chip: 'bg-bad-tint text-bad-ink' }
}

/** Список выводов без заливки: цвет живёт только в маркере и подписи.
 *  Залитых блоков подряд быть не должно — они спорят друг с другом. */
function FindingList({
  title,
  items,
  tone,
  marker,
}: {
  title: string
  items: string[]
  tone: string
  marker: string
}) {
  if (items.length === 0) return null
  return (
    <div>
      <h4 className={cn('mb-2 text-[11px] font-bold uppercase tracking-[0.05em]', tone)}>
        {title} <span className="tnum font-semibold opacity-60">{items.length}</span>
      </h4>
      <ul className="space-y-1.5">
        {items.map((item, index) => (
          <li key={index} className="flex items-start gap-2">
            <span className={cn('mt-[7px] size-1.5 shrink-0 rounded-full', marker)} />
            <span className="text-[12.5px] leading-snug text-ink-2">{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function AnswerBlock({ answer, followUps, index }: { answer: ReportAnswer; followUps: ReportAnswer[]; index: number }) {
  const [showTranscript, setShowTranscript] = useState(false)
  const [showVideo, setShowVideo] = useState(false)
  const analysis = answer.analysis
  const hasVideo = Boolean(answer.video_path && answer.video_media?.playable)
  const duration = Math.round(((answer.video_media?.duration_ms ?? 0) || answer.end_ms - answer.start_ms) / 1000)
  const label = answer.score !== null ? scoreLabel(answer.score) : null

  return (
    <article id={`answer-${answer.id}`} className="scroll-mt-6 overflow-hidden rounded-xl bg-card shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
      {/* Полоса слева кодирует силу ответа — видно ещё до чтения текста. */}
      <div className="flex">
        <span
          className={cn(
            'w-1.5 shrink-0',
            answer.score === null ? 'bg-line' : answer.score >= 8 ? 'bg-ok' : answer.score >= 6 ? 'bg-warn' : 'bg-bad',
          )}
        />
        <div className="min-w-0 flex-1">
          <header className="flex items-start gap-4 border-b border-line px-5 py-4">
            <span className="tnum mt-0.5 grid size-6 shrink-0 place-items-center rounded-md bg-secondary text-[12px] font-bold text-ink-3">
              {index}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[14.5px] font-semibold leading-snug text-ink">{answer.question}</p>
              <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-ink-3">
                <span className="tnum">{timecode(answer.start_ms)}</span>
                {duration > 0 && <span className="tnum">· {duration} сек</span>}
                {followUps.length > 0 && <span>· {followUps.length} уточнения</span>}
                {analysis?.confidence_0_1 !== undefined && (
                  <span className="tnum">· уверенность оценки {Math.round((analysis.confidence_0_1 ?? 0) * 100)}%</span>
                )}
              </p>
            </div>
            {answer.score !== null && label && (
              <span className="shrink-0 text-right">
                <span className="block whitespace-nowrap">
                  <span className={cn('tnum text-[26px] leading-none font-bold tracking-[-0.03em]', scoreTone(answer.score))}>
                    {answer.score.toFixed(1)}
                  </span>
                  <span className="tnum text-[15px] font-semibold text-ink-3">&nbsp;/&nbsp;10</span>
                </span>
                <span className={cn('pill mt-1.5', label.chip)}>{label.text}</span>
              </span>
            )}
          </header>

          <div className="space-y-3.5 px-5 py-4">
            {analysis?.summary && (
              <p className="text-[13px] leading-relaxed text-ink-2">{analysis.summary}</p>
            )}

            <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
              <div className="space-y-4">
                <FindingList
                  title="Прозвучало"
                  items={analysis?.covered_must_have ?? []}
                  tone="text-ok-ink"
                  marker="bg-ok"
                />
                <FindingList
                  title="Сверх ожидаемого"
                  items={analysis?.covered_nice_to_have ?? []}
                  tone="text-ok-ink"
                  marker="bg-ok/50"
                />
              </div>

              {/* Минусы одним разделом: фактическая ошибка и «не прозвучало» —
                  разные вещи, но обе против кандидата, и искать их в двух местах
                  неудобно. Внутри они всё равно различимы маркером. */}
              {((analysis?.detected_red_flags ?? []).length > 0 ||
                (analysis?.missing_must_have ?? []).length > 0) && (
                <div>
                  <h4 className="mb-2 text-[11px] font-bold uppercase tracking-[0.05em] text-bad-ink">
                    Минусы ответа{' '}
                    <span className="tnum font-semibold opacity-60">
                      {(analysis?.detected_red_flags ?? []).length + (analysis?.missing_must_have ?? []).length}
                    </span>
                  </h4>
                  <ul className="space-y-1.5">
                    {(analysis?.detected_red_flags ?? []).map((flag, index) => (
                      <li key={`flag-${index}`} className="flex items-start gap-2">
                        <AlertTriangle className="mt-[2px] size-3.5 shrink-0 text-bad" strokeWidth={2.4} />
                        <span className="text-[12.5px] leading-snug font-medium text-ink">{flag}</span>
                      </li>
                    ))}
                    {(analysis?.missing_must_have ?? []).map((item, index) => (
                      <li key={`missing-${index}`} className="flex items-start gap-2">
                        <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-line-2" />
                        <span className="text-[12.5px] leading-snug text-ink-2">не прозвучало: {item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {(analysis?.evidence_quotes ?? []).length > 0 && (
              <section>
                <h4 className="mb-2 text-[11px] font-bold uppercase tracking-[0.05em] text-ink-3">
                  Дословно из ответа
                </h4>
                <ul className="space-y-1.5">
                  {(analysis?.evidence_quotes ?? []).map((quote, qi) => (
                    <li key={qi} className="border-l-2 border-line-2 pl-3 text-[12.5px] leading-snug text-ink-2">
                      «{quote}»
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <div className="flex flex-wrap items-center gap-2 pt-0.5">
              {hasVideo && (
                <button
                  type="button"
                  onClick={() => setShowVideo((value) => !value)}
                  className={cn(
                    'inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-[12.5px] font-medium transition-colors',
                    showVideo
                      ? 'border-brand bg-brand-tint text-brand'
                      : 'border-line text-ink-2 hover:border-brand hover:text-brand',
                  )}
                >
                  <Play className="size-3.5" strokeWidth={2.4} />
                  {showVideo ? 'Свернуть видео' : `Смотреть видеоответ${duration > 0 ? ` · ${duration} сек` : ''}`}
                </button>
              )}
              <button
                type="button"
                onClick={() => setShowTranscript((value) => !value)}
                className="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-[12.5px] font-medium text-ink-2 transition-colors hover:border-brand hover:text-brand"
              >
                <FileText className="size-3.5" strokeWidth={1.9} />
                {showTranscript ? 'Скрыть транскрипт' : 'Транскрипт'}
              </button>
            </div>

            {showVideo && hasVideo && (
              <video
                src={answer.video_path ?? undefined}
                controls
                autoPlay
                className="w-full max-w-lg rounded-lg border border-line bg-ink"
              />
            )}

            {showTranscript && (
              <p className="whitespace-pre-wrap rounded-lg bg-secondary/60 px-4 py-3 text-[12.5px] leading-relaxed text-ink-2">
                {answer.transcript || 'Транскрипт пуст'}
              </p>
            )}

            {followUps.length > 0 && (
              <div className="space-y-3 border-l-2 border-brand/30 pl-4">
                {followUps.map((item) => (
                  <div key={item.id}>
                    <p className="text-[11px] font-bold uppercase tracking-[0.04em] text-brand">
                      Уточнение {item.follow_up_index ?? ''}
                      {item.probe_reason && (
                        <span className="ml-2 font-normal normal-case tracking-normal text-ink-3">{item.probe_reason}</span>
                      )}
                    </p>
                    <p className="mt-1 text-[13px] font-medium text-ink">{item.question}</p>
                    {item.transcript && <p className="mt-1 text-[12.5px] leading-snug text-ink-2">{item.transcript}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </article>
  )
}

// ---------------------------------------------------------------- страница

function seconds(ms: number) {
  if (!ms || ms < 1000) return null
  const total = Math.round(ms / 1000)
  return total < 60 ? `${total} с` : `${Math.floor(total / 60)} мин ${total % 60} с`
}

/** Прокторинг собирался всё интервью, но до отчёта не доходил: сигналы копились
 *  в базе и никто их не видел. Показываем их рекрутеру как evidence — отдельно
 *  от оценки и без вердикта, решение о добросовестности остаётся за человеком. */
function ProctoringSection({ sessionId }: { sessionId: number }) {
  const [data, setData] = useState<ProctoringSummary | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    api
      .get<ProctoringSummary>(`/api/proctoring/${sessionId}/summary`)
      .then(setData)
      .catch(() => setFailed(true))
  }, [sessionId])

  if (failed || !data) return null

  const browser = [
    { label: 'Уходы со вкладки', value: data.tab_switches, extra: seconds(data.tab_hidden_duration_ms) },
    { label: 'Потери фокуса', value: data.window_blurs, extra: seconds(data.window_blur_duration_ms) },
    { label: 'Вставки из буфера', value: data.clipboard_pastes, extra: null },
    { label: 'Копирования', value: data.clipboard_copies, extra: null },
    { label: 'Выходы из fullscreen', value: data.fullscreen_exits, extra: null },
    { label: 'Обрывы сети', value: data.network_interruptions, extra: null },
    { label: 'Обрывы камеры и микрофона', value: data.media_interruptions, extra: null },
  ]
  const vision = [
    { label: 'Лицо не найдено', value: data.face_missing_episodes, extra: seconds(data.face_missing_duration_ms) },
    { label: 'Несколько лиц', value: data.multiple_faces_episodes, extra: seconds(data.multiple_faces_duration_ms) },
    { label: 'Отвод головы', value: data.head_away_episodes, extra: seconds(data.head_away_duration_ms) },
    { label: 'Отвод взгляда', value: data.gaze_away_episodes, extra: seconds(data.gaze_away_duration_ms) },
  ]

  const tile = (item: { label: string; value: number; extra: string | null }) => (
    <div
      key={item.label}
      className={cn(
        'rounded-lg border px-3 py-2.5',
        item.value > 0 ? 'border-warn/30 bg-warn-tint' : 'border-line bg-secondary',
      )}
    >
      <p className={cn('tnum text-[18px] font-bold leading-none', item.value > 0 ? 'text-warn-ink' : 'text-ink-3')}>
        {item.value}
      </p>
      <p className="mt-1.5 text-[11.5px] leading-snug text-ink-3">{item.label}</p>
      {item.extra && <p className="mt-0.5 text-[11px] text-ink-3">суммарно {item.extra}</p>}
    </div>
  )

  return (
    <section className="mt-6 overflow-hidden rounded-xl bg-card shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
        <h2 className="flex items-center gap-2 text-[15px] font-bold text-ink-700">
          <ShieldCheck className="size-4 text-ink-3" strokeWidth={2.2} />
          Прокторинг
        </h2>
        <span className="tnum text-[12px] text-ink-3">
          {data.total_events === 0 ? 'сигналов не зафиксировано' : `${data.total_events} событий`}
        </span>
      </header>

      <div className="p-5">
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-ink-3">Браузер</p>
        <div className="mt-2.5 grid gap-2 sm:grid-cols-3 lg:grid-cols-4">{browser.map(tile)}</div>

        <p className="mt-5 text-[10.5px] font-semibold uppercase tracking-[0.06em] text-ink-3">Видеопоток</p>
        {data.vision_available ? (
          <div className="mt-2.5 grid gap-2 sm:grid-cols-3 lg:grid-cols-4">{vision.map(tile)}</div>
        ) : (
          <p className="mt-2 rounded-lg border border-dashed border-line-2 px-4 py-3 text-[12.5px] text-ink-3">
            Анализ видеопотока не выполнялся: MediaPipe не запустился у кандидата. Это не признак нарушения.
          </p>
        )}

        <p className="mt-5 text-[12px] leading-snug text-ink-3">{data.disclaimer}</p>
      </div>
    </section>
  )
}

export function ReportPage() {
  const { id } = useParams()
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setReport(await api.get<ReportResponse>(`/api/reports/${id}`))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const derived = useMemo(() => {
    // Сначала риски и частичные — рекрутеру важно увидеть проблемы, а не листать
    // до них через подтверждённое.
    const order: Record<Verdict, number> = { risk: 0, partial: 1, unknown: 2, confirmed: 3 }
    const mustHave = [...(report?.vacancy_coverage?.must_have ?? [])].sort(
      (a, b) => order[verdictOf(a)] - order[verdictOf(b)],
    )
    const counts: Record<Verdict, number> = { confirmed: 0, partial: 0, risk: 0, unknown: 0 }
    mustHave.forEach((item) => (counts[verdictOf(item)] += 1))
    const scored = (report?.answers ?? []).filter((a) => !a.is_follow_up && a.score !== null)
    const weakest = scored.length
      ? scored.reduce((min, item) => ((item.score ?? 10) < (min.score ?? 10) ? item : min))
      : null
    const redFlags = (report?.answers ?? []).flatMap((a) => a.analysis?.detected_red_flags ?? [])
    return { mustHave, counts, weakest, redFlags }
  }, [report])

  if (error) {
    return (
      <PageBody>
        <p className="rounded-lg border border-bad/25 bg-bad-tint px-4 py-3 text-[13px] text-bad-ink">{error}</p>
      </PageBody>
    )
  }
  if (!report) {
    return (
      <PageBody>
        <Skeleton className="mb-6 h-28 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </PageBody>
    )
  }

  const roots = report.answers.filter((a) => !a.is_follow_up)
  const followUpsOf = (root: ReportAnswer) =>
    report.answers.filter((a) => a.is_follow_up && a.root_question_id === root.root_question_id)
  const { mustHave, counts, weakest, redFlags } = derived

  return (
    <>
      <PageHeader
        eyebrow={
          <Link
            to="/candidates"
            className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-ink-3 transition-colors hover:text-brand"
          >
            <ArrowLeft className="size-3.5" strokeWidth={2.2} />
            Все кандидаты
          </Link>
        }
        title={report.candidate_name}
        description={`${report.vacancy_title} · заключение от ${new Date(report.generated_at).toLocaleDateString('ru-RU')}`}
      />

      <PageBody>
        {mustHave.length > 0 && (
          <section className="mb-5 overflow-hidden rounded-xl bg-card shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
            <header className="border-b border-line px-5 py-4">
              <h2 className="text-[15px] font-bold text-ink-700">Требования вакансии</h2>
            </header>
            <ul className="divide-y divide-line">
              {mustHave.map((item, index) => {
                const verdict = VERDICT[verdictOf(item)]
                const Icon = verdict.icon
                const quotes = quotesOf(item)
                return (
                  <li key={index} className="flex items-start gap-3 px-5 py-3.5">
                    <span className={cn('mt-0.5 grid size-5 shrink-0 place-items-center rounded-full', verdict.chip)}>
                      <Icon className="size-3" strokeWidth={2.6} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] font-semibold text-ink">{titleOf(item)}</span>
                      {quotes.map((quote, qi) => (
                        <span key={qi} className="mt-1 block text-[12px] leading-snug text-ink-3">
                          «{quote}»
                        </span>
                      ))}
                    </span>
                    <span className={cn('pill shrink-0', verdict.chip)}>{verdict.label}</span>
                  </li>
                )
              })}
            </ul>
          </section>
        )}

        <VerdictCard
          report={report}
          counts={counts}
          weakest={weakest}
          redFlags={redFlags}
          onDone={() => void load()}
        />

        <div className="mb-4 flex items-baseline gap-3">
          <h2 className="text-[15px] font-bold text-ink-700">Ответы кандидата</h2>
          <span className="tnum text-[12px] text-ink-3">{roots.length}</span>
          <span className="h-px flex-1 bg-line" />
        </div>

        <div className="space-y-4">
          {roots.map((answer, index) => (
            <AnswerBlock key={answer.id} answer={answer} followUps={followUpsOf(answer)} index={index + 1} />
          ))}
          {roots.length === 0 && (
            <p className="rounded-xl border border-dashed border-line-2 px-6 py-12 text-center text-[13px] text-ink-3">
              Ответов нет — интервью не пройдено
            </p>
          )}
        </div>

        {report.unanswered_questions.length > 0 && (
          <section className="mt-6 overflow-hidden rounded-xl bg-card shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
              <h2 className="text-[15px] font-bold text-ink-700">Не проверено</h2>
              <span className="tnum text-[12px] text-ink-3">{report.unanswered_questions.length}</span>
            </header>
            <p className="px-5 pt-3 text-[12px] leading-snug text-ink-3">
              Кандидат не ответил на эти вопросы — интервью завершено досрочно. Отсутствие
              ответа не означает отсутствие навыка; итоговый балл считается только по
              отвеченным вопросам.
            </p>
            <ul className="divide-y divide-line px-1 py-2">
              {report.unanswered_questions.map((item) => (
                <li key={item.question_id} className="flex items-start gap-3 px-4 py-3">
                  <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-secondary text-ink-3">
                    <CircleHelp className="size-3" strokeWidth={2.6} />
                  </span>
                  <span className="min-w-0 flex-1 text-[13.5px] text-ink">{item.question}</span>
                  <span className="pill shrink-0 bg-secondary text-ink-3">не проверялось</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <ProctoringSection sessionId={report.session_id} />

        {report.full_video_path && report.full_video_media?.playable && (
          <section className="mt-6 rounded-xl bg-card p-5 shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
            <h2 className="mb-3 text-[14px] font-bold text-ink-700">Полная запись интервью</h2>
            <video src={report.full_video_path} controls preload="none" className="w-full rounded-lg border border-line bg-ink" />
          </section>
        )}
      </PageBody>
    </>
  )
}
