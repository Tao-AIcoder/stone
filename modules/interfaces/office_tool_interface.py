"""
modules/interfaces/office_tool_interface.py - Office file operations ABC for STONE.

Allows swapping python-docx/openpyxl/python-pptx with LibreOffice API or
other backends without changing tool logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OfficeWriteOptions:
    """Styling options for office document writes."""
    # Common
    bold: bool = False
    italic: bool = False
    font_size: int | None = None        # points; None = use default
    heading_level: int | None = None    # 1-6 for Word headings; None = body text

    # Excel specific
    cell_format: str | None = None      # e.g. "#,##0.00", "YYYY-MM-DD"
    wrap_text: bool = False

    # Extra metadata passed through to implementations
    extra: dict[str, Any] = field(default_factory=dict)


class OfficeToolInterface(ABC):
    """
    Abstract interface for Office file operations.

    Supported formats:
      - .docx  (Word)
      - .xlsx  (Excel)
      - .pptx  (PowerPoint)

    Phase 1b scope: content + basic styles (heading/bold/italic/table/cell format).
    Images, formulas, animations are out of scope for Phase 1b.
    """

    @abstractmethod
    async def create(
        self,
        path: str,
        fmt: str,
        title: str = "",
        content: str = "",
        options: OfficeWriteOptions | None = None,
    ) -> str:
        """
        Create a new Office file.
        Returns the absolute path of the created file.
        """
        ...

    @abstractmethod
    async def read(self, path: str) -> str:
        """
        Read an Office file and return its content as plain text
        (tables rendered as Markdown tables, headings preserved).
        """
        ...

    @abstractmethod
    async def append(
        self,
        path: str,
        content: str,
        options: OfficeWriteOptions | None = None,
    ) -> bool:
        """Append content to an existing Office file."""
        ...

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete an Office file. Returns True on success."""
        ...

    @abstractmethod
    def supported_formats(self) -> list[str]:
        """Return list of supported file extensions (e.g. ['.docx', '.xlsx'])."""
        ...


__all__ = ["OfficeWriteOptions", "OfficeToolInterface"]
