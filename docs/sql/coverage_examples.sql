-- Pool coverage heatmap ------------------------------------------------------
-- Requires `indexctl eval` followed by `indexctl export-idmap --duckdb ...`
-- to populate v_pool_coverage.
SELECT
    modules.repo_path,
    pool.channel AS channel,
    COUNT(*) AS hits,
    AVG(pool.score) AS avg_score
FROM v_pool_coverage AS pool
LEFT JOIN modules ON modules.repo_path = pool.uri
GROUP BY modules.repo_path, pool.channel
ORDER BY hits DESC, modules.repo_path, channel;

-- Channel contribution report -------------------------------------------------
SELECT
    pool.channel AS channel,
    pool.lang,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT pool.chunk_id) AS unique_chunks,
    APPROX_COUNT_DISTINCT(pool.query_id) AS queries_touched
FROM v_pool_coverage AS pool
GROUP BY pool.channel, pool.lang
ORDER BY total_rows DESC;

-- Module × symbol coverage ---------------------------------------------------
WITH exploded AS (
    SELECT
        pool.query_id,
        pool.channel,
        pool.chunk_id,
        modules.repo_path,
        UNNEST(pool.symbol_hits) AS symbol_hit
    FROM v_pool_coverage AS pool
    LEFT JOIN modules ON modules.repo_path = pool.uri
)
SELECT
    repo_path,
    channel,
    COUNT(DISTINCT symbol_hit) AS distinct_symbols
FROM exploded
WHERE symbol_hit IS NOT NULL
GROUP BY repo_path, channel
ORDER BY distinct_symbols DESC;
