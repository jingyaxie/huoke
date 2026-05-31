from datetime import date

from app.services.report_service import ReportService


def test_report_markdown_template():
    class DummyRepo:
        def list_hot(self, limit=10):
            return []

    class DummySession:
        pass

    service = ReportService(DummySession())
    service.video_repo = DummyRepo()
    title, markdown, summary, model = "t", "# hi", "s", None
    html = service.build_html(title, markdown, summary, "template", model, date(2026, 5, 30))
    assert "2026-05-30" in html
    assert "hi" in html
