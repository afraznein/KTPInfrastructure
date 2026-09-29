SELECT
  server_id,
  match_id,
  half,
  attempt_id,
  event_kind,
  flag_index,
  flag_name,
  capturing_team,
  owner_before,
  allies_in_zone,
  axis_in_zone,
  stop_reason,
  -- progress columns: `peak_progress` is what makes an interrupted capture
  -- readable -- how far the capture had got when it was stopped. See
  -- scripts/interruptions.py; the suppression bands are cut on it.
  progress,
  peak_progress,
  timetocap,
  game_time,
  event_epoch,
  producer_sequence,
  event_time
FROM ktp_objective_attempt_events
WHERE BINARY match_id = BINARY {{MATCH_ID}}
ORDER BY half, event_epoch, producer_sequence, id;
