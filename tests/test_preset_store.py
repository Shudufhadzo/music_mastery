from mastery_native.engine import MasteringControls
from mastery_native.preset_store import MasteringPresetStore


def test_preset_store_saves_and_loads_named_controls(tmp_path):
    store = MasteringPresetStore(tmp_path / "presets.json")

    store.save_preset("Album Warm", MasteringControls(gain_db=4.0, target_lufs=-10.0))

    loaded = store.load_preset("Album Warm")

    assert loaded is not None
    assert loaded.gain_db == 4.0
    assert loaded.target_lufs == -10.0


def test_preset_store_lists_saved_names_sorted(tmp_path):
    store = MasteringPresetStore(tmp_path / "presets.json")

    store.save_preset("Zulu", MasteringControls(gain_db=2.0))
    store.save_preset("Alpha", MasteringControls(gain_db=1.0))

    assert store.list_names() == ["Alpha", "Zulu"]
