from predictor.names import clubs_match, match_one, name_similarity, normalize


def test_normalize_strips_accents_and_special_letters():
    assert normalize("Martin Ødegaard") == "martin odegaard"
    assert normalize("Joško Gvardiol") == "josko gvardiol"
    assert normalize("Jean-Philippe Mateta") == "jean philippe mateta"


def test_word_order_and_hyphens_do_not_matter():
    assert name_similarity("Son Heung-min", "Heung-Min Son") >= 0.95


def test_exact_nickname_beats_partial_name():
    candidates = [(["Gabriel dos Santos Magalhães", "Gabriel"], ["Arsenal", "ARS"]),
                  (["Gabriel Fernando de Jesus", "G.Jesus"], ["Arsenal", "ARS"])]
    assert match_one(["Gabriel"], ["Arsenal FC"], candidates) == 0


def test_single_name_inside_full_name_needs_the_club():
    candidates = [(["Estêvão Willian"], ["Chelsea FC"])]
    assert match_one(["Estevao"], [], candidates) is None
    assert match_one(["Estevao"], ["Chelsea"], candidates) == 0


def test_ambiguous_match_returns_none():
    candidates = [(["Ben Davies"], ["Spurs"]), (["Ben Davies"], ["Liverpool"])]
    assert match_one(["Ben Davies"], [], candidates) is None
    assert match_one(["Ben Davies"], ["Liverpool"], candidates) == 1


def test_unrelated_names_do_not_match():
    assert match_one(["Erling Haaland"], ["Man City"], [(["Kevin De Bruyne"], ["Man City"])]) is None


def test_clubs_match_ignores_fc_suffix():
    assert clubs_match("Arsenal FC", "Arsenal")
    assert clubs_match("AFC Bournemouth", "Bournemouth")
    assert not clubs_match("Manchester United FC", "Manchester City")
