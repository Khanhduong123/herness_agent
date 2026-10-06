"""Unit tests for FigmaExtractor."""

from harness_agent.figma.extractor import FigmaExtractor


def test_extractor_autolayout_flexbox_mapping():
    raw_node = {
        "id": "10:20",
        "name": "CardContainer",
        "type": "FRAME",
        "layoutMode": "VERTICAL",
        "primaryAxisAlignItems": "SPACE_BETWEEN",
        "counterAxisAlignItems": "CENTER",
        "paddingTop": 16,
        "paddingRight": 24,
        "paddingBottom": 16,
        "paddingLeft": 24,
        "itemSpacing": 12,
        "layoutGrow": 1.0,
        "layoutAlign": "STRETCH",
        "absoluteBoundingBox": {
            "x": 0,
            "y": 0,
            "width": 320,
            "height": 480,
        },
        "children": [
            {
                "id": "10:21",
                "name": "Header",
                "type": "FRAME",
                "layoutMode": "HORIZONTAL",
                "itemSpacing": 8,
                "children": [],
            }
        ],
    }

    layout = FigmaExtractor.extract_frame_layout(raw_node)
    assert layout.id == "10:20"
    assert layout.name == "CardContainer"
    assert layout.layout_mode == "VERTICAL"
    assert layout.primary_axis_align == "SPACE_BETWEEN"
    assert layout.counter_axis_align == "CENTER"
    assert layout.padding == {"top": 16.0, "right": 24.0, "bottom": 16.0, "left": 24.0}
    assert layout.item_spacing == 12.0
    assert layout.width == 320.0
    assert layout.height == 480.0
    assert layout.layout_grow == 1.0
    assert layout.layout_align == "STRETCH"
    assert len(layout.children) == 1
    assert layout.children[0].id == "10:21"
    assert layout.children[0].layout_mode == "HORIZONTAL"


def test_extractor_color_and_typography_tokens():
    raw_node = {
        "id": "1:2",
        "name": "Button",
        "type": "FRAME",
        "cornerRadius": 8.0,
        "fills": [
            {
                "type": "SOLID",
                "color": {"r": 0.2, "g": 0.4, "b": 0.8, "a": 1.0},
                "opacity": 0.5,
            },
            {
                "type": "GRADIENT_LINEAR",
                "imageRef": "grad_123",
            },
        ],
        "effects": [
            {
                "type": "DROP_SHADOW",
                "visible": True,
                "color": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.25},
                "offset": {"x": 0, "y": 4},
                "radius": 10,
            }
        ],
        "children": [
            {
                "id": "1:3",
                "name": "ButtonText",
                "type": "TEXT",
                "style": {
                    "fontFamily": "Inter",
                    "fontSize": 14,
                    "fontWeight": 600,
                    "lineHeightPx": 20,
                    "textAlignHorizontal": "CENTER",
                },
                "fills": [
                    {
                        "type": "SOLID",
                        "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
                    }
                ],
            }
        ],
    }

    tokens = FigmaExtractor.extract_design_tokens(raw_node)

    # 1. Colors
    assert len(tokens.colors) >= 2
    solid_fill = next(c for c in tokens.colors if c.get("type") == "SOLID")
    # alpha = 1.0 * 0.5 = 0.5
    assert "hex" in solid_fill
    assert "rgba" in solid_fill
    assert solid_fill["rgba"] == "rgba(51, 102, 204, 0.50)"

    gradient_fill = next(c for c in tokens.colors if c.get("type") == "GRADIENT_LINEAR")
    assert gradient_fill["asset_ref"] == "grad_123"

    # 2. Typography
    assert len(tokens.typography) == 1
    typo = tokens.typography[0]
    assert typo["font_family"] == "Inter"
    assert typo["font_size"] == 14
    assert typo["font_weight"] == 600
    assert typo["line_height"] == 20
    assert typo["text_align"] == "CENTER"

    # 3. Radius
    assert len(tokens.radius) == 1
    assert tokens.radius[0]["corner_radius"] == 8.0

    # 4. Shadows
    assert len(tokens.shadows) == 1
    shadow = tokens.shadows[0]
    assert shadow["type"] == "DROP_SHADOW"
    assert shadow["offset_y"] == 4.0
    assert shadow["radius"] == 10.0
