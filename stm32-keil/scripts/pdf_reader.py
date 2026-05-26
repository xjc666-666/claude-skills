"""
Query STM32 Chinese PDF reference manuals for register definitions and pin mappings.

Uses PyMuPDF (fitz) for PDF text extraction with section indexing for fast lookup.
"""
import os
import sys
import json
import re
from pathlib import Path
from typing import Dict, Optional, List, Tuple

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Warning: PyMuPDF (fitz) is required. Install with: pip install PyMuPDF")
    fitz = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import ensure_dir


# PDF reference manuals stored in skill's references/ directory
def _get_pdf_paths():
    ref_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references")
    return {
        "F103": os.path.join(ref_dir, "STM32F103_reference_manual.pdf"),
        "F407": os.path.join(ref_dir, "STM32F407_reference_manual.pdf"),
    }

PDF_PATHS = _get_pdf_paths()

# Cache directory for PDF indices
CACHE_DIR = str(Path(__file__).resolve().parent.parent / "references" / "pdf_cache")


class PDFReader:
    """PDF reference manual reader with section indexing and caching."""

    def __init__(self, family: str, pdf_path: Optional[str] = None):
        """
        Args:
            family: "F103" or "F407"
            pdf_path: Path to PDF file (auto-detected from PDF_PATHS if None)
        """
        self.family = family
        self.pdf_path = pdf_path or PDF_PATHS.get(family, "")
        self.doc = None
        self.section_index = {}  # {section_name: [start_page, end_page]}
        self._loaded = False

    def open(self) -> bool:
        """Open the PDF and load/build section index."""
        if fitz is None:
            print("Error: PyMuPDF not installed")
            return False

        if not self.pdf_path or not os.path.isfile(self.pdf_path):
            print(f"Error: PDF not found at {self.pdf_path}")
            return False

        try:
            self.doc = fitz.open(self.pdf_path)
        except Exception as e:
            print(f"Error opening PDF: {e}")
            return False

        # Try to load cached index
        cache_file = self._get_cache_path()
        if os.path.isfile(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    self.section_index = json.load(f)
                self._loaded = True
                return True
            except Exception:
                pass

        # Build index from PDF
        self._build_index()
        self._loaded = True
        return True

    def close(self) -> None:
        """Close the PDF document."""
        if self.doc:
            self.doc.close()
            self.doc = None

    def query(self, keywords: str, max_pages: int = 10) -> str:
        """
        Search the PDF for content matching keywords.

        Args:
            keywords: Search keywords (e.g., "GPIOA 时钟", "USART 波特率")
            max_pages: Maximum pages to search around matches

        Returns:
            Extracted text from relevant sections
        """
        if not self._loaded:
            if not self.open():
                return ""

        # First, search in section index
        matching_sections = self._search_index(keywords)

        results = []

        if matching_sections:
            for section_name, (start_page, end_page) in matching_sections[:3]:
                text = self._extract_pages(start_page, end_page, max_pages)
                if text:
                    results.append(f"## {section_name}\n{text}")

        # Also do a full-text search on nearby pages
        if not results:
            text = self._search_full_text(keywords, max_pages)
            if text:
                results.append(text)

        return "\n\n".join(results) if results else f"未找到与 '{keywords}' 相关的内容"

    def query_register(self, register_name: str) -> str:
        """
        Search for a specific register definition.

        Args:
            register_name: Register name (e.g., "GPIOA_CRL", "RCC_CR")

        Returns:
            Register description and bit field definitions
        """
        if not self._loaded:
            if not self.open():
                return ""

        return self.query(register_name, max_pages=3)

    def query_pin_function(self, pin: str) -> str:
        """
        Search for pin alternate function mappings.

        Args:
            pin: Pin name (e.g., "PA0", "PB6", "PA9")

        Returns:
            Pin function description
        """
        if not self._loaded:
            if not self.open():
                return ""

        return self.query(f"{pin} 复用 功能", max_pages=5)

    def query_peripheral(self, peripheral: str) -> str:
        """
        Search for a peripheral chapter (e.g., GPIO, USART, TIM).

        Args:
            peripheral: Peripheral name (e.g., "GPIO", "USART", "TIM2")

        Returns:
            Relevant chapter content
        """
        if not self._loaded:
            if not self.open():
                return ""

        # Map common peripheral names to Chinese chapter titles
        chapter_map = {
            "GPIO": "通用和复用功能I/O",
            "USART": "通用同步异步收发器",
            "UART": "通用同步异步收发器",
            "TIM": "定时器",
            "SPI": "串行外设接口",
            "I2C": "内部集成电路",
            "ADC": "模数转换器",
            "DAC": "数模转换器",
            "DMA": "直接存储器存取",
            "RCC": "复位和时钟控制",
            "NVIC": "嵌套向量中断控制器",
            "EXTI": "外部中断",
            "RTC": "实时时钟",
            "FLASH": "闪存存储器",
            "PWR": "电源控制",
            "WWDG": "看门狗",
            "IWDG": "独立看门狗",
            "SDIO": "SDIO接口",
            "CAN": "控制器区域网络",
            "FSMC": "灵活的静态存储器控制器",
            "FMC": "灵活的存储器控制器",
        }

        chinese_name = chapter_map.get(peripheral.upper(), peripheral)
        return self.query(chinese_name, max_pages=15)

    def get_table_of_contents(self) -> List[Dict]:
        """Get the PDF table of contents."""
        if not self._loaded:
            if not self.open():
                return []

        toc = self.doc.get_toc()
        return [
            {"level": item[0], "title": item[1], "page": item[2]}
            for item in toc
        ]

    def _build_index(self) -> None:
        """Build section index from PDF table of contents."""
        toc = self.doc.get_toc()
        self.section_index = {}

        for i, (level, title, page) in enumerate(toc):
            # Find the next item at same or higher level to determine end page
            end_page = self.doc.page_count
            for j in range(i + 1, len(toc)):
                if toc[j][0] <= level:
                    end_page = toc[j][2] - 1
                    break

            self.section_index[title] = [page, min(end_page, page + 50)]

        # Cache the index
        cache_file = self._get_cache_path()
        ensure_dir(os.path.dirname(cache_file))
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(self.section_index, f, ensure_ascii=False, indent=2)

    def _search_index(self, keywords: str) -> List[Tuple[str, Tuple[int, int]]]:
        """Search section index for matching keywords."""
        kw_list = [kw.strip().lower() for kw in keywords.split() if kw.strip()]
        results = []

        for section_name, pages in self.section_index.items():
            section_lower = section_name.lower()
            score = sum(1 for kw in kw_list if kw in section_lower)
            if score > 0:
                results.append((section_name, (pages[0], pages[1]), score))

        results.sort(key=lambda x: x[2], reverse=True)
        return [(name, pages) for name, pages, _ in results]

    def _extract_pages(self, start_page: int, end_page: int,
                       max_pages: int) -> str:
        """Extract text from a page range, limited to max_pages."""
        actual_end = min(end_page, start_page + max_pages)
        texts = []

        for page_num in range(start_page, actual_end + 1):
            if 0 <= page_num - 1 < self.doc.page_count:
                page = self.doc[page_num - 1]  # fitz pages are 0-indexed
                text = page.get_text()
                if text.strip():
                    texts.append(text)

        return "\n".join(texts)

    def _search_full_text(self, keywords: str, max_context: int) -> str:
        """Search the full PDF text for keywords."""
        kw_list = [kw.strip().lower() for kw in keywords.split() if kw.strip()]
        if not kw_list:
            return ""

        results = []
        pages_searched = 0

        for page_num in range(min(self.doc.page_count, 200)):  # Limit search
            page = self.doc[page_num]
            text = page.get_text().lower()

            matches = sum(1 for kw in kw_list if kw in text)
            if matches >= len(kw_list) * 0.5:  # At least half the keywords match
                results.append({
                    "page": page_num + 1,
                    "text": page.get_text(),
                    "score": matches,
                })
                pages_searched += 1
                if pages_searched >= max_context:
                    break

        if not results:
            return ""

        results.sort(key=lambda x: x["score"], reverse=True)
        return "\n\n".join(
            f"[第{r['page']}页]\n{r['text'][:3000]}"
            for r in results[:5]
        )

    def _get_cache_path(self) -> str:
        """Get cache file path for the section index."""
        ensure_dir(CACHE_DIR)
        family = self.family.lower()
        return os.path.join(CACHE_DIR, f"{family}_index.json")


# Module-level convenience functions

def query_register(chip: str, register: str) -> str:
    """Convenience function to query a register for a specific chip."""
    family = "F103" if "F103" in chip else "F407"
    reader = PDFReader(family)
    try:
        result = reader.query_register(register)
        return result
    finally:
        reader.close()


def query_pin(chip: str, pin: str) -> str:
    """Convenience function to query pin function for a specific chip."""
    family = "F103" if "F103" in chip else "F407"
    reader = PDFReader(family)
    try:
        result = reader.query_pin_function(pin)
        return result
    finally:
        reader.close()


def query_peripheral(chip: str, peripheral: str) -> str:
    """Convenience function to query a peripheral chapter."""
    family = "F103" if "F103" in chip else "F407"
    reader = PDFReader(family)
    try:
        result = reader.query_peripheral(peripheral)
        return result
    finally:
        reader.close()


def query(chip: str, keywords: str) -> str:
    """General query — search the PDF for any keywords."""
    family = "F103" if "F103" in chip else "F407"
    reader = PDFReader(family)
    try:
        result = reader.query(keywords)
        return result
    finally:
        reader.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Query STM32 reference manual PDFs")
    parser.add_argument("--chip", required=True,
                        help="Chip model (e.g., STM32F407ZGT6)")
    parser.add_argument("--query", default=None,
                        help="General keyword search")
    parser.add_argument("--register", default=None,
                        help="Search for specific register")
    parser.add_argument("--pin", default=None,
                        help="Search for pin function (e.g., PA9)")
    parser.add_argument("--peripheral", default=None,
                        help="Search for peripheral chapter (e.g., GPIO, USART)")
    parser.add_argument("--toc", action="store_true",
                        help="Print table of contents")

    args = parser.parse_args()

    if args.toc:
        family = "F103" if "F103" in args.chip else "F407"
        reader = PDFReader(family)
        try:
            reader.open()
            toc = reader.get_table_of_contents()
            for item in toc[:50]:
                prefix = "  " * (item["level"] - 1)
                print(f"{prefix}{item['title']} (p.{item['page']})")
        finally:
            reader.close()
    elif args.register:
        print(query_register(args.chip, args.register))
    elif args.pin:
        print(query_pin(args.chip, args.pin))
    elif args.peripheral:
        print(query_peripheral(args.chip, args.peripheral))
    elif args.query:
        print(query(args.chip, args.query))
    else:
        parser.print_help()
