type ButtonProps = {
  children: string
  onClick?: () => void
}

export function Button({ children, onClick }: ButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-md bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500"
    >
      {children}
    </button>
  )
}
