import type { Stage } from '@/lib/types'
import { cn } from '@/lib/utils'

/** Цвет закреплён за смыслом этапа, а не за акцентом интерфейса:
 *  зелёный только «продвинут», красный только «отказ». */
export const STAGE_META: Record<
  Stage,
  { short: string; full: string; bar: string; dot: string; chip: string; strip: string }
> = {
  applied: {
    short: 'Новые',
    full: 'Новые',
    bar: 'bg-ink-3',
    dot: 'bg-ink-3',
    chip: 'bg-secondary text-ink-2',
    strip: '#9095A8',
  },
  invited: {
    short: 'Приглаш.',
    full: 'Приглашены',
    bar: 'bg-wait',
    dot: 'bg-wait',
    chip: 'bg-wait-tint text-wait',
    strip: '#18A8FF',
  },
  interviewed: {
    short: 'Прошли',
    full: 'Прошли интервью',
    bar: 'bg-warn',
    dot: 'bg-warn',
    chip: 'bg-warn-tint text-warn-ink',
    strip: '#E29500',
  },
  advanced: {
    short: 'Продвин.',
    full: 'Продвинуты',
    bar: 'bg-ok',
    dot: 'bg-ok',
    chip: 'bg-ok-tint text-ok-ink',
    strip: '#12A87C',
  },
  rejected: {
    short: 'Отказ',
    full: 'Отклонены',
    bar: 'bg-bad',
    dot: 'bg-bad',
    chip: 'bg-bad-tint text-bad-ink',
    strip: '#E7364F',
  },
}

export const STAGE_ORDER: Stage[] = ['applied', 'invited', 'interviewed', 'advanced', 'rejected']

/** Счётчики по колонкам без цветной полосы: полоса при малых числах всё равно
 *  не читается, а внимание нужно на том, что требует действия. */
export function StageStrip({ counts, total }: { counts: Record<Stage, number>; total: number }) {
  const needsAction = counts.applied + counts.interviewed
  return (
    <div>
      {needsAction > 0 && (
        <p className="mb-2.5 text-[12px] font-semibold text-ink">
          {counts.interviewed > 0 && (
            <span className="text-warn-ink">
              {counts.interviewed} ждут вердикта
            </span>
          )}
          {counts.interviewed > 0 && counts.applied > 0 && <span className="text-ink-3"> · </span>}
          {counts.applied > 0 && <span className="text-ink-2">{counts.applied} без ссылки</span>}
        </p>
      )}
      {needsAction === 0 && total > 0 && (
        <p className="mb-2.5 text-[12px] text-ink-3">Действий не требуется</p>
      )}
      <dl className="grid grid-cols-5 gap-1 border-t border-line pt-2.5">
        {STAGE_ORDER.map((stage) => (
          <div key={stage} className="min-w-0">
            <dt className="truncate text-[10px] font-medium text-ink-3">{STAGE_META[stage].short}</dt>
            <dd
              className={cn(
                'tnum mt-1 text-[16px] leading-none font-bold tracking-[-0.02em]',
                counts[stage] > 0 ? 'text-ink' : 'text-ink-3/40',
              )}
            >
              {counts[stage]}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
