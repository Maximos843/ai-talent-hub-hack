import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, Loader2, Pencil, Plus, Search, Sparkles, Wand2 } from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/AppShell'
import { api } from '@/lib/api'
import type { BankQuestionRow } from '@/lib/types'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

const lines = (value: string) => value.split('\n').map((line) => line.trim()).filter(Boolean)

function RubricBlock({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  if (items.length === 0) return null
  return (
    <div>
      <p className={cn('mb-1 text-[10.5px] font-semibold uppercase tracking-[0.05em]', tone)}>{title}</p>
      <ul className="space-y-1">
        {items.map((item, index) => (
          <li key={index} className="text-[12.5px] leading-snug text-ink-2">
            — {item}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Редактор вопроса: текст и рубрика, по которой оценивается ответ. */
function QuestionEditor({
  question,
  open,
  onOpenChange,
  onSaved,
}: {
  question: BankQuestionRow | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}) {
  const [text, setText] = useState('')
  const [competency, setCompetency] = useState('')
  const [tags, setTags] = useState('')
  const [reference, setReference] = useState('')
  const [must, setMust] = useState('')
  const [nice, setNice] = useState('')
  const [flags, setFlags] = useState('')
  const [extras, setExtras] = useState('')
  const [busy, setBusy] = useState(false)
  const [drafting, setDrafting] = useState(false)

  /** Собирает рубрику по тексту вопроса и заодно приводит формулировку в вид,
   *  который не стыдно озвучить кандидату. Всё заполненное можно править. */
  async function draftWithAi() {
    if (text.trim().length < 10) return toast.error('Сначала напишите вопрос')
    setDrafting(true)
    try {
      const draft = await api.post<{
        question: string
        rewritten: boolean
        competency: string
        tags: string[]
        reference_answer: string
        must_have: string[]
        nice_to_have: string[]
        red_flags: string[]
        possible_extra_questions: string[]
      }>('/api/workspace/questions/draft', { question: text.trim(), competency: competency.trim() })
      setText(draft.question)
      setCompetency(draft.competency)
      setTags(draft.tags.join(', '))
      setReference(draft.reference_answer)
      setMust(draft.must_have.join('\n'))
      setNice(draft.nice_to_have.join('\n'))
      setFlags(draft.red_flags.join('\n'))
      setExtras(draft.possible_extra_questions.join('\n'))
      toast.success('Рубрика собрана', {
        description: draft.rewritten ? 'Формулировку тоже привели в рабочий вид' : 'Проверьте и поправьте, если нужно',
      })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setDrafting(false)
    }
  }

  useEffect(() => {
    setText(question?.question ?? '')
    setCompetency(question?.competency ?? '')
    setTags((question?.tags ?? []).join(', '))
    setReference(question?.reference_answer ?? '')
    setMust((question?.must_have ?? []).join('\n'))
    setNice((question?.nice_to_have ?? []).join('\n'))
    setFlags((question?.red_flags ?? []).join('\n'))
    setExtras((question?.possible_extra_questions ?? []).join('\n'))
  }, [question, open])

  async function save() {
    if (text.trim().length < 10) return toast.error('Вопрос слишком короткий')
    setBusy(true)
    const body = {
      question: text.trim(),
      competency: competency.trim() || 'general',
      tags: tags.split(',').map((t) => t.trim().toLowerCase()).filter(Boolean),
      reference_answer: reference.trim(),
      must_have: lines(must),
      nice_to_have: lines(nice),
      red_flags: lines(flags),
      possible_extra_questions: lines(extras),
    }
    try {
      if (question?.database_id) await api.patch(`/api/questions/${question.database_id}`, body)
      else await api.post('/api/questions', body)
      toast.success(question ? 'Вопрос обновлён' : 'Вопрос добавлен в банк')
      onOpenChange(false)
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const fields: Array<[string, string, string, (value: string) => void, string]> = [
    ['Обязательно должно прозвучать', must, 'Один сигнал на строку', setMust, 'text-ok-ink'],
    ['Усилит ответ', nice, 'Один сигнал на строку', setNice, 'text-ink-2'],
    ['Красные флаги', flags, 'Конкретные ошибки или тревожные признаки', setFlags, 'text-bad-ink'],
    ['Уточняющие вопросы', extras, 'Не более двух', setExtras, 'text-brand'],
  ]

  return (
    <Dialog open={open} onOpenChange={(value) => (busy ? null : onOpenChange(value))}>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-[19px] font-bold">
            {question ? 'Редактирование вопроса' : 'Новый вопрос в банк'}
          </DialogTitle>
        </DialogHeader>

        <div className="mt-2 space-y-4">
          <div>
            <div className="mb-1.5 flex items-center justify-between gap-3">
              <label className="text-[12.5px] font-semibold text-ink-700">Текст вопроса</label>
              <button
                type="button"
                onClick={() => void draftWithAi()}
                disabled={drafting || text.trim().length < 10}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-[12px] font-medium text-brand transition-colors hover:bg-brand-tint disabled:opacity-40"
              >
                {drafting ? (
                  <Loader2 className="size-3.5 animate-spin" strokeWidth={2.2} />
                ) : (
                  <Wand2 className="size-3.5" strokeWidth={2} />
                )}
                {drafting ? 'Собираем…' : 'Собрать рубрику по вопросу'}
              </button>
            </div>
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={3}
              placeholder="Напишите вопрос хоть в телеграфном виде — модель развернёт и соберёт критерии оценки"
              className="w-full resize-y rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[13.5px] leading-relaxed outline-none placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-[12.5px] font-semibold text-ink-700">Компетенция</label>
              <input
                value={competency}
                onChange={(event) => setCompetency(event.target.value)}
                placeholder="databases"
                className="w-full rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[13.5px] outline-none focus:border-brand focus:ring-2 focus:ring-brand/15"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-[12.5px] font-semibold text-ink-700">Теги через запятую</label>
              <input
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder="sql, postgresql"
                className="w-full rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[13.5px] outline-none focus:border-brand focus:ring-2 focus:ring-brand/15"
              />
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-[12.5px] font-semibold text-ink-700">Ориентир сильного ответа</label>
            <textarea
              value={reference}
              onChange={(event) => setReference(event.target.value)}
              rows={3}
              className="w-full resize-y rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[13px] leading-relaxed outline-none focus:border-brand focus:ring-2 focus:ring-brand/15"
            />
          </div>

          {fields.map(([label, value, hint, setter, tone]) => (
            <div key={label}>
              <label className={cn('mb-1.5 block text-[12.5px] font-semibold', tone)}>{label}</label>
              <textarea
                value={value}
                onChange={(event) => setter(event.target.value)}
                rows={3}
                placeholder={hint}
                className="w-full resize-y rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[13px] leading-relaxed outline-none placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
              />
            </div>
          ))}

          <div className="flex justify-end gap-2 border-t border-line pt-4">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={busy}
              className="rounded-lg px-4 py-2.5 text-[13px] font-medium text-ink-2 transition-colors hover:bg-secondary"
            >
              Отмена
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2.5 text-[13px] font-semibold text-white transition-colors hover:bg-brand-press disabled:opacity-40"
            >
              {busy && <Loader2 className="size-3.5 animate-spin" strokeWidth={2.4} />}
              Сохранить
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function QuestionBankPage() {
  const [items, setItems] = useState<BankQuestionRow[] | null>(null)
  const [meta, setMeta] = useState<{ competencies: string[]; count: number } | null>(null)
  const [query, setQuery] = useState('')
  const [competency, setCompetency] = useState('all')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [editing, setEditing] = useState<BankQuestionRow | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [error, setError] = useState('')

  function load() {
    api.get<BankQuestionRow[]>('/api/questions').then(setItems).catch((e) => setError(e.message))
    api.get<{ competencies: string[]; count: number }>('/api/questions/meta').then(setMeta).catch(() => {})
  }

  useEffect(load, [])

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (items ?? []).filter((item) => {
      if (competency !== 'all' && item.competency !== competency) return false
      if (!needle) return true
      return `${item.question} ${item.competency} ${item.tags.join(' ')}`.toLowerCase().includes(needle)
    })
  }, [items, query, competency])

  const key = (item: BankQuestionRow) => String(item.database_id ?? item.bank_id ?? item.question)

  return (
    <>
      <PageHeader
        eyebrow={<span className="text-[12.5px] font-medium text-ink-3">Рабочее место</span>}
        title="Банк вопросов"
        description="Общий банк для всех вакансий. Отсюда система подбирает ядро интервью, а недостающее дописывает модель — сгенерированные вопросы тоже попадают сюда и переиспользуются."
        actions={
          <button
            type="button"
            onClick={() => {
              setEditing(null)
              setEditorOpen(true)
            }}
            className="inline-flex items-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-[13px] font-semibold text-white shadow-[0_4px_12px_rgba(0,87,255,0.22)] transition-colors hover:bg-brand-press"
          >
            <Plus className="size-4" strokeWidth={2.4} />
            Добавить вопрос
          </button>
        }
      />

      <PageBody>
        {error && (
          <p className="rounded-lg border border-bad/25 bg-bad-tint px-4 py-3 text-[13px] text-bad-ink">{error}</p>
        )}

        {!items && !error && <Skeleton className="h-96 rounded-xl" />}

        {items && (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <div className="relative min-w-56 flex-1">
                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-3" strokeWidth={2} />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Поиск по тексту, компетенции и тегам"
                  className="w-full rounded-lg border border-line-2 bg-card py-2.5 pl-9 pr-3.5 text-[13.5px] outline-none transition-colors placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
                />
              </div>
              <select
                value={competency}
                onChange={(event) => setCompetency(event.target.value)}
                className="rounded-lg border border-line-2 bg-card px-3 py-2.5 text-[13.5px] outline-none focus:border-brand"
              >
                <option value="all">Все компетенции</option>
                {(meta?.competencies ?? []).map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
              <span className="tnum text-[12.5px] text-ink-3">
                {rows.length} из {items.length}
              </span>
            </div>

            <ul className="divide-y divide-line overflow-hidden rounded-xl bg-card shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
              {rows.map((item) => {
                const id = key(item)
                const open = expanded.has(id)
                return (
                  <li key={id}>
                    <div className="flex items-start gap-3 px-4 py-3.5">
                      <div className="min-w-0 flex-1">
                        <p className="text-[13.5px] leading-snug text-ink">{item.question}</p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[10.5px] font-medium text-ink-3">
                            {item.competency}
                          </span>
                          {item.tags.slice(0, 4).map((tag) => (
                            <span key={tag} className="text-[10.5px] text-ink-3">
                              {tag}
                            </span>
                          ))}
                          {item.usage_count > 0 && (
                            <span className="tnum rounded-md bg-brand-tint px-1.5 py-0.5 text-[10.5px] font-semibold text-brand">
                              в {item.usage_count} вакансиях
                            </span>
                          )}
                          {item.must_have.length === 0 && (
                            <span className="rounded-md bg-warn-tint px-1.5 py-0.5 text-[10.5px] font-semibold text-warn-ink">
                              нет рубрики
                            </span>
                          )}
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={() => {
                          setEditing(item)
                          setEditorOpen(true)
                        }}
                        className="shrink-0 rounded-md p-1.5 text-ink-3 transition-colors hover:bg-secondary hover:text-brand"
                        title="Редактировать"
                      >
                        <Pencil className="size-3.5" strokeWidth={1.9} />
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setExpanded((current) => {
                            const next = new Set(current)
                            if (next.has(id)) next.delete(id)
                            else next.add(id)
                            return next
                          })
                        }
                        className="shrink-0 rounded-md p-1.5 text-ink-3 transition-colors hover:bg-secondary hover:text-ink"
                        title="Показать рубрику"
                      >
                        <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} strokeWidth={2} />
                      </button>
                    </div>

                    {open && (
                      <div className="space-y-3.5 border-t border-line bg-secondary/40 px-4 py-3.5">
                        {item.reference_answer && (
                          <div>
                            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.05em] text-ink-3">
                              Ориентир сильного ответа
                            </p>
                            <p className="text-[12.5px] leading-relaxed text-ink-2">{item.reference_answer}</p>
                          </div>
                        )}
                        <RubricBlock title="Обязательно должно прозвучать" items={item.must_have} tone="text-ok-ink" />
                        <RubricBlock title="Усилит ответ" items={item.nice_to_have} tone="text-ink-2" />
                        <RubricBlock title="Красные флаги" items={item.red_flags} tone="text-bad-ink" />
                        <RubricBlock
                          title="Уточнения, если ответ поверхностный"
                          items={item.possible_extra_questions}
                          tone="text-brand"
                        />
                        {item.must_have.length === 0 && !item.reference_answer && (
                          <p className="flex items-center gap-2 text-[12.5px] text-warn-ink">
                            <Sparkles className="size-3.5" strokeWidth={2.2} />
                            Рубрики нет — по этому вопросу ответ оценить нечем.
                          </p>
                        )}
                      </div>
                    )}
                  </li>
                )
              })}
              {rows.length === 0 && (
                <li className="px-6 py-14 text-center text-[13px] text-ink-3">Ничего не нашлось</li>
              )}
            </ul>
          </>
        )}
      </PageBody>

      <QuestionEditor question={editing} open={editorOpen} onOpenChange={setEditorOpen} onSaved={load} />
    </>
  )
}
