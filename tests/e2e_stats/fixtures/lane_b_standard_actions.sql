-- Minimal stock DoD action data needed by the isolated Lane B match.
-- Production HLStatsX databases already contain these rows; Lane B rebuilds
-- from DDL-only fixtures and must restore realistic configuration before the
-- daemon caches hlstats_Actions at startup.

INSERT IGNORE INTO hlstats_Actions
    (game, code, reward_player, reward_team, team, description,
     for_PlayerActions, for_PlayerPlayerActions, for_TeamActions,
     for_WorldActions, count)
VALUES
    ('dod', 'dod_control_point', 6, 1, '', 'Control Points Captured', '1', '0', '1', '0', 0),
    ('dod', 'dod_capture_area', 6, 1, '', 'Areas Captured', '1', '0', '1', '0', 0),
    ('dod', 'kill_streak_2', 0, 0, '', '2 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_3', 0, 0, '', '3 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_4', 0, 0, '', '4 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_5', 0, 0, '', '5 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_6', 0, 0, '', '6 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_7', 0, 0, '', '7 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_8', 0, 0, '', '8 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_9', 0, 0, '', '9 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_10', 0, 0, '', '10 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_11', 0, 0, '', '11 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_12', 0, 0, '', '12 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_13', 0, 0, '', '13 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_14', 0, 0, '', '14 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_15', 0, 0, '', '15 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_16', 0, 0, '', '16 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_17', 0, 0, '', '17 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_18', 0, 0, '', '18 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_19', 0, 0, '', '19 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_20', 0, 0, '', '20 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_21', 0, 0, '', '21 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_22', 0, 0, '', '22 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_23', 0, 0, '', '23 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_24', 0, 0, '', '24 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_25', 0, 0, '', '25 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_26', 0, 0, '', '26 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_27', 0, 0, '', '27 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_28', 0, 0, '', '28 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_29', 0, 0, '', '29 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_30', 0, 0, '', '30 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_31', 0, 0, '', '31 Kill Streak', '1', '0', '0', '0', 0),
    ('dod', 'kill_streak_32', 0, 0, '', '32 Kill Streak', '1', '0', '0', '0', 0);
