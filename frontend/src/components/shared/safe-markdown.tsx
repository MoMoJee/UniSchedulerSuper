export function SafeMarkdown({ content }: { content: string }) {
  // FR-2 只提供安全文本占位；FR-5 引入受限 Markdown renderer 前不解析任何 HTML。
  return <p className="whitespace-pre-wrap break-words">{content}</p>;
}
