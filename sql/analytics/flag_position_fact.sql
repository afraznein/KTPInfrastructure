-- Static flag coordinates for the selected match's server and map.
SELECT DISTINCT
    fp.flag_index,
    fp.flag_name,
    fp.origin_x,
    fp.origin_y
FROM ktp_flag_positions fp
JOIN ktp_matches m
  ON m.server_id = fp.server_id AND m.map_name = fp.map_name
WHERE m.match_id = {{MATCH_ID}}
ORDER BY fp.flag_index;
