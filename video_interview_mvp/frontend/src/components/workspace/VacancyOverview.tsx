import { AlertTriangle, FileText } from 'lucide-react'
import type { Requirement, VacancyDetail } from '@/lib/types'
import { cn } from '@/lib/utils'

const WEIGHT_LABEL = ['вскользь', 'обязательно', 'критично']

function RequirementList({ items, accent }: { items: Requirement[]; accent: boolean }) {
  if (items.length === 0) {
    return <p className="px-4 py-6 text-center text-[12.5px] text-ink-3">Требования не разобраны</p>
  }
  return (
    <ul className="divide-y divide-line">
      {items.map((item, index) => (
        <li key={`${item.skill}-${index}`} className="flex items-start gap-3 px-4 py-3">
          <span
            className="mt-1 flex shrink-0 items-center gap-[3px]"
            title={`Вес: ${WEIGHT_LABEL[item.weight - 1] ?? ''}`}
          >
            {[1, 2, 3].map((level) => (
              <span
                key={level}
                className={cn(
                  'h-3 w-1 rounded-full',
                  level <= item.weight ? (accent ? 'bg-brand' : 'bg-ink-3') : 'bg-line-2',
                )}
              />
            ))}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13.5px] font-medium leading-snug">{item.skill}</span>
            {item.evidence && (
              <span className="mt-1 block font-mono text-[11px] leading-snug text-ink-3">«{item.evidence}»</span>
            )}
          </span>
        </li>
      ))}
    </ul>
  )
}

function Panel({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl border border-line bg-card">
      <header className="flex items-baseline gap-2.5 border-b border-line px-4 py-3">
        <h3 className="text-[13px] font-semibold">{title}</h3>
        {count !== undefined && <span className="tnum text-[11.5px] text-ink-3">{count}</span>}
      </header>
      {children}
    </section>
  )
}

export function VacancyOverview({ vacancy }: { vacancy: VacancyDetail }) {
  const hasProfile = vacancy.must_have.length > 0 || vacancy.nice_to_have.length > 0

  return (
    <div className="grid gap-5 lg:grid-cols-[1.15fr_1fr]">
      <div className="space-y-5">
        {vacancy.summary && (
          <div className="rounded-xl border border-line bg-card p-5">
            <p className="text-[14px] leading-relaxed text-ink-2">{vacancy.summary}</p>
          </div>
        )}

        <Panel title="Текст вакансии">
          <div className="max-h-[520px] overflow-y-auto px-5 py-4">
            <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink-2">
              {vacancy.vacancy_text || 'Описание не заполнено'}
            </p>
          </div>
        </Panel>

        {vacancy.detected_tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {vacancy.detected_tags.map((tag) => (
              <span
                key={tag}
                className="rounded-md bg-brand-tint px-2 py-1 text-[11.5px] font-medium text-brand"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-5">
        {!hasProfile && (
          <div className="flex gap-3 rounded-xl border border-line bg-card p-4">
            <FileText className="mt-0.5 size-4 shrink-0 text-ink-3" strokeWidth={1.9} />
            <p className="text-[12.5px] leading-relaxed text-ink-2">
              Вакансия создана до появления разбора требований, поэтому веса и цитаты не заполнены. Новые
              вакансии через конструктор получают их автоматически.
            </p>
          </div>
        )}

        {vacancy.must_have.length > 0 && (
          <Panel title="Обязательные требования" count={vacancy.must_have.length}>
            <RequirementList items={vacancy.must_have} accent />
          </Panel>
        )}

        {vacancy.nice_to_have.length > 0 && (
          <Panel title="Желательные" count={vacancy.nice_to_have.length}>
            <RequirementList items={vacancy.nice_to_have} accent={false} />
          </Panel>
        )}

        {vacancy.stop_factors.length > 0 && (
          <section className="rounded-xl border border-bad/20 bg-bad-tint/60 p-4">
            <h3 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-bad-ink">
              <AlertTriangle className="size-3.5" strokeWidth={2.1} />
              Стоп-факторы и противоречия
            </h3>
            <ul className="space-y-1.5">
              {vacancy.stop_factors.map((factor, index) => (
                <li key={index} className="text-[12.5px] leading-snug text-ink-2">
                  — {factor}
                </li>
              ))}
            </ul>
          </section>
        )}

        {vacancy.responsibilities.length > 0 && (
          <Panel title="Обязанности" count={vacancy.responsibilities.length}>
            <ul className="space-y-2 px-4 py-3.5">
              {vacancy.responsibilities.map((item, index) => (
                <li key={index} className="text-[12.5px] leading-snug text-ink-2">
                  — {item}
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </div>
    </div>
  )
}
