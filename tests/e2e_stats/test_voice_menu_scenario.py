from . import voice_menu_scenario as vm

SLOTS = [["attack", "hold", "fallback", "left", "right", "sticktogether", "cover", "usegrens", "ceasefire"],
         ["yessir", "negative", "backup", "fireinhole", "grenade", "sniper", "fireleft", "fireright", "areaclear"],
         ["gogogo", "displace", "enemyahead", "enemybehind", "mgahead", "moveupmg", "needammo", "usebazooka", "bazookaspotted"]]


def body(*, logged=None, subs=None, n=27):
    out = []
    for i in range(n):
        m, s = divmod(i, 9)
        name = SLOTS[m][s]
        out.append(f"[VM] PICK n={i + 1} bot=3 bname=Bot{i % 4} menu={m + 1} slot={s + 1}")
        lg = (logged or {}).get(i, name)
        if lg:
            out.append(f'"Bot{i % 4}<3><BOT><Allies>" triggered "voicemenu_{lg}"')
        sb = (subs or {}).get(i, name)
        if sb:
            out.append(f"[VM] SUB to=4 text=#Voice_subtitle_{sb}")
    out.append("[VM] END picks=27")
    return "\n".join(out)


def test_every_slot_confirmed_is_ok():
    assert vm.judge(body())["status"] == "ok"


def test_nation_variants_count_as_the_same_voice():
    v = vm.judge(body(subs={25: "usepiat", 26: "pschreckspotted", 0: "moveout"}))
    assert v["status"] == "ok", v


def test_a_wrong_slot_is_a_pipeline_failure_naming_the_slot():
    v = vm.judge(body(logged={10: "yessir"}))
    assert v["status"] == "pipeline" and "2.2 logged yessir but the game played negative" in v["detail"]


def test_an_unlogged_pick_is_a_pipeline_failure():
    v = vm.judge(body(logged={4: ""}))
    assert v["status"] == "pipeline" and "not logged: 1.5" in v["detail"]


def test_no_subtitles_at_all_is_not_exercised_not_a_pass():
    v = vm.judge(body(subs={i: "" for i in range(27)}))
    assert v["status"] == "not_exercised"


def test_abort_is_not_exercised():
    assert vm.judge("[VM] ABORT no bots\n")["status"] == "not_exercised"
