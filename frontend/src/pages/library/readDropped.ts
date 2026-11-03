/** Every entry of a directory (the reader hands them over in batches until it returns none). */
async function readAll(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  const all: FileSystemEntry[] = []
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
      reader.readEntries(resolve, reject),
    )
    if (batch.length === 0) return all
    all.push(...batch)
  }
}

async function walk(entry: FileSystemEntry, out: File[]): Promise<void> {
  try {
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) =>
        (entry as FileSystemFileEntry).file(resolve, reject),
      )
      out.push(file)
    } else if (entry.isDirectory) {
      for (const child of await readAll((entry as FileSystemDirectoryEntry).createReader())) {
        await walk(child, out)
      }
    }
  } catch {
    // An unreadable file or folder is left out; the rest of the drop still counts.
  }
}

/**
 * The files of a drop, with the files inside dropped folders (all levels). Without the entry API
 * (`webkitGetAsEntry`) it is the plain `files` list, where a folder is not readable.
 *
 * The entries are taken before the first `await`: the browser empties the drop data once the
 * event handler has returned.
 */
export async function readDropped(data: DataTransfer): Promise<File[]> {
  const entries: FileSystemEntry[] = []
  for (const item of Array.from(data.items ?? [])) {
    if (item.kind !== 'file') continue
    const entry = item.webkitGetAsEntry?.()
    if (entry) entries.push(entry)
  }
  if (entries.length === 0) return Array.from(data.files ?? [])
  const files: File[] = []
  for (const entry of entries) await walk(entry, files)
  return files
}
