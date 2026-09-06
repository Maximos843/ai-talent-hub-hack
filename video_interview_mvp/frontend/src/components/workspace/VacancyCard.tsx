import { Link } from 'react-router-dom'
import { ArrowUpRight, CircleDashed } from 'lucide-react'
import type { VacancyCardData } from '@/lib/types'
import { StageStrip } from './StageStrip'
import { cn } from '@/lib/utils'

const GRADE_LABEL: Record<string, string> = {
  junior: 'Junior',
  middle: 'Middle',
  senior: 'Senior',
  principal: 'Principal',
}

export function VacancyCard({ vacancy }: { vacancy: VacancyCardData }) {
  const isDraft = vacancy.status === 'draft'
  const isClosed = vacancy.status === 'closed'

  return (
    <Link
      to={`/vacancies/${vacancy.id}`}
      className={cn(
        'group relative flex flex-col rounded-xl bg-card p-5 transition-all duration-200',
        'shadow-[0_6px_24px_rgba(19,19,19,0.06)] hover:-translate-y-0.5 hover:shadow-[0_10px_30px_rgba(19,19,19,0.09)]',
        isClosed && 'opacity-60 saturate-0 hover:opacity-90 hover:saturate-100',
      )}
    >
      <div className="mb-3.5 flex items-start justify-between gap-3">
        <span className="rounded-md bg-secondary px-1.5 py-1 text-[10.5px] font-bold uppercase tracking-[0.03em] text-ink-2">
          {GRADE_LABEL[vacancy.grade ?? ''] ?? (vacancy.grade || '—')}
        </span>
        {isDraft ? (
          <span className="pill bg-secondary text-ink-2">
            <CircleDashed className="size-3" strokeWidth={2.2} />
            Черновик
          </span>
        ) : isClosed ? (
          <span className="pill bg-secondary text-ink-3">Закрыта</span>
        ) : (
          <span className="pill bg-ok-tint text-ok-ink">
            <span className="size-1.5 rounded-full bg-ok" />
            Активна
          </span>
        )}
      </div>

      <h3 className="text-[18px] leading-snug font-bold tracking-[-0.02em] text-ink-700">{vacancy.title}</h3>

      <div className="mb-5 mt-3 flex flex-wrap gap-1.5">
        {vacancy.detected_tags.slice(0, 4).map((tag) => (
          <span key={tag} className="rounded-md bg-brand-tint px-2 py-[3px] text-[11px] font-medium text-brand">
            {tag}
          </span>
        ))}
        {vacancy.detected_tags.length > 4 && (
          <span className="tnum rounded-md px-1 py-[3px] text-[10.5px] text-ink-3">
            +{vacancy.detected_tags.length - 4}
          </span>
        )}
      </div>

      <div className="mt-auto">
        {isDraft ? (
          <p className="rounded-lg border border-dashed border-line-2 px-3 py-2.5 text-[12px] leading-snug text-ink-2">
            Пул вопросов не утверждён&nbsp;— ссылку кандидату выдать нельзя.
            <span className="tnum ml-1 text-ink-3">{vacancy.questions_count} предложено</span>
          </p>
        ) : (
          <StageStrip counts={vacancy.stage_counts} total={vacancy.candidates_total} />
        )}
      </div>

      <ArrowUpRight
        className="absolute right-4 top-1/2 size-4 -translate-y-1/2 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100"
        strokeWidth={1.75}
      />
    </Link>
  )
}
