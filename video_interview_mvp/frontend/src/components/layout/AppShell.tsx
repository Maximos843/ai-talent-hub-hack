import { NavLink, useLocation } from 'react-router-dom'
import { BriefcaseBusiness, ClipboardCheck, LibraryBig, LogOut, Users } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { CurrentUser } from '@/lib/types'
import { cn } from '@/lib/utils'

/** Имя продукта. Оно же звучит в приветствии кандидату, поэтому короткое
 *  и легко произносимое вслух. Менять здесь — поменяется везде. */
export const PRODUCT_NAME = 'Ника'

const HR_NAV = [
  { to: '/vacancies', label: 'Вакансии', icon: BriefcaseBusiness },
  { to: '/candidates', label: 'Кандидаты', icon: Users },
  { to: '/questions', label: 'Банк вопросов', icon: LibraryBig },
]

// У менеджера одна задача — вынести финальное решение по переданным ему
// кандидатам. Остальные разделы ему всё равно закрыты на бэкенде.
const MANAGER_NAV = [{ to: '/review', label: 'На решение', icon: ClipboardCheck }]

function initials(user: CurrentUser) {
  const source = (user.full_name || user.username).trim()
  return source
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

export function AppShell({ user, children }: { user: CurrentUser; children: React.ReactNode }) {
  const location = useLocation()
  const nav = user.role === 'hr' ? HR_NAV : MANAGER_NAV

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-line bg-card lg:flex">
        <div className="px-6 pb-8 pt-7">
          {/* Имя в самозакрывающемся теге: инструмент для инженеров, но с лицом —
              это же имя нейросеть называет кандидату в начале интервью. */}
          <div className="font-mono text-[19px] leading-none font-semibold tracking-[0.08em]">
            <span className="text-ink-3">&lt;</span>
            <span className="text-ink">{PRODUCT_NAME[0]}</span>
            <span className="text-brand">{PRODUCT_NAME.slice(1)}</span>
            <span className="text-brand">/</span>
            <span className="text-ink-3">&gt;</span>
          </div>
          <p className="mt-2 text-[11px] tracking-[0.02em] text-ink-3">
            ИИ-интервьюер · Napoleon&nbsp;IT
          </p>
        </div>

        <nav className="flex-1 pr-3">
          {nav.map(({ to, label, icon: Icon }) => {
            const active = location.pathname.startsWith(to)
            return (
              <NavLink
                key={to}
                to={to}
                className={cn(
                  'relative flex h-12 items-center gap-3 rounded-r-lg pl-6 pr-3 text-[14px] transition-colors duration-200',
                  active ? 'nav-bracket font-semibold text-brand' : 'text-ink-2 hover:bg-secondary hover:text-ink',
                )}
              >
                <Icon className={cn('size-[19px]', active ? 'text-brand' : 'text-ink-3')} strokeWidth={1.9} />
                {label}
              </NavLink>
            )
          })}
        </nav>

        <div className="border-t border-line p-3">
          <div className="flex items-center gap-3 rounded-lg px-2 py-2">
            <span className="grid size-9 shrink-0 place-items-center rounded-full bg-brand-tint text-[12px] font-bold text-brand">
              {initials(user)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-semibold leading-tight">
                {user.full_name || user.username}
              </span>
              <span className="block text-[11.5px] text-ink-3">
                {user.role === 'hr' ? 'Рекрутер' : 'Нанимающий менеджер'}
              </span>
            </span>
            <button
              type="button"
              title="Выйти"
              onClick={async () => {
                await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
                window.location.href = '/login'
              }}
              className="rounded-lg p-2 text-ink-3 transition-colors hover:bg-bad-tint hover:text-bad"
            >
              <LogOut className="size-4" strokeWidth={1.9} />
            </button>
          </div>
        </div>
      </aside>

      <main className="lg:pl-64">{children}</main>
    </div>
  )
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: React.ReactNode
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <header className="border-b border-line bg-card px-6 pb-7 pt-8 sm:px-9">
      <div className="mx-auto flex max-w-[1240px] flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="min-w-0">
          {eyebrow && <div className="mb-2.5">{eyebrow}</div>}
          <h1 className="text-[28px] leading-[1.15] font-bold tracking-[-0.025em] sm:text-[31px]">{title}</h1>
          {description && <p className="mt-2 max-w-2xl text-[13.5px] leading-relaxed text-ink-2">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </header>
  )
}

export function PageBody({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-[1240px] px-6 py-8 sm:px-9">{children}</div>
}

/** Плитка статистики по образцу Sofi: заголовок, крупное число в цвете
 *  метрики и иконка в скруглённом квадрате той же семьи цветов. */
export function StatTile({
  label,
  value,
  hint,
  icon: Icon,
  tone = 'ink',
}: {
  label: string
  value: React.ReactNode
  hint?: string
  icon?: LucideIcon
  tone?: 'ink' | 'brand' | 'ok' | 'bad' | 'warn' | 'violet'
}) {
  const tones = {
    ink: { text: 'text-ink', chip: 'bg-secondary text-ink-2' },
    brand: { text: 'text-brand', chip: 'bg-brand text-white' },
    ok: { text: 'text-ok', chip: 'bg-ok text-white' },
    bad: { text: 'text-bad', chip: 'bg-bad text-white' },
    warn: { text: 'text-warn-ink', chip: 'bg-warn text-white' },
    violet: { text: 'text-[#7518D1]', chip: 'bg-[#7518D1] text-white' },
  }[tone]

  return (
    <div className="flex items-start justify-between gap-3 rounded-xl bg-card p-4 shadow-[0_6px_24px_rgba(19,19,19,0.06)]">
      <div className="min-w-0">
        <p className="text-[13px] font-semibold leading-tight text-ink-700">{label}</p>
        <p className={cn('tnum mt-2 text-[30px] leading-none font-bold tracking-[-0.03em]', tones.text)}>{value}</p>
        {hint && <p className="mt-2 text-[11.5px] leading-snug text-ink-3">{hint}</p>}
      </div>
      {Icon && (
        <span className={cn('grid size-11 shrink-0 place-items-center rounded-xl', tones.chip)}>
          <Icon className="size-5" strokeWidth={1.9} />
        </span>
      )}
    </div>
  )
}
