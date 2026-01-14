# Assets Folder

This folder contains optional overlay files for video rendering.

## Overlay Image (Optional)

To add an overlay to your videos:

1. Create a PNG image with transparency (alpha channel)
2. Name it `overlay.png`
3. Place it in this folder

**Recommended specs:**
- Format: PNG with alpha channel
- Resolution: 2560x1440 (or match your video resolution)
- Transparency: Make the center transparent to show video underneath
- Content: Add your branding, logo, or frame around the edges

**Example use cases:**
- Logo in corner
- Decorative frame around edges  
- Chapter title overlay
- Branding watermark

## If No Overlay

If `overlay.png` doesn't exist, videos will be rendered without overlay (faster rendering).

---

**Note**: The system automatically falls back to rendering without overlay if the overlay processing fails.
