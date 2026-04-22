import { ReactNode } from "react";

/**
 * Render a subset of markdown (**bold** only) as React nodes.
 *
 * The brief generator is prompted to emit only ``**bold**`` — nothing else.
 * Using a regex saves pulling in a full markdown lib just for this.
 */
export function renderInlineMarkdown(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const regex = /\*\*(.+?)\*\*/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(<b key={key++}>{match[1]}</b>);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts;
}
