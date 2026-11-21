import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ComponentSummary } from "../types";
import { ChevronLeftIcon, CloseIcon, SearchIcon } from "./Icons";

interface Props {
  equipmentModel: string;
  busy: boolean;
  onSelect: (partNumber: string) => void;
  onClose: () => void;
}

export function ManualSearch({ equipmentModel, busy, onSelect, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<ComponentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const result = await api.components(query.trim() || undefined, equipmentModel);
        if (!cancelled) {
          setItems(result);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "تعذر تحميل القطع.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, query ? 300 : 0);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, equipmentModel]);

  return (
    <div className="sheet-backdrop" onClick={onClose} role="presentation">
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="البحث اليدوي عن قطعة"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="sheet-head">
          <div>
            <h2>البحث اليدوي</h2>
            <p>{equipmentModel}</p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="إغلاق">
            <CloseIcon size={20} />
          </button>
        </header>

        <div className="search-field">
          <SearchIcon size={19} />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="اكتب اسم القطعة أو رقمها…"
            dir="auto"
            inputMode="search"
          />
        </div>

        <div className="search-results">
          {loading && <div className="search-state">جارٍ البحث…</div>}
          {!loading && error && <div className="search-state error">{error}</div>}
          {!loading && !error && items.length === 0 && (
            <div className="search-state">لا توجد نتائج مطابقة.</div>
          )}

          {items.map((item) => (
            <button
              key={item.part_number}
              className="search-item"
              onClick={() => onSelect(item.part_number)}
              disabled={busy}
            >
              <span className="search-item-main">
                <span className="search-part" dir="ltr">
                  {item.part_number}
                </span>
                <strong>{item.arabic_name}</strong>
                <small dir="ltr">{item.english_name}</small>
              </span>
              <span className="search-item-side">
                <span className="sample-tag">تجريبي</span>
                <ChevronLeftIcon size={20} />
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
