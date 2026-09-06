import { useRef, useState } from 'react'
import { FileUp, Loader2, Mail, Send, X } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { api } from '@/lib/api'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

export function AddCandidateDialog({
  vacancyId,
  open,
  onOpenChange,
  onCreated,
}: {
  vacancyId: number
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [telegram, setTelegram] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function reset() {
    setName('')
    setEmail('')
    setTelegram('')
    setFile(null)
    setBusy(false)
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    const form = new FormData()
    form.append('candidate_name', name.trim())
    form.append('email', email.trim())
    form.append('telegram_username', telegram.trim())
    if (file) form.append('file', file)
    try {
      await api.upload(`/api/workspace/vacancies/${vacancyId}/candidates`, form)
      toast.success(`${name.trim()} добавлен`, {
        description: file ? 'Резюме разобрано, соответствие вакансии посчитано' : 'Ссылку отправите отдельным действием',
      })
      reset()
      onOpenChange(false)
      onCreated()
    } catch (e) {
      toast.error((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(value) => (busy ? null : (onOpenChange(value), value || reset()))}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-[21px] font-semibold">Новый кандидат</DialogTitle>
          <DialogDescription className="text-[13px] leading-relaxed text-ink-2">
            Кандидат попадёт в колонку «Новые». Ссылка на интервью отправляется отдельным действием&nbsp;— так
            видно, кому ещё не написали.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="mt-2 space-y-5">
          <div>
            <label htmlFor="candidateName" className="eyebrow mb-2 block text-ink-2">
              Имя кандидата
            </label>
            <input
              id="candidateName"
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoFocus
              placeholder="Алексей Петров"
              className="w-full rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[14px] outline-none transition-colors placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="candidateEmail" className="eyebrow mb-2 flex items-center gap-1.5 text-ink-2">
                <Mail className="size-3" strokeWidth={2} />
                Почта
              </label>
              <input
                id="candidateEmail"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="petr@example.com"
                className="w-full rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[14px] outline-none transition-colors placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
              />
            </div>
            <div>
              <label htmlFor="candidateTg" className="eyebrow mb-2 flex items-center gap-1.5 text-ink-2">
                <Send className="size-3" strokeWidth={2} />
                Telegram
              </label>
              <input
                id="candidateTg"
                value={telegram}
                onChange={(event) => setTelegram(event.target.value)}
                placeholder="@petr_dev"
                className="w-full rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[14px] outline-none transition-colors placeholder:text-ink-3/70 focus:border-brand focus:ring-2 focus:ring-brand/15"
              />
            </div>
          </div>

          <div>
            <span className="eyebrow mb-2 block text-ink-2">
              Резюме <span className="normal-case tracking-normal text-ink-3">— необязательно</span>
            </span>

            {file ? (
              <div className="flex items-center gap-3 rounded-lg border border-line bg-secondary/60 px-3.5 py-3">
                <FileUp className="size-4 shrink-0 text-brand" strokeWidth={1.75} />
                <span className="min-w-0 flex-1 truncate text-[13px]">{file.name}</span>
                <span className="tnum shrink-0 text-[11px] text-ink-3">{Math.round(file.size / 1024)} КБ</span>
                <button
                  type="button"
                  onClick={() => setFile(null)}
                  className="shrink-0 rounded p-1 text-ink-3 transition-colors hover:text-bad"
                >
                  <X className="size-3.5" strokeWidth={2} />
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragging(false)
                  const dropped = event.dataTransfer.files?.[0]
                  if (dropped) setFile(dropped)
                }}
                className={cn(
                  'flex w-full flex-col items-center gap-1.5 rounded-lg border border-dashed px-4 py-7 transition-colors',
                  dragging ? 'border-brand bg-brand-tint' : 'border-line-2 hover:border-brand/60 hover:bg-secondary/50',
                )}
              >
                <FileUp className="size-5 text-ink-3" strokeWidth={1.5} />
                <span className="text-[13px] font-medium">Перетащите PDF или выберите файл</span>
                <span className="text-[11.5px] text-ink-3">
                  Разберём и посчитаем соответствие обязательным требованиям
                </span>
              </button>
            )}
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.txt,.md"
              hidden
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>

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
              type="submit"
              disabled={busy || !name.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2.5 text-[13px] font-semibold text-white transition-colors hover:bg-brand-press disabled:opacity-40"
            >
              {busy && <Loader2 className="size-3.5 animate-spin" strokeWidth={2.5} />}
              {busy ? (file ? 'Разбираем резюме…' : 'Добавляем…') : 'Добавить'}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
