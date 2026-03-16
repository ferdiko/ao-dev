export interface FSNode {
  id: string;
  name: string;
  type: "folder" | "file";
  parentId: string | null;
  content?: string; // markdown content for files
}

let _nextId = 1;
function id() {
  return `fs-${_nextId++}`;
}

function file(name: string, parentId: string, content: string): FSNode {
  return { id: id(), name, type: "file", parentId, content };
}

function folder(name: string, parentId: string | null): FSNode {
  return { id: id(), name, type: "folder", parentId };
}

export function createMockFilesystem(): FSNode[] {
  const root = { id: "root", name: "priors", type: "folder" as const, parentId: null };

  const sqlBest = folder("SQL Best Practices", "root");
  const errHandling = folder("Error Handling", "root");
  const schemaDesign = folder("Schema Design", "root");

  const nodes: FSNode[] = [
    root,
    sqlBest,
    errHandling,
    schemaDesign,

    file("query-optimization.md", sqlBest.id, `# Query Optimization

## Use Indexes Effectively

Always ensure that columns used in WHERE clauses, JOIN conditions, and ORDER BY statements have appropriate indexes.

### Example

\`\`\`sql
-- Slow: full table scan
SELECT * FROM orders WHERE customer_email = 'user@example.com';

-- Fast: indexed lookup
CREATE INDEX idx_orders_email ON orders(customer_email);
SELECT * FROM orders WHERE customer_email = 'user@example.com';
\`\`\`

## Avoid SELECT *

Only select the columns you actually need. This reduces I/O and memory usage.

## Use EXPLAIN ANALYZE

Always profile your queries before deploying to production. Look for sequential scans on large tables.
`),

    file("indexing-strategies.md", sqlBest.id, `# Indexing Strategies

## B-Tree Indexes (Default)

Best for equality and range queries. PostgreSQL creates B-tree indexes by default.

## Composite Indexes

When queries filter on multiple columns, a composite index can be more efficient than separate single-column indexes.

\`\`\`sql
CREATE INDEX idx_orders_status_date ON orders(status, created_at);
\`\`\`

**Column order matters**: place the most selective column first.

## Partial Indexes

Index only a subset of rows to save space and improve performance:

\`\`\`sql
CREATE INDEX idx_active_users ON users(email) WHERE active = true;
\`\`\`
`),

    file("join-patterns.md", sqlBest.id, `# Join Patterns

## Prefer Explicit JOIN Syntax

Always use explicit JOIN syntax instead of comma-separated tables in FROM clause.

## Know Your Join Types

- **INNER JOIN**: Only matching rows from both tables
- **LEFT JOIN**: All rows from left table, matching from right
- **CROSS JOIN**: Cartesian product (rarely what you want)

## Avoid N+1 Queries

When fetching related data, use JOINs or subqueries instead of looping:

\`\`\`sql
-- Bad: N+1 pattern (in application code)
-- Good: single query with JOIN
SELECT o.*, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.status = 'pending';
\`\`\`
`),

    file("common-sql-errors.md", errHandling.id, `# Common SQL Errors

## NULL Comparisons

Never use \`= NULL\` or \`!= NULL\`. Use \`IS NULL\` and \`IS NOT NULL\` instead.

\`\`\`sql
-- Wrong
SELECT * FROM users WHERE deleted_at = NULL;

-- Correct
SELECT * FROM users WHERE deleted_at IS NULL;
\`\`\`

## Type Mismatches

Ensure consistent types in comparisons. Implicit casts can prevent index usage.

## Ambiguous Column References

Always qualify column names with table aliases in JOINs to avoid ambiguity errors.
`),

    file("debugging-tips.md", errHandling.id, `# Debugging Tips

## Check the Query Plan

\`\`\`sql
EXPLAIN ANALYZE SELECT * FROM orders WHERE status = 'pending';
\`\`\`

Look for:
- **Seq Scan** on large tables (missing index)
- **Nested Loop** with high row counts (consider hash join)
- **Sort** operations (add index for ORDER BY)

## Use Transaction Isolation

When debugging data issues, wrap investigations in a transaction:

\`\`\`sql
BEGIN;
-- your investigative queries here
ROLLBACK; -- never accidentally modify data
\`\`\`

## Log Slow Queries

Configure \`log_min_duration_statement\` in PostgreSQL to capture slow queries automatically.
`),

    file("normalization-rules.md", schemaDesign.id, `# Normalization Rules

## First Normal Form (1NF)

- Each column contains atomic (indivisible) values
- No repeating groups or arrays in a single column

## Second Normal Form (2NF)

- Must be in 1NF
- Every non-key column depends on the entire primary key

## Third Normal Form (3NF)

- Must be in 2NF
- No transitive dependencies (non-key columns depending on other non-key columns)

## When to Denormalize

Denormalization is acceptable when:
- Read performance is critical and writes are infrequent
- Reporting queries join many tables
- Caching computed values avoids expensive aggregations
`),

    file("general-guidelines.md", "root", `# General Guidelines

## Writing Good Priors

Each prior should be:
1. **Specific** — Address a single, well-defined topic
2. **Actionable** — Provide clear guidance, not just observations
3. **Evidence-based** — Include examples from actual failure cases
4. **Concise** — Keep to essential information only

## Organizing Priors

Group related priors into folders by domain area. Use descriptive folder names that make the taxonomy self-evident.

## Review Process

Priors should be reviewed periodically to ensure they remain relevant as the system evolves. Remove or update priors that no longer apply.
`),
  ];

  return nodes;
}
