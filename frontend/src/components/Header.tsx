import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Moon, Sun } from 'lucide-react'

import { api } from '@/lib/api'
import { useTheme } from '@/lib/useTheme'
import uniguideLogo from '@/assets/uniguide_logo.png'

export function Header() {
  const { data, isError } = useQuery({ queryKey: ['health'], queryFn: api.health })
  const { theme, toggleTheme } = useTheme()

  return (
    <header className="border-b border-border bg-primary text-primary-foreground">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <Link to="/" className="flex items-center">
          <img src={uniguideLogo} alt="UniGuide" className="h-8 w-auto" />
        </Link>
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5 text-xs text-primary-foreground/70">
            <span
              className={`size-1.5 rounded-full ${data?.status === 'ok' ? 'bg-success' : isError ? 'bg-destructive' : 'bg-muted'}`}
            />
            {data?.status === 'ok' ? 'API connected' : isError ? 'API unreachable' : 'Connecting…'}
          </span>
          <button
            type="button"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            className="rounded-md p-1.5 text-primary-foreground/80 hover:bg-primary-foreground/10 hover:text-primary-foreground"
          >
            {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
        </div>
      </div>
    </header>
  )
}
