from predictor.__main__ import main


def test_failed_training_keeps_the_previous_dataset_and_model(small_raw):
    # small_raw has 4 players, too few to train on, so `train` must fail without touching files.
    small_raw.PLAYERS_PATH.write_text('{"old": "dataset"}', encoding="utf-8")
    small_raw.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    small_raw.MODEL_PATH.write_text('{"old": "model"}', encoding="utf-8")
    assert main(["train"]) == 1
    assert small_raw.PLAYERS_PATH.read_text(encoding="utf-8") == '{"old": "dataset"}'
    assert small_raw.MODEL_PATH.read_text(encoding="utf-8") == '{"old": "model"}'


def test_fetch_without_a_key_is_a_clean_error(paths, monkeypatch, capsys):
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "your-key-here")
    assert main(["fetch"]) == 1
    assert "No API key" in capsys.readouterr().err
