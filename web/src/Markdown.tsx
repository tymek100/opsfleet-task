import { useRef, useState, type ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Copy, Download, Check } from "lucide-react";

export function csvValue(value: string): string {
  // Quoting alone does not prevent spreadsheets from evaluating formulas.
  const safe =
    /^[\s]*[=+\-@\t\r]/.test(value) &&
    !/^-?\d+(?:[.,]\d+)*%?$/.test(value.trim())
      ? `'${value}`
      : value;
  return `"${safe.replaceAll('"', '""')}"`;
}
export function toCsv(rows: string[][]) {
  return rows.map((row) => row.map(csvValue).join(",")).join("\r\n");
}

function Table({ children, ...props }: ComponentPropsWithoutRef<"table">) {
  const ref = useRef<HTMLTableElement>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const rows = () =>
    Array.from(ref.current?.rows || [], (row) =>
      Array.from(row.cells, (cell) => cell.textContent || ""),
    );
  async function copy() {
    try {
      await navigator.clipboard.writeText(toCsv(rows()));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Copy unavailable. Use Download CSV.");
    }
  }
  function download() {
    const url = URL.createObjectURL(
      new Blob([toCsv(rows())], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "retail-insight-table.csv";
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="table-card">
      <div className="table-toolbar">
        <span>Table</span>
        <div>
          <button type="button" onClick={copy} aria-label="Copy table as CSV">
            {copied ? <Check size={14} /> : <Copy size={14} />}
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            type="button"
            onClick={download}
            aria-label="Download table as CSV"
          >
            <Download size={14} />
            CSV
          </button>
        </div>
      </div>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Results table"
      >
        <table ref={ref} {...props}>
          {children}
        </table>
      </div>
      {error && <span role="status">{error}</span>}
    </div>
  );
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ node: _node, ...props }) => <Table {...props} />,
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer noopener" />
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
