"""Figma AST extractor for Auto-layout and Design Tokens."""

from typing import Any, Dict, List

from harness_agent.figma.models import FigmaColor, FigmaDesignTokens, FigmaNodeLayout


class FigmaExtractor:
    """Extracts semantic auto-layout and design tokens from raw Figma nodes."""

    @classmethod
    def extract_frame_layout(cls, raw_node: Dict[str, Any]) -> FigmaNodeLayout:
        """Bóc tách Auto-layout (direction, alignment, padding, gap, sizing modes).

        Prunes heavy internal vector fields (e.g., fillGeometry, strokeGeometry,
        vectorPaths, etc.) to keep layout clean for LLMs.
        """
        node_id = raw_node.get("id", "")
        name = raw_node.get("name", "")
        node_type = raw_node.get("type", "FRAME")

        layout_mode = raw_node.get("layoutMode")  # HORIZONTAL, VERTICAL, or None
        primary_axis_align = raw_node.get("primaryAxisAlignItems")
        counter_axis_align = raw_node.get("counterAxisAlignItems")

        # Padding extraction
        padding = {
            "top": float(raw_node.get("paddingTop", 0.0)),
            "right": float(raw_node.get("paddingRight", 0.0)),
            "bottom": float(raw_node.get("paddingBottom", 0.0)),
            "left": float(raw_node.get("paddingLeft", 0.0)),
        }

        item_spacing = float(raw_node.get("itemSpacing", 0.0))

        # Dimensions from absoluteBoundingBox
        bbox = raw_node.get("absoluteBoundingBox") or {}
        width = float(bbox.get("width")) if "width" in bbox else None
        height = float(bbox.get("height")) if "height" in bbox else None

        layout_grow = float(raw_node.get("layoutGrow", 0.0))
        layout_align = raw_node.get("layoutAlign")

        # Recursively process children, skipping deep heavy vector data
        children_layouts: List[FigmaNodeLayout] = []
        for child in raw_node.get("children", []):
            if isinstance(child, dict):
                children_layouts.append(cls.extract_frame_layout(child))

        return FigmaNodeLayout(
            id=node_id,
            name=name,
            type=node_type,
            layout_mode=layout_mode,
            primary_axis_align=primary_axis_align,
            counter_axis_align=counter_axis_align,
            padding=padding,
            item_spacing=item_spacing,
            width=width,
            height=height,
            layout_grow=layout_grow,
            layout_align=layout_align,
            children=children_layouts,
        )

    @classmethod
    def extract_design_tokens(cls, raw_node: Dict[str, Any]) -> FigmaDesignTokens:
        """Bóc tách design tokens: color fills, typography, radius, shadows."""
        colors: List[Dict[str, Any]] = []
        typography: List[Dict[str, Any]] = []
        radius: List[Dict[str, Any]] = []
        shadows: List[Dict[str, Any]] = []

        cls._traverse_tokens(raw_node, colors, typography, radius, shadows)

        return FigmaDesignTokens(
            colors=colors,
            typography=typography,
            radius=radius,
            shadows=shadows,
        )

    @classmethod
    def _traverse_tokens(
        cls,
        node: Dict[str, Any],
        colors: List[Dict[str, Any]],
        typography: List[Dict[str, Any]],
        radius: List[Dict[str, Any]],
        shadows: List[Dict[str, Any]],
    ) -> None:
        node_name = node.get("name", "")

        # 1. Colors (fills and strokes)
        for fill in node.get("fills", []):
            if not isinstance(fill, dict) or not fill.get("visible", True):
                continue
            fill_type = fill.get("type", "")
            if fill_type == "SOLID" and "color" in fill:
                c = fill["color"]
                opacity = float(fill.get("opacity", 1.0))
                alpha = float(c.get("a", 1.0)) * opacity
                figma_color = FigmaColor(
                    r=float(c.get("r", 0.0)),
                    g=float(c.get("g", 0.0)),
                    b=float(c.get("b", 0.0)),
                    a=alpha,
                )
                colors.append(
                    {
                        "source": f"{node_name} (fill)",
                        "type": "SOLID",
                        "hex": figma_color.hex,
                        "rgba": figma_color.rgba_css,
                    }
                )
            elif fill_type in ("GRADIENT_LINEAR", "GRADIENT_RADIAL", "IMAGE"):
                colors.append(
                    {
                        "source": f"{node_name} (fill)",
                        "type": fill_type,
                        "asset_ref": fill.get("imageRef"),
                    }
                )

        # 2. Typography (Text nodes)
        if node.get("type") == "TEXT" and "style" in node:
            style = node["style"]
            line_height = style.get("lineHeightPx") or style.get("lineHeightPercent")
            typography.append(
                {
                    "node_name": node_name,
                    "font_family": style.get("fontFamily"),
                    "font_size": style.get("fontSize"),
                    "font_weight": style.get("fontWeight"),
                    "line_height": line_height,
                    "text_align": style.get("textAlignHorizontal"),
                }
            )

        # 3. Corner Radius
        corner_radius = node.get("cornerRadius")
        if corner_radius is not None:
            radius.append(
                {
                    "node_name": node_name,
                    "corner_radius": float(corner_radius),
                }
            )
        elif "rectangleCornerRadii" in node:
            radius.append(
                {
                    "node_name": node_name,
                    "radii": [float(r) for r in node["rectangleCornerRadii"]],
                }
            )

        # 4. Effects (Shadows & Blurs)
        for effect in node.get("effects", []):
            if not isinstance(effect, dict) or not effect.get("visible", True):
                continue
            eff_type = effect.get("type", "")
            if "SHADOW" in eff_type:
                color_dict = effect.get("color", {})
                figma_color = FigmaColor(
                    r=float(color_dict.get("r", 0.0)),
                    g=float(color_dict.get("g", 0.0)),
                    b=float(color_dict.get("b", 0.0)),
                    a=float(color_dict.get("a", 1.0)),
                )
                offset = effect.get("offset", {})
                shadows.append(
                    {
                        "node_name": node_name,
                        "type": eff_type,
                        "hex": figma_color.hex,
                        "rgba": figma_color.rgba_css,
                        "radius": float(effect.get("radius", 0.0)),
                        "offset_x": float(offset.get("x", 0.0)),
                        "offset_y": float(offset.get("y", 0.0)),
                    }
                )

        # Recurse children
        for child in node.get("children", []):
            if isinstance(child, dict):
                cls._traverse_tokens(child, colors, typography, radius, shadows)
