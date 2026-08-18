"""年代志仓储: cover / year / taxonomy / method / timeline_debt 卡片。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from novel_agent.domain.models import AnnalsCardRecord
from novel_agent.domain.schemas.annals import (
    AnnalsCover,
    FestivalTaxonomyCard,
    MethodLibraryCard,
    TimelineAlignDebt,
    YearCard,
)

KIND_COVER = "cover"
KIND_YEAR = "year"
KIND_TAXONOMY = "festival_taxonomy"
KIND_METHOD = "method"
KIND_DEBT = "timeline_debt"
COVER_KEY = "cover"


class AnnalsRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def upsert_cover(self, project_id: int, cover: AnnalsCover, *, status: str) -> None:
        self._upsert(
            project_id,
            KIND_COVER,
            COVER_KEY,
            cover.model_dump(),
            status=status,
        )

    def get_cover(self, project_id: int) -> tuple[AnnalsCover, str] | None:
        rec = self._get(project_id, KIND_COVER, COVER_KEY)
        if rec is None:
            return None
        return AnnalsCover.model_validate(rec.payload), rec.status

    def upsert_year(self, project_id: int, card: YearCard, *, status: str) -> None:
        self._upsert(
            project_id,
            KIND_YEAR,
            str(card.year),
            card.model_dump(),
            status=status,
            year=card.year,
        )

    def get_year(self, project_id: int, year: int) -> tuple[YearCard, str] | None:
        rec = self._get(project_id, KIND_YEAR, str(year))
        if rec is None:
            return None
        return YearCard.model_validate(rec.payload), rec.status

    def list_years(self, project_id: int) -> list[tuple[YearCard, str]]:
        recs = self.s.exec(
            select(AnnalsCardRecord)
            .where(
                AnnalsCardRecord.project_id == project_id,
                AnnalsCardRecord.kind == KIND_YEAR,
            )
            .order_by(AnnalsCardRecord.year)  # type: ignore[attr-defined]
        ).all()
        return [(YearCard.model_validate(rec.payload), rec.status) for rec in recs]

    def replace_taxonomy(
        self,
        project_id: int,
        cards: list[FestivalTaxonomyCard],
        *,
        status: str,
    ) -> None:
        rows = [(card.festival_id, card.model_dump(), None) for card in cards]
        self._replace_kind(project_id, KIND_TAXONOMY, rows, status=status)

    def list_taxonomy(self, project_id: int) -> list[FestivalTaxonomyCard]:
        return [
            FestivalTaxonomyCard.model_validate(rec.payload)
            for rec in self._list_kind(project_id, KIND_TAXONOMY)
        ]

    def replace_methods(
        self,
        project_id: int,
        cards: list[MethodLibraryCard],
        *,
        status: str,
    ) -> None:
        rows = [(card.film_title, card.model_dump(), None) for card in cards]
        self._replace_kind(project_id, KIND_METHOD, rows, status=status)

    def list_methods(self, project_id: int) -> list[MethodLibraryCard]:
        return [
            MethodLibraryCard.model_validate(rec.payload)
            for rec in self._list_kind(project_id, KIND_METHOD)
        ]

    def replace_debts(
        self,
        project_id: int,
        cards: list[TimelineAlignDebt],
        *,
        status: str,
    ) -> None:
        rows = [
            (f"{card.chapter_key}:{card.issue}", card.model_dump(), None) for card in cards
        ]
        self._replace_kind(project_id, KIND_DEBT, rows, status=status)

    def list_debts(self, project_id: int) -> list[TimelineAlignDebt]:
        return [
            TimelineAlignDebt.model_validate(rec.payload)
            for rec in self._list_kind(project_id, KIND_DEBT)
        ]

    def r6_complete(self, project_id: int) -> bool:
        got = self.get_cover(project_id)
        if got is None:
            return False
        cover, status = got
        if status != "confirmed":
            return False
        if not cover.applicable:
            return True
        if cover.span_start is None or cover.span_end is None:
            return False
        years = {card.year: year_status for card, year_status in self.list_years(project_id)}
        for year in range(cover.span_start, cover.span_end + 1):
            if year not in years:
                return False
        return all(years.get(year) == "confirmed" for year in cover.plot_hit_years)

    def _get(self, project_id: int, kind: str, card_key: str) -> AnnalsCardRecord | None:
        return self.s.exec(
            select(AnnalsCardRecord).where(
                AnnalsCardRecord.project_id == project_id,
                AnnalsCardRecord.kind == kind,
                AnnalsCardRecord.card_key == card_key,
            )
        ).first()

    def _upsert(
        self,
        project_id: int,
        kind: str,
        card_key: str,
        payload: dict,
        *,
        status: str,
        year: int | None = None,
    ) -> None:
        rec = self._get(project_id, kind, card_key)
        if rec is None:
            rec = AnnalsCardRecord(
                project_id=project_id,
                kind=kind,
                card_key=card_key,
                year=year,
                status=status,
                payload=payload,
            )
        else:
            rec.payload = payload
            rec.status = status
            rec.year = year
            rec.updated_at = datetime.now(UTC)
        self.s.add(rec)
        self.s.flush()

    def _list_kind(self, project_id: int, kind: str) -> list[AnnalsCardRecord]:
        return list(
            self.s.exec(
                select(AnnalsCardRecord)
                .where(
                    AnnalsCardRecord.project_id == project_id,
                    AnnalsCardRecord.kind == kind,
                )
                .order_by(AnnalsCardRecord.card_key)  # type: ignore[attr-defined]
            ).all()
        )

    def _replace_kind(
        self,
        project_id: int,
        kind: str,
        rows: list[tuple[str, dict, int | None]],
        *,
        status: str,
    ) -> None:
        existing = self.s.exec(
            select(AnnalsCardRecord).where(
                AnnalsCardRecord.project_id == project_id,
                AnnalsCardRecord.kind == kind,
            )
        ).all()
        for rec in existing:
            self.s.delete(rec)
        self.s.flush()
        for card_key, payload, year in rows:
            self.s.add(
                AnnalsCardRecord(
                    project_id=project_id,
                    kind=kind,
                    card_key=card_key,
                    year=year,
                    status=status,
                    payload=payload,
                )
            )
        self.s.flush()
