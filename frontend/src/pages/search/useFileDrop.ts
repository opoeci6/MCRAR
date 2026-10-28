import { useEffect, useRef, useState } from 'react'

/** Whether a drag carries files (and not, say, selected text or a link). */
function hasFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files')
}

/**
 * Lets the whole page take a dropped file: returns whether a file is being dragged over it, for
 * an overlay, and calls `onFile` with the first file dropped. Other drags are left alone. The
 * browser's own "open the file" is always stopped for files; while `disabled` nothing else
 * happens (no overlay, no call).
 */
export function useFileDrop(onFile: (file: File) => void, disabled: boolean): boolean {
  const [dragging, setDragging] = useState(false)
  const latest = useRef({ onFile, disabled })
  useEffect(() => {
    latest.current = { onFile, disabled }
  })

  useEffect(() => {
    // Entering a child fires `dragenter` for it before `dragleave` for the parent, so the
    // overlay stays while the count is above zero.
    let depth = 0
    const end = () => {
      depth = 0
      setDragging(false)
    }
    const enter = (event: DragEvent) => {
      if (!hasFiles(event)) return
      event.preventDefault()
      if (latest.current.disabled) return
      depth += 1
      setDragging(true)
    }
    const over = (event: DragEvent) => {
      if (!hasFiles(event)) return
      event.preventDefault()
      if (event.dataTransfer) event.dataTransfer.dropEffect = latest.current.disabled ? 'none' : 'copy'
    }
    const leave = (event: DragEvent) => {
      if (!hasFiles(event) || depth === 0) return
      depth -= 1
      if (depth === 0) setDragging(false)
    }
    const drop = (event: DragEvent) => {
      if (!hasFiles(event)) return
      event.preventDefault()
      end()
      const file = event.dataTransfer?.files?.[0]
      if (file && !latest.current.disabled) latest.current.onFile(file)
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragover', over)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
    }
  }, [])

  return dragging && !disabled
}
