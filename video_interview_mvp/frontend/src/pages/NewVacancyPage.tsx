import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, FileUp, Loader2, Sparkles, TriangleAlert, Wand2, X } from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/AppShell'
import { SkillPicker } from '@/components/workspace/SkillPicker'
import { api } from '@/lib/api'
import type { Requirement, SkillEntry } from '@/lib/types'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

interface ParsedVacancy {
  title: string
  grade: string
  summary: string
  must_have: Requirement[]
  nice_to_have: Requirement[]
  responsibilities: string[]
  stop_factors: string[]
  tags: string[]
  vacancy_text: string
  source_filename: string
  demo_mode: boolean
}

const GRADES = [
  ['junior', 'Junior'],
  ['middle', 'Middle'],
  ['senior', 'Senior'],
  ['principal', 'Principal'],
] as const

export function NewVacancyPage() {
  const navigate = useNavigate()
  const importRef = useRef<HTMLInputElement>(null)

  const [title, setTitle] = useState('')
  const [grade, setGrade] = useState<string>('middle')
  const [description, setDescription] = useState('')
  const [mustHave, setMustHave] = useState<Requirement[]>([])
  const [stopFactors, setStopFactors] = useState<string[]>([])
  const [sourceFile, setSourceFile] = useState('')

  const [library, setLibrary] = useState<SkillEntry[]>([])
  const [importing, setImporting] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get<SkillEntry[]>('/api/workspace/skills').then(setLibrary).catch(() => setLibrary([]))
  }, [])

  const coverage = useMemo(() => new Map(library.map((entry) => [entry.skill, entry.questions])), [library])
  const uncovered = mustHave.filter((item) => (coverage.get(item.skill.toLowerCase()) ?? 0) === 0)
  const covered = mustHave.filter((item) => (coverage.get(item.skill.toLowerCase()) ?? 0) > 0)
  const competencies = new Set<string>()
  for (const item of mustHave) {
    library.find((entry) => entry.skill === item.skill.toLowerCase())?.competencies.forEach((c) => competencies.add(c))
  }

  function applyParsed(parsed: ParsedVacancy, keepTitle: boolean) {
    if (parsed.title && !keepTitle) setTitle(parsed.title)
    if (parsed.grade) setGrade(parsed.grade)

    // В поле навыков идут короткие теги, а не требования целыми предложениями.
    // Вес берём из разбора требований: если тег встретился в обязательном
    // требовании, он весомее, чем упомянутый вскользь.
    const weightOf = (tag: string) => {
      const inMust = parsed.must_have.find((item) => item.skill.toLowerCase().includes(tag))
      if (inMust) return inMust.weight
      return parsed.nice_to_have.some((item) => item.skill.toLowerCase().includes(tag)) ? 1 : 2
    }
    const merged = new Map(mustHave.map((item) => [item.skill.toLowerCase(), item]))
    for (const tag of parsed.tags) {
      const key = tag.toLowerCase()
      if (!merged.has(key)) merged.set(key, { skill: key, weight: weightOf(key), evidence: '' })
    }
    setMustHave([...merged.values()])
    setStopFactors(parsed.stop_factors)
  }

  async function importFile(file: File) {
    setImporting(true)
    const form = new FormData()
    form.append('file', file)
    form.append('vacancy_text', '')
    try {
      const parsed = await api.upload<ParsedVacancy>('/api/workspace/vacancies/parse', form)
      setDescription(parsed.vacancy_text)
      setSourceFile(parsed.source_filename)
      applyParsed(parsed, false)
      toast.success(`Разобран файл ${file.name}`, {
        description: parsed.demo_mode ? 'Demo-режим: ключ LLM не задан' : 'Проверьте требования и веса',
      })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setImporting(false)
    }
  }

  /** Достаёт навыки из уже введённого описания — чтобы не перебирать теги руками. */
  async function extractFromDescription() {
    if (description.trim().length < 40) return toast.error('Слишком короткое описание для разбора')
    setExtracting(true)
    const form = new FormData()
    form.append('vacancy_text', description)
    try {
      const parsed = await api.upload<ParsedVacancy>('/api/workspace/vacancies/parse', form)
      applyParsed(parsed, Boolean(title.trim()))
      toast.success('Навыки извлечены из описания', { description: 'Лишние можно убрать крестиком' })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setExtracting(false)
    }
  }

  function composeText() {
    const parts = [title.trim(), description.trim()]
    if (mustHave.length) parts.push('Обязательные требования: ' + mustHave.map((i) => i.skill).join(', '))
    if (grade) parts.push('Грейд: ' + grade)
    return parts.filter(Boolean).join('\n\n')
  }

  async function save() {
    if (!title.trim()) return toast.error('Укажите название вакансии')
    if (mustHave.length === 0) return toast.error('Добавьте хотя бы один навык')
    setSaving(true)
    try {
      const created = await api.post<{
        id: number
        suggested_questions_count: number
        from_bank: number
        generated: number
      }>(
        '/api/workspace/vacancies',
        {
          title: title.trim(),
          grade,
          vacancy_text: composeText(),
          summary: description.trim().slice(0, 900),
          source_filename: sourceFile,
          must_have: mustHave,
          nice_to_have: [],
          responsibilities: [],
          stop_factors: stopFactors,
          tags: mustHave.map((item) => item.skill),
        },
      )
      toast.success(`Подобрано вопросов: ${created.suggested_questions_count}`, {
        description:
          created.generated > 0
            ? `${created.from_bank} из банка, ${created.generated} написала модель. Остался последний шаг — утвердить пул`
            : 'Остался последний шаг — утвердить пул',
      })
      navigate(`/vacancies/${created.id}/questions`)
    } catch (e) {
      toast.error((e as Error).message)
      setSaving(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Новая вакансия"
        description="Загрузите файл с описанием — система разберёт требования сама. Или заполните поля вручную."
      />
      <input
        ref={importRef}
        type="file"
        accept=".pdf,.txt,.md"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) void importFile(file)
          event.target.value = ''
        }}
      />

      <PageBody>
        {/* Импорт вынесен наверх отдельным блоком: это самый быстрый путь,
            и он не должен прятаться кнопкой в углу шапки. */}
        <button
          type="button"
          onClick={() => importRef.current?.click()}
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            const dropped = event.dataTransfer.files?.[0]
            if (dropped) void importFile(dropped)
          }}
          disabled={importing}
          className={cn(
            'mb-6 flex w-full items-center gap-4 rounded-xl border-2 border-dashed px-6 py-5 text-left transition-colors',
            dragging ? 'border-brand bg-brand-tint' : 'border-line-2 bg-card hover:border-brand hover:bg-brand-tint/40',
            importing && 'pointer-events-none opacity-70',
          )}
        >
          <span className="grid size-12 shrink-0 place-items-center rounded-xl bg-brand text-white">
            {importing ? (
              <Loader2 className="size-5 animate-spin" strokeWidth={2.2} />
            ) : (
              <FileUp className="size-5" strokeWidth={2} />
            )}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[15px] font-bold text-ink-700">
              {importing ? 'Разбираем файл…' : 'Загрузить описание вакансии файлом'}
            </span>
            <span className="mt-0.5 block text-[12.5px] text-ink-2">
              {importing
                ? 'Обычно занимает 15–20 секунд'
                : 'PDF или текст. Перетащите сюда или нажмите — название, требования и веса заполнятся сами'}
            </span>
          </span>
          {sourceFile && !importing && (
            <span className="shrink-0 rounded-md bg-ok-tint px-2 py-1 text-[11.5px] font-semibold text-ok-ink">
              {sourceFile}
            </span>
          )}
        </button>

        <div className="grid gap-5 lg:grid-cols-[1.35fr_1fr]">
          <div className="rounded-xl bg-card p-6 shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
            <div className="space-y-6">
              {/* 1. Название */}
              <div className="grid gap-4 sm:grid-cols-[1fr_auto]">
                <div>
                  <label htmlFor="vacTitle" className="mb-2 block text-[13px] font-semibold text-ink-700">
                    Название вакансии
                  </label>
                  <input
                    id="vacTitle"
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="Senior Frontend Engineer (React)"
                    className="w-full rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[15px] font-medium outline-none transition-colors placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
                  />
                </div>
                <div>
                  <span className="mb-2 block text-[13px] font-semibold text-ink-700">Грейд</span>
                  <div className="flex gap-1 rounded-[10px] bg-secondary p-1">
                    {GRADES.map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setGrade(value)}
                        className={cn(
                          'rounded-lg px-3 py-2 text-[12.5px] transition-all duration-200',
                          grade === value
                            ? 'bg-card font-semibold text-ink shadow-[0_1px_3px_rgba(0,0,0,0.1)]'
                            : 'font-medium text-ink-3 hover:text-ink-2',
                        )}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* 2. Описание */}
              <div>
                <label htmlFor="vacDesc" className="mb-2 block text-[13px] font-semibold text-ink-700">
                  Описание и требования
                </label>
                <textarea
                  id="vacDesc"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  rows={9}
                  placeholder="Чем предстоит заниматься, какой стек, какие требования обязательны…"
                  className="w-full resize-y rounded-lg border border-line-2 bg-card px-3.5 py-3 text-[13.5px] leading-relaxed outline-none transition-colors placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
                />
              </div>

              {/* 3. Навыки */}
              <div>
                <div className="mb-2.5 flex items-center justify-between gap-3">
                  <span className="text-[13px] font-semibold text-ink-700">Навыки</span>
                  <button
                    type="button"
                    onClick={() => void extractFromDescription()}
                    disabled={extracting || description.trim().length < 40}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-[12px] font-medium text-brand transition-colors hover:bg-brand-tint disabled:opacity-40"
                  >
                    {extracting ? (
                      <Loader2 className="size-3.5 animate-spin" strokeWidth={2.2} />
                    ) : (
                      <Wand2 className="size-3.5" strokeWidth={2} />
                    )}
                    {extracting ? 'Разбираем…' : 'Подобрать из описания'}
                  </button>
                </div>
                <SkillPicker
                  label=""
                  hint="вес задаёт, что считать несоответствием"
                  items={mustHave}
                  library={library}
                  accent
                  onChange={setMustHave}
                />
              </div>

              {stopFactors.length > 0 && (
                <section className="rounded-xl border border-bad/20 bg-bad-tint/60 p-4">
                  <h3 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-bad-ink">
                    <TriangleAlert className="size-3.5" strokeWidth={2.1} />
                    Противоречия в описании
                  </h3>
                  <ul className="space-y-1.5">
                    {stopFactors.map((factor, index) => (
                      <li key={index} className="flex items-start gap-2 text-[12.5px] leading-snug text-ink-2">
                        <span className="flex-1">— {factor}</span>
                        <button
                          type="button"
                          onClick={() => setStopFactors(stopFactors.filter((_, i) => i !== index))}
                          className="rounded p-0.5 text-ink-3 hover:text-bad"
                        >
                          <X className="size-3" strokeWidth={2.5} />
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>

            {/* Главное действие — в конце формы, во всю ширину */}
            <div className="mt-7 border-t border-line pt-5">
              <button
                type="button"
                onClick={() => void save()}
                disabled={saving || !title.trim() || mustHave.length === 0}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-6 py-3.5 text-[14px] font-bold text-white shadow-[0_4px_12px_rgba(0,87,255,0.22)] transition-all hover:bg-brand-press hover:shadow-[0_6px_16px_rgba(0,87,255,0.32)] disabled:opacity-40 disabled:shadow-none"
              >
                {saving ? <Loader2 className="size-4 animate-spin" strokeWidth={2.2} /> : null}
                {saving ? 'Подбираем вопросы…' : 'Создать вакансию и подобрать вопросы'}
                {!saving && <ArrowRight className="size-4" strokeWidth={2.2} />}
              </button>
              {saving && (
                <p className="mt-2.5 text-center text-[12px] text-ink-3">
                  Модель пишет вопросы под навыки, которых нет в банке&nbsp;— это занимает около минуты
                </p>
              )}
              {(!title.trim() || mustHave.length === 0) && (
                <p className="mt-2.5 text-center text-[12px] text-ink-3">
                  {!title.trim() ? 'Укажите название' : 'Добавьте хотя бы один навык'}
                  {' — без этого вопросы подобрать не под что'}
                </p>
              )}
            </div>
          </div>

          <aside className="lg:sticky lg:top-6 lg:self-start">
            <div className="rounded-xl bg-card p-5 shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
              <h3 className="flex items-center gap-2 text-[14px] font-bold text-ink-700">
                <Sparkles className="size-4 text-brand" strokeWidth={2} />
                Что проверит интервью
              </h3>
              <p className="mt-1.5 text-[12px] leading-snug text-ink-3">
                Что готово в банке, берём оттуда. Под остальное модель напишет вопросы при создании
                вакансии — чтобы ни одно требование не осталось непроверенным.
              </p>

              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-secondary p-3">
                  <p className="tnum text-[24px] leading-none font-bold text-ink-700">{covered.length}</p>
                  <p className="mt-1.5 text-[11.5px] leading-tight text-ink-2">из банка вопросов</p>
                </div>
                <div className={cn('rounded-lg p-3', uncovered.length > 0 ? 'bg-brand-tint' : 'bg-secondary')}>
                  <p
                    className={cn(
                      'tnum text-[24px] leading-none font-bold',
                      uncovered.length > 0 ? 'text-brand' : 'text-ink-3',
                    )}
                  >
                    {uncovered.length}
                  </p>
                  <p
                    className={cn(
                      'mt-1.5 text-[11.5px] leading-tight',
                      uncovered.length > 0 ? 'text-brand/80' : 'text-ink-3',
                    )}
                  >
                    достроит ИИ
                  </p>
                </div>
              </div>

              {uncovered.length > 0 && (
                <div className="mt-4">
                  <p className="mb-2 text-[11.5px] font-semibold uppercase tracking-[0.05em] text-brand">
                    Вопросы напишет модель
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {uncovered.map((item) => (
                      <span
                        key={item.skill}
                        className="rounded-md bg-brand-tint px-2 py-1 text-[11.5px] font-medium text-brand"
                      >
                        {item.skill}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {competencies.size > 0 && (
                <div className="mt-4 border-t border-line pt-4">
                  <p className="mb-2 text-[11.5px] font-semibold uppercase tracking-[0.05em] text-ink-3">
                    Компетенции интервью
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {[...competencies].map((competency) => (
                      <span
                        key={competency}
                        className="rounded-md bg-secondary px-2 py-1 text-[11.5px] font-medium text-ink-2"
                      >
                        {competency}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {mustHave.length === 0 && (
                <p className="mt-4 rounded-lg border border-dashed border-line-2 px-3 py-4 text-center text-[12px] leading-snug text-ink-3">
                  Добавьте навыки&nbsp;— и здесь появится, что интервью сможет проверить
                </p>
              )}
            </div>
          </aside>
        </div>
      </PageBody>
    </>
  )
}
