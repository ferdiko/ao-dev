SELECT team, ROUND(AVG(score), 2) AS avg_score
FROM run_metrics
GROUP BY team
ORDER BY avg_score DESC;
