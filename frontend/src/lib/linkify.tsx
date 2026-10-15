import type { ReactNode } from 'react'
import { strings } from '../strings'

/** http(s) URLs only. A closing parenthesis ends the URL, so "(https://x.org/a)" keeps its ")". */
const URL_PATTERN = /https?:\/\/[^\s)]+/gi
/** Sentence punctuation that is not part of the URL when it comes last. */
const TRAILING_PUNCTUATION = /[.,]+$/

/**
 * Splits `text` into plain strings and links to the http(s) URLs in it, so a credit line shows
 * clickable links. Nothing else is ever turned into a link (no `javascript:` and the like).
 */
export function linkify(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(URL_PATTERN)) {
    const url = match[0].replace(TRAILING_PUNCTUATION, '')
    const start = match.index
    if (start > last) nodes.push(text.slice(last, start))
    nodes.push(
      <a key={start} href={url} target="_blank" rel="noreferrer noopener">
        {url}
        <span className="sr-only"> {strings.common.opensInNewTab}</span>
      </a>,
    )
    last = start + url.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}
