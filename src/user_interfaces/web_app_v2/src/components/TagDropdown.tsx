import { useState, useRef, useEffect, useCallback } from "react";
import { X, Plus, Check } from "lucide-react";
import type { Tag } from "../data/mock";
import { TAG_COLORS, mockTags } from "../data/mock";

// ── Tag badge (reusable) ──────────────────────────────

function contrastText(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.55 ? "#1a1a1a" : "#ffffff";
}

export function TagBadge({
  tag,
  onRemove,
  size = "default",
}: {
  tag: Tag;
  onRemove?: () => void;
  size?: "small" | "default";
}) {
  const fg = contrastText(tag.color);
  const small = size === "small";
  return (
    <span
      className="tag-pill"
      style={{
        background: tag.color,
        color: fg,
        fontSize: small ? 10 : 12,
        padding: small ? "0px 7px" : "2px 10px",
        borderRadius: small ? 8 : 10,
      }}
    >
      {tag.name}
      {onRemove && (
        <button
          className="tag-remove"
          style={{ color: fg }}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        >
          <X size={small ? 10 : 12} />
        </button>
      )}
    </span>
  );
}

// ── Color swatch picker (inline) ──────────────────────

function ColorPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (c: string) => void;
}) {
  return (
    <div className="tag-color-picker">
      {TAG_COLORS.map((c) => (
        <button
          key={c}
          className={`tag-color-swatch${c === value ? " selected" : ""}`}
          style={{ background: c }}
          onClick={() => onChange(c)}
        >
          {c === value && <Check size={10} color="#fff" />}
        </button>
      ))}
    </div>
  );
}

// ── Main dropdown ─────────────────────────────────────

export function TagDropdown({
  selectedTags,
  allTags,
  onToggle,
  onCreate,
  onDelete,
}: {
  selectedTags: Tag[];
  allTags: Tag[];
  onToggle: (tag: Tag) => void;
  onCreate: (name: string, color: string) => void;
  onDelete?: (tag: Tag) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [newColor, setNewColor] = useState(TAG_COLORS[0]);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as HTMLElement)) {
        setOpen(false);
        setCreating(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Focus input when opening
  useEffect(() => {
    if (open && inputRef.current) inputRef.current.focus();
  }, [open]);

  const selectedIds = new Set(selectedTags.map((t) => t.id));
  const filtered = allTags.filter((t) =>
    t.name.toLowerCase().includes(search.toLowerCase()),
  );
  const exactMatch = allTags.some(
    (t) => t.name.toLowerCase() === search.toLowerCase(),
  );
  const showCreate = search.trim() && !exactMatch;

  const handleCreate = useCallback(() => {
    if (!search.trim()) return;
    onCreate(search.trim().toLowerCase(), newColor);
    setSearch("");
    setCreating(false);
  }, [search, newColor, onCreate]);

  return (
    <div className="tag-dropdown" ref={dropdownRef}>
      {/* Trigger: show current tags + add button */}
      <div className="tag-dropdown-trigger" onClick={() => setOpen(!open)}>
        {selectedTags.length > 0 ? (
          selectedTags.map((t) => (
            <TagBadge
              key={t.id}
              tag={t}
              onRemove={() => onToggle(t)}
            />
          ))
        ) : (
          <span className="tag-placeholder">Add tags...</span>
        )}
        <button
          className="tag-add-btn"
          onClick={(e) => {
            e.stopPropagation();
            setOpen(!open);
          }}
        >
          <Plus size={13} />
        </button>
      </div>

      {/* Dropdown menu */}
      {open && (
        <div className="tag-dropdown-menu">
          <input
            ref={inputRef}
            className="tag-dropdown-search"
            placeholder="Filter or create tag..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && showCreate) {
                if (creating) handleCreate();
                else setCreating(true);
              }
              if (e.key === "Escape") {
                setOpen(false);
                setSearch("");
              }
            }}
          />

          <div className="tag-dropdown-list">
            {filtered.map((tag) => (
              <div
                key={tag.id}
                className={`tag-dropdown-item${selectedIds.has(tag.id) ? " selected" : ""}`}
                onClick={() => onToggle(tag)}
              >
                <span
                  className="tag-dot"
                  style={{ background: tag.color }}
                />
                <span className="tag-dropdown-item-name">{tag.name}</span>
                {selectedIds.has(tag.id) && (
                  <Check size={14} className="tag-check" />
                )}
                {onDelete && (
                  <button
                    className="tag-delete-btn"
                    title={`Delete "${tag.name}"`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(tag);
                    }}
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
            ))}

            {filtered.length === 0 && !showCreate && (
              <div className="tag-dropdown-empty">No tags found</div>
            )}

            {showCreate && !creating && (
              <button
                className="tag-dropdown-item tag-dropdown-create"
                onClick={() => setCreating(true)}
              >
                <Plus size={14} />
                <span>
                  Create <strong>"{search}"</strong>
                </span>
              </button>
            )}
          </div>

          {/* Inline create: color picker */}
          {creating && (
            <div className="tag-create-panel">
              <div className="tag-create-label">Pick a color for "{search}"</div>
              <ColorPicker value={newColor} onChange={setNewColor} />
              <div className="tag-create-actions">
                <button className="tag-create-confirm" onClick={handleCreate}>
                  Create tag
                </button>
                <button
                  className="tag-create-cancel"
                  onClick={() => {
                    setCreating(false);
                    setSearch("");
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
