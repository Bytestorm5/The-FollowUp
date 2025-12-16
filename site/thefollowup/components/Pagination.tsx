import Link from "next/link";

export interface PaginationProps {
  basePath: string; // e.g. "/feed"
  page: number;
  pageSize: number;
  total: number;
  // Optional extra query params to preserve
  params?: Record<string, string | number | undefined>;
}

function buildHref(
  basePath: string,
  page: number,
  pageSize: number,
  params?: Record<string, string | number | undefined>
) {
  const u = new URL(basePath, "http://dummy.local");
  u.searchParams.set("page", String(page));
  u.searchParams.set("pageSize", String(pageSize));
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined) continue;
      u.searchParams.set(k, String(v));
    }
  }
  // Strip origin placeholder
  return u.pathname + (u.search ? u.search : "");
}

export default function Pagination({ basePath, page, pageSize, total, params }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const prevPage = page > 1 ? page - 1 : 1;
  const nextPage = page < totalPages ? page + 1 : totalPages;

  return (
    <div className="mt-10 flex items-center justify-between">
      <div className="text-sm text-foreground/70">
        Page {page} of {totalPages}
      </div>
      <div className="flex items-center gap-2">
        <Link
          href={buildHref(basePath, prevPage, pageSize, params)}
          className={`rounded-md border px-3 py-2 text-sm ${
            page <= 1 ? "pointer-events-none opacity-50" : "hover:bg-black/5"
          }`}
          aria-disabled={page <= 1}
        >
          Previous
        </Link>
        <Link
          href={buildHref(basePath, nextPage, pageSize, params)}
          className={`rounded-md border px-3 py-2 text-sm ${
            page >= totalPages ? "pointer-events-none opacity-50" : "hover:bg-black/5"
          }`}
          aria-disabled={page >= totalPages}
        >
          Next
        </Link>
      </div>
    </div>
  );
}
