import { useMemo, useState } from "react";

type Candidate = {
  id: string;
  sender_name: string;
  sender_email: string;
  subject: string;
  date?: string;
  account: string;
  folder: string;
  email_count: number;
  unsubscribe_url: string;
  mailto?: string | null;
  source: "header" | "body";
  one_click: boolean;
};

type Stats = {
  accounts_scanned?: number;
  folders_scanned?: number;
  emails_scanned?: number;
  emails_with_unsubscribe?: number;
};

// Rendered inside a shadow DOM by LoadExternalComponent, so styles are inline.
const s = {
  card: { fontFamily: "system-ui, sans-serif", border: "1px solid #e4e4e7", borderRadius: 12, padding: 16, background: "#fff", color: "#18181b", maxWidth: 960 },
  header: { display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" as const, marginBottom: 12 },
  title: { fontSize: 16, fontWeight: 600, margin: 0 },
  stats: { fontSize: 12, color: "#71717a" },
  search: { width: "100%", boxSizing: "border-box" as const, padding: "8px 10px", border: "1px solid #d4d4d8", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  list: { listStyle: "none", margin: 0, padding: 0, maxHeight: 520, overflowY: "auto" as const },
  row: { display: "flex", alignItems: "center", gap: 12, padding: "10px 4px", borderTop: "1px solid #f4f4f5" },
  info: { flex: 1, minWidth: 0 },
  sender: { fontSize: 14, fontWeight: 600, whiteSpace: "nowrap" as const, overflow: "hidden", textOverflow: "ellipsis" },
  meta: { fontSize: 12, color: "#71717a", whiteSpace: "nowrap" as const, overflow: "hidden", textOverflow: "ellipsis" },
  badge: { fontSize: 11, padding: "1px 6px", borderRadius: 999, background: "#f4f4f5", color: "#52525b", marginLeft: 6, fontWeight: 500 },
  button: { flexShrink: 0, padding: "7px 12px", borderRadius: 8, fontSize: 13, fontWeight: 600, textDecoration: "none", background: "#dc2626", color: "#fff", border: "none", cursor: "pointer" },
  done: { flexShrink: 0, padding: "7px 12px", borderRadius: 8, fontSize: 13, fontWeight: 600, textDecoration: "none", background: "#e4e4e7", color: "#3f3f46" },
};

function UnsubscribeList({ candidates = [], stats = {} }: { candidates: Candidate[]; stats: Stats }) {
  const [query, setQuery] = useState("");
  const [opened, setOpened] = useState<Record<string, boolean>>({});

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return candidates;
    return candidates.filter((c) =>
      [c.sender_name, c.sender_email, c.subject, c.account].some((v) => v?.toLowerCase().includes(q)),
    );
  }, [candidates, query]);

  const openedCount = Object.keys(opened).length;

  return (
    <div style={s.card}>
      <div style={s.header}>
        <h3 style={s.title}>📭 {candidates.length} senders with an "Unsubscribe" link</h3>
        <span style={s.stats}>
          {stats.accounts_scanned ?? "?"} accounts · {stats.folders_scanned ?? "?"} folders · {stats.emails_scanned ?? "?"} emails
          scanned · {openedCount} opened
        </span>
      </div>
      <input style={s.search} placeholder="Filter by sender, subject or account…" value={query} onChange={(e) => setQuery(e.target.value)} />
      <ul style={s.list}>
        {visible.map((c) => (
          <li key={c.id} style={s.row}>
            <div style={s.info}>
              <div style={s.sender} title={c.sender_email}>
                {c.sender_name || c.sender_email}
                <span style={s.badge}>{c.email_count} emails</span>
                {c.one_click && <span style={s.badge}>one-click</span>}
                {c.source === "body" && <span style={s.badge}>link in body</span>}
              </div>
              <div style={s.meta} title={c.subject}>
                {c.subject}
              </div>
              <div style={s.meta}>
                {c.sender_email} · {c.account} · {c.date ? new Date(c.date).toLocaleDateString() : ""}
              </div>
            </div>
            <a
              href={c.unsubscribe_url}
              target="_blank"
              rel="noopener noreferrer"
              style={opened[c.id] ? s.done : s.button}
              title={c.unsubscribe_url}
              onClick={() => setOpened((prev) => ({ ...prev, [c.id]: true }))}
            >
              {opened[c.id] ? "✓ Opened" : c.unsubscribe_url.startsWith("mailto:") ? "Unsubscribe by email ↗" : "Unsubscribe ↗"}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default {
  unsubscribe_list: UnsubscribeList,
};
