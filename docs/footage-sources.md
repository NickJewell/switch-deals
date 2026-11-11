# Footage sources (findings for Phase 4)

_Checked 2026-11-11._

## What doesn't work
- **Price API and EU Solr catalogue:** no video fields at all. They provide images only: `image_url_sq_s`, `image_url_h16x9_s` (1600 px wide) and wishlist banners.
- **UK game pages (`nintendo.com/en-gb/...`):** the trailer player is empty in the HTML. Its gallery (`_gItems`) has `video_id` / `video_content_url` fields, but all of them were empty on every page checked. `ec.nintendo.com/GB/...` just redirects to the same page.
- **YouTube:** downloading from it is ruled out by YouTube's terms. At most, log the URLs.

## What works: US store gallery videos
- The US store page `https://www.nintendo.com/us/store/products/<urlKey>/` embeds its data as JSON in `__NEXT_DATA__`.
- Go to `props.pageProps.initialApolloState["Product:{...}"]` and pick the entry whose `urlKey` matches the page.
- Each entry in its `productGallery` has `resourceType: "video"` and a `publicId` such as `/store/software/<switch|switch2>/<US nsuid>/Video/<sha256>`.
- The download URL is `https://assets.nintendo.com/video/upload<publicId>`. It returns a direct MP4: H.264 720p30 with AAC audio, 70–90 s for the samples checked.
- **US product IDs differ from the UK ones**: FF7 Rebirth is `70010000112478` in the UK and `70010000112477` in the US. Match on the store page: `urlKey` is usually the title's slug followed by `-switch` or `-switch-2`.
- **Coverage is partial**, because publishers upload these optionally:
  - On 2026-W46, 3 of the 8 picks had them: Wild Hearts S (2), Talos (1) and RCT3 (1).
  - FF7 Rebirth, WWE 2K26, GTA Trilogy, Hot Wheels and Deponia had screenshots only.

## Proposed resolver order
1. `assets/trailers/<nsuid>.mp4`: dropped in by hand, from a press kit or your own capture.
2. A US store gallery video, if there is one. Cache it under `data/cache/`.
3. A slow pan-and-zoom over the screenshots and banner.

These are publishers' promotional videos, so YouTube copyright (Content ID) claims are possible. Keep the guardrail: trailer footage at most about 50% of any segment, and no clip longer than 8 s.
