export interface FailureAnalysis {
  id: string;
  analysisId: string;
  runId: string;
  name: string;
  input: string;
  output: string;
  version: string;
  startTime: string;
  status: "running" | "completed";
  report: string | null;
}

const SAMPLE_REPORT = `## Failure Analysis Report

### Summary

The SQL query generated for this request fails because the agent incorrectly assumes a \`revenue\` column exists directly on the \`sales\` table, when in fact revenue must be computed as \`quantity * unit_price\`.

### Root Cause

The agent's schema retrieval step correctly identified the \`sales\` table but did not surface individual column definitions. As a result, the LLM hallucinated a \`revenue\` column that does not exist. The generated query:

\`\`\`sql
SELECT quarter, SUM(revenue) FROM sales GROUP BY quarter
\`\`\`

…fails with: \`column "revenue" does not exist\`.

### Expected Behavior

The agent should have generated:

\`\`\`sql
SELECT quarter, SUM(quantity * unit_price) AS revenue
FROM sales
GROUP BY quarter
\`\`\`

### Suggested Fix

1. Ensure the schema retrieval step returns column-level detail, not just table names.
2. Add a prior instructing the agent to verify column existence before generating queries.
3. Consider adding a SQL validation step before returning the final query to the user.

### Affected Components

- **Schema Retrieval Node** (node 1): Missing column-level detail
- **SQL Generation Node** (node 3): Hallucinated column name based on incomplete schema
`;

const SAMPLE_REPORT_2 = `## Failure Analysis Report

### Summary

The query to find the top 10 products by return rate fails because the agent uses \`COUNT(r.id) * 100.0 / COUNT(o.id)\` without properly joining the \`returns\` table with a LEFT JOIN, resulting in inflated return rates.

### Root Cause

The agent used an INNER JOIN between \`orders\` and \`returns\`, which excludes orders that were never returned. This makes the denominator (total orders) equal to the numerator (returned orders), producing a 100% return rate for every product.

### Expected Behavior

A LEFT JOIN should be used so that orders without returns are included in the count, giving an accurate return rate percentage.

### Suggested Fix

1. Change the JOIN type from INNER JOIN to LEFT JOIN on the returns table.
2. Add a prior about using LEFT JOIN when computing ratios that include zero-count cases.
`;

export const mockFailureAnalyses: FailureAnalysis[] = [
  {
    id: "fa-1",
    analysisId: "a3f8c1e2",
    runId: "2fad5b74",
    name: "Run 47 – Revenue Query",
    input: "Show the total revenue by quarter for 2025 from the sales ...",
    output: "SELECT quarter, SUM(revenue) FROM sales WHERE year =...",
    version: "9c4d7f2a",
    startTime: "2026-03-13 09:14:32",
    status: "completed",
    report: SAMPLE_REPORT,
  },
  {
    id: "fa-2",
    analysisId: "b7d4e9a1",
    runId: "3619e3ae",
    name: "Run 44 – Return Rate",
    input: "Find the top 10 products by return rate with category brea...",
    output: "SELECT p.name, COUNT(r.id) * 100.0 / COUNT(o.id) AS ret...",
    version: "ae21b4f7",
    startTime: "2026-03-13 09:15:01",
    status: "completed",
    report: SAMPLE_REPORT_2,
  },
  {
    id: "fa-3",
    analysisId: "c2e6f0b5",
    runId: "c7af2d35",
    name: "Run 46 – Customer Purchases",
    input: "List all customers who made purchases above $500 in Ma...",
    output: "",
    version: "1b8e3c6d",
    startTime: "2026-03-13 09:16:45",
    status: "running",
    report: null,
  },
];
