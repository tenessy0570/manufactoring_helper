from collections import defaultdict
from collections.abc import Sequence

from app.domains.catalog.models import CatalogCandidate, MarketGroup

ROOT_NAMES = frozenset({"ship equipment", "ammunition & charges", "drones"})


class MarketTreeSelector:
    def select(self, groups: Sequence[MarketGroup]) -> list[CatalogCandidate]:
        indexed = {group.market_group_id: group for group in groups}
        children: dict[int, list[MarketGroup]] = defaultdict(list)
        for group in groups:
            if group.parent_group_id is not None:
                if group.parent_group_id not in indexed:
                    raise ValueError("Incomplete market group tree")
                children[group.parent_group_id].append(group)
        roots = [
            group
            for group in groups
            if group.parent_group_id is None and group.name.strip().lower() in ROOT_NAMES
        ]
        if {group.name.strip().lower() for group in roots} != ROOT_NAMES:
            raise ValueError("Expected catalog roots are missing")
        selected: dict[int, CatalogCandidate] = {}

        def visit(group: MarketGroup, category: str, path: list[int], is_rig: bool) -> None:
            if group.market_group_id in path:
                raise ValueError("Cycle in market group tree")
            if "capital" in group.name.lower():
                return
            path = [*path, group.market_group_id]
            is_rig = is_rig or group.name.strip().lower() == "rigs"
            for type_id in group.types:
                selected[type_id] = CatalogCandidate(
                    type_id=type_id,
                    market_group_id=group.market_group_id,
                    market_group_name=group.name,
                    category=category,
                    group_path=path,
                    is_rig=is_rig,
                )
            for child in sorted(
                children[group.market_group_id], key=lambda item: item.market_group_id
            ):
                visit(child, category, path, is_rig)

        for root in sorted(roots, key=lambda item: item.market_group_id):
            visit(root, root.name, [], False)
        return [selected[type_id] for type_id in sorted(selected)]
