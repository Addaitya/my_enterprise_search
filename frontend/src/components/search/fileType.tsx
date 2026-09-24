export function fileTypeEmoji(fileType: string | null): string {
  switch ((fileType ?? '').toLowerCase()) {
    case 'pdf':
      return '📄'
    case 'txt':
      return '📃'
    case 'csv':
      return '📊'
    default:
      return '📁'
  }
}

export function scorePillClass(score: number): string {
  if (score >= 0.9) return 'bg-emerald-50 text-emerald-600'
  if (score >= 0.7) return 'bg-amber-50 text-amber-600'
  return 'bg-gray-100 text-gray-500'
}
