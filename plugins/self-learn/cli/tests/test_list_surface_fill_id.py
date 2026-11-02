"""Keep queue rows without paying for their surface-fill probes."""
import json

from self_learn import cli


def test_surface_fill_id_keeps_other_rows_and_only_probes_selected(monkeypatch, tmp_path, capsys):
    rows = [{"id": "lrn-aa000001"}, {"id": "lrn-aa000002"}]
    monkeypatch.setattr(cli, "resolve_home", lambda: tmp_path)
    monkeypatch.setattr(cli, "_home_gate", lambda home: None)
    monkeypatch.setattr(cli, "_warn_unparseable", lambda home: None)
    monkeypatch.setattr(cli, "list_items", lambda *a, **kw: [dict(r) for r in rows])
    probed = []
    def fill(home, items):
        probed.extend(i["id"] for i in items)
        for item in items:
            item["surface_fill"] = {"skill-md": {"words": 1}}
    monkeypatch.setattr(cli, "_add_surface_fill", fill)
    args = cli._build_parser().parse_args(["list", "--json", "--surface-fill-id", rows[0]["id"]])
    assert cli._cmd_list(args.as_json, args.include_deferred,
                         surface_fill_id=args.surface_fill_id) == 0
    data = json.loads(capsys.readouterr().out)
    assert [i["id"] for i in data] == [i["id"] for i in rows]
    assert probed == [rows[0]["id"]]
    assert data[0]["surface_fill"] == {"skill-md": {"words": 1}}
    assert "surface_fill" not in data[1]
