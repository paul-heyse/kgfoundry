-- Pool coverage heatmap ------------------------------------------------------
-- Requires `indexctl eval` followed by `indexctl export-idmap --duckdb ...`
-- to populate v_pool_coverage.
SELECT
    modules.repo_path,
    pool.source AS channel,
    COUNT(*) AS hits,
    AVG(pool.score) AS avg_score
FROM v_pool_coverage AS pool
LEFT JOIN modules ON modules.repo_path = pool.uri
GROUP BY modules.repo_path, pool.source
ORDER BY hits DESC, modules.repo_path, channel;

-- Channel contribution report -------------------------------------------------
SELECT
    pool.source AS channel,
    pool.lang,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT pool.chunk_id) AS unique_chunks,
    APPROX_COUNT_DISTINCT(pool.query_id) AS queries_touched
FROM v_pool_coverage AS pool
GROUP BY pool.source, pool.lang
ORDER BY total_rows DESC;
