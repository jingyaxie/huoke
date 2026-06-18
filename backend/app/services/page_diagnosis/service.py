from __future__ import annotations

from app.services.page_diagnosis.contracts import CrawlFailureSignal, PageDiagnosis, PageSnapshot
from app.services.page_diagnosis.rules import fallback_diagnosis, rule_prefilter


class PageDiagnosisService:
    """上层诊断引擎：规则优先，失败降级 fallback。"""

    def analyze(
        self,
        signal: CrawlFailureSignal,
        snapshot: PageSnapshot | None,
    ) -> PageDiagnosis:
        ruled = rule_prefilter(signal, snapshot)
        if ruled is not None:
            return ruled
        return fallback_diagnosis(signal, snapshot)
