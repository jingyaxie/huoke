from pathlib import Path

from playwright.async_api import async_playwright


class PdfService:
    async def html_to_pdf(self, html: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html, wait_until="networkidle")
            await page.pdf(path=str(output_path), format="A4", print_background=True)
            await browser.close()
        return output_path

