import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";

const ROWS_PER_PAGE_OPTIONS = [10, 20, 50, 100];

export function PaginationBar({
  rowsPerPage,
  setRowsPerPage,
  currentPage,
  setCurrentPage,
  totalPages,
}: {
  rowsPerPage: number;
  setRowsPerPage: (value: number) => void;
  currentPage: number;
  setCurrentPage: (value: number) => void;
  totalPages: number;
}) {
  return (
    <div className="pagination-bar">
      <div className="pagination-rows-per-page">
        <span>Rows per page</span>
        <select
          value={rowsPerPage}
          onChange={(event) => {
            setRowsPerPage(Number(event.target.value));
            setCurrentPage(1);
          }}
        >
          {ROWS_PER_PAGE_OPTIONS.map((value) => (
            <option key={value} value={value}>{value}</option>
          ))}
        </select>
      </div>
      <div className="pagination-nav">
        <span className="pagination-info">
          Page {currentPage} of {totalPages}
        </span>
        <button className="pagination-btn" disabled={currentPage <= 1} onClick={() => setCurrentPage(1)}>
          <ChevronsLeft size={16} />
        </button>
        <button className="pagination-btn" disabled={currentPage <= 1} onClick={() => setCurrentPage(currentPage - 1)}>
          <ChevronLeft size={16} />
        </button>
        <button className="pagination-btn" disabled={currentPage >= totalPages} onClick={() => setCurrentPage(currentPage + 1)}>
          <ChevronRight size={16} />
        </button>
        <button className="pagination-btn" disabled={currentPage >= totalPages} onClick={() => setCurrentPage(totalPages)}>
          <ChevronsRight size={16} />
        </button>
      </div>
    </div>
  );
}
