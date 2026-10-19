import type { LlmUse, ParsedQuery } from '../../api/types'
import { searchStrings } from './strings'
import styles from './SearchPage.module.css'

const r = searchStrings.reading

export interface QueryReadingProps {
  parsed: ParsedQuery
  /** What the LLM did with the query; null or absent when it was off or not ready. */
  llm?: LlmUse | null
}

/** "How your search was read": by rules or by the LLM, and the parsed query as the backend saw it. */
export function QueryReading({ parsed, llm }: QueryReadingProps) {
  const byLlm = parsed.source === 'llm'
  const verdict = [byLlm ? r.byLlm(llm?.model ?? '') : r.byRules, byLlm && llm?.cached ? r.cached : null]
    .filter(Boolean)
    .join(' · ')
  const notes = parsed.notes ?? []
  const terms = parsed.search_terms ?? []
  return (
    <details className={styles.reading}>
      <summary>
        {r.summary}: {verdict}
      </summary>
      <div className={styles.readingBody}>
        {llm && !llm.used && llm.error ? <p>{r.llmFailed(llm.error)}</p> : null}
        {terms.length > 0 ? <p>{r.searchTerms(terms.join(', '))}</p> : null}
        {notes.length > 0 ? (
          <div>
            <strong>{r.notes}</strong>
            <ul>
              {notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <pre className={styles.parsedJson} aria-label={r.parsed} tabIndex={0}>
          {JSON.stringify(parsed, null, 2)}
        </pre>
      </div>
    </details>
  )
}
