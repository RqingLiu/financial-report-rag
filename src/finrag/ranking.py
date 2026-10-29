"""Shared rank interleaving, independent of legacy issuer resolution/evaluation."""

from .models import Hit


def interleave(rankings: list[list[Hit]]) -> list[Hit]:
    output, seen = [], set()
    for i in range(max((len(r) for r in rankings), default=0)):
        for rank in rankings:
            if i < len(rank) and rank[i].chunk.id not in seen:
                output.append(rank[i])
                seen.add(rank[i].chunk.id)
    return output
