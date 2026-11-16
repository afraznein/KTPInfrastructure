### Lane B: the own-weapon drive's drop now reaches the game (2026-11-15)

- `own_weapon_kill_scenario` had answered `not_exercised` on every nightly since it was added on
  10-30: the game never handed B the gun, so the pickup was always synthetic. The drive's own
  trace shows why. B's weapon bits were identical before and after `drop` on every nightly checked,
  so B never let go of its primary and could not take A's.
- Two causes, and both had to be fixed. Under extension mode KTPAMXX installs no `Cmd_Argv`
  override (it lives only in the Metamod `meta_engfuncs` table), so `amxclient_cmd` fires the
  plugin forwards with its own arguments while `dod.so`'s `ClientCommand` reads whatever line the
  engine tokenized last. The drive now tokenizes the same line with `server_cmd` + `server_exec`
  first. And `drop` needs the entity classname: the drive now builds `weapon_<log name>` instead of
  a display name.
- Measured on dispatched runs: tokenize with the display name, drop did nothing; classname without
  the tokenize, drop did nothing; both together, B dropped its gun, the game's touch handed it A's,
  a real `dod_client_weaponpickup` fired, the verdict was `ok` and the run was green.
- The verdict logic is unchanged: a synthetic pickup is still `not_exercised` and still gates the
  nightly. No waiver was added.
