"""Rendu d'une barre de score ASCII à partir d'un float 0-100."""

BLOCKS = "▏▎▍▌▋▊▉█"


def render_score_bar(score: float, width: int = 6) -> str:
    """Retourne une chaîne de 'width' caractères représentant le score.

    Exemple : render_score_bar(82, 6) -> '█████▊'
    """
    score = max(0.0, min(100.0, score))
    full_blocks = int(score / 100 * width)
    partial_index = int(((score / 100 * width) - full_blocks) * len(BLOCKS))
    result = "█" * full_blocks
    if full_blocks < width:
        if partial_index > 0:
            result += BLOCKS[partial_index - 1]
        result += " " * (width - len(result))
    return result[:width]
