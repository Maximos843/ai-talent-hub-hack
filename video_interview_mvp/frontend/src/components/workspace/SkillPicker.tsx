import { useMemo, useRef, useState } from 'react'
import { Check, Plus, Sparkles, X } from 'lucide-react'
import type { Requirement, SkillEntry } from '@/lib/types'
import { cn } from '@/lib/utils'

const WEIGHT_LABEL = ['вскользь', 'обязательно', 'критично']

/** Навык + вес + признак того, проверяется ли он вопросами из банка. */
export function SkillPicker({
  label,
  hint,
  items,
  library,
  accent,
  onChange,
}: {
  label: string
  hint?: string
  items: Requirement[]
  library: SkillEntry[]
  accent: boolean
  onChange: (items: Requirement[]) => void
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const coverage = useMemo(() => new Map(library.map((entry) => [entry.skill, entry.questions])), [library])
  const chosen = useMemo(() => new Set(items.map((item) => item.skill.toLowerCase())), [items])

  const suggestions = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return library
      .filter((entry) => !chosen.has(entry.skill) && (!needle || entry.skill.includes(needle)))
      .slice(0, 8)
  }, [library, query, chosen])

  function add(skill: string) {
    const clean = skill.trim().toLowerCase()
    if (!clean || chosen.has(clean)) return
    onChange([...items, { skill: clean, weight: accent ? 2 : 1, evidence: '' }])
    setQuery('')
    inputRef.current?.focus()
  }

  return (
    <section>
      {(label || hint) && (
        <div className="mb-2 flex items-baseline gap-2.5">
          {label && <h3 className="text-[13px] font-semibold text-ink-700">{label}</h3>}
          {label && <span className="tnum text-[11.5px] text-ink-3">{items.length}</span>}
          {hint && <span className="ml-auto text-[11.5px] text-ink-3">{hint}</span>}
        </div>
      )}

      {items.length > 0 && (
        <ul className="mb-2.5 flex flex-wrap gap-1.5">
          {items.map((item, index) => {
            const questions = coverage.get(item.skill.toLowerCase()) ?? 0
            return (
              <li
                key={`${item.skill}-${index}`}
                className={cn(
                  'inline-flex items-center gap-2 rounded-lg py-1.5 pl-2.5 pr-1.5 text-[12.5px] font-medium',
                  accent ? 'bg-brand-tint text-brand' : 'bg-secondary text-ink-2',
                )}
              >
                {questions === 0 && (
                  <Sparkles className="size-3 shrink-0 opacity-70" strokeWidth={2.2} aria-label="вопрос достроит ИИ" />
                )}
                <span>{item.skill}</span>

                <span className="flex items-center gap-[3px]" title={`Вес: ${WEIGHT_LABEL[item.weight - 1]}`}>
                  {[1, 2, 3].map((level) => (
                    <button
                      key={level}
                      type="button"
                      aria-label={WEIGHT_LABEL[level - 1]}
                      onClick={() => {
                        const next = [...items]
                        next[index] = { ...item, weight: level }
                        onChange(next)
                      }}
                      className={cn(
                        'h-3 w-1 rounded-full transition-colors',
                        level <= item.weight ? 'bg-current opacity-90' : 'bg-current opacity-25',
                      )}
                    />
                  ))}
                </span>

                <button
                  type="button"
                  onClick={() => onChange(items.filter((_, i) => i !== index))}
                  className="rounded p-0.5 opacity-60 transition-opacity hover:opacity-100"
                  aria-label={`Убрать ${item.skill}`}
                >
                  <X className="size-3" strokeWidth={2.5} />
                </button>
              </li>
            )
          })}
        </ul>
      )}

      <div className="relative">
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 140)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              add(suggestions[0]?.skill ?? query)
            }
          }}
          placeholder="Начните вводить навык — kafka, postgresql…"
          className="w-full rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[13.5px] outline-none transition-colors placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
        />

        {open && (suggestions.length > 0 || query.trim()) && (
          <ul className="absolute z-20 mt-1.5 max-h-64 w-full overflow-y-auto rounded-xl bg-card p-1.5 shadow-[0_12px_40px_rgba(19,19,19,0.12)]">
            {suggestions.map((entry) => (
              <li key={entry.skill}>
                <button
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => add(entry.skill)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-secondary"
                >
                  <Check className="size-3.5 shrink-0 text-ink-3" strokeWidth={2.2} />
                  <span className="flex-1 text-[13px] font-medium">{entry.skill}</span>
                  <span className="tnum shrink-0 text-[11px] text-ink-3">{entry.questions} вопр.</span>
                </button>
              </li>
            ))}
            {query.trim() && !suggestions.some((entry) => entry.skill === query.trim().toLowerCase()) && (
              <li>
                <button
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => add(query)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-secondary"
                >
                  <Plus className="size-3.5 shrink-0 text-brand" strokeWidth={2.5} />
                  <span className="flex-1 text-[13px]">
                    Добавить «<span className="font-semibold">{query.trim()}</span>»
                  </span>
                  <span className="shrink-0 text-[11px] text-brand">вопрос достроит ИИ</span>
                </button>
              </li>
            )}
          </ul>
        )}
      </div>
    </section>
  )
}
