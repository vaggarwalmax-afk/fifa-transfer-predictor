from predictor.names import assign_matches, clubs_match, match_one, name_similarity, normalize


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


def test_assignment_goes_to_the_strongest_match_not_the_first_asked():
    candidates = [(["Gabriel dos Santos Magalhães", "Gabriel"], ["Arsenal", "ARS"])]
    queries = [(["Gabriel Jesus"], ["Arsenal FC"]),  # partial match, asked first
               (["Gabriel"], ["Arsenal FC"])]        # exact match
    assert assign_matches(queries, candidates) == {1: 0}


def test_fpl_club_spellings_match_football_data():
    assert clubs_match("Nott'm Forest", "Nottingham Forest FC")
    assert clubs_match("NFO", "NOT")
    assert clubs_match("Sheffield Utd", "Sheffield United FC")
    assert clubs_match("Spurs", "Tottenham Hotspur FC")


def test_fuzzy_shortcut_does_not_change_any_match(monkeypatch):
    import random
    import string

    import predictor.names as names

    rng = random.Random(7)

    def typo(word):
        i = rng.randrange(len(word))
        return word[:i] + rng.choice(string.ascii_lowercase) + word[i + 1:]

    base = ["".join(rng.choice("aeioulnrst") for _ in range(rng.randint(5, 9))) for _ in range(120)]
    candidates = [([f"{a} {b}"], [rng.choice(["Arsenal", "Chelsea", "Everton"])])
                  for a, b in zip(base[::2], base[1::2])]
    queries = [([f"{typo(n[0].split()[0])} {n[0].split()[1]}"], [c[0]]) for n, c in candidates]
    queries += [([f"{rng.choice(base)} {rng.choice(base)}"], ["Arsenal"]) for _ in range(40)]

    fast = names.assign_matches(queries, candidates)
    monkeypatch.setattr(names, "_FUZZY_FLOOR", 0.0)  # always compute the full ratio
    names.normalize.cache_clear()
    assert names.assign_matches(queries, candidates) == fast
    assert fast  # the typo'd names do match
