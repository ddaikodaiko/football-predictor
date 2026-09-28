import live


def test_live_names_match_by_similarity_and_elimination():
    theirs = ["Borussia Mönchengladbach", "1. FC Köln", "TSG 1899 Hoffenheim", "FC Bayern München"]
    ours = ["M'gladbach", "FC Koln", "Hoffenheim", "Bayern Munich"]
    assert live.name_map(theirs, ours) == dict(zip(theirs, ours))
