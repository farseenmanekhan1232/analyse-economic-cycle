import Link from 'next/link'
import { cn } from '@/lib/utils'

const links = [
  { href: '/', label: 'Today' },
  { href: '/holdings', label: 'Portfolio' },
  { href: '/swing', label: 'Research' },
]

export function AppNav({ active }: { active?: string }) {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/90 backdrop-blur">
      <a
        href="#main-content"
        className="sr-only rounded-md bg-background px-4 py-2 text-sm font-medium focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:ring-2 focus:ring-ring"
      >
        Skip to content
      </a>
      <div className="mx-auto flex h-14 max-w-5xl items-center gap-3 px-4 sm:gap-5">
        <Link
          href="/"
          className="shrink-0 text-base font-semibold tracking-[-0.02em] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Pulse
        </Link>
        <nav aria-label="Primary" className="ml-auto flex items-center gap-0.5 sm:gap-1">
          {links.map((link) => {
            const current = active === link.href
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={current ? 'page' : undefined}
                className={cn(
                  'flex h-11 items-center border-b-2 px-2 text-[13px] transition-colors sm:px-3 sm:text-sm',
                  current
                    ? 'border-foreground font-medium text-foreground'
                    : 'border-transparent text-muted-foreground hover:text-foreground',
                )}
              >
                {link.label}
              </Link>
            )
          })}
        </nav>
        <Link
          href="/sync"
          aria-current={active === '/sync' ? 'page' : undefined}
          className={cn(
            'flex h-11 shrink-0 items-center border-l pl-3 text-xs transition-colors sm:pl-4',
            active === '/sync'
              ? 'border-border font-medium text-foreground'
              : 'border-border text-muted-foreground hover:text-foreground',
          )}
        >
          Data
        </Link>
      </div>
    </header>
  )
}
