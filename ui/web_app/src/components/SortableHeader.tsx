import { ChevronUp, ChevronDown } from "lucide-react";
import type { SortState } from "../hooks/useStoredSortState";

export function SortableHeader({
  label,
  sortKey,
  sort,
  onSort,
  className: extraClass,
}: {
  label: string;
  sortKey: string;
  sort: SortState;
  onSort: (key: string) => void;
  className?: string;
}) {
  const active = sort?.key === sortKey;

  return (
    <th
      className={`sortable-th${active ? " sorted" : ""}${extraClass ? ` ${extraClass}` : ""}`}
      onClick={() => onSort(sortKey)}
    >
      <span className="th-sort-content">
        {label}
        {active && (
          sort.direction === "asc"
            ? <ChevronUp size={12} className="sort-icon" />
            : <ChevronDown size={12} className="sort-icon" />
        )}
      </span>
    </th>
  );
}
