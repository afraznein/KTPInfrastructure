-- Per-half availability of the producer-observed death-group links
-- (docs/TELEMETRY_CAUSAL_LINKS_V1.md, columns from KTPHLStatsX migrate_054).
-- Counts only. A link resolves on the TYPED key -- same server, match, half,
-- referent stream and producer_sequence -- because sequences are per event type
-- and restart each half, so a bare integer names nothing. NULL is an honest
-- no-parent and is never counted as an unresolved link.
-- Every BINARY match-id test is paired with a plain equality so the index is
-- usable: hlstats_Events_Frags is MyISAM, and a scan here holds a table read
-- lock that stalls the stats daemon's frag UPDATEs until it finishes.
-- Read only. {{MATCH_ID}} is replaced with one safely quoted SQL literal by
-- scripts/match_analytics.py.
SELECT
    ae.half AS half,
    'assist' AS stream,
    COUNT(*) AS events,
    SUM(ae.causal_parent_life_sequence IS NOT NULL) AS life_linked,
    SUM(ae.causal_parent_life_sequence IS NOT NULL AND EXISTS (
        SELECT 1 FROM ktp_life_events le
        WHERE le.server_id = ae.server_id
          AND le.match_id = ae.match_id
          AND BINARY le.match_id = BINARY ae.match_id
          AND le.half = ae.half
          AND le.boundary_kind = 'end'
          AND le.producer_sequence = ae.causal_parent_life_sequence
    )) AS life_resolved,
    SUM(ae.causal_parent_frag_sequence IS NOT NULL) AS frag_linked,
    SUM(ae.causal_parent_frag_sequence IS NOT NULL AND EXISTS (
        SELECT 1 FROM hlstats_Events_Frags pf
        WHERE pf.serverId = ae.server_id
          AND pf.producer_match_id = ae.match_id
          AND BINARY pf.producer_match_id = BINARY ae.match_id
          AND pf.producer_half = ae.half
          AND pf.producer_sequence = ae.causal_parent_frag_sequence
    )) AS frag_resolved
FROM ktp_assist_events ae
WHERE ae.match_id = {{MATCH_ID}}
  AND BINARY ae.match_id = BINARY {{MATCH_ID}}
  AND ae.half > 0
GROUP BY ae.half
UNION ALL
SELECT
    f.producer_half AS half,
    'frag' AS stream,
    COUNT(*) AS events,
    SUM(f.causal_parent_life_sequence IS NOT NULL) AS life_linked,
    SUM(f.causal_parent_life_sequence IS NOT NULL AND EXISTS (
        SELECT 1 FROM ktp_life_events le
        WHERE le.server_id = f.serverId
          AND le.match_id = f.producer_match_id
          AND BINARY le.match_id = BINARY f.producer_match_id
          AND le.half = f.producer_half
          AND le.boundary_kind = 'end'
          AND le.producer_sequence = f.causal_parent_life_sequence
    )) AS life_resolved,
    NULL AS frag_linked,
    NULL AS frag_resolved
FROM hlstats_Events_Frags f
WHERE f.producer_match_id = {{MATCH_ID}}
  AND BINARY f.producer_match_id = BINARY {{MATCH_ID}}
  AND f.producer_half > 0
GROUP BY f.producer_half
ORDER BY half, stream;
