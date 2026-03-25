import { useState, useRef, useEffect, useCallback } from "react";
import { X, Plus, Check } from "lucide-react";
import { contrastTagText, TAG_COLORS, type Tag } from "../tags";

export function TagBadge({
  tag,
  onRemove,
  size = "default",
}: {
  tag: Tag;
  onRemove?: () => void;
  size?: "small" | "default";
}) {
  const fg = contrastTagText(tag.color);
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
          type="button"
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
  const [newColor, setNewColor] = useState<string>(TAG_COLORS[0]);
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

  const selectedIds = new Set(selectedTags.map((t) => t.tag_id));
  const filtered = allTags.filter((t) =>
    t.name.toLowerCase().includes(search.toLowerCase()),
  );
  const exactMatch = allTags.some(
    (t) => t.name.toLowerCase() === search.toLowerCase(),
  );
  const showCreate = search.trim() && !exactMatch;

  const handleCreate = useCallback(() => {
    if (!search.trim()) return;
    onCreate(search.trim(), newColor);
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
              key={t.tag_id}
              tag={t}
              onRemove={() => onToggle(t)}
            />
          ))
        ) : (
          <span className="tag-placeholder">Add tags...</span>
        )}
        <button
          className="tag-add-btn"
          type="button"
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
                key={tag.tag_id}
                className={`tag-dropdown-item${selectedIds.has(tag.tag_id) ? " selected" : ""}`}
                onClick={() => onToggle(tag)}
              >
                <span
                  className="tag-dot"
                  style={{ background: tag.color }}
                />
                <span className="tag-dropdown-item-name">{tag.name}</span>
                {selectedIds.has(tag.tag_id) && (
                  <Check size={14} className="tag-check" />
                )}
                {onDelete && (
                  <button
                    className="tag-delete-btn"
                    type="button"
                    title={`Delete "${tag.name}"`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpen(false);
                      setCreating(false);
                      setSearch("");
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
                type="button"
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
                <button className="tag-create-confirm" type="button" onClick={handleCreate}>
                  Create tag
                </button>
                <button
                  className="tag-create-cancel"
                  type="button"
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
