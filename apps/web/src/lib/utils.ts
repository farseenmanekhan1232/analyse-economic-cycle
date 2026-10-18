import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Display dates as "09 Apr 2027". Accepts ISO date or datetime strings. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—"
  const dayPart = value.slice(0, 10)
  const d = new Date(`${dayPart}T12:00:00`)
  if (Number.isNaN(d.getTime())) return value
  const dd = String(d.getDate()).padStart(2, "0")
  const mmm = d.toLocaleString("en-GB", { month: "short" })
  const yyyy = d.getFullYear()
  return `${dd} ${mmm} ${yyyy}`
}

/** Display datetimes as "09 Apr 2027, 19:45". */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—"
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return formatDate(value)
  const date = formatDate(value)
  const hh = String(d.getHours()).padStart(2, "0")
  const mm = String(d.getMinutes()).padStart(2, "0")
  return `${date}, ${hh}:${mm}`
}
