"""Icon for the "Умный дом" tab: a house with a wireless signal, as on icon.png.

Astra accepts only an SVG string for a tab icon (the `icon_svg` field of
@ui_page/UiContribution). Astra 0.2.7 no longer draws a PNG embedded through
<image> - the tab stays blank - so this is plain vector SVG that follows the
theme via currentColor, like the other working tab icons. The markup carries
no scripts and no off-machine references, which the registry would reject.
"""

TAB_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M3.5 11 12 4l8.5 7"/>'
    '<path d="M5.5 9.5V20h13V9.5"/>'
    '<path d="M8.8 12.8a4.6 4.6 0 0 1 6.4 0M10.4 14.8a2.2 2.2 0 0 1 3.2 0"/>'
    '<circle cx="12" cy="17.2" r=".6" fill="currentColor"/></svg>'
)
