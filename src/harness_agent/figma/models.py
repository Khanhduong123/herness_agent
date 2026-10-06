"""Figma domain models and schemas."""

from pydantic import BaseModel, Field


class FigmaColor(BaseModel):
    """Normalized Figma color representation with float values [0.0, 1.0]."""

    r: float = Field(ge=0.0, le=1.0)
    g: float = Field(ge=0.0, le=1.0)
    b: float = Field(ge=0.0, le=1.0)
    a: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def hex(self) -> str:
        """Converts float [0.0, 1.0] to #RRGGBB or #RRGGBBAA."""
        ri, gi, bi = round(self.r * 255), round(self.g * 255), round(self.b * 255)
        if self.a < 1.0:
            ai = round(self.a * 255)
            return f"#{ri:02X}{gi:02X}{bi:02X}{ai:02X}"
        return f"#{ri:02X}{gi:02X}{bi:02X}"

    @property
    def rgba_css(self) -> str:
        """Converts to CSS rgba(r, g, b, a) format."""
        ri, gi, bi = round(self.r * 255), round(self.g * 255), round(self.b * 255)
        return f"rgba({ri}, {gi}, {bi}, {self.a:.2f})"


class FigmaAssetExport(BaseModel):
    """Metadata for an exported Figma asset saved locally."""

    node_id: str
    local_path: str
    format: str
    file_size_bytes: int
