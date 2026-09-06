import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronDown,
  Loader2,
  Undo2,
  Wand2,
  Plus,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/AppShell'
import { api } from '@/lib/api'
import type { BoardResponse, Requirement } from '@/lib/types'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

interface BankQuestion {
  session_question_id: number
  id: number
  question: string
  competency: string
  tags: string[]
  must_have: string[]
  nice_to_have: string[]
  red_flags?: string[]
  reference_answer?: string
  possible_extra_questions?: string[]
  is_approved: boolean
  is_custom?: boolean
  original_question?: string
  rewritten?: boolean
}

/** Рубрика вопроса: по этим сигналам пайплайн и оценивает ответ. */
function Rubric({
  question,
  onRevert,
}: {
  question: BankQuestion
  onRevert: (question: BankQuestion) => void
}) {
  const blocks: Array<[string, string[], string]> = [
    ['Обязательно должно прозвучать', question.must_have ?? [], 'text-ok-ink'],
    ['Усилит ответ', question.nice_to_have ?? [], 'text-ink-2'],
    ['Красные флаги', question.red_flags ?? [], 'text-bad-ink'],
    ['Уточнения, если ответ поверхностный', question.possible_extra_questions ?? [], 'text-brand'],
  ]
  return (
    <div className="space-y-3.5 border-t border-line bg-secondary/40 px-4 py-3.5 pl-[46px]">
      {question.rewritten && question.original_question && (
        <div className="flex items-start gap-2.5 rounded-lg border border-brand/20 bg-brand-tint/60 px-3 py-2.5">
          <Wand2 className="mt-0.5 size-3.5 shrink-0 text-brand" strokeWidth={2.2} />
          <div className="min-w-0 flex-1">
            <p className="text-[10.5px] font-semibold uppercase tracking-[0.05em] text-brand">
              Формулировка приведена в рабочий вид
            </p>
            <p className="mt-1 text-[12.5px] leading-snug text-ink-2">
              Было: «{question.original_question}»
            </p>
          </div>
          <button
            type="button"
            onClick={() => onRevert(question)}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line bg-card px-2 py-1 text-[11.5px] font-medium text-ink-2 transition-colors hover:border-brand hover:text-brand"
          >
            <Undo2 className="size-3" strokeWidth={2.2} />
            Вернуть
          </button>
        </div>
      )}
      {question.reference_answer && (
        <div>
          <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.05em] text-ink-3">
            Ориентир сильного ответа
          </p>
          <p className="text-[12.5px] leading-relaxed text-ink-2">{question.reference_answer}</p>
        </div>
      )}
      {blocks.map(([title, items, tone]) =>
        items.length > 0 ? (
          <div key={title}>
            <p className={cn('mb-1 text-[10.5px] font-semibold uppercase tracking-[0.05em]', tone)}>{title}</p>
            <ul className="space-y-1">
              {items.map((item, index) => (
                <li key={index} className="text-[12.5px] leading-snug text-ink-2">
                  — {item}
                </li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
      {(question.must_have ?? []).length === 0 && !question.reference_answer && (
        <p className="text-[12.5px] text-ink-3">Рубрика не заполнена — вопрос не будет участвовать в оценке.</p>
      )}
    </div>
  )
}

/** Требование считается закрытым, если его слово встречается в вопросе,
 *  его тегах, компетенции или ожидаемых сигналах ответа. */
function covers(requirement: string, questions: BankQuestion[]) {
  const words = requirement
    .toLowerCase()
    .split(/[^a-zа-яё0-9+#.]+/i)
    .filter((word) => word.length > 2)
  if (words.length === 0) return false
  const haystack = questions
    .map((q) => `${q.question} ${q.competency} ${q.tags.join(' ')} ${(q.must_have ?? []).join(' ')}`)
    .join(' ')
    .toLowerCase()
  return words.some((word) => haystack.includes(word))
}

export function VacancyQuestionsPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [questions, setQuestions] = useState<BankQuestion[] | null>(null)
  const [requirements, setRequirements] = useState<Requirement[]>([])
  const [vacancyTitle, setVacancyTitle] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState(false)

  const load = useCallback(async () => {
    try {
      const [details, board] = await Promise.all([
        api.get<{ title: string; questions: BankQuestion[] }>(`/api/vacancies/${id}`),
        api.get<BoardResponse>(`/api/workspace/vacancies/${id}/board`),
      ])
      setVacancyTitle(details.title)
      setQuestions(details.questions)
      setRequirements(board.vacancy.must_have)
      const approved = details.questions.filter((q) => q.is_approved).map((q) => q.id)
      // Пул ещё не утверждали — предлагаем разумный стартовый набор из 5 вопросов.
      setSelected(new Set(approved.length > 0 ? approved : details.questions.slice(0, 5).map((q) => q.id)))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const chosen = useMemo(
    () => (questions ?? []).filter((q) => selected.has(q.id)),
    [questions, selected],
  )
  const uncovered = requirements.filter((item) => !covers(item.skill, chosen))
  const tooMany = selected.size > 6

  async function addCustom() {
    const text = draft.trim()
    if (text.length < 10) return toast.error('Вопрос слишком короткий')
    setAdding(true)
    try {
      const created = await api.post<BankQuestion>(`/api/workspace/vacancies/${id}/questions`, {
        question: text,
      })
      setQuestions((current) => [...(current ?? []), created])
      setSelected((current) => new Set([...current, created.id]))
      setExpanded((current) => new Set([...current, created.id]))
      setDraft('')
      toast.success('Вопрос добавлен', { description: 'Рубрика оценки собрана — проверьте её ниже' })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setAdding(false)
    }
  }

  async function revert(question: BankQuestion) {
    if (!question.original_question) return
    try {
      await api.patch(`/api/workspace/questions/${question.id}`, { question: question.original_question })
      setQuestions((current) =>
        (current ?? []).map((item) =>
          item.id === question.id
            ? { ...item, question: question.original_question as string, rewritten: false }
            : item,
        ),
      )
      toast.success('Вернул исходную формулировку')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function approve() {
    setSaving(true)
    try {
      await api.post(`/api/vacancies/${id}/approve-questions`, [...selected])
      await api.patch(`/api/workspace/vacancies/${id}/status`, { status: 'active' })
      toast.success('Пул утверждён', { description: 'Вакансия открыта, можно заводить кандидатов' })
      navigate(`/vacancies/${id}`)
    } catch (e) {
      toast.error((e as Error).message)
      setSaving(false)
    }
  }

  if (error) {
    return (
      <PageBody>
        <p className="rounded-lg border border-bad/25 bg-bad-tint px-4 py-3 text-[13px] text-bad-ink">{error}</p>
      </PageBody>
    )
  }

  if (!questions) {
    return (
      <PageBody>
        <Skeleton className="mb-6 h-10 w-72" />
        <Skeleton className="h-96 rounded-xl" />
      </PageBody>
    )
  }

  return (
    <>
      <PageHeader
        eyebrow={
          <Link
            to={`/vacancies/${id}`}
            className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-ink-3 transition-colors hover:text-brand"
          >
            <ArrowLeft className="size-3.5" strokeWidth={2.2} />
            {vacancyTitle}
          </Link>
        }
        title="Вопросы интервью"
        description="Отметьте, что кандидат услышит на интервью. Справа видно, какие требования вакансии эти вопросы закрывают."
      />

      <PageBody>
        <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
          <div>
            {tooMany && (
              <div className="mb-4 flex items-start gap-3 rounded-xl border border-warn/25 bg-warn-tint px-4 py-3">
                <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn-ink" strokeWidth={2.1} />
                <p className="text-[12.5px] leading-relaxed text-warn-ink">
                  <b className="font-semibold">Выбрано {selected.size} вопросов — это много.</b> Каждый лишний
                  стоит около 15% доли кандидатов, дошедших до конца; сокращение с 8 до 4 поднимало completion
                  с 58% до 84%. Оптимум — 4–6.
                </p>
              </div>
            )}

            <div className="mb-4 rounded-xl bg-card p-4 shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
              <div className="mb-2 flex items-center gap-2">
                <Plus className="size-4 text-brand" strokeWidth={2.4} />
                <h3 className="text-[13px] font-semibold text-ink-700">Добавить свой вопрос</h3>
              </div>
              <p className="mb-3 text-[12px] leading-snug text-ink-3">
                Напишите вопрос как есть, хоть в телеграфном виде. Модель приведёт формулировку в рабочий
                вид — его услышит кандидат — и соберёт рубрику: что обязательно должно прозвучать, что усилит
                ответ, какие красные флаги и какие уточнения задать, если ответ окажется поверхностным.
                Без рубрики вопрос не участвует в оценке.
              </p>
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) void addCustom()
                }}
                rows={2}
                placeholder="Например: как работает ивент луп"
                className="w-full resize-y rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[13.5px] leading-relaxed outline-none transition-colors placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
              />
              <div className="mt-2.5 flex items-center justify-between gap-3">
                <span className="text-[11.5px] text-ink-3">
                  {adding ? 'Собираем рубрику, около 10 секунд…' : 'Cmd + Enter — добавить'}
                </span>
                <button
                  type="button"
                  onClick={() => void addCustom()}
                  disabled={adding || draft.trim().length < 10}
                  className="inline-flex items-center gap-2 rounded-lg bg-brand px-3.5 py-2 text-[12.5px] font-semibold text-white transition-colors hover:bg-brand-press disabled:opacity-40"
                >
                  {adding ? (
                    <Loader2 className="size-3.5 animate-spin" strokeWidth={2.4} />
                  ) : (
                    <Sparkles className="size-3.5" strokeWidth={2.2} />
                  )}
                  {adding ? 'Собираем…' : 'Добавить и собрать рубрику'}
                </button>
              </div>
            </div>

            <ul className="divide-y divide-line overflow-hidden rounded-xl bg-card shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
              {questions.map((question) => {
                const on = selected.has(question.id)
                return (
                  <li key={question.id}>
                    <label
                      className={cn(
                        'flex cursor-pointer items-start gap-3 px-4 py-3.5 transition-colors',
                        on ? 'bg-brand-tint/40' : 'hover:bg-secondary/50',
                      )}
                    >
                      <span
                        className={cn(
                          'mt-0.5 grid size-[18px] shrink-0 place-items-center rounded-[5px] border transition-colors',
                          on ? 'border-brand bg-brand text-white' : 'border-line-2 bg-card',
                        )}
                      >
                        {on && <Check className="size-3" strokeWidth={3.2} />}
                      </span>
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={(event) => {
                          const next = new Set(selected)
                          if (event.target.checked) next.add(question.id)
                          else next.delete(question.id)
                          setSelected(next)
                        }}
                        className="sr-only"
                      />
                      <span className="min-w-0 flex-1">
                        <span className={cn('block text-[13.5px] leading-snug', on ? 'text-ink' : 'text-ink-2')}>
                          {question.question}
                        </span>
                        <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[10.5px] font-medium text-ink-3">
                            {question.competency}
                          </span>
                          {question.is_custom && (
                            <span className="rounded-md bg-brand-tint px-1.5 py-0.5 text-[10.5px] font-semibold text-brand">
                              свой
                            </span>
                          )}
                          {question.rewritten && (
                            <span
                              className="inline-flex items-center gap-1 rounded-md bg-secondary px-1.5 py-0.5 text-[10.5px] font-medium text-ink-3"
                              title="Формулировку привели в рабочий вид"
                            >
                              <Wand2 className="size-2.5" strokeWidth={2.4} />
                              переформулирован
                            </span>
                          )}
                          {question.tags.slice(0, 3).map((tag) => (
                            <span key={tag} className="text-[10.5px] text-ink-3">
                              {tag}
                            </span>
                          ))}
                        </span>
                      </span>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.preventDefault()
                          setExpanded((current) => {
                            const next = new Set(current)
                            if (next.has(question.id)) next.delete(question.id)
                            else next.add(question.id)
                            return next
                          })
                        }}
                        className="mt-0.5 shrink-0 rounded-md p-1 text-ink-3 transition-colors hover:bg-secondary hover:text-ink"
                        title="Показать рубрику оценки"
                      >
                        <ChevronDown
                          className={cn(
                            'size-4 transition-transform',
                            expanded.has(question.id) && 'rotate-180',
                          )}
                          strokeWidth={2}
                        />
                      </button>
                    </label>
                    {expanded.has(question.id) && <Rubric question={question} onRevert={(item) => void revert(item)} />}
                  </li>
                )
              })}
            </ul>
          </div>

          <aside className="lg:sticky lg:top-6 lg:self-start">
            <div className="rounded-xl bg-card p-5 shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
              <div className="flex items-baseline justify-between">
                <h3 className="text-[14px] font-bold text-ink-700">Выбрано вопросов</h3>
                <span
                  className={cn(
                    'tnum text-[30px] leading-none font-bold tracking-[-0.03em]',
                    tooMany ? 'text-warn-ink' : selected.size === 0 ? 'text-ink-3' : 'text-brand',
                  )}
                >
                  {selected.size}
                </span>
              </div>
              <p className="mt-1.5 text-[12px] text-ink-3">Рекомендованный диапазон — 4–6 вопросов</p>

              {requirements.length > 0 && (
                <div className="mt-5 border-t border-line pt-4">
                  <p className="mb-2.5 text-[11.5px] font-semibold uppercase tracking-[0.05em] text-ink-3">
                    Покрытие требований
                  </p>
                  <ul className="space-y-1.5">
                    {requirements.map((item) => {
                      const ok = covers(item.skill, chosen)
                      return (
                        <li key={item.skill} className="flex items-center gap-2 text-[12.5px]">
                          {ok ? (
                            <CheckCircle2 className="size-3.5 shrink-0 text-ok" strokeWidth={2.2} />
                          ) : (
                            <TriangleAlert className="size-3.5 shrink-0 text-warn" strokeWidth={2.2} />
                          )}
                          <span className={ok ? 'text-ink-2' : 'font-medium text-warn-ink'}>{item.skill}</span>
                        </li>
                      )
                    })}
                  </ul>
                  {uncovered.length > 0 && (
                    <p className="mt-3 text-[11.5px] leading-snug text-warn-ink">
                      {uncovered.length}{' '}
                      {uncovered.length === 1 ? 'требование не проверяется' : 'требований не проверяются'} —
                      промах по ним нельзя будет отличить от зоны роста.
                    </p>
                  )}
                </div>
              )}

              <button
                type="button"
                onClick={() => void approve()}
                disabled={saving || selected.size === 0}
                className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-5 py-3 text-[13.5px] font-bold text-white shadow-[0_4px_12px_rgba(0,87,255,0.22)] transition-all hover:bg-brand-press hover:shadow-[0_6px_16px_rgba(0,87,255,0.32)] disabled:opacity-40 disabled:shadow-none"
              >
                {saving && <Loader2 className="size-4 animate-spin" strokeWidth={2.2} />}
                Утвердить пул и открыть вакансию
              </button>
              {selected.size === 0 && (
                <p className="mt-2 text-center text-[12px] text-ink-3">Выберите хотя бы один вопрос</p>
              )}
            </div>
          </aside>
        </div>
      </PageBody>
    </>
  )
}
