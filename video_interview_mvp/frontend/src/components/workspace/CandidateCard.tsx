import { Clock3, Copy, FileText, Mail, Paperclip, Send } from 'lucide-react'
import type { CandidateCardData } from '@/lib/types'
import { cn } from '@/lib/utils'

function scoreTone(score: number) {
  if (score >= 7.5) return 'text-ok'
  if (score >= 5) return 'text-warn-ink'
  return 'text-bad'
}

function shortDate(value: string | null) {
  if (!value) return null
  return new Date(value).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

export function CandidateCard({
  candidate,
  onInvite,
  onCopyLink,
  onDragStart,
  busy,
}: {
  candidate: CandidateCardData
  onInvite: (candidate: CandidateCardData) => void
  onCopyLink: (candidate: CandidateCardData) => void
  onDragStart: (candidate: CandidateCardData) => void
  busy: boolean
}) {
  // Колонка уже говорит, на каком кандидат этапе. Полоса поэтому кодирует
  // другое — чей сейчас ход. Это модель Greenhouse и Ashby: красный значит
  // «ждём действия команды», серый — «ждём кандидата».
  const turn = candidate.waiting_on
  const days = candidate.days_in_stage ?? 0
  const stale = turn === 'candidate' && days > 5
  const turnLabel =
    turn === 'recruiter' ? 'ждёт вас' : turn === 'manager' ? 'ждёт менеджера' : turn === 'candidate' ? 'ждём кандидата' : null

  return (
    <article
      draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = 'move'
        onDragStart(candidate)
      }}
      className={cn(
        'ring-card ring-card-hover group relative cursor-grab rounded-lg bg-card p-3 transition-shadow duration-200 active:cursor-grabbing',
        candidate.stage === 'rejected' && 'opacity-70',
        busy && 'pointer-events-none opacity-50',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-[13.5px] font-semibold leading-snug text-ink">{candidate.name}</h4>
        {candidate.overall_score !== null && (
          <span className={cn('tnum shrink-0 text-[17px] leading-none font-bold tracking-[-0.02em]', scoreTone(candidate.overall_score))}>
            {candidate.overall_score.toFixed(1)}
          </span>
        )}
      </div>

      {candidate.match_score !== null && candidate.overall_score === null && (
        <p className="mt-1.5 text-[11.5px] text-ink-3">
          Резюме к вакансии <span className="tnum font-bold text-ink-2">{candidate.match_score.toFixed(1)}</span>
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-ink-3">
        {candidate.resume_filename && (
          <span className="inline-flex items-center gap-1" title={candidate.resume_filename}>
            <Paperclip className="size-3" strokeWidth={1.9} />
            резюме
          </span>
        )}
        {candidate.telegram_username && (
          <span className="inline-flex items-center gap-1" title={`@${candidate.telegram_username}`}>
            <Send className="size-3" strokeWidth={1.9} />
            tg
          </span>
        )}
        {candidate.email && (
          <span className="inline-flex items-center gap-1" title={candidate.email}>
            <Mail className="size-3" strokeWidth={1.9} />
            почта
          </span>
        )}
        <span className="tnum">{candidate.question_count} вопр.</span>
        {shortDate(candidate.invited_at ?? candidate.created_at) && (
          <span className="tnum">{shortDate(candidate.invited_at ?? candidate.created_at)}</span>
        )}
      </div>

      {(turnLabel || days >= 2) && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {turnLabel && (
            <span
              className={cn(
                'pill',
                turn === 'recruiter'
                  ? 'bg-bad-tint text-bad-ink'
                  : turn === 'manager'
                    ? 'bg-warn-tint text-warn-ink'
                    : 'bg-secondary text-ink-3',
              )}
            >
              {turnLabel}
            </span>
          )}
          {days >= 2 && (
            <span
              className={cn(
                'tnum inline-flex items-center gap-1 text-[10.5px] font-semibold',
                stale ? 'text-warn-ink' : 'text-ink-3',
              )}
              title="Дней в текущем этапе"
            >
              <Clock3 className="size-3" strokeWidth={2.1} />
              {days} дн.
            </span>
          )}
        </div>
      )}

      {candidate.recommendation && (
        <p className="mt-2.5 border-t border-line pt-2.5 text-[11.5px] leading-snug text-ink-2">
          {candidate.recommendation}
        </p>
      )}

      <div className="mt-3 flex gap-1.5">
        {candidate.stage === 'applied' && (
          <button
            type="button"
            onClick={() => onInvite(candidate)}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-brand px-2.5 py-1.5 text-[11.5px] font-semibold text-white transition-colors hover:bg-brand-press"
          >
            <Send className="size-3" strokeWidth={2} />
            Отправить ссылку
          </button>
        )}
        {candidate.stage === 'invited' && (
          <button
            type="button"
            onClick={() => onCopyLink(candidate)}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[11.5px] font-medium text-ink-2 transition-colors hover:border-brand hover:text-brand"
          >
            <Copy className="size-3" strokeWidth={1.9} />
            Копировать ссылку
          </button>
        )}
        {candidate.has_report && (
          <a
            href={`/app/reports/${candidate.id}`}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[11.5px] font-medium text-ink-2 transition-colors hover:border-brand hover:text-brand"
          >
            <FileText className="size-3" strokeWidth={1.9} />
            Заключение
          </a>
        )}
      </div>
    </article>
  )
}
