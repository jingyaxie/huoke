from datetime import date

from sqlalchemy import select

from app.models.daily_report import DailyReport
from app.repositories.base import BaseRepository


class ReportRepository(BaseRepository):
    def get_by_date(self, report_date: date) -> DailyReport | None:
        return self.session.scalar(select(DailyReport).where(DailyReport.report_date == report_date))

    def upsert(
        self,
        *,
        report_date: date,
        provider: str,
        model: str | None,
        title: str,
        summary: str | None,
        content_markdown: str,
        content_html: str | None,
        pdf_path: str | None,
    ) -> DailyReport:
        report = self.get_by_date(report_date)
        if report is None:
            report = DailyReport(
                report_date=report_date,
                provider=provider,
                model=model,
                title=title,
                summary=summary,
                content_markdown=content_markdown,
                content_html=content_html,
                pdf_path=pdf_path,
            )
            self.session.add(report)
        else:
            report.provider = provider
            report.model = model
            report.title = title
            report.summary = summary
            report.content_markdown = content_markdown
            report.content_html = content_html
            report.pdf_path = pdf_path
        self.session.flush()
        return report

    def list_recent(self, limit: int = 30):
        return self.session.scalars(select(DailyReport).order_by(DailyReport.report_date.desc()).limit(limit)).all()

